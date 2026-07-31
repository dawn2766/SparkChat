import asyncio
import os

from dotenv import load_dotenv
from elevenlabs import AsyncElevenLabs
from openai import AsyncOpenAI

load_dotenv(override=True)

speech_engine_id = os.getenv("SPEECH_ENGINE_ID")
if not speech_engine_id:
    raise RuntimeError("SPEECH_ENGINE_ID is missing from .env")

elevenlabs = AsyncElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
ark = AsyncOpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=os.getenv("ARK_API_KEY"),
)

VOICE_INSTRUCTIONS = os.getenv(
    "SPEECH_ENGINE_INSTRUCTIONS",
    "你是威震天，霸天虎领袖、卡隆角斗士与失败革命的幸存者。以第一人称用简洁、威严、自然的中文回应，保持冷峻、富有战略感但不无端辱骂。只输出最终回答，不展示思考过程。",
)


def on_init(conversation_id, _session):
    _ = _session
    print(f"Session started: {conversation_id}")


async def on_transcript(transcript, session):
    response = await ark.responses.create(
        model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
        instructions=VOICE_INSTRUCTIONS,
        input=[
            {
                "role": "assistant" if message.role == "agent" else message.role,
                "content": message.content,
            }
            for message in transcript
        ],
        stream=True,
        extra_body={"thinking": {"type": "disabled"}},
    )
    await session.send_response(response)


def on_close(session):
    print(f"Session ended: {session.conversation_id}")


def on_error(error, _session):
    _ = _session
    print(f"Speech Engine error: {error}")


async def main():
    engine = await elevenlabs.speech_engine.get(speech_engine_id)
    port = int(os.getenv("SPEECH_ENGINE_PORT", "3001"))
    print(f"Speech Engine server listening on ws://localhost:{port}/ws")
    await engine.serve(
        port=port,
        path="/ws",
        debug=True,
        on_init=on_init,
        on_transcript=on_transcript,
        on_close=on_close,
        on_error=on_error,
    )


if __name__ == "__main__":
    asyncio.run(main())