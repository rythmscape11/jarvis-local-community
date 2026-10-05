"""Create synthetic presets from the licensed local Kokoro bundle, not human recordings."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from jarvis.config import Settings, MODELS
from jarvis.engines import LocalSpeech


async def main():
    speech = LocalSpeech(lambda: Settings())
    try:
        for name, voice in [
            ("female", "kokoro-af_heart"),
            ("male", "kokoro-am_michael"),
        ]:
            wav = await speech.synthesize(
                "The sun rises over the quiet garden. We have time to take a breath and enjoy the morning. I am here to help you plan a good day.",
                voice,
            )
            (MODELS / "chatterbox").mkdir(parents=True, exist_ok=True)
            (MODELS / "chatterbox" / f"{name}.wav").write_bytes(wav)
    finally:
        await speech.close()


asyncio.run(main())
