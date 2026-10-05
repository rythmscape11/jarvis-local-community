# Development verification — 5 October 2026

Tested hardware: Apple M5 MacBook Pro, 24GB unified memory, macOS 27.0.1 arm64. Python 3.11.9; Node 24.13.0; Whisper small Metal; Silero ONNX; local Heart voice. Windows source/build scripts are included but physical Windows operation is unverified.

Backend regression tests cover argument validation, origin/session protection, directory traversal, idempotency, persistent reminders/jobs, memory migrations/corrections/deletion, cancellation races, stale audio, connector approval, and release-check validation/privacy/offline behaviour. Frontend tests and TypeScript/Vite build pass. Real hosted-model inference with an isolated synthetic archive recalled the project colour and city across a database restart; a conflicting generated answer was excluded. This is live inference with synthetic data, not a physical microphone test.

Synthetic PCM tested the installed Silero → Whisper → hosted model → local Heart pipeline and spoken interruptions. A real-room test must still be repeated on every target device. No live email was sent, phone call connected or appointment booked as part of verification. Calendar writes are tested with substituted HTTP; an actual grant and target-account end-to-end test remain required.

## Manual microphone acceptance

1. Download models. Choose local Ollama/Heart, disable news and update checks, disconnect optional cloud connectors, then disable the network.
2. Start a conversation. Ask “What is the capital of France?”; verify the transcript and spoken answer without pressing Finish.
3. Ask a follow-up naturally, then request a long story. Say “Stop speaking” midway; verify immediate playback pause and no resumed old sentence or queued audio. Leave ten seconds to check for acoustic self-triggering. Repeat with headphones.
4. Create a reminder tomorrow at 10 AM, checking the actual date and configured timezone. Create/search a note and index an explicitly selected text directory. Verify filenames/excerpts.
5. Tell Jarvis a disposable fact. Close/reopen and ask about it. Inspect/correct/delete it in Memory; restart and verify the deleted statement is absent from search. Do not use confidential data for this test.
6. Deny/re-enable microphone permission, disconnect/reconnect an audio device, and stop a model service. Verify clear error states and working text input.

Unsigned preview: Developer ID signing/notarization, physical acoustic checks, iPhone linking/call handoff, actual Calendar modification and Windows installer/audio verification remain release prerequisites. Update notification logic is verified with simulated newer releases; future signed automatic installation is not implemented.

## Owner protection

Experimental local speaker embedding extraction, encrypted enrollment and passphrase gates are implemented. Deterministic security tests cover encrypted restart/delete, expiry, wrong passwords, unknown speakers, enrollment races and API/WebSocket refusal. Real local-model fixture tests accepted a held-out same-speaker recording and rejected a different-speaker recording; replay was accepted. See OWNER_VOICE_SECURITY.md for measurements and limits. Owner microphone enrollment and false-accept/false-reject rates are not verified.


5 October final owner-protection checks: 149 backend tests, 13 frontend tests, desktop session test, Ruff, dependency consistency and TypeScript/Vite build passed. The actual frozen Mac runtime extracted speaker embeddings and encrypted/decrypted a disposable profile, denied private records while locked, stayed locked after restart, rejected a wrong passphrase and deleted the voiceprint after authorized unlock. The owner’s real voice is not enrolled; physical-room, replay/synthetic-resistance and Windows-device accuracy are not verified. Public source CI checks run separately on Ubuntu.
## Version 0.3 checks (5 October 2026)

Current-data routing, stateless Google REST contracts, cited-only results, opt-out, safety caps, dated offline cache, voice enumeration, invitation/Meet/cancellation, paginated calendar availability, Maps encoding, appointment briefs, private pairing/approval/revocation/expiry and socket restrictions are covered by isolated deterministic tests. Google response and calendar write tests are mocked unless separately identified as live below. The new tests do not establish iPhone hardware operation or invitation delivery.

Live public RSS retrieval succeeded on the M5: five India records were returned, including same-day publication timestamps, in 0.56 seconds (isolated database; see live-news-smoke.json). This measures retrieval, not end-to-end speech latency. Calendar editing was authorized in the owner installation; one specifically approved synthetic event was created and read back successfully, then removed through Google Calendar with an “Event deleted” confirmation. No guests, invitation, email or call were sent. The new cancellation adapter's contract is independently tested; the real setup-event cleanup used the Calendar UI.

The frozen Mac runtime is tested against disposable records for authentication, generated documents, idempotency and restart persistence (ci-runtime-smoke.json). Real iPhone capture, Windows microphone/installer UI, singing, signed distribution and macOS reboot/login behavior remain separate prerequisites; a source test or CI build must not be reported as verification of those physical behaviors.

Installed 0.3 live checks: India news conversation returned five actual source links and three local Heart audio chunks using the configured Groq GPT-OSS-20B provider. On the M5/24GB, model first token was 1740.6 ms (including source-prefetch time), TTS first audio 6166.5 ms, overall first audio 8047.9 ms and total 10346.3 ms. A WebSocket interruption acknowledgement took 2.62 ms and no stale output appeared during five seconds of observation. These are one-run measurements, not microphone/acoustic or general latency guarantees.

Google account voice synthesis passed: Gemini 3.8 Flash-Lite TTS, Kore, HTTP 200, 5.07 seconds generation for 10.24 seconds of non-silent WAV audio. Cited search did not pass: Gemini 2.5 Flash-Lite returned 404; the configurable Gemini 3.1 Flash-Lite request returned 429. Search remains disabled in the owner installation. The project was visibly Free tier, and billing was not changed. See google-live-verification.json and installed-0.3-verification.json. Heart remains the local default.
## Version 0.3.1 recovery checks

Gemini/compatible-provider server failures receive one cancellable retry only before output, followed by a sanitized provider-unavailable message. HTTP 429/auth/model errors and partial-stream disconnects are not retried; no provider is switched automatically. Isolated tests cover bounded attempts, cancellation and no partial-output replay. Google's own service availability is outside the application.

The first Windows CI run timed out. Its log identified missing `tzdata` and `ZoneInfoNotFoundError: Asia/Kolkata`. The pinned first-party timezone package is now included in source dependencies and both frozen runtime packaging commands. A subprocess test forces an empty OS timezone path and verifies the actual +05:30 conversion. Windows CI must pass independently before any installer is reported verified.

The corrected Windows rerun completed all backend cases in 41 seconds: 190 passed and two POSIX-only mode-bit assertions failed. Those assertions now run only on POSIX; the corresponding OAuth/encryption/restart tests still execute on Windows. This does not establish Windows ACL isolation or hardware behavior; those require a real Windows account/device check.

After the owner approved Keychain access, the installed 0.3.1 Gemini synthetic greeting passed (HTTP 200), with 7279.0 ms first-token time and 7280.4 ms total. It sent no owner history and did not change billing. The selected model and Aoede voice were preserved.

The owner's selected Aoede Google voice also generated valid audio from the installed 0.3.1 preview endpoint: HTTP 200, 24 kHz WAV, 9.76 seconds audio in 4.48 seconds. This synthetic request sent no owner conversation content; physical playback/subjective naturalness were not tested. The real GitHub latest-release feed reports v0.3.1; the app's verifier recognizes it as available to 0.2.0 and up to date for 0.3.1, without automatic executable installation.
