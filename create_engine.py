import asyncio
import os

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs

load_dotenv(override=True)


async def main():
    ws_url = os.getenv("SPEECH_ENGINE_WS_URL")
    if not ws_url:
        raise RuntimeError("SPEECH_ENGINE_WS_URL is missing from .env")

    elevenlabs = AsyncElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    speech_engine = {
        "ws_url": ws_url,
        "request_headers": {"ngrok-skip-browser-warning": "true"},
    }
    engine_id = os.getenv("SPEECH_ENGINE_ID")

    if engine_id:
        await elevenlabs.speech_engine.update(
            engine_id,
            speech_engine=speech_engine,
        )
        print(f"Speech Engine updated: {engine_id}")
    else:
        engine = await elevenlabs.speech_engine.create(
            name=os.getenv("SPEECH_ENGINE_NAME", "SparkChat Voice Agent"),
            speech_engine=speech_engine,
        )
        print(f"Speech Engine ID: {engine.engine_id}")
        print("Copy it into SPEECH_ENGINE_ID in .env")


if __name__ == "__main__":
    asyncio.run(main())