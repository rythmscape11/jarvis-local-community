#!/usr/bin/env python3
import platform
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from jarvis import config
from jarvis.engines import Silero
import importlib.metadata as metadata


def main():
    failures = []

    def check(name, ok, detail):
        print(("OK   " if ok else "FAIL ") + name + ": " + str(detail))
        if not ok:
            failures.append(name)

    print("Jarvis Local doctor — " + platform.platform())
    check(
        "Architecture",
        platform.machine() in {"arm64", "aarch64", "AMD64", "x86_64"},
        platform.machine(),
    )
    check("Python", sys.version_info >= (3, 11), platform.python_version())
    for package in [
        "fastapi",
        "piper-tts",
        "onnxruntime",
        "httpx",
        "uvicorn",
        "kokoro-onnx",
        "espeakng-loader",
        "python-docx",
        "reportlab",
        "pypdf",
    ]:
        try:
            check(package, True, metadata.version(package))
        except metadata.PackageNotFoundError:
            check(package, False, "Run setup")
    check(
        "Dashboard build",
        (config.ROOT / "frontend/dist/index.html").exists(),
        "frontend/dist/index.html",
    )
    binary = (
        config.ROOT
        / "vendor/whisper.cpp/build/bin"
        / ("whisper-server.exe" if sys.platform == "win32" else "whisper-server")
    )
    check("whisper.cpp", binary.exists(), binary)
    check(
        "Whisper small",
        (config.MODELS / "ggml-small.bin").exists(),
        config.MODELS / "ggml-small.bin",
    )
    check(
        "Piper voice",
        (config.MODELS / "en_US-ljspeech-high.onnx").exists()
        and (config.MODELS / "en_US-ljspeech-high.onnx.json").exists(),
        "en_US-ljspeech-high",
    )
    check(
        "Kokoro voices",
        (config.MODELS / "kokoro-v1.0.onnx").exists()
        and (config.MODELS / "voices-v1.0.bin").exists(),
        "8 selectable local English voices",
    )
    if sys.platform == "darwin":
        check(
            "Native Indian voice helper",
            (config.ROOT / "native/mac-voice").is_file(),
            "Run setup to compile native/mac-voice.swift",
        )
    try:
        check("Silero ONNX", True, Silero().probability(bytes(1024)))
    except Exception as error:
        check("Silero ONNX", False, str(error))
    import asyncio
    from jarvis.engines import Ollama, Whisper

    async def engines():
        model = Ollama()
        whisper = Whisper()
        try:
            available = await model.available()
            check(
                "Ollama local model",
                "qwen3:4b-instruct" in available,
                "qwen3:4b-instruct (offline baseline)",
            )
        except Exception:
            check(
                "Ollama service",
                False,
                "Not running; ./start launches native Ollama when its port is free",
            )
        print(
            "INFO Whisper service: "
            + ("running" if await whisper.health() else "stopped; ./start launches it")
        )
        await model.close()
        await whisper.close()

        from jarvis.providers import ModelRouter

        provider = ModelRouter(config.read_settings)
        try:
            check(
                "Selected provider",
                config.read_settings().model in await provider.available(),
                config.read_settings().provider,
            )
        except Exception:
            check(
                "Selected provider", False, "Check provider settings and connectivity"
            )
        finally:
            await provider.close()

    asyncio.run(engines())
    for port in (config.PORT, 8178, 11437):
        with socket.socket() as sock:
            busy = sock.connect_ex(("127.0.0.1", port)) == 0
        print(
            f"INFO Port {port}: "
            + ("in use; verify service ownership" if busy else "available")
        )
    print(
        "MANUAL Microphone: browser/electron permission requires a user gesture. Start conversation, allow microphone, verify native sample rate, say a question and pause for automatic turn detection."
    )
    print(
        "MANUAL Offline: disconnect Wi-Fi after setup; repeat the voice test. News refresh, calendar and hosted model providers require network."
    )
    print(
        "RESULT "
        + (
            "dependencies ready"
            if not failures
            else str(len(failures)) + " prerequisites need attention"
        )
    )
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
