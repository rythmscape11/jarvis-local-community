#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
jarvis_root="$(pwd)"
swiftc native/mac-voice.swift -o native/mac-voice
PYTHONPATH="$jarvis_root/backend" .venv/bin/pyinstaller --noconfirm --clean --onedir --name jarvis-runtime --distpath build --workpath build/pyinstaller --specpath scripts --paths "$jarvis_root/backend" --add-data "$jarvis_root/backend:backend" --add-data "$jarvis_root/frontend/dist:frontend/dist" --collect-all piper --collect-all onnxruntime --collect-all jarvis --hidden-import jarvis.main --collect-all kokoro_onnx --collect-all espeakng_loader --collect-all phonemizer --collect-all language_tags --collect-all segments --collect-all csvw --collect-all openpyxl --collect-all pptx --collect-all docx --collect-all reportlab --collect-all pypdf --hidden-import pyautogui --hidden-import uvicorn --hidden-import keyring.backends.macOS --hidden-import keyring.backends.Windows --hidden-import scipy.signal scripts/start.py
npm ci --prefix desktop
CSC_IDENTITY_AUTO_DISCOVERY=false npm run dist:mac --prefix desktop
