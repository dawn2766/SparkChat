import asyncio
import json
import os
import uuid

import websockets
from dotenv import load_dotenv

from doubao_realtime import (
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


def upstream_headers():
    app_id = os.getenv("DOUBAO_SPEECH_APP_ID")
    access_key = os.getenv("DOUBAO_SPEECH_ACCESS_KEY")
    if not app_id or not access_key:
        raise RuntimeError("DOUBAO_SPEECH_APP_ID 或 DOUBAO_SPEECH_ACCESS_KEY 尚未配置")
    return {
        "X-Api-App-ID": app_id,
        "X-Api-Access-Key": access_key,
        "X-Api-Resource-Id": os.getenv("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog"),
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }


def session_payload(config):
    speaker_id = config["speakerId"]
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
    if speaker_id.startswith(("S_", "ICL_", "saturn_")):
        payload["tts"]["extra"] = {"tts_2.0_model": "seed-tts-2.0"}
        payload["dialog"] = {
            "character_manifest": (
                config.get("persona", "保持自然、简洁、有帮助。")
                + "\n\n表达方式：使用原创的低沉、冷峻、克制的机械统帅声线。语速偏慢，咬字硬朗，句尾坚定下沉，带自然的金属生命体重量感；不要尖叫、不要卡通化、不要夸张咆哮，始终保持中文清晰可懂。"
            ),
            "extra": {"model": "2.2.0.0", "input_mod": "keep_alive"},
        }
    else:
        payload["dialog"] = {
            "bot_name": config.get("name", "数字角色")[:20],
            "system_role": config.get("persona", "保持自然、简洁、有帮助。"),
            "speaking_style": "使用自然、简洁、适合直接朗读的中文回答。",
            "extra": {"model": "1.2.1.1", "input_mod": "keep_alive"},
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
    port = int(os.getenv("SPEECH_ENGINE_PORT", "3101"))
    async with websockets.serve(handle_browser, "127.0.0.1", port, max_size=None):
        print(f"Doubao realtime proxy listening on ws://127.0.0.1:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())