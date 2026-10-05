# Optional owner protection — experimental

Whisper recognizes words; it does not identify the owner. Jarvis adds a separate, local sherpa-onnx 1.13.8 / 3D-Speaker CAM++ speaker-embedding adapter. It is off until explicit enrollment. It never grants access based only on a voice.

## Enable on your device

Download the 28,281,164-byte model explicitly. Source installation:

```sh
.venv/bin/python scripts/download-owner-model.py
```

Installed Mac application:

```sh
"/Applications/Jarvis Local.app/Contents/Resources/runtime/jarvis-runtime" --download-owner-model
```

The model is SHA256-verified against the upstream release checksum before use: `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`. No automatic model download happens during conversation. Configure `JARVIS_MODELS` before startup to use another directory.

In Settings, open **Owner protection**, choose a unique passphrase of at least eight characters (prefer a long passphrase), consent to recording your own voice, and record four different eight-second samples in a quiet room. Three form the template; the fourth must match two enrollment samples before activation. If enrollment fails, protection stays off. Do not paste your passphrase into chat or use an API key/Mac login password as this passphrase.

Enable owner lock, then enter the passphrase on the lock screen. A ten-minute lease belongs to that authenticated browser session. Restart, expiry, Lock now, mismatched speech, missing/corrupt model or verification failure blocks access. Every spoken request is checked before its transcript or private context is sent to the agent/provider. Stop-speaking commands remain available to anyone. Typed interaction requires a valid passphrase lease. Short speech (under 1.5 seconds), noise and changed devices can cause rejection. Use a longer complete sentence or type after unlocking.

While locked, private API routes and WebSockets are denied. The conversation UI is unmounted; queued playback and microphone capture are stopped. Unknown speakers get no guest chat, private memories, mail, calendar, tools or owner voiceprints. Locking cancels connections/generation, but cannot undo or guarantee cancellation of an external action already submitted. Scheduled tasks authorized earlier may continue independently.

## Storage and recovery

Audio samples are kept in browser/backend memory for enrollment and discarded; raw audio is not persisted. Only normalized voice embeddings are stored in `owner-voice.enc.json`, encrypted with Fernet using a key derived from the passphrase with scrypt (N=131072, r=8, p=1). Files are private to the OS user. Templates are never sent to an LLM, cloud speech API, telemetry, public source or downloads. Five wrong unlock attempts impose a one-minute process-local cooldown. An attacker possessing the file can still try guesses offline; use a strong passphrase and OS disk encryption.

After unlocking, Settings provides deletion of the encrypted voiceprint, requiring the passphrase again. There is no unauthenticated reset API. Forgotten passphrase: stop Jarvis, authenticate into the appropriate OS account, back up data, and remove only `owner-voice.enc.json` from that user's application-data directory. This disables protection and must be treated as OS-level recovery. File access/administrator control defeats this app-level lock; separate password-protected OS accounts and screen locking remain necessary.

## What this does not prove

Speaker similarity is not proof of identity or liveness. Recordings and generated imitation can match; the test replay was accepted. A voice alone never unlocks the workspace. This is not diarization, anti-spoofing, biometric certification or protection against somebody controlling the OS account or an already-unlocked keyboard. Exact owner approval remains required for external communications/actions. Family-friendly mode is not access control.

The multilingual model is a candidate, not a claim of tested Bengali/Indian-accent accuracy. Consent-based tests with the actual owner and other people, room noise, replay, synthetic imitation and each target audio device are still required. No false-accept/false-reject rate is asserted.

## Verification

Deterministic tests exercise encrypted persistence, password failures/rate limiting, restart/expiry, corrupt profiles, same/different fake embeddings, enrollment races, profile deletion, locked HTTP/WS boundaries, and rejection before agent invocation or private transcription. These use substituted embeddings, not biometric evidence.

The real local engine was tested on public upstream recordings: repeated enrollment fixture plus a held-out same-speaker sample, and one different-speaker sample. Same-speaker similarity 0.814; different-speaker 0.202; a replay matched. On Apple M5 / 24GB / macOS 27.0.1 arm64, CPU two threads: initial extraction 149.5 ms, warm held-out extraction 21.0 ms and other speaker 29.8 ms. This small fixture test cannot establish security accuracy. The owner has not been enrolled.

Before relying on it, test these in a disposable local workspace: owner enrollment/held-out acceptance; consenting non-owner rejection with no private context/tool calls; underlength/noisy samples; device changes; restart and PIN expiry; stopping during speech; replay/synthetic limitations; missing/checksum-invalid model; delete/reset. Never enroll another person's voice silently.

Sources: [sherpa-onnx speaker API](https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html), [official examples](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py), [model release/checksums](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models), [3D-Speaker Apache-2.0 source licence](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE). Model/runtime licences are recorded separately from application GPL-3.0.
