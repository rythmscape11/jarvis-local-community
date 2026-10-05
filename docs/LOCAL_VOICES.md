# Optional local multilingual speech

Heart remains the default. All optional engines use separate, persistent worker processes; cancellation stops only the owned worker and discards its response. No microphone recordings are saved. Inference sets Hugging Face and Transformers offline flags and disables telemetry. Engine/model downloads require internet once. This is not a claim that a physically disconnected network test has been performed.

| Engine | Runtime | Download excluding Python packages | Language scope |
|---|---|---:|---|
| Kokoro | Core ONNX | Existing bundle | English plus Hindi, French, Spanish, Italian, Portuguese presets. Each of those language paths generated a valid WAV in this pass. |
| Qwen CustomVoice 1.7B 4-bit | MLX, Apple Silicon only | 2.31 GB | English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian. English tested; no Bengali/Hindi support. |
| Chatterbox multilingual | MLX, Apple Silicon only | 2.71 GB + 0.495 GB S3 tokenizer | Upstream advertises 23 languages including Hindi, excluding Bengali. English tested; other languages need listening evaluation. Two synthetic Kokoro reference voices, not a person's cloned voice. |
| Indic Parler | Separate PyTorch runtime | About 3.76 GB + description tokenizer | Upstream advertises 21 languages, including Bengali/Hindi. Gated download needs the owner's own access consent/login. Do not claim ready until all required files and runtime exist and actual synthesis passes. |

The registry exposes optional voices only when prerequisite files/runtime exist. Availability checks are prerequisites, not guarantees of voice quality or pronunciation. Recognition language and speech-engine support are separate. Unsupported speech leaves the full text visible; an English voice can be selected. No automatic unrequested cloud switch occurs.

From the repository, after core setup:

```sh
.venv/bin/python scripts/install-local-voices.py qwen --data "$HOME/Library/Application Support/Jarvis Local"
.venv/bin/python scripts/install-local-voices.py chatterbox --data "$HOME/Library/Application Support/Jarvis Local"
# Generate references in the SAME installed model folder (requires core Kokoro assets):
JARVIS_MODELS="$HOME/Library/Application Support/Jarvis Local/models" PYTHONPATH=backend .venv/bin/python scripts/prepare-chatterbox-voices.py

```

Indic installation uses the same command with `indic`. Review the publisher's access agreement first, then sign the Hugging Face client in privately; never paste a token into chat. The installer uses pinned repository revisions and compatible, separate dependency locks. `--source-models models` copies an already downloaded local model tree without requiring credentials. `JARVIS_MLX_PYTHON` and `JARVIS_INDIC_PYTHON` override the Python executable; `JARVIS_MODELS` overrides model storage. Optional runtimes are not bundled in the default installer. Windows MLX is unsupported; Windows Indic/PyTorch remains unverified.

Pinned sources: [MLX Qwen weights](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit) revision `f35faf19b0cc2160865af64ecf0f22f83d335135`; [Chatterbox MLX weights](https://huggingface.co/mlx-community/chatterbox-multilingual-v3) revision `03565773edd72e949572557597af8063bb49a18a`; [S3 tokenizer](https://huggingface.co/mlx-community/S3TokenizerV2) revision `e0c9886f0e1c35ae85b1f27277416fb19fc72bec`; [Indic Parler](https://huggingface.co/ai4bharat/indic-parler-tts) revision `7b527af5ee8ed1f9a28d80b19703ed9bb8ba10ca`. Review upstream model and dependency license notices before redistribution. Indic description tokenizer is pinned to `google/flan-t5-large` revision `0613663d0d48ea86ba8cb3d7a44f0f65dc596a2a`; its language-model weights are not downloaded for that tokenizer.

The Kokoro upstream integer-speed conversion could truncate a fractional speed to zero, causing the ONNX Loop/Expand failure. Jarvis now forwards the requested speed as float32. Actual synthesis passed at configured pace 0.8, 1.0, 1.2 and 1.4. Larger pace values slow speech.
