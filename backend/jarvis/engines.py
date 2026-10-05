"""Replaceable local engines, reused sessions/processes, no audio retention."""

import asyncio
import io
import json
import wave
from typing import Protocol
import httpx
import numpy as np
import onnxruntime as ort
from .config import OLLAMA, WHISPER, MODELS, VAD_PATH


class SpeechRecognition(Protocol):
    async def transcribe(self, pcm: bytes, language: str) -> str: ...


class SpeechGeneration(Protocol):
    async def synthesize(self, text: str, voice: str) -> bytes: ...


class LanguageModel(Protocol):
    def stream(self, messages: list, tools: list, settings): ...


class Ollama:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=OLLAMA, timeout=httpx.Timeout(120, connect=3), trust_env=False
        )

    async def available(self):
        r = await self.client.get("/api/tags")
        r.raise_for_status()
        return [
            m["name"]
            for m in r.json()["models"]
            if not m.get("remote_host")
            and not m.get("remote_model")
            and m.get("size", 0) > 1_000_000
        ]

    async def stream(self, messages, tools, settings):
        # Metadata checked for every request: remote aliases cannot sneak through.
        local = await self.available()
        model = settings.model
        if model not in local and model + ":latest" not in local:
            raise ValueError(
                "Selected local model is unavailable. Download it with ollama pull."
            )
        async with self.client.stream(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "tools": tools,
                "stream": True,
                "think": False,
                "keep_alive": "10m",
                "options": {
                    "num_ctx": settings.context_tokens,
                    "num_predict": settings.response_tokens,
                    "temperature": 0.3,
                },
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    yield json.loads(line)

    async def close(self):
        await self.client.aclose()


class Whisper:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=WHISPER, timeout=90, trust_env=False)
        self.lock = asyncio.Lock()

    async def health(self):
        try:
            r = await self.client.get("/", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def transcribe(self, pcm, language):
        if len(pcm) < 6400:
            return ""
        if (
            np.sqrt(
                np.mean((np.frombuffer(pcm, dtype="<i2").astype(float) / 32768) ** 2)
            )
            < 0.002
        ):
            return ""
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        async with self.lock:
            r = await self.client.post(
                "/inference",
                files={"file": ("audio.wav", output.getvalue(), "audio/wav")},
                data={
                    "response_format": "json",
                    "language": language,
                    "temperature": "0.0",
                    "prompt": "Jarvis. Voice names: Hannah, Diana, Autumn, Austin, Daniel, Troy, Heart, Bella, Nicole, Sarah, Emma, Isabella, George, Michael, Rishi, Tara, Aman.",
                },
            )
        r.raise_for_status()
        return r.json().get("text", "").strip()

    async def close(self):
        await self.client.aclose()


class Piper:
    def __init__(self, settings=None):
        self.settings = settings
        self.voices = {}
        self.lock = asyncio.Lock()

    def available(self):
        return [
            p.stem
            for p in MODELS.glob("*.onnx")
            if p.with_suffix(".onnx.json").exists()
        ]

    async def synthesize(self, text, voice):
        if voice not in self.available():
            raise ValueError(
                "Piper voice is unavailable. Download the voice and JSON config."
            )

        def work():
            from piper import PiperVoice, SynthesisConfig

            if voice not in self.voices:
                self.voices[voice] = PiperVoice.load(str(MODELS / (voice + ".onnx")))
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                self.voices[voice].synthesize_wav(
                    text,
                    wav,
                    syn_config=SynthesisConfig(
                        length_scale=self.settings().voice_pace
                        if self.settings
                        else 1.05
                    ),
                )
            return output.getvalue()

        # Cancellation cannot stop ONNX mid-sentence. Retain lock until thread finishes.
        async with self.lock:
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise


class KokoroSession:
    """Normalize the upstream 0.4.9 adapter's speed dtype to the ONNX contract."""

    def __init__(self, session):
        self.session = session
        self.requested_speed = 1.0
        self._model_path = session._model_path
        self.float_speed = any(
            i.name == "speed" and i.type == "tensor(float)"
            for i in session.get_inputs()
        )

    def get_inputs(self):
        return self.session.get_inputs()

    def run(self, outputs, inputs):
        if self.float_speed:
            # kokoro-onnx 0.4.9 truncates fractional speeds to int32 before run().
            # Casting that zero back to float causes division by zero in ONNX.
            inputs = dict(
                inputs, speed=np.asarray([self.requested_speed], dtype=np.float32)
            )
        return self.session.run(outputs, inputs)


class LocalSpeech(Piper):
    """Kokoro expressive voices with Piper retained as an independent fallback."""

    def __init__(self, settings=None):
        super().__init__(settings)
        self.kokoro = None
        self.phoneme_directory = None
        from .speech import GroqSpeech, MacSpeech

        from .local_voices import LocalVoiceWorkers

        self.local_workers = LocalVoiceWorkers(settings)
        self.google = None
        self.online = GroqSpeech(settings)
        self.native = MacSpeech(settings)

    def available(self, online_enabled=None, google_enabled=None):
        voices = super().available()
        if (MODELS / "kokoro-v1.0.onnx").exists() and (
            MODELS / "voices-v1.0.bin"
        ).exists():
            voices += [
                "kokoro-af_heart",
                "kokoro-af_bella",
                "kokoro-af_nicole",
                "kokoro-af_sarah",
                "kokoro-am_michael",
                "kokoro-bf_emma",
                "kokoro-bf_isabella",
                "kokoro-bm_george",
                "kokoro-af_aoede",
                "kokoro-af_kore",
                "kokoro-af_nova",
                "kokoro-am_fenrir",
                "kokoro-am_puck",
                "kokoro-bm_fable",
            ]
        from .local_voices import KOKORO_EXTRA

        if (MODELS / "kokoro-v1.0.onnx").exists() and (
            MODELS / "voices-v1.0.bin"
        ).exists():
            voices += list(KOKORO_EXTRA)
        voices += self.local_workers.available()
        voices += self.native.available()
        if (
            online_enabled
            if online_enabled is not None
            else self.settings and self.settings().online_voice_enabled
        ):
            from .speech import GROQ_VOICES

            voices += list(GROQ_VOICES)
        if (google_enabled is not None or online_enabled is not False) and (
            google_enabled
            if google_enabled is not None
            else self.settings and self.settings().google_voice_enabled
        ):
            from .google_ai import VOICES

            voices += list(VOICES)
        return voices

    def supports_text(self, text, voice, language=None):
        from .local_voices import text_language, voice_languages

        language = text_language(
            text, language or (self.settings().language if self.settings else "en")
        )
        return language in voice_languages(voice)

    async def synthesize(self, text, voice, language=None):
        if not self.supports_text(text, voice, language):
            raise ValueError(
                "Selected voice does not support this language. Select a compatible voice; the text answer remains available."
            )
        if voice.startswith(("qwen-", "indic-", "chatterbox-")):
            return await self.local_workers.synthesize(text, voice, language=language)
        if voice.startswith("gemini-"):
            if not self.google:
                raise ValueError("Google voice adapter unavailable")
            return await self.google.synthesize(text, voice)
        if voice.startswith("groq-"):
            return await self.online.synthesize(text, voice)
        if voice.startswith("mac-"):
            return await self.native.synthesize(text, voice)
        if not voice.startswith("kokoro-"):
            return await super().synthesize(text, voice)
        if voice not in self.available():
            raise ValueError("Kokoro model and voices must be downloaded first")

        def work():
            from kokoro_onnx import Kokoro
            from kokoro_onnx.config import EspeakConfig
            import espeakng_loader
            import tempfile
            import shutil

            if self.kokoro is None:
                # eSpeak expects the parent of espeak-ng-data. Its macOS wheel
                # also fails on long paths, so stage only phoneme data in a short
                # owned temporary directory. No microphone audio is written.
                self.phoneme_directory = tempfile.TemporaryDirectory(
                    prefix="jarvis-phonemes-"
                )
                shutil.copytree(
                    espeakng_loader.get_data_path(),
                    self.phoneme_directory.name + "/espeak-ng-data",
                )
                options = ort.SessionOptions()
                options.intra_op_num_threads = 4
                options.inter_op_num_threads = 1
                session = ort.InferenceSession(
                    str(MODELS / "kokoro-v1.0.onnx"),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
                self.kokoro = Kokoro.from_session(
                    KokoroSession(session),
                    str(MODELS / "voices-v1.0.bin"),
                    espeak_config=EspeakConfig(
                        lib_path=espeakng_loader.get_library_path(),
                        data_path=self.phoneme_directory.name,
                    ),
                )
            speed = 1 / self.settings().voice_pace if self.settings else 1.0
            self.kokoro.sess.requested_speed = speed
            samples, rate = self.kokoro.create(
                text,
                voice=voice.removeprefix("kokoro-"),
                speed=speed,
                lang={
                    "h": "hi",
                    "e": "es",
                    "f": "fr-fr",
                    "i": "it",
                    "p": "pt-br",
                    "b": "en-gb",
                }.get(voice.removeprefix("kokoro-")[0], "en-us"),
            )
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(
                    (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                )
            return output.getvalue()

        async with self.lock:
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def synthesize_expressive(self, text, voice, style):
        if not self.supports_text(text, voice):
            raise ValueError(
                "Selected voice does not support this language; select a compatible voice."
            )
        if voice.startswith(("qwen-", "indic-", "chatterbox-")):
            return await self.local_workers.synthesize(text, voice, style)
        if voice.startswith("gemini-"):
            if not self.google:
                raise ValueError("Google voice adapter unavailable")
            return await self.google.synthesize(text, voice, style)
        if voice.startswith("groq-"):
            return await self.online.synthesize(text, voice, style)
        return await self.synthesize(text, voice)

    async def close(self):
        await self.local_workers.close()
        await self.online.close()
        await self.native.close()
        if self.phoneme_directory:
            self.phoneme_directory.cleanup()


class Silero:
    def __init__(self):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(VAD_PATH), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def probability(self, pcm):
        samples = (
            np.frombuffer(pcm, dtype="<i2").astype(np.float32).reshape(1, -1) / 32768
        )
        if samples.shape[1] != 512:
            raise ValueError("Silero frame must contain 512 samples")
        audio = np.concatenate((self.context, samples), axis=1)
        output, self.state = self.session.run(
            None,
            {
                "input": audio,
                "state": self.state,
                "sr": np.array(16000, dtype=np.int64),
            },
        )
        self.context = audio[:, -64:]
        return float(output[0][0])
