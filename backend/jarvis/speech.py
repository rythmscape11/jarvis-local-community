"""Optional explicit online speech and native macOS speech adapters."""

import asyncio
import base64
import io
import json
import os
import re
import sys
import subprocess
import tempfile
import time
import wave
import numpy as np
from pathlib import Path
import httpx
from . import config
from .credentials import credentials

GROQ_VOICES = tuple(
    "groq-" + v for v in ("hannah", "diana", "autumn", "austin", "daniel", "troy")
)


def normalize_wav(blob):
    """Streaming RIFF uses sentinel lengths; rebuild from actual received PCM."""
    if not 44 <= len(blob) <= 8_000_000:
        raise ValueError("Speech response exceeds the audio size limit")
    with wave.open(io.BytesIO(blob), "rb") as wav:
        channels, width, rate = (
            wav.getnchannels(),
            wav.getsampwidth(),
            wav.getframerate(),
        )
        pcm = wav.readframes(wav.getnframes())
    if (
        channels not in (1, 2)
        or width != 2
        or not 16000 <= rate <= 48000
        or not pcm
        or len(pcm) % (channels * width)
    ):
        raise ValueError("Speech service returned unsupported PCM audio")
    if np.max(np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.int32))) < 20:
        raise ValueError(
            "Speech service returned silent audio. Try again or choose another voice."
        )
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return out.getvalue()


def speech_parts(text, limit=200):
    text = re.sub(r"\[[^\]]*\]", "", text).strip()
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            raise ValueError("A spoken word exceeds the speech service limit")
        parts.append(text[:cut])
        text = text[cut:].strip()
    return parts


def groq_limit_message(body, headers):
    """Extract only allowlisted limit categories; never display upstream raw errors."""
    category = ""
    if len(body) <= 8192:
        try:
            message = json.loads(body).get("error", {}).get("message", "")
            if isinstance(message, str):
                for kind in (
                    "tokens per day",
                    "tokens per minute",
                    "requests per day",
                    "requests per minute",
                ):
                    if kind in message.lower():
                        category = " (" + kind + ")"
                        break
        except (ValueError, AttributeError, TypeError):
            pass
    retry = str(headers.get("retry-after", ""))
    wait = ""
    if re.fullmatch(r"\d{1,6}", retry) and 0 < int(retry) <= 604800:
        wait = f" Retry in {int(retry):,} seconds."
    return f"Groq voice is rate-limited{category}.{wait} Choose a downloaded local voice or wait."


class GroqSpeech:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=5),
            trust_env=False,
            follow_redirects=False,
        )
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def synthesize(self, text, voice, style="natural"):
        if not self.settings().online_voice_enabled or voice not in GROQ_VOICES:
            raise ValueError("Enable optional Groq online voice in Settings first")
        from .providers import credential_name

        key = await credentials.read(credential_name("https://api.groq.com/openai/v1"))
        if not key:
            raise ValueError("Groq voice needs your saved Groq API key")
        direction = {
            # Orpheus defaults to conversational cadence without directions.
            "natural": "",
            "story": "[warm] ",
            "poetry": "[dramatic] ",
            "cheerful": "[cheerful] ",
            "warm": "[warm] ",
            "singsong": "[singsong] ",
            "giggling": "[giggling] ",
        }.get(style, "")
        blobs = []
        async with self.lock:
            for part in speech_parts(text, 200 - len(direction)):
                # Conservative free-tier default. Cancellation aborts waits and HTTP.
                delay = 60 / self.settings().groq_voice_rpm - (
                    time.monotonic() - self.last_request
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                self.last_request = time.monotonic()
                async with self.client.stream(
                    "POST",
                    "https://api.groq.com/openai/v1/audio/speech",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": "canopylabs/orpheus-v1-english",
                        "voice": voice[5:],
                        "input": direction + part,
                        "response_format": "wav",
                    },
                ) as response:
                    if response.status_code == 429:
                        error = bytearray()
                        async for chunk in response.aiter_bytes():
                            error.extend(chunk[: 8193 - len(error)])
                            if len(error) > 8192:
                                break
                        raise ValueError(
                            groq_limit_message(bytes(error), response.headers)
                        )
                    if response.status_code in (401, 403):
                        raise ValueError(
                            "Groq voice access unavailable. Check the key and Orpheus access in the Groq console."
                        )
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 8_000_000:
                            raise ValueError(
                                "Speech response exceeds the audio size limit"
                            )
                blobs.append(normalize_wav(bytes(data)))
        output = io.BytesIO()
        with wave.open(output, "wb") as dest:
            params = None
            for blob in blobs:
                with wave.open(io.BytesIO(blob), "rb") as src:
                    current = (
                        src.getnchannels(),
                        src.getsampwidth(),
                        src.getframerate(),
                    )
                    if params is None:
                        params = current
                        dest.setnchannels(current[0])
                        dest.setsampwidth(current[1])
                        dest.setframerate(current[2])
                    if current != params:
                        raise ValueError(
                            "Speech service changed audio format within a sentence"
                        )
                    dest.writeframes(src.readframes(src.getnframes()))
        return output.getvalue()

    async def close(self):
        await self.client.aclose()


class MacSpeech:
    def __init__(self, settings):
        self.settings = settings
        root = Path(os.getenv("JARVIS_RESOURCES", str(config.ROOT)))
        self.binary = root / "native/mac-voice"
        self.process = None
        self.lock = asyncio.Lock()
        self.system_voices = []
        if sys.platform == "darwin":
            try:
                inventory = subprocess.run(
                    ["/usr/bin/say", "-v", "?"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                ).stdout
                self.system_voices = [
                    "mac-" + name
                    for name in ("Rishi", "Tara", "Aman")
                    if re.search(r"^" + name + r"(?:\s|\()", inventory, re.M)
                ]
            except (OSError, subprocess.SubprocessError):
                pass

    def available(self):
        return (
            self.system_voices
            if sys.platform == "darwin" and self.binary.is_file()
            else []
        )

    async def synthesize(self, text, voice):
        if voice not in self.available():
            raise ValueError("Native Indian voice helper unavailable on this system")
        async with self.lock:
            if voice in ("mac-Tara", "mac-Aman"):
                await self.close()
                # macOS's persistent system speech daemon supports these voices;
                # AVFoundation's standalone helper exposes only compact voices.
                # The short-lived CLI is a client, not a model process.
                with tempfile.TemporaryDirectory(
                    prefix="jarvis-system-speech-"
                ) as folder:
                    path = Path(folder) / "speech.wav"
                    self.process = await asyncio.create_subprocess_exec(
                        "/usr/bin/say",
                        "-v",
                        voice[4:],
                        "-r",
                        str(round(175 / self.settings().voice_pace)),
                        "-o",
                        str(path),
                        "--file-format=WAVE",
                        "--data-format=LEI16@22050",
                        "-f",
                        "-",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        await asyncio.wait_for(
                            self.process.communicate(text[:1200].encode()), 30
                        )
                        if self.process.returncode:
                            raise ValueError("macOS rejected the selected voice")
                        return normalize_wav(path.read_bytes())
                    finally:
                        await self.close()
            if self.process is None or self.process.returncode is not None:
                self.process = await asyncio.create_subprocess_exec(
                    str(self.binary),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=8_000_000,
                )
            try:
                request = (
                    json.dumps(
                        {
                            "text": text,
                            "voice": voice[4:],
                            "pace": self.settings().voice_pace,
                        }
                    )
                    + "\n"
                )
                self.process.stdin.write(request.encode())
                await self.process.stdin.drain()
                line = await asyncio.wait_for(self.process.stdout.readline(), 30)
                result = json.loads(line)
                if not result.get("ok"):
                    raise ValueError(
                        "Selected system voice is not installed; download it in macOS Spoken Content settings"
                    )
                return normalize_wav(base64.b64decode(result["wav"], validate=True))
            except BaseException:
                await self.close()
                raise

    async def close(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        self.process = None
