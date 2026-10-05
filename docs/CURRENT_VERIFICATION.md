# Version 0.3.2 candidate verification

6 October 2026. Actual test host: Apple M5 MacBook Pro, 24 GB unified memory, macOS 27.0.1 arm64. This is a development candidate, not a claim of commercial release readiness.

## Automated and packaged checks

225 backend tests, 13 frontend tests, the TypeScript/Vite build and one Electron session test passed. The backend regression suite covers malformed arguments, authenticated exact-origin HTTP/WebSocket boundaries, document symlinks and credential exclusions, duplicate writes, stale output, cancellation races, model failures, reminder/job restart recovery, selective memory deletion and idempotency tombstones. The frontend audio/HTTP tests and production TypeScript/Vite build pass. The Electron local-session test passes. The actual frozen Mac runtime passes six document export formats (DOCX/PDF/Markdown/CSV/XLSX/PPTX), workflow and record persistence after restart, authenticated access and memory deletion. Tests use disposable records, not owner mail/calendar.

See `final-runtime-inference.json` for the final live inference gate and actual timings. Its input speech is synthesized, not a physical microphone. It exercises native Whisper, native Ollama and real Kokoro audio through the production WebSocket controller. Checks include complete ordered speech, cancellation with eight seconds of stale-output observation, new questions after cancellation, truthful model/settings responses, natural-language notes/reminders, duplicate writes and real document indexing. A reminder acknowledgement defect found by this gate was corrected: local reminders cannot be described as Google Calendar writes.

## Settings usability change

Settings uses the full page, with separate Voice & language, AI model, Memory & privacy, Live information, System, Updates, Startup and Connections groups. Less frequent controls are expandable. Cards use three columns on wide screens, two on medium screens and one on narrow screens; there is one page scrollbar instead of a narrow modal. Keyboard focus remains within the settings page, Escape returns to Jarvis, and Cancel discards unsaved form values. Immediate connector/security actions remain explicitly described.

Compilation and code review do not establish rendered layout quality. Final desktop/narrow-screen screenshots and keyboard journeys remain pending: the host Mac is locked and the computer-control tool could not unlock it. A local browser attempt was also blocked by the browser client. No attempt is reported as a successful visual check.

## Remaining release gates

- Unlock the host and verify the installed candidate: Settings alignment/keyboard flow, physical microphone denial/recovery, hands-free endpointing, wake activation, spoken stop and room echo. Previous owner listening confirmations establish earlier Heart audibility, not the entire new build.
- Disconnect internet physically and repeat a local voice question. Local-only inference and offline flags have been exercised, but physical network disconnection is not verified.
- Indic Bengali/Hindi synthesis is not ready: verified weights alone do not complete its gated tokenizer/configuration download. Optional Qwen/Chatterbox English and Kokoro Hindi/French/Spanish/Italian/Portuguese WAV generation were tested; subjective naturalness and multilingual pronunciation are not certified.
- The public Windows verification run passed backend/frontend tests, NSIS installer packaging and actual frozen-runtime persistence checks. See windows-0.3.2-verification.json. Physical Windows microphone, install UI, permissions, login startup and acoustic checks remain separate.
- The Mac candidate is ad-hoc signed and its resource seal verified; Developer ID signing and notarization remain unavailable. No new public binary release is claimed while these physical/rendered gates remain open.
- iPhone pairing, private Tailscale access and on-device voice remain unverified. Mobile setup was paused at the owner's request to finish these tests first.

## Owner acceptance procedure

After unlocking, quit the existing app and open the candidate. In Settings, navigate each section at desktop and narrow width, Tab through controls, preview Heart, change a setting then Cancel and reopen, and save a pace change. In an activated conversation ask a spoken question, create the tomorrow-at-10-AM reminder, retrieve a note, ask a follow-up based on a prior conversation, and correct/forget a synthetic phrase. During a long reply say “Stop speaking”; wait ten seconds and ask a new question. Verify the earlier reply never resumes. Restart and inspect notes/reminders/memory/jobs. Repeat offline using Ollama and a local voice. Avoid real email sends, call placement or invitations in acceptance tests.
