"""Official model assets, verified before use. No raw audio or credentials."""

import hashlib
import time
import urllib.request
from pathlib import Path

ASSETS = {
    "ggml-small.bin": (
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    ),
    "silero_vad.onnx": (
        "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.1/src/silero_vad/data/silero_vad.onnx",
        "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
    ),
    "en_US-ljspeech-high.onnx": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx",
        "5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a",
    ),
    "en_US-ljspeech-high.onnx.json": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx.json",
        "7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14",
    ),
    "kokoro-v1.0.onnx": (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
        "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    ),
    "voices-v1.0.bin": (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin",
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in ASSETS.items():
        target = directory / name
        if target.is_file() and digest(target) == expected:
            print("Verified " + name, flush=True)
            continue
        temporary = target.with_name(name + ".partial")
        for attempt in range(3):
            try:
                print("Downloading " + name, flush=True)
                # Avoid expired cached GitHub release redirects.
                request = urllib.request.Request(
                    url + "?download=" + str(time.time_ns()),
                    headers={"User-Agent": "Jarvis-Local-Setup/0.1"},
                )
                with (
                    urllib.request.urlopen(request, timeout=60) as response,
                    temporary.open("wb") as output,
                ):
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                if digest(temporary) != expected:
                    raise ValueError("SHA256 mismatch for " + name)
                temporary.replace(target)
                break
            except Exception:
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
