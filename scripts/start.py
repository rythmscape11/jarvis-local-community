#!/usr/bin/env python3
"""Loopback supervisor. Terminates only child processes that it started."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
RESOURCE = Path(os.getenv("JARVIS_RESOURCES", str(ROOT)))
if FROZEN:
    from platformdirs import user_data_dir

    os.environ.setdefault("JARVIS_DATA", user_data_dir("Jarvis Local", "Jarvis Local"))
    os.environ.setdefault(
        "JARVIS_MODELS", str(Path(os.environ["JARVIS_DATA"]) / "models")
    )
    sys.path.insert(0, str(ROOT / "backend"))
else:
    sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def json_get(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.load(response)


def occupied(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--no-browser", action="store_true")
    args.add_argument("--serve", action="store_true")
    args.add_argument("--download-models", action="store_true")
    options = args.parse_args()
    if options.download_models:
        from jarvis import config

        from jarvis.model_assets import download

        download(config.MODELS)
        print(
            "Speech models verified. Separately run: OLLAMA_HOST=127.0.0.1:11437 ollama pull qwen3:4b-instruct",
            flush=True,
        )
        return
    if options.serve:
        import uvicorn

        uvicorn.run(
            "jarvis.main:app",
            host="127.0.0.1",
            port=int(os.getenv("JARVIS_PORT", "8765")),
            access_log=False,
        )
        return
    from jarvis import config
    import shutil

    children = []
    handles = []

    def launch(command, env, name, cwd=None):
        logfile = config.DATA / (name + ".log")
        handle = open(logfile, "ab")
        os.chmod(logfile, 0o600)
        handles.append(handle)
        process = subprocess.Popen(
            command, env=env, cwd=cwd or ROOT, stdout=handle, stderr=handle
        )
        children.append(process)
        return process

    def shutdown(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        port = config.PORT
        if occupied(port):
            raise RuntimeError(
                f"Port {port} is occupied. Stop the existing Jarvis instance or change JARVIS_PORT. No unrelated process will be killed."
            )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        env["OLLAMA_NO_CLOUD"] = "1"
        from urllib.parse import urlparse

        ollama_port = urlparse(config.OLLAMA).port or 11434
        if not occupied(ollama_port):
            binary = os.getenv("OLLAMA_BINARY") or shutil.which("ollama")
            if not binary and sys.platform == "darwin":
                candidate = Path("/Applications/Ollama.app/Contents/Resources/ollama")
                binary = str(candidate) if candidate.exists() else None
            if not binary:
                raise RuntimeError(
                    "Native Ollama is missing. Install Ollama for your OS."
                )
            env["OLLAMA_HOST"] = f"127.0.0.1:{ollama_port}"
            launch([binary, "serve"], env, "ollama")
        else:
            json_get(
                config.OLLAMA + "/api/version"
            )  # refuse a port owned by another kind of service
        whisper_port = urlparse(config.WHISPER).port or 8178
        if not occupied(whisper_port):
            binary = Path(
                os.getenv(
                    "WHISPER_BINARY",
                    str(
                        RESOURCE
                        / "vendor/whisper.cpp/build/bin"
                        / (
                            "whisper-server.exe"
                            if sys.platform == "win32"
                            else "whisper-server"
                        )
                    ),
                )
            )
            model_path = Path(
                os.getenv("WHISPER_MODEL", str(config.MODELS / "ggml-small.bin"))
            )
            if not model_path.is_absolute():
                model_path = RESOURCE / model_path
            if not binary.exists() or not model_path.exists():
                raise RuntimeError(
                    "whisper-server or configured STT model is missing. Run ./setup."
                )
            launch(
                [
                    str(binary),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(whisper_port),
                    "-m",
                    str(model_path),
                    "-t",
                    "4",
                    "-sns",
                    "--public",
                    str(RESOURCE / "vendor/whisper.cpp/examples/server/public"),
                ],
                env,
                "whisper",
            )
        server = launch(
            [sys.executable, "--serve"]
            if FROZEN
            else [sys.executable, str(Path(__file__).resolve()), "--serve"],
            env,
            "backend",
        )
        for _ in range(90):
            if server.poll() is not None:
                raise RuntimeError("Backend exited. Inspect data/backend.log.")
            try:
                if json_get(config.ORIGIN + "/api/ready").get("ready"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Backend startup timed out")
        token = (config.DATA / "auth.token").read_text().strip()
        url = config.ORIGIN + "/#token=" + token
        # Access token is intentionally never printed in terminal/logs.
        print("Jarvis Local is ready at " + config.ORIGIN, flush=True)
        if not options.no_browser:
            webbrowser.open(url)
        while server.poll() is None:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError("An owned engine exited. Inspect data logs.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
