"""Central registry for model identifiers used by SparkChat.

Model IDs intentionally carry no date or version suffix: Ark resolves each name
to the latest released snapshot of that model family.
"""

TRANSLATION_MODEL = "deepseek-v4-flash"
DEFAULT_CHAT_MODEL = "doubao-seed-character"
MEMORY_MODEL = "deepseek-v4-flash"
VIDEO_TRANSCRIPTION_MODEL = "doubao-seed-2-1-turbo"
DEEPSEEK_ASSISTANT_NAME = "DeepSeek"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_MODELS = {
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}

CHAT_MODELS = {
    "doubao-seed-character": "Doubao Seed Character",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}

TTS_MODEL = "seed-tts-2.0-expressive"
TTS_RESOURCE_ID = "seed-icl-2.0"

REALTIME_O2_MODEL = "2.1.0.0"
REALTIME_SC2_MODEL = "2.2.0.0"
REALTIME_LEGACY_MODEL = "1.2.1.1"
