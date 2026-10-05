#!/usr/bin/env python3
"""Install optional fixed local voices. Downloads weights; never uses inference APIs."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPOS = {
    "qwen": (
        "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
        "f35faf19b0cc2160865af64ecf0f22f83d335135",
        "qwen-tts",
    ),
    "chatterbox": (
        "mlx-community/chatterbox-multilingual-v3",
        "03565773edd72e949572557597af8063bb49a18a",
        "chatterbox",
    ),
    "indic": (
        "ai4bharat/indic-parler-tts",
        "7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca",
        "indic-parler",
    ),
    "s3": (
        "mlx-community/S3TokenizerV2",
        "e0c9886f0e1c35ae85b1f27277416fb19fc72bec",
        "s3-tokenizer",
    ),
    "description": (
        "google/flan-t5-large",
        "0613663d0d48ea86ba8cb3d7a44f0f65dc596a2a",
        "indic-parler/description-tokenizer",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=["qwen", "chatterbox", "indic"])
    parser.add_argument(
        "--data", type=Path, required=True, help="Your Jarvis data directory"
    )
    parser.add_argument("--models", type=Path, help="Optional model directory override")
    parser.add_argument(
        "--source-models",
        type=Path,
        help="Copy already downloaded models instead of using the network",
    )
    args = parser.parse_args()
    if args.engine != "indic" and (
        platform.system() != "Darwin" or platform.machine() != "arm64"
    ):
        parser.error(
            "The MLX voice adapter currently requires Apple Silicon macOS. Kokoro and Piper remain available on Windows."
        )
    root = Path(__file__).resolve().parents[1]
    data = args.data.expanduser().resolve()
    models = (args.models or data / "models").expanduser().resolve()
    family = "indic" if args.engine == "indic" else "mlx"
    environment = data / "voice-runtimes" / family
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(
                root
                / "requirements"
                / (
                    "voices-indic.lock"
                    if family == "indic"
                    else "voices-mlx-macos.lock"
                )
            ),
        ],
        check=True,
    )
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    engines = [args.engine] + (
        {"qwen": [], "chatterbox": ["s3"], "indic": ["description"]}[args.engine]
    )
    for engine in engines:
        repo, revision, directory = REPOS[engine]
        target = models / directory
        if args.source_models:
            source = args.source_models.expanduser().resolve() / directory
            if not source.is_dir():
                parser.error(f"Missing downloaded model directory: {directory}")
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".cache"),
            )
        else:
            patterns = (
                ["tokenizer*", "spiece.model", "special_tokens_map.json"]
                if engine == "description"
                else [
                    "*.json",
                    "*.safetensors",
                    "*.txt",
                    "*.model",
                    "speech_tokenizer/*",
                ]
            )
            code = "from huggingface_hub import snapshot_download; import sys,json; a=json.loads(sys.argv[1]); snapshot_download(**a)"
            subprocess.run(
                [
                    str(python),
                    "-c",
                    code,
                    json.dumps(
                        {
                            "repo_id": repo,
                            "revision": revision,
                            "local_dir": str(target),
                            "allow_patterns": patterns,
                            "max_workers": 2,
                        }
                    ),
                ],
                check=True,
            )
        print("Installed", directory, flush=True)
    if args.engine == "chatterbox" and not all(
        (models / "chatterbox" / f"{v}.wav").exists() for v in ["female", "male"]
    ):
        print(
            "Chatterbox needs synthetic reference presets. From a configured source checkout run scripts/prepare-chatterbox-voices.py with JARVIS_MODELS set to this directory."
        )
    if args.engine == "indic":
        print(
            "Indic access must be granted by AI4Bharat. Authenticate using hf auth login privately if the download reports access denied. Never paste tokens into Jarvis chat."
        )


if __name__ == "__main__":
    main()
