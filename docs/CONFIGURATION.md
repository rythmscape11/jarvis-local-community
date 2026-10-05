# Configuration and tool extension

`.env.example` documents loopback ports, model identifiers, explicit paths, and application allowlists. Copy it to `.env`. Environment takes precedence. Model, voice, context budget (4096–8192, initially 4096), timezone (Asia/Kolkata), and recognition language (en/bn/auto) are persisted in data/settings.json through validated backend settings. Native Whisper model path is configured through WHISPER_MODEL and requires a restart. No engine uses a cloud fallback.

Separate SQLite tables: conversations, extractive summaries, explicit memory, notes, reminders, documents/FTS5, directories, background jobs, tool executions, generated_documents, migrations. Schema migrations are tracked by user_version and migrations(version). Migration 1 is idempotent. Future migrations should run transactions once per version, never erase owner data.

Reads and ordinary local notes/reminders are permitted by default. Tools have Pydantic JSON schemas, independently validated arguments, extra-field rejection, risk classification, timeout, structured ok/data or ok/error result, and durable idempotency records. Two tool operations can execute concurrently; per-key locks make concurrent retries share the committed result. Four model tool rounds and at most four calls per round bound the controller. One indexing worker, a 16-job queue, a 120-second deadline, cooperative cancellation and no automatic retries bound background work. Startup marks queued/running jobs and running tool records interrupted; it does not replay uncertain effects.

## Add a tool

1. Define an Arguments subclass in backend/jarvis/tools.py with `extra='forbid'`, strict types, length limits and descriptive fields.
2. Register `(schema, description, risk, timeout_seconds)` in DEFINITIONS.
3. Add an execution branch to Tools.dispatch or delegate it to a connector/platform adapter.
4. Return checked results. A subprocess start is only `launch_requested`; a queued job is only `queued`, never complete.
5. Test malformed inputs, unavailable service, timeouts, duplicate keys, restart interruption and cancellation after a possible side effect.
6. For any future destructive operation or external communication, add an explicit owner-confirmation workflow. Those risk classes must be blocked until that workflow exists. Never add raw model-provided shell command strings.

Example schema:

```python
class ReadProject(Arguments):
    project_id: str = Field(pattern=r'^[a-z0-9-]{1,60}$')
# DEFINITIONS['read_project'] = (ReadProject, 'Read configured project metadata', 'read', 10)
# dispatch: validate project against configuration, use authenticated API, check status, return structured fields.
```

Documents and connector responses are untrusted data. They never create allowed directories, applications, or tools. The owner explicitly selects absolute roots through the UI. Symlinks resolve inside those roots; binaries, credential filenames, credential-like content, files above 512 KB, dependency folders and unsupported extensions are skipped. Incremental indexing hashes contents, replaces changed files, and removes vanished/excluded records. Explicit removal purges the root's FTS records. The root selection endpoint is unavailable to the model.

Memory is explicit owner-supplied key/value information. Inspect/add/edit/forget controls are in the dashboard. Forgetting purges related durable memory plus conversation context and execution history so erased facts are not recovered from summaries. It does not claim secure deletion from Time Machine, OS backups or old SQLite WAL copies. Notes have separate FTS search.

## Optional calendar

Create a Google OAuth Desktop client with Calendar API enabled. Keep the downloaded client JSON outside the repo; set GOOGLE_CLIENT_FILE to its absolute path. Select Connect calendar. Authorization opens the system browser, uses PKCE and a loopback callback, and asks for calendar.readonly. Refresh credentials are kept in the OS keychain via keyring. No credential is sent to React or logs. The calendar remains Not connected without this configuration. Live OAuth requires your account consent and has not been fabricated. Calendar, enabled RSS feeds, and a selected hosted model provider use network access; offline assistant operations do not require them. The Settings credential-file import accepts a Google Desktop client JSON and stores it in the private data folder. Connect is unavailable until the client is configured.

## Desktop product boundary

Electron has nodeIntegration off, contextIsolation on, sandbox on, restricted IPC senders, denied external navigation, and audio-only microphone permission. Only the Google OAuth authorization page can open externally. Login startup uses Electron's OS-supported API and is enabled in Settings after installing the packaged app. It is not a background daemon while the app is closed. Fullscreen preserves interrupt/mute/exit controls and follows reduced motion preferences.

Mac application actions use allowlisted bundle identifiers. Windows uses explicit configured absolute .exe paths with no shell expansion. Build and test installers on each target OS. This Mac implementation does not establish Windows audio, installer, login-startup or GPU performance. Further connectors, destructive-action confirmation, code signing, notarization, automatic update security, data export/import and license clearance are product release gates. “All possible actions” is not a supported claim.


## Voice changes and provider scope

`set_voice(name)` and `list_voices()` are typed local tools. Voice names are a strict enum of installed choices; unknown or missing assets fail rather than report success. The voice is persisted and subsequent sentence synthesis reads the current setting. Emma is the default calm female option.

The compatible provider stores keys by a hash of the validated endpoint in OS-backed keyring. Moving to another endpoint does not carry its key. Groq GPT-OSS 20B uses `max_completion_tokens=1024`, `reasoning_effort=low`, `include_reasoning=false`; reasoning deltas are never displayed or spoken. Provider errors are explicit, with no automatic action replay or cloud fallback.


Additional saved settings: `online_voice_enabled=false`, `groq_voice_rpm=10` (1–60; raise only for an account that supports it), `child_mode=false`, `long_speech_sentences=48` (6–80; safety bound for all spoken replies, with a visible notice when reached), `response_tokens=650` (320–4096). Explicit long narration overrides that turn's generation budget to 2048 without overwriting saved settings. `groq-*` voice IDs require opt-in and the key for the fixed Groq HTTPS endpoint. `mac-Rishi`, `mac-Tara`, `mac-Aman` require installed system voices and the compiled helper on macOS. Source setup compiles `native/mac-voice.swift`; packaging includes its compiled helper. No raw microphone audio is retained; the macOS system speech client temporarily writes synthesized output in an owned directory and deletes it on completion/cancellation.

`create_document(title,content,format)` supports `docx`, `pdf`, `md`, with a 160-character title, 20,000-character content, local-write risk and 20-second deadline. Download checked files using authenticated `GET /api/generated-documents/{id}/download`. Hash changes, missing files, and paths outside the private export directory are rejected. The model cannot supply an export path. Migration 4 adds generated document records. Cancellation may have completed a file already; inspect the records rather than silently replaying it.

Unsigned macOS updates may require reapproving Jarvis runtime access to its saved Keychain item. Only the owner enters their Mac password in the system dialog. Online credentials are read off the event loop with an eight-second wait and at most one pending read per adapter; local startup does not warm an online voice. Denied or pending access preserves local UI/tools and produces an actionable provider warning.

`online_voice_fallback=none` accepts `kokoro-af_heart`, `kokoro-bf_emma`, `mac-Tara`, `mac-Rishi`, or `en_US-ljspeech-high` when downloaded. It handles online speech failures only, announces the fallback on screen, and keeps that voice for the rest of that turn. It never changes the primary voice or invokes a remote service from a local voice. Online model/speech adapters share a process-local, endpoint-scoped Keychain read; an explicit connection test retries a completed denial without duplicating a pending OS prompt. Cache invalidation after a credential change prevents stale reads from being forwarded to another endpoint.

## Current sources and companion

`google_search_enabled=false`, `google_search_model=gemini-3.1-flash-lite`, `google_voice_enabled=false` and `google_tts_model=gemini-3.8-flash-lite-tts` are saved settings. The per-user Gemini key is stored in keyring under the fixed Google-compatible endpoint. Each feature is separately enabled; enabling Google does not enable Groq. Local fallback enumeration excludes both remote adapters. Read [LIVE_DATA.md](LIVE_DATA.md) before enabling provider data transmission.

Migration 7 adds hashed, expiring paired-device records. `companion.json` is private runtime configuration, excluded from Git. The gateway binds to 127.0.0.1:8770, disabled to remote clients by default. `JARVIS_COMPANION_SERVER=0` disables gateway startup (useful in isolated tests). Private Tailscale HTTPS and exact desktop approval are required for phone access; see [setup](DAILY_GUIDE_AND_DEVICES.md).

New typed tools: `search_current_news(query)` (read, 50s, cited public search); `find_meeting_slots(start,end,duration_minutes,timezone,day_start,day_end)` (read, 30s); `cancel_calendar_event(event_id)` (approval required, 20s); `get_directions(destination,origin,mode)` (read, 5s); `prepare_appointment_call(recipient,purpose,preferred_times,questions,number)` (local write, 10s). JSON schemas are generated from strict Pydantic types. Tools not exposed for the current request are rejected independently of the model.
