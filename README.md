# Jarvis Local

A working local personal voice assistant: React/TypeScript dashboard, native Ollama, Metal-accelerated whisper.cpp, Silero ONNX voice activity detection, local Kokoro voices with maintained Piper fallback, FastAPI/WebSocket, and SQLite/FTS5. The offline assistant does not require a paid API, subscription or cloud inference. Optional model APIs, expressive Groq voices, optional Google Calendar and news feeds use internet only when enabled/configured.

The verified development target is Apple M5 MacBook Pro, 24 GB unified memory, macOS 27.0.1. Source and Windows build scripts are included; Windows runtime, installer, permissions and audio remain unverified. This is a development release, not a claim of universal hardware support or readiness for commercial sale.

## Download

[Public source](https://github.com/rythmscape11/jarvis-local-community) · [Releases and downloads](https://github.com/rythmscape11/jarvis-local-community/releases)

The macOS Apple Silicon development archive includes the Python runtime, frontend and native Whisper server. Copy Jarvis Local.app to Applications, install native Ollama, and download the models before first launch:

```sh
"/Applications/Jarvis Local.app/Contents/Resources/runtime/jarvis-runtime" --download-models
OLLAMA_HOST=127.0.0.1:11437 OLLAMA_NO_CLOUD=1 ollama serve
# In another terminal:
OLLAMA_HOST=127.0.0.1:11437 ollama pull qwen3:4b-instruct
```

Then open Jarvis Local from Applications. The archive is a development build, without Apple Developer ID signing/notarization. macOS may prevent launch; do not disable system protections. Use the source setup below or wait for a signed release if your system blocks the preview. Windows source/build instructions are included; no verified Windows installer is claimed.

Each person configures their own optional API keys and Google connections in Settings. No developer account, shared API, personal database or memory is supplied. See [privacy, OS-user isolation and update behaviour](docs/PRIVACY_AND_UPDATES.md).

## Fresh macOS setup

Prerequisites: Apple Silicon Mac, Python 3.11+, Node 22+, CMake 3.21+, Git, and Xcode Command Line Tools. `xcode-select --install` installs Apple's compiler tools. Install [native Ollama](https://ollama.com/download/mac). Do not use Docker for inference. A 24 GB Mac comfortably meets the initial target; smaller machines need a smaller configurable model. Intel Mac builds must be compiled and verified separately.

```sh
git clone https://github.com/rythmscape11/jarvis-local-community.git
cd jarvis-local-community
./setup
./start
```

If the faster default qwen3:4b-instruct is not already downloaded, in a second terminal while the launcher runs:

```sh
OLLAMA_HOST=127.0.0.1:11437 ollama pull qwen3:4b-instruct
```

If Ollama is not yet running, start an isolated native service first:

```sh
OLLAMA_HOST=127.0.0.1:11437 OLLAMA_NO_CLOUD=1 ollama serve
```

No API account is required for local inference. This source repository is public.

Explicit verified speech-model download command (also run by setup; verifies SHA-256 and skips complete matching downloads):

```sh
.venv/bin/python scripts/start.py --download-models
```

Individual Whisper/VAD/Piper download examples:

```sh
curl -fL https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin -o models/ggml-small.bin
curl -fL https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.1/src/silero_vad/data/silero_vad.onnx -o models/silero_vad.onnx
.venv/bin/python -m piper.download_voices --download-dir models en_US-ljspeech-high
```

Approximate downloads: Qwen3 4B instruct Q4_K_M 2.5 GB (optional Qwen3 8B 5.23 GB), Kokoro ONNX 325 MB and shared voices 28 MB, multilingual Whisper small 488 MB (465 MiB), Silero 2.3 MB, default Piper LJ Speech high 114 MB (109 MiB) plus 5 KB JSON. Native runtimes and dependencies add disk usage. Paths and model names are configurable in `.env` and Settings. Alternative Whisper ggml models are available from [whisper.cpp's official model instructions](https://github.com/ggml-org/whisper.cpp/tree/v1.8.3/models); smaller models trade recognition quality for speed.

## Desktop installer build

```sh
./scripts/package-mac.sh
open "desktop/release/mac-arm64/Jarvis Local.app"
```

The Mac app bundles the Python runtime, frontend and native whisper-server. It relies on separately installed native Ollama and downloaded models, which are deliberately excluded from Git and the app bundle. The packaged app uses `~/Library/Application Support/Jarvis Local` for data and models. Before its first launch on another Mac, use the bundled downloader:

```sh
"desktop/release/mac-arm64/Jarvis Local.app/Contents/Resources/runtime/jarvis-runtime" --download-models
OLLAMA_HOST=127.0.0.1:11437 ollama pull qwen3:4b-instruct
```

Install by copying the .app to Applications. The current development build is unsigned; a signed/notarized release requires Apple Developer credentials. Do not imply Gatekeeper readiness from a local launch. In the installed app, Settings → Start Jarvis when I log in uses the operating system login-item API. Actual reboot/login activation must be checked on the target Mac. Wake listening needs prior microphone consent; enabling login startup alone does not authorize microphone capture.

Windows source setup requires Python 3.11+, Node 22+, Git, CMake, Visual Studio C++ build tools and native Ollama:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
powershell -ExecutionPolicy Bypass -File start.ps1
# Build on an actual Windows host:
powershell -ExecutionPolicy Bypass -File scripts/package-windows.ps1
```

This emits an NSIS installer on Windows. The Windows target is x64, with CPU whisper.cpp by default. The Mac binary cannot be used on Windows. Windows bundle paths use explicitly configured absolute .exe names in JARVIS_APPLICATIONS; the shipped example uses Mac identifiers. Adjust that allowlist before enabling Windows application actions. Windows ARM and Intel Mac compatibility are not established by these scripts.

## Using Jarvis

- **Text:** type a message or choose an example. Qwen output streams; executed tool results appear separately.
- **Voice:** Start conversation for natural turn-taking: speak, then pause. Silero ends the utterance automatically. Push to talk (Option+Space) remains available; this fallback uses Finish speaking. Echo cancellation is requested. The actual input sample rate is shown; AudioWorklet PCM is resampled correctly. The browser smoke test captured at 44,100 Hz, not an assumed 16 kHz.
- **Hands-free:** activate a session explicitly; Silero finds speech boundaries. Microphone capture is retained during output for spoken interruption. Strong speech requests an immediate provisional playback pause; local Whisper checks whether it is a new request, a stop command, or speaker echo. Say “Stop speaking,” “Please stop talking,” or “Could you stop speaking please?”; address a new question to “Jarvis.” Accepted interruptions cancel generation and discard all old audio. Stop (Esc) remains an immediate fallback. Speaker echo rejection avoids a new answer; begin interruptions with “Jarvis” or an explicit stop command. Stop/Escape closes the microphone and preserves that paused state across restart. Use headphones where acoustic echo cancellation is unreliable.
- **Wake:** enable Listen locally for “Hey Jarvis.” Silero segments speech and native Whisper verifies the wake phrase. While waiting, non-wake speech is discarded. One “Hey Jarvis” opens a 45-second follow-up window renewed after each completed reply, so subsequent questions need no repeated wake phrase. After inactivity the UI returns to Waiting for Hey Jarvis. Say a command after the phrase, or say “Hey Jarvis,” wait for “I'm listening,” then speak. It adds transcription latency and is not a dedicated instant keyword engine. Once enabled, the desktop attempts to rearm at launch if OS microphone permission allows it. A stopped session stays paused across launches until explicitly reactivated.
- **Voice quality:** open Choose voice for the numbered Downloaded Kokoro voices group with fourteen local English voices (Heart on fresh offline installs) and the Piper fallback; choose natural, brisk or relaxed pacing. Scroll inside the list; local and online choices are grouped separately. Human naturalness is subjective. No Bengali voice quality or spoken Bengali capability is claimed. Bengali/mixed-language recognition is configurable; Bengali responses remain text with an explicit English voice fallback.
- **Fullscreen:** expand the voice panel. Its spectrum and contour use actual microphone/speaker samples, with keyboard-accessible stop/mute/exit and reduced-motion support.
- **Automatic conversation memory:** every user and assistant turn is stored locally. Relevant past user messages are searched across chats automatically, including all existing saved conversations, without pressing “Remember this.” Only user statements enter the personal recall index; assistant guesses do not become personal facts. Memory → Search / inspect shows recent messages (100 at a time) or up to 20 relevant full records; edit or delete a message, or clear all conversation history. Correcting a message removes its paired old answer and summaries. Explicit preferences and notes remain separate. Recall uses SQLite FTS5 literal keyword search, not model retraining or perfect semantic recall; only bounded relevant excerpts fit the configured context. Disable automatic recall in Settings if desired. Online providers receive selected excerpts. Forgetting an explicit preference also purges chat context to prevent resurrection.
- **Documents:** select a directory by absolute path, wait for the indexing job to succeed, then search. TXT/Markdown/common code are supported. Binary, credential-like and oversized files, dependency folders, and symlink escapes are excluded. Search returns actual filenames and excerpts. Removing a selected root deletes its index; it never deletes source files.
- **Reminders:** relative dates use the current local time and Asia/Kolkata. Notes/reminders persist. Notifications appear in the dashboard while it runs; acknowledged reminders do not repeat after restart. Overdue pending reminders return after restart. This is not an OS reminder daemon when Jarvis is closed.
- **Jobs:** one bounded worker maintains durable queued/running/succeeded/failed/cancelled/interrupted states. Startup never silently replays uncertain writes.
- **News:** selected world/India/business/technology/science/politics/sport/culture RSS feeds refresh every 24 hours while Jarvis runs, and can be refreshed manually. Source URLs and timestamps are retained. Queries/search stay local. Cached news is not exhaustive, immediate/live coverage is not guaranteed, and offline age is always visible. Analysis comes from the selected model and must be distinguished from source facts. RSS publisher terms need separate review for a commercial product.
- **Optional API model:** select OpenAI-compatible API, specify a local HTTP or remote HTTPS base URL and model ID, and store its key in the OS keychain. Hosted inference sends conversation and requested tool results to that endpoint; there is no automatic fallback. SSE chat/completions and tool-call-capable providers are supported by this adapter. Arbitrary noncompatible protocols require their own adapter. Groq live inference and voice-command execution were verified with the owner-configured key. Credentials remain in the OS keychain; Settings → Test connection sends only a synthetic test prompt. Groq requires internet and is subject to the account’s current quotas and pricing.
- **System control:** off by default. Enable owner-reviewed control, request a bounded click/scroll/hotkey/ASCII typing action in a configured application, inspect the pending request, then approve or reject it. No model request can approve itself. After approval, switch to the target within three seconds; the adapter refuses an unexpected foreground app. macOS needs Accessibility/Automation permission, and previews need Screen Recording. Primary monitor only; input delivery does not prove the app task succeeded. Corner fail-safe remains enabled. Shell execution, purchases, automatic message sending and unchecked autonomous control are not implemented.
- **Calendar:** Google Desktop OAuth with PKCE and OS-keychain tokens. Read-only and owner-reviewed event creation/editing scopes are separate. New events have no invitations; editing recurring events is not supported. Calendar writing requires the user's actual grant. Email creation/replying also requires reviewing exact recipient and content before sending.

## Offline use and verification

After setup, local text/voice, tools, document search, memory and jobs use only loopback/native engines. Disable news networking and leave the provider set to Ollama to run without external requests. Disconnect Wi-Fi and repeat a voice question. Optional calendar, news refresh and hosted models require internet. No raw audio is retained by default; no cloud fallback or telemetry is added.

```sh
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
npm test --prefix frontend
npm run build --prefix frontend
.venv/bin/python scripts/live_smoke.py
.venv/bin/python scripts/wake_smoke.py
```

Live scripts create clearly identified fixture records and a generated audio sample. They test actual engines with synthesized input; they do not prove a physical microphone, room acoustics, owner voice recognition or Windows operation. See [VERIFICATION.md](docs/VERIFICATION.md) for measured results, acceptance status and the exact manual procedure. Backend/API provider tests using substitutes are labelled separately.

## Troubleshooting

Microphone denied: allow the browser/Jarvis app in macOS Privacy & Security → Microphone, then start a new session. Device changes end the old capture safely; choose the new input in Settings. Use headphones if room echo tails trigger unwanted speech after playback. Spoken interruption is available in an explicitly active conversation/wake session. If echo suppression is unreliable, use headphones and begin with “Jarvis”; Esc/Stop remains available. Physical room acoustics still require the manual test in VERIFICATION.md.

Model unavailable: ensure native Ollama runs on the configured isolated port and `ollama list` on that host shows a local model. Cloud aliases are rejected by the local adapter. Voice unavailable: run the verified model downloader. Kokoro requires its ONNX plus shared voices BIN; Piper requires ONNX and JSON. STT unavailable: verify whisper-server and WHISPER_MODEL, then restart. Silence/empty transcripts produce an explicit message rather than an invented answer. API errors appear as errors, never successful tools.

Port occupied: run doctor and inspect the owner; do not kill unrelated services. Default backend is 8765, Whisper 8178, Ollama 11437. Bindings remain loopback. In development, use the built dashboard served by FastAPI; the exact-origin guard deliberately does not authorize arbitrary Vite preview origins.

Authentication: launch through ./start or the desktop app. The access token is in private data/auth.token and must not be put in Git or screenshots. Session cookies expire after 12 hours. Restart/open through the launcher to bootstrap again. App logs, SQLite data, secrets, models and caches are ignored by Git. Optional screen previews stay local and are not automatically submitted to the model.

Detailed [configuration/tool extension](docs/CONFIGURATION.md), [audio and WebSocket contract](docs/AUDIO_PROTOCOL.md), and [license inventory](docs/LICENSES.md) are included. The code uses GPL-3.0-only with the maintained Piper runtime; public commercial distribution requires the applicable source/notice obligations and model/feed license review. The public source and development release are distributed under GPL-3.0-only.

## Expressive voices, stories and voice-created documents

Say “Change your voice to Hannah” (online), “Change your voice to Tara” (local Indian female) or “Change your voice to Rishi” (local Indian male). The voice picker also offers previews and changes the saved selection. Recognition of unfamiliar names varies: if the transcript shows another word, use the picker rather than accepting an incorrect change. This was observed with a synthetic Piper recording of Hannah. Spoken instructions can also request a calm female voice without a name.

Enable Groq online voice explicitly in Settings and save a Groq key in the OS keychain. Voices: Hannah, Diana, Autumn, Austin, Daniel and Troy. Text sent for speech is sent to Groq. Speech requires separate Orpheus account access; the owner completes any legal acceptance. The engine reuses an HTTP client, validates actual non-silent PCM, repairs streamed WAV header sizes, limits each request to 200 characters, and applies conservative 10 requests/minute pacing. Account quotas and pricing apply; this may create pauses during long narration. Ordinary conversation omits vocal directions, following the Orpheus guidance. An optional `online_voice_fallback` setting lets you select a downloaded local voice if online speech fails. The default is disabled (`none`); when selected, Jarvis shows a notice and uses that local voice for the rest of the current reply, without changing the saved primary voice. Without a fallback, a silent/error/quota response preserves the on-screen answer and stops further TTS for that turn. No local engine automatically sends text to a hosted service. See [official Orpheus documentation](https://console.groq.com/docs/text-to-speech/orpheus).

For extended offline stories, select a local voice. Explicit story, poem and detailed requests raise the output budget to 2,048 tokens and permit up to 48 spoken sentences (configurable). Ordinary replies remain concise. Family-friendly mode adds guidance for children; it is not a certified child-safety moderation service. Context and selected memory continue to build on prior turns. Narrative and poetry directions apply to Orpheus; local voices use their normal cadence. A dedicated singing model and verified musical performance are not implemented. The TTS adapter supports documented expressive directions, but laugh/singsong quality is not verified and is not automatically inserted into ordinary replies.

Say “Create a Word document from this voice note…” with a title and body, or request PDF/Markdown. Jarvis creates a real local draft, checks it, records its hash, and returns a verified result. Workspace → Notes & documents lists downloads. DOCX is editable. Basic headings, bullets and numbered lists are supported; markup cannot load external images or execute code. Files stay in the private data folder with restricted permissions. Repeated identical tool keys return one document. Documents are drafts for review; uncertain dictation may need correction. Bengali PDF fonts are not configured; use DOCX/Markdown for Bengali text.

Native Indian voices use Apple's installed voice assets through a reusable helper/system speech daemon. No Apple voice model is redistributed. Fresh Macs may require downloading the voice in system settings. Windows builds retain Kokoro/Piper and optional Groq; the Apple voice adapter does not run on Windows.


Keychain prompts: use your Mac login password in the macOS dialog and choose Always Allow for the Jarvis credential when offered. Model and online speech share a single endpoint-scoped read, reuse an approved key only in process memory, and never write it to logs or ordinary files. Denial is remembered for the current process to prevent prompt loops; Settings → Test API connection explicitly retries. Changing/removing a key invalidates the cached read. An unsigned update may still require new OS approval. Do not reset the entire Keychain to troubleshoot this app. [Apple guidance](https://support.apple.com/guide/keychain-access/kyca1243/mac).

Windows verification: `.github/workflows/windows.yml` is a manual, bounded Windows 2025 build job. It installs pinned dependencies, builds native Whisper, runs regression checks, creates an unsigned NSIS installer and exercises the actual frozen backend with disposable records. It does not establish microphone, installer UI, voice inference, login startup, Windows ACL privacy or Windows signing. Run it from the private repository Actions page after checking the account’s included Actions minutes/budget; no paid capacity or automatic trigger is enabled.

## Local workflows and optional Google connections

Workspace → Automations adds ten workflow families, private local background analysis, schedules, checked DOCX/PDF/MD/CSV/XLSX/PPTX drafts, inspectable activity and exact owner-reviewed writes. Google Gmail reading/threaded replies, Tasks, Drive uploads, named public API reads and local Home Assistant lights require their real connection prerequisites. Google Gemini is an optional free-tier preset, never a cloud fallback. See [automation setup, privacy and limitations](docs/AUTOMATIONS.md).

Daily guidance and the current device/Google integration limits are documented in [DAILY_GUIDE_AND_DEVICES.md](docs/DAILY_GUIDE_AND_DEVICES.md). Fullscreen is a labelled toolbar button that opens the minimalist voice view; Exit fullscreen returns to a normal window.

Groq HTTP 429 responses are rate limits, not proof that your entire account quota is exhausted. Jarvis reports the minute/day token/request category and retry delay when provided by Groq; malformed provider errors stay generic. The console Cost view is not a real-time speech-limit counter. A live Hannah probe on 5 October 2026 succeeded with 52 requests remaining; earlier rate-limit responses were not captured and their exact bucket cannot be reconstructed. See `docs/groq-voice-rate-limit-check.json`.

## Software updates and privacy

The app checks the fixed public release feed daily, displays a notice for newer versions and provides an owner-reviewed download link. Disable checks for offline use. No silent installation or cross-user memory syncing occurs. Each installation uses its own OS credential store and local records; people sharing an unlocked OS account share one workspace. [Details and release procedure](docs/PRIVACY_AND_UPDATES.md).

## Optional owner protection

Explicit enrollment combines a local encrypted voiceprint with a passphrase lease. Unknown voices stay locked. This experimental feature is off until enrollment; replay is a known limitation. See [model download, enrollment, tests, deletion and recovery](docs/OWNER_VOICE_SECURITY.md).
