param([switch]$SkipModelDownload)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
& .venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
npm ci --prefix frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
npm run build --prefix frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
if (!(Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force -Path models,data,vendor | Out-Null
if (!(Test-Path vendor\whisper.cpp)) {
    git clone --depth 1 --branch v1.8.3 https://github.com/ggml-org/whisper.cpp vendor\whisper.cpp
    if ($LASTEXITCODE -ne 0) { throw 'Whisper source download failed' }
}
cmake -S vendor\whisper.cpp -B vendor\whisper.cpp\build -DWHISPER_BUILD_SERVER=ON -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=OFF
if ($LASTEXITCODE -ne 0) { throw 'Whisper configuration failed' }
cmake --build vendor\whisper.cpp\build --config Release -j 4
if ($LASTEXITCODE -ne 0) { throw 'Whisper build failed' }
if (Test-Path vendor\whisper.cpp\build\bin\Release) { Copy-Item vendor\whisper.cpp\build\bin\Release\* vendor\whisper.cpp\build\bin -Force }
if (!$SkipModelDownload) {
    & .venv\Scripts\python.exe scripts/start.py --download-models
    if ($LASTEXITCODE -ne 0) { throw 'Speech model verification failed' }
} else {
    Write-Host 'Speech models intentionally skipped. Download before using voice conversation.'
}
Write-Host 'Install native Ollama. Run start.ps1, then in another terminal: $env:OLLAMA_HOST="127.0.0.1:11437"; ollama pull qwen3:4b-instruct'
Write-Host 'Configure JARVIS_APPLICATIONS with allowlisted absolute .exe paths. Windows operation is not verified on the Mac development host.'
