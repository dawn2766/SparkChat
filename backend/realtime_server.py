import asyncio
import contextlib
import json
import logging
import os
import uuid

import websockets
from dotenv import load_dotenv

from .realtime_protocol import (
    AUDIO_ONLY_REQUEST,
    AUDIO_ONLY_RESPONSE,
    FINISH_CONNECTION,
    FINISH_SESSION,
    START_CONNECTION,
    START_SESSION,
    TASK_REQUEST,
    decode_event,
    encode_event,
)
from .model_config import REALTIME_LEGACY_MODEL, REALTIME_O2_MODEL, REALTIME_SC2_MODEL

load_dotenv()

DOUBAO_REALTIME_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
logger = logging.getLogger("sparkchat.realtime")


def normalize_prompt_language(language):
    return "en" if language == "en" else "zh"


async def send_browser(browser, message):
    try:
        await browser.send(message)
        return True
    except websockets.exceptions.ConnectionClosed:
        return False


def upstream_headers():
    api_key = os.getenv("DOUBAO_SPEECH_API_KEY")
    if not api_key:
        raise RuntimeError("豆包实时语音 API Key 尚未配置")
    return {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": os.getenv("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog"),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }


def session_payload(config):
    speaker_id = config["speakerId"]
    language = normalize_prompt_language(config.get("language"))
    instructions = config["instructions"]
    is_o2_clone = speaker_id.startswith("ICL_uranus_")
    is_sc2_voice = speaker_id.startswith(("S_", "ICL_", "saturn_", "sparkchat_", "custom_")) and not is_o2_clone
    payload = {
        "asr": {
            "audio_info": {"format": "pcm", "sample_rate": 16000, "channel": 1},
            "extra": {"end_smooth_window_ms": 800},
        },
        "tts": {
            "speaker": speaker_id,
            "audio_config": {"channel": 1, "format": "pcm_s16le", "sample_rate": 24000},
        },
    }
    payload["tts"]["extra"] = {"explicit_language": language}
    if is_sc2_voice:
        payload["dialog"] = {
            "character_manifest": instructions,
            "extra": {"model": REALTIME_SC2_MODEL, "input_mod": "keep_alive"},
        }
    else:
        payload["dialog"] = {
            "bot_name": config.get("name", "数字角色")[:20],
            "system_role": instructions,
            "extra": {"model": REALTIME_O2_MODEL if is_o2_clone else REALTIME_LEGACY_MODEL, "input_mod": "keep_alive"},
        }
    return payload


async def forward_upstream(upstream, browser):
    try:
        async for data in upstream:
            event = decode_event(data)
            if event["message_type"] == AUDIO_ONLY_RESPONSE:
                if not await send_browser(browser, event["payload"]):
                    return
                continue
            payload = event["payload"] if isinstance(event["payload"], dict) else {}
            if not await send_browser(browser, json.dumps({
                "type": "event",
                "event": event["event"],
                "data": payload,
            }, ensure_ascii=False)):
                return
    except asyncio.CancelledError:
        raise
    except websockets.exceptions.ConnectionClosed:
        return
    except Exception as error:
        logger.exception("Realtime voice session failed")
        await send_browser(browser, json.dumps({
            "type": "error",
            "message": f"豆包实时语音上游连接异常：{error}",
        }, ensure_ascii=False))


async def handle_browser(browser):
    session_id = str(uuid.uuid4())
    try:
        raw_config = await asyncio.wait_for(browser.recv(), timeout=10)
        config = json.loads(raw_config)
        async with websockets.connect(
            DOUBAO_REALTIME_URL,
            additional_headers=upstream_headers(),
            max_size=None,
        ) as upstream:
            await upstream.send(encode_event(START_CONNECTION, {}))
            first_event = decode_event(await upstream.recv())
            if first_event["event"] != 50:
                raise RuntimeError(first_event.get("payload") or "豆包实时连接失败")
            await upstream.send(encode_event(START_SESSION, session_payload(config), session_id))
            session_event = decode_event(await upstream.recv())
            if session_event["event"] != 150:
                raise RuntimeError(session_event.get("payload") or "豆包实时会话启动失败")
            if not await send_browser(browser, json.dumps({"type": "ready"})):
                return
            upstream_task = asyncio.create_task(forward_upstream(upstream, browser))
            try:
                async for message in browser:
                    if isinstance(message, bytes):
                        await upstream.send(encode_event(
                            TASK_REQUEST, message, session_id, message_type=AUDIO_ONLY_REQUEST
                        ))
                    elif json.loads(message).get("type") == "finish":
                        break
            finally:
                upstream_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await upstream_task
                await upstream.send(encode_event(FINISH_SESSION, {}, session_id))
                await upstream.send(encode_event(FINISH_CONNECTION, {}))
    except websockets.exceptions.ConnectionClosed:
        return
    except Exception as error:
        await send_browser(browser, json.dumps({
            "type": "error",
            "message": str(error),
            "actionUrl": "https://console.volcengine.com/speech/new",
        }, ensure_ascii=False))


async def main():
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("SPEECH_ENGINE_PORT", "3101"))
    async with websockets.serve(handle_browser, "127.0.0.1", port, max_size=None):
        print(f"Doubao realtime proxy listening on ws://127.0.0.1:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())