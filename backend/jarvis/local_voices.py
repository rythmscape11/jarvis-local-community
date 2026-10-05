"""Optional offline voice workers. Heavy engines remain outside the core runtime."""

import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from .config import DATA, MODELS, ROOT

LANGUAGES = {
    "en": "English",
    "bn": "Bengali",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
    "ar": "Arabic",
    "auto": "Automatic / mixed language",
}
QWEN_LANGS = ("en", "zh", "ja", "ko", "de", "fr", "ru", "pt", "es", "it")
CHATTER_LANGS = (
    "ar",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fi",
    "fr",
    "he",
    "hi",
    "it",
    "ja",
    "ko",
    "ms",
    "nl",
    "no",
    "pl",
    "pt",
    "ru",
    "sv",
    "sw",
    "tr",
    "zh",
)
INDIC_LANGS = (
    "as",
    "bn",
    "brx",
    "doi",
    "en",
    "gu",
    "hi",
    "kn",
    "kok",
    "mai",
    "ml",
    "mni",
    "mr",
    "ne",
    "or",
    "sa",
    "sat",
    "sd",
    "ta",
    "te",
    "ur",
)
VOICES = {}
for speaker in (
    "Serena",
    "Vivian",
    "Ryan",
    "Aiden",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ono_Anna",
    "Sohee",
):
    VOICES["qwen-" + speaker] = {
        "name": "Qwen " + speaker.replace("_", " "),
        "engine": "qwen",
        "speaker": speaker,
        "languages": QWEN_LANGS,
        "preview_language": "en",
    }
for name, speaker, lang in [
    ("Aditi", "Aditi", "bn"),
    ("Arjun", "Arjun", "bn"),
    ("Divya", "Divya", "hi"),
    ("Rohit", "Rohit", "hi"),
    ("Mary", "Mary", "en"),
    ("Thoma", "Thoma", "en"),
]:
    VOICES["indic-" + name] = {
        "name": "Indic " + name,
        "engine": "indic",
        "speaker": speaker,
        "languages": INDIC_LANGS,
        "preview_language": lang,
    }
for name in ("female", "male"):
    VOICES["chatterbox-" + name] = {
        "name": "Chatterbox " + name,
        "engine": "chatterbox",
        "speaker": name,
        "languages": CHATTER_LANGS,
        "preview_language": "en",
    }
# These voices are already in Kokoro's downloaded bundle; no new weights required.
KOKORO_EXTRA = {
    "kokoro-hf_alpha": ("Hindi Alpha", "hi"),
    "kokoro-hf_beta": ("Hindi Beta", "hi"),
    "kokoro-hm_omega": ("Hindi Omega", "hi"),
    "kokoro-hm_psi": ("Hindi Psi", "hi"),
    "kokoro-ef_dora": ("Spanish Dora", "es"),
    "kokoro-em_alex": ("Spanish Alex", "es"),
    "kokoro-ff_siwis": ("French Siwis", "fr"),
    "kokoro-if_sara": ("Italian Sara", "it"),
    "kokoro-im_nicola": ("Italian Nicola", "it"),
    "kokoro-pf_dora": ("Portuguese Dora", "pt"),
    "kokoro-pm_alex": ("Portuguese Alex", "pt"),
}
PREVIEWS = {
    "en": "Hello. I'm Jarvis. I'm here to help you think things through.",
    "bn": "নমস্কার। আমি জার্ভিস। আজ তোমার দিন কেমন কাটছে?",
    "hi": "नमस्ते। मैं जार्विस हूँ। आज आपका दिन कैसा रहा?",
    "es": "Hola. Soy Jarvis. Estoy aquí para ayudarte.",
    "fr": "Bonjour. Je suis Jarvis. Je suis là pour vous aider.",
    "it": "Ciao. Sono Jarvis. Sono qui per aiutarti.",
    "pt": "Olá. Sou Jarvis. Estou aqui para ajudar.",
}


def text_language(text, configured="en"):
    # Script evidence takes precedence over an English recognition setting.
    for pattern, lang in [
        (r"[\u0980-\u09ff]", "bn"),
        (r"[\u0900-\u097f]", "hi"),
        (r"[\u0b80-\u0bff]", "ta"),
        (r"[\u0c00-\u0c7f]", "te"),
        (r"[\u0d00-\u0d7f]", "ml"),
        (r"[\u0c80-\u0cff]", "kn"),
        (r"[\u0a80-\u0aff]", "gu"),
        (r"[\u3040-\u30ff]", "ja"),
        (r"[\uac00-\ud7af]", "ko"),
        (r"[\u4e00-\u9fff]", "zh"),
        (r"[\u0400-\u04ff]", "ru"),
        (r"[\u0600-\u06ff]", "ar"),
    ]:
        if re.search(pattern, text):
            if lang == "hi" and configured in {
                "hi",
                "mr",
                "ne",
                "sa",
                "mai",
                "doi",
                "kok",
            }:
                return configured
            if lang == "ar" and configured in {"ur", "sd", "ar"}:
                return configured
            return lang
    return configured if configured != "auto" else "en"


def voice_languages(voice):
    if voice in VOICES:
        return VOICES[voice]["languages"]
    if voice in KOKORO_EXTRA:
        return (KOKORO_EXTRA[voice][1],)
    if voice.startswith("gemini-"):
        return (
            "en",
            "bn",
            "hi",
            "es",
            "fr",
            "de",
            "it",
            "pt",
            "ru",
            "zh",
            "ja",
            "ko",
            "ta",
            "te",
            "mr",
            "gu",
            "kn",
            "ml",
            "ar",
            "ur",
        )
    return ("en",)


def preview_text(voice):
    lang = (
        VOICES.get(voice, {}).get("preview_language")
        or (KOKORO_EXTRA.get(voice) or ("", "en"))[1]
    )
    return PREVIEWS.get(lang, PREVIEWS["en"])


class LocalVoiceWorkers:
    def __init__(self, settings=None):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.process = None
        self.engine = None
        self.sequence = 0

    def runtime(self, engine):
        family = "indic" if engine == "indic" else "mlx"
        override = os.getenv("JARVIS_" + family.upper() + "_PYTHON")
        if override:
            return Path(override).expanduser().resolve()
        installed = (
            DATA
            / "voice-runtimes"
            / family
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        development = (
            ROOT / (".venv-indic" if family == "indic" else ".venv-qwen") / "bin/python"
        )
        return installed if installed.exists() else development

    def ready(self, engine):
        directory = {
            "qwen": "qwen-tts",
            "indic": "indic-parler",
            "chatterbox": "chatterbox",
        }[engine]
        needed = [
            MODELS / directory / "model.safetensors",
            MODELS / directory / "config.json",
        ]
        if engine == "qwen":
            needed += [MODELS / directory / "speech_tokenizer/model.safetensors"]
        if engine == "indic":
            needed += [
                MODELS / directory / "tokenizer.json",
                MODELS / directory / "tokenizer_config.json",
                MODELS / directory / "preprocessor_config.json",
                MODELS / directory / "description-tokenizer/tokenizer_config.json",
            ]
        if engine == "chatterbox":
            needed += [
                MODELS / "s3-tokenizer/model.safetensors",
                MODELS / directory / "female.wav",
                MODELS / directory / "male.wav",
            ]
        return self.runtime(engine).is_file() and all(p.is_file() for p in needed)

    def available(self):
        return [v for v, info in VOICES.items() if self.ready(info["engine"])]

    async def _stop(self):
        process, self.process = self.process, None
        self.engine = None
        if process:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def synthesize(self, text, voice, style="natural", language=None):
        if voice not in VOICES or voice not in self.available():
            raise ValueError(
                "Download the optional local voice model and its runtime first"
            )
        if not text.strip() or len(text) > 800:
            raise ValueError("Local speech needs between 1 and 800 characters")
        configured = self.settings().language if self.settings else "en"
        language = text_language(text, language or configured)
        if language not in voice_languages(voice):
            raise ValueError(
                "This voice does not support "
                + LANGUAGES.get(language, language)
                + ". Text remains available; select a compatible voice."
            )
        engine = VOICES[voice]["engine"]
        async with self.lock:
            try:
                if (
                    not self.process
                    or self.process.returncode is not None
                    or self.engine != engine
                ):
                    await self._stop()
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k
                        not in {
                            "HF_TOKEN",
                            "HUGGING_FACE_HUB_TOKEN",
                            "GOOGLE_API_KEY",
                            "GROQ_API_KEY",
                            "GEMINI_API_KEY",
                        }
                    }
                    env.update(
                        HF_HUB_OFFLINE="1",
                        TRANSFORMERS_OFFLINE="1",
                        HF_HUB_DISABLE_TELEMETRY="1",
                        DO_NOT_TRACK="1",
                        TOKENIZERS_PARALLELISM="false",
                    )
                    worker = Path(__file__).with_name("voice_worker.py")
                    starting = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            str(self.runtime(engine)),
                            str(worker),
                            engine,
                            str(MODELS),
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                            env=env,
                            limit=12_000_000,
                        )
                    )
                    try:
                        self.process = await asyncio.shield(starting)
                    except asyncio.CancelledError:
                        # Reap a child created while its startup await was cancelled.
                        self.process = await starting
                        raise
                    self.engine = engine
                self.sequence += 1
                request = {
                    "id": self.sequence,
                    "text": text,
                    "voice": voice,
                    "style": style,
                    "language": language,
                }
                self.process.stdin.write(
                    (json.dumps(request, ensure_ascii=False) + "\n").encode()
                )
                await self.process.stdin.drain()
                async with asyncio.timeout(120):
                    line = await self.process.stdout.readline()
                try:
                    result = json.loads(line)
                except (ValueError, UnicodeError) as error:
                    raise ValueError(
                        "Local voice worker returned an invalid response; text remains available."
                    ) from error
                if (
                    not isinstance(result, dict)
                    or result.get("id") != self.sequence
                    or not result.get("ok")
                ):
                    raise ValueError(
                        "Local voice generation failed. Check the optional runtime and model installation."
                    )
                wav = base64.b64decode(result["audio"], validate=True)
                from .speech import normalize_wav

                return normalize_wav(wav)
            except asyncio.CancelledError:
                # Stop only our child process. Discard its response before reusing state.
                await self._stop()
                raise
            except Exception as error:
                await self._stop()
                if isinstance(error, ValueError):
                    raise
                raise ValueError(
                    "Local voice worker unavailable or timed out; text remains available."
                ) from error

    async def close(self):
        async with self.lock:
            await self._stop()
