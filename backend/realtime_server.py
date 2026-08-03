import asyncio
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

load_dotenv(override=True)

DOUBAO_REALTIME_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
logger = logging.getLogger("sparkchat.realtime")


def upstream_headers():
    api_key = os.getenv("DOUBAO_SPEECH_API_KEY")
    if not api_key:
        raise RuntimeError("豆包实时语音 API Key 尚未配置")
    return {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": os.getenv("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog"),
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }


def session_payload(config):
    speaker_id = config["speakerId"]
    language = config.get("language", "")
    instructions = config["instructions"]
    speaking_style = config.get("speakingStyle", "自然、清晰地说话，同时保持角色自身的语气。")
    is_o2_clone = speaker_id.startswith("ICL_uranus_")
    is_sc2_voice = speaker_id.startswith(("S_", "ICL_", "saturn_")) and not is_o2_clone
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
    if language:
        payload["tts"]["extra"] = {"explicit_language": language}
    if is_sc2_voice:
        payload["dialog"] = {
            "character_manifest": f"{instructions}\n\n说话方式：{speaking_style}",
            "extra": {"model": "2.2.0.0", "input_mod": "keep_alive"},
        }
    else:
        payload["dialog"] = {
            "bot_name": config.get("name", "数字角色")[:20],
            "system_role": instructions,
            "speaking_style": speaking_style,
            "extra": {"model": "2.1.0.0" if is_o2_clone else "1.2.1.1", "input_mod": "keep_alive"},
        }
    return payload


async def forward_upstream(upstream, browser):
    try:
        async for data in upstream:
            event = decode_event(data)
            if event["message_type"] == AUDIO_ONLY_RESPONSE:
                await browser.send(event["payload"])
                continue
            payload = event["payload"] if isinstance(event["payload"], dict) else {}
            await browser.send(json.dumps({
                "type": "event",
                "event": event["event"],
                "data": payload,
            }, ensure_ascii=False))
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Realtime voice session failed")
        await browser.send(json.dumps({
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
            await browser.send(json.dumps({"type": "ready"}))
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
                await upstream.send(encode_event(FINISH_SESSION, {}, session_id))
                await upstream.send(encode_event(FINISH_CONNECTION, {}))
    except Exception as error:
        await browser.send(json.dumps({
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