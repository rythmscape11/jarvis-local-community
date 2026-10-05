#!/usr/bin/env python3
"""Explicit speaker model download with size and SHA256 verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from jarvis.config import MODELS
from jarvis.owner import download_model

if __name__ == "__main__":
    download_model(MODELS)
