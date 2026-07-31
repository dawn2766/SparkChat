import os

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.core.api_error import ApiError


VOICE_NAME = "SparkChat Megatron Commander"
VOICE_DESCRIPTION = (
    "A deep, mature Mandarin Chinese male commander voice with controlled authority, "
    "measured pacing, crisp articulation, restrained gravel, and a subtle synthetic "
    "metallic resonance. Intimidating through composure rather than shouting. Rich low "
    "frequencies, cinematic presence, emotionally complex and reflective. Original voice; "
    "do not imitate any real actor or existing performance."
)
PREVIEW_TEXT = (
    "力量从来不是喧嚣。真正的统帅，只需要让每一道命令都抵达它应有的位置。"
    "我曾在卡隆的矿井中仰望看不见的天空，也曾在角斗场听见万众为自由呐喊。"
    "如今我更清楚，推翻枷锁远比建立秩序容易。若你要与我同行，就说出你的目标，"
    "不要献上空洞的奉承。意志、判断与承担后果的勇气，才是值得尊重的力量。"
)


def main():
    load_dotenv(override=True)
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing from .env")

    client = ElevenLabs(api_key=api_key)
    existing = next(
        (voice for voice in client.voices.get_all().voices if voice.name == VOICE_NAME),
        None,
    )
    if existing:
        print(f"SPARKCHAT_VOICE_MEGADEEP={existing.voice_id}")
        print("Reused existing Megatron voice.")
        return

    try:
        design = client.text_to_voice.design(
            voice_description=VOICE_DESCRIPTION,
            text=PREVIEW_TEXT,
            should_enhance=True,
            quality=1.0,
        )
    except ApiError as error:
        if error.status_code == 403 and "paid plan" in str(error.body).lower():
            raise RuntimeError(
                "ElevenLabs Voice Design API requires a paid plan. "
                "Upgrade the account, then rerun this script."
            ) from error
        raise
    if not design.previews:
        raise RuntimeError("ElevenLabs returned no voice previews")

    selected = design.previews[0]
    voice = client.text_to_voice.create(
        voice_name=VOICE_NAME,
        voice_description=VOICE_DESCRIPTION,
        generated_voice_id=selected.generated_voice_id,
        labels={"language": "zh", "project": "SparkChat", "role": "Megatron"},
    )
    print(f"SPARKCHAT_VOICE_MEGADEEP={voice.voice_id}")
    print("Created Megatron voice successfully.")


if __name__ == "__main__":
    main()