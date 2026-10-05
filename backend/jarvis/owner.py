"""Optional local owner lock. Voice matching supplements, never replaces, a password.

No raw audio is retained. An encrypted voiceprint is unlocked with an owner
passphrase; unknown/short/noisy speech closes all owner leases. This is not
anti-spoofing, nor protection against someone who controls the OS account.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
import threading
from pathlib import Path

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

MODEL = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"


def normalize(vector):
    value = np.asarray(vector, dtype=np.float32)
    if value.ndim != 1 or not 64 <= len(value) <= 1024 or not np.isfinite(value).all():
        raise ValueError("Invalid speaker embedding")
    norm = float(np.linalg.norm(value))
    if norm < 1e-6:
        raise ValueError("Empty speaker embedding")
    return value / norm


class Speaker:
    def __init__(self, models: Path):
        self.path = models / MODEL
        self.engine = None
        self.lock = threading.Lock()

    def extract(self, pcm):
        with self.lock:
            return self._extract(pcm)

    def _extract(self, pcm):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if not 1.5 * 16000 <= len(samples) <= 16 * 16000:
            raise ValueError("Speech is too short or long to verify identity")
        if float(np.sqrt(np.mean(samples**2))) < 0.008:
            raise ValueError("Speech is too quiet for owner verification")
        if self.engine is None:
            if not self.path.is_file():
                raise ValueError(
                    "Owner voice model missing. Run scripts/download-owner-model.py"
                )
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != MODEL_SHA256:
                raise ValueError("Owner voice model checksum mismatch")
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.path), num_threads=2, provider="cpu", debug=False
            )
            if not config.validate():
                raise ValueError("Owner voice model is unavailable")
            self.engine = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        stream = self.engine.create_stream()
        stream.accept_waveform(sample_rate=16000, waveform=samples)
        stream.input_finished()
        if not self.engine.is_ready(stream):
            raise ValueError("More speech is needed for owner verification")
        return normalize(self.engine.compute(stream))


def download_model(directory: Path):
    """Explicit network operation; never invoked by voice verification."""
    import httpx

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MODEL
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        print(
            "Owner model already verified. Enrollment remains off until explicitly enabled."
        )
        return
    temporary = path.with_suffix(".download")
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.stream(
            "GET",
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
            + MODEL,
            follow_redirects=True,
            timeout=60,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 32 * 1024**2:
                        raise ValueError("Owner model exceeded expected download size")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise ValueError("Owner model checksum mismatch")
        temporary.replace(path)
        print(
            f"Owner model verified: {size} bytes. Enrollment remains off until explicitly enabled."
        )
    finally:
        temporary.unlink(missing_ok=True)


class OwnerLock:
    LEASE_SECONDS = 600

    def __init__(self, data: Path, speaker):
        self.path = data / "owner-voice.enc.json"
        self.speaker = speaker
        self.leases = {}
        self.prints = None
        self.failures = 0
        self.retry_at = 0
        self.mutex = asyncio.Lock()

    @property
    def enabled(self):
        # Even corrupt enrollment remains locked, never silently disables.
        return self.path.exists()

    def allowed(self, token):
        return not self.enabled or (
            self.prints is not None and self.leases.get(token, 0) > time.monotonic()
        )

    def status(self, token):
        return {
            "enabled": self.enabled,
            "locked": not self.allowed(token),
            "model_downloaded": self.speaker.path.is_file(),
            "experimental": True,
            "lease_seconds": self.LEASE_SECONDS,
        }

    def lock(self):
        self.leases.clear()
        self.prints = None

    @staticmethod
    def key(password, salt):
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ValueError("Use an owner passphrase of 8–128 characters")
        return base64.urlsafe_b64encode(
            hashlib.scrypt(
                password.encode(),
                salt=salt,
                n=2**17,
                r=8,
                p=1,
                maxmem=256 * 1024**2,
                dklen=32,
            )
        )

    async def enroll(self, token, password, samples):
        async with self.mutex:
            if self.enabled:
                raise ValueError(
                    "Owner already enrolled. Unlock and remove enrollment first"
                )
            if len(samples) != 4:
                raise ValueError(
                    "Three owner recordings and a separate test recording are required"
                )
            if any(not 4 * 32000 <= len(pcm) <= 16 * 32000 for pcm in samples):
                raise ValueError("Each enrollment recording must be 4–16 seconds")
            prints = [
                await asyncio.to_thread(self.speaker.extract, pcm[: 8 * 32000])
                for pcm in samples[:3]
            ]
            if any(
                float(a @ b) < 0.65
                for i, a in enumerate(prints)
                for b in prints[i + 1 :]
            ):
                raise ValueError(
                    "Enrollment voices differ. Record the same owner in a quiet room"
                )
            held_out = await asyncio.to_thread(self.speaker.extract, samples[3])
            if sorted(float(held_out @ value) for value in prints)[-2] < 0.75:
                raise ValueError(
                    "Owner test sample did not match. Enrollment remains off"
                )
            salt = secrets.token_bytes(32)
            key = await asyncio.to_thread(self.key, password, salt)
            payload = json.dumps(
                {"model": MODEL_SHA256, "prints": [v.tolist() for v in prints]}
            ).encode()
            sealed = Fernet(key).encrypt(payload).decode()
            temporary = self.path.with_suffix(".tmp")
            temporary.touch(mode=0o600)
            temporary.chmod(0o600)
            temporary.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "salt": base64.b64encode(salt).decode(),
                        "sealed": sealed,
                    }
                )
            )
            temporary.replace(self.path)
            self.lock()
            self.prints = prints
            self.leases[token] = time.monotonic() + self.LEASE_SECONDS

    async def unlock(self, token, password):
        async with self.mutex:
            if time.monotonic() < self.retry_at:
                raise ValueError("Too many unlock attempts. Wait one minute")
            try:
                envelope = json.loads(self.path.read_text())
                if envelope["version"] != 1:
                    raise ValueError("Unsupported owner profile")
                key = await asyncio.to_thread(
                    self.key,
                    password,
                    base64.b64decode(envelope["salt"], validate=True),
                )
                value = json.loads(Fernet(key).decrypt(envelope["sealed"].encode()))
                if value["model"] != MODEL_SHA256 or len(value["prints"]) != 3:
                    raise ValueError("Invalid owner profile")
                prints = [normalize(v) for v in value["prints"]]
            except (InvalidToken, ValueError, KeyError, OSError, TypeError) as error:
                self.failures += 1
                if self.failures >= 5:
                    self.retry_at = time.monotonic() + 60
                    self.failures = 0
                raise ValueError(
                    "Passphrase incorrect or owner profile damaged"
                ) from error
            self.failures = 0
            self.prints = prints
            self.leases[token] = time.monotonic() + self.LEASE_SECONDS

    async def remove(self, token, password):
        await self.unlock(token, password)
        async with self.mutex:
            self.path.unlink()
            self.lock()

    async def verify(self, token, pcm):
        if not self.enabled:
            return True
        async with self.mutex:
            if not self.allowed(token):
                return False
            try:
                vector = await asyncio.to_thread(self.speaker.extract, pcm[: 8 * 32000])
                matches = sorted(float(vector @ v) for v in self.prints)
                # Two enrollment samples must match. No probability claim.
                accepted = matches[-2] >= 0.75
            except Exception:
                accepted = False
            if not accepted:
                self.lock()
            return accepted
