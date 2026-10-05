$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$JarvisRoot = (Get-Location).Path
$env:PYTHONPATH = "$JarvisRoot\backend"
& .venv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --name jarvis-runtime --distpath build --workpath build\pyinstaller --specpath scripts --paths "$JarvisRoot\backend" --add-data "$JarvisRoot\backend;backend" --add-data "$JarvisRoot\frontend\dist;frontend/dist" --collect-all piper --collect-all sherpa_onnx --collect-all sherpa_onnx_core --collect-all cryptography --collect-all onnxruntime --collect-all jarvis --hidden-import jarvis.main --collect-all kokoro_onnx --collect-all espeakng_loader --collect-all phonemizer --collect-all language_tags --collect-all segments --collect-all csvw --collect-all openpyxl --collect-all pptx --collect-all docx --collect-all reportlab --collect-all pypdf --hidden-import uvicorn --hidden-import keyring.backends.Windows --hidden-import scipy.signal --hidden-import pyautogui scripts\start.py
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed' }
npm ci --prefix desktop
if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed' }
npm run dist:win --prefix desktop
if ($LASTEXITCODE -ne 0) { throw 'Windows installer packaging failed' }
