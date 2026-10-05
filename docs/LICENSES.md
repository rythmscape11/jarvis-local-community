# Dependency and distribution license notes

Checked against upstream documentation on 5 October 2026. This is a source/packaging inventory, not a claim of commercial clearance for a future product.

| Component | Source license / evidence | Distribution note |
|---|---|---|
| Jarvis Local application | GPL-3.0-only (LICENSE) | Current combined Python runtime includes maintained Piper. Provide corresponding source and notices when distributing under GPL. Commercial sale is possible subject to the applicable license requirements; a proprietary closed-source edition is not established here. |
| Piper 1.8.0 | [OHF-Voice COPYING](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING), GPL-3.0 | Keep GPL source obligations and bundled espeak-ng notices. |
| Piper fallback en_US-ljspeech-high | [Piper model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/high/MODEL_CARD); dataset [LJ Speech](https://keithito.com/LJ-Speech-Dataset/), public domain | Chosen after checking the training dataset rather than relying on the voice repository's general license label. Review model-specific artifacts for any future redistribution. |
| Earlier smoke-test en_US-lessac-medium | [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD), references [research-only dataset terms](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) | Used in initial local verification only. Not the product default or a commercially cleared bundle. Models are excluded from Git and installers. |
| whisper.cpp v1.8.3 | [MIT](https://github.com/ggml-org/whisper.cpp/blob/v1.8.3/LICENSE) | Preserve copyright notice. Metal/Accelerate native on Mac. |
| Whisper small | [OpenAI Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE) | Download model separately. |
| Ollama 0.15.5 tested | [MIT](https://github.com/ollama/ollama/blob/main/LICENSE) | Native prerequisite, not redistributed in the installer. Ollama model licenses remain separate. |
| Qwen3 4B instruct / optional 8B | [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B), Apache-2.0 | User pulls the model through native Ollama. Preserve model notices for future bundles. |
| Silero VAD v6.2.1 | [MIT](https://github.com/snakers4/silero-vad/blob/v6.2.1/LICENSE) | Download only the ONNX model; PyTorch is not an MVP dependency. |
| ONNX Runtime | [MIT](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) | CPU runtime for Piper/Silero. |
| React, Vite, FastAPI, Electron | Upstream MIT licenses | Preserve notices when packaging. |
| SQLite | [Public domain](https://sqlite.org/copyright.html) | FTS5 is included in the tested Python SQLite build. |

A dedicated openWakeWord model was evaluated but not bundled: the framework and pretrained model licenses are distinct, and commercial compatibility must not be inferred from code license alone. The implemented local wake mode uses Silero + native Whisper with an explicit anchored phrase instead.

Before selling publicly: confirm all model/voice notices, fulfill copyleft obligations or replace the adapter with a compatible alternative, test Windows on actual hardware, obtain signing/notarization credentials, perform physical microphone/acoustic checks, and verify any external connector consent and distribution rules. Public source is GPL-3.0-only; the binary is a development preview, not a certified commercial product.


Kokoro ONNX adapter: [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), MIT. Kokoro model: [Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M), Apache-2.0. The phonemizer depends on [eSpeak NG](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING), GPL-3.0-or-later. Preserve the corresponding notices and source obligations for redistributed runtimes.

Creator reference review: the linked KaushikShresth07 version-4 gists were reviewed for architecture ideas; no source code or media was copied. No explicit reuse licence was found in the reviewed gists. The later phone-control Short is by a different creator and links no repository in its expanded description. These references do not establish any commercial reuse permission.


Document exporters use python-docx (MIT), pypdf (BSD-3-Clause), ReportLab (BSD) and ReportLab's bundled Bitstream Vera font under its font license. Preserve package license files in distribution. Apple's native voices are OS-provided assets and are not included in Jarvis downloads or repository. Groq Orpheus is an optional hosted service subject to its current terms/access/pricing; it is not part of the offline core.


Owner protection uses sherpa-onnx 1.13.8 ([Apache-2.0](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/LICENSE)) with a separately downloaded 3D-Speaker CAM++ model ([source and Apache-2.0 licence](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE)). The model and user voiceprints are excluded from downloads. Cryptography 46.0.5 uses Apache-2.0/BSD-3-Clause ([upstream licence files](https://github.com/pyca/cryptography/tree/46.0.5)); packaged third-party licence files remain included.

Timezone portability: pinned first-party [tzdata](https://github.com/python/tzdata) 2026.5 supplies IANA data where an OS database is unavailable, including Windows. Package metadata declares Apache-2.0; preserve its included license notices in frozen distributions.
