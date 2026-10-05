# Browser audio and session contract

Capture uses `getUserMedia` and an AudioWorklet, not MediaRecorder. Requested echo cancellation, noise suppression and gain control depend on the device/browser. Browser `AudioContext.sampleRate` is measured (44,100 Hz on the browser smoke test). The worklet averages actual input channels into mono float32 at the native rate. A persistent 32-tap windowed-sinc FIR resampler converts to 16,000 Hz; phase and preceding samples survive each block. Samples are clamped and explicitly encoded as signed 16-bit little-endian PCM.

Worklet blocks contain 2048 native samples. The frontend sends 1024 resampled samples per audio message (64 ms, 2048 bytes; base64 transport). The backend accepts up to 4096 bytes per message, 100 messages/sec, 32 KB total JSON message size, and a maximum 60-second utterance. These are PCM samples, never Opus/WebM container data. Silero receives 512-sample / 32-ms frames with its recurrent state and 64-sample context. Hands-free starts after three frames above 0.55 and ends after 25 frames below 0.35. Ten pre-roll frames preserve speech onset. Silence does not grow an unlimited buffer.

## Authentication and IDs

UI is served by FastAPI from the built frontend on http://127.0.0.1:8765. Launchers bootstrap with a secret in a URL fragment, immediately remove it from browser history, and POST it to `/api/session`. The fragment never reaches the HTTP access log. The backend sets an HttpOnly SameSite=Strict cookie with a 12-hour session. Access token file permissions are 0600; data directory is 0700. The WebSocket requires that cookie plus the exact local Origin. Arbitrary origins and non-loopback engine URLs are denied.

Server `hello` assigns a conversation `session_id`. The UI can resume its saved conversation with `resume`. Every capture/text turn supplies a UUID `turn_id`; every audio chunk has a monotonically increasing `seq` from zero. Server responses include session and turn IDs. Both ends reject superseded output. Audio sequence mismatches stop playback.

## Client → server messages

- `resume`: `{type, session_id}`
- `text`: `{type, turn_id, text, voice: true}`
- `capture_start`: `{type, turn_id, mode: "ptt"|"handsfree"|"wake", sample_rate:16000, source_sample_rate:44100, encoding:"pcm_s16le"}`
- `audio`: `{type, turn_id, seq, audio:"base64 PCM", voice:true}`
- `barge_audio`: `{type, turn_id, seq, audio:"base64 PCM"}`; same mono 16 kHz encoding and size bounds, separate sequence counter. Sent only during speaking in explicitly activated continuous sessions.
- `capture_stop`: `{type, turn_id, voice:true}`
- `interrupt`: `{type}`
- `playback_done`: `{type, turn_id}`
- `ping`: `{type}`

## Server → client messages

- `hello`: session ID
- `state`: idle, listening, transcribing, thinking, executing, speaking, interrupted, error
- `capture_ended`: hands-free segmentation completed; microphone admission closes
- `transcript`: actual completed Whisper transcript (no provisional/live claims)
- `delta`: final natural-language response fragments (Ollama streaming)
- `tool`: tool name, running/succeeded/failed, validated structured result
- `audio`: seq, voice (actual engine identifier), text (sanitized words submitted to synthesis), encoding=`wav`, base64 self-contained PCM WAV from the selected local engine or explicitly enabled online engine. If the configured local fallback is used, a preceding warning identifies it; sequence ordering and cancellation guards stay the same.
- `barge_candidate`: current turn; provisionally suspend playback
- `barge_rejected`: current turn and rejection reason; resume the same playback queue
- `barge_in`: global event with new_turn UUID and stopped boolean; invalidate old turn, clear audio, then accept subsequent new-turn events
- `metrics`: measured STT timing
- `done`: final text, audio_count, model/TTS/total timings
- `stop_detected`: recognized stop/pause command; client closes microphone and cancels the turn without generating a conversational reply
- `wake_session`: active, timeout_ms; bounded conversational follow-up eligibility and UI countdown
- `wake_detected`: has_command; genuine local Whisper recognition of an anchored wake phrase
- `interrupted`: cancelled_turn plus current persisted action records
- `warning`, `error`, `pong`

## Playback, cancellation and echo protection

Ollama planning/tool rounds are buffered. The final tool-free response streams to the screen. Complete sentences enter a bounded TTS queue (six chunks, each at most 400 characters); no tool JSON, reasoning field or code fences are spoken. Ordinary replies are concise by prompt instruction, but their safe text is no longer silently cut off after three sentences. All replies share the configurable narration safety limit (initially 48 sentences); reaching it produces a visible warning. Numbered list labels do not count as sentences, and long sentences are split at word boundaries instead of discarded. Kokoro's loaded ONNX session and Piper's loaded voice are reused. Each sentence is a WAV chunk at its own sample rate (24,000 Hz for Kokoro; use each WAV header for alternatives). Browser decodeAudioData converts appropriately to the output AudioContext. Sequential decode chains and AudioBufferSource scheduling preserve order with a 30-ms starting margin. `playback_done` is sent only after all scheduled buffers drain.

Interrupt stops all current AudioBufferSources, resets the decode queue and its epoch, closes microphone admission, clears queued server generation, and invalidates the turn before cancellation. Late decoded audio and misbehaving cancelled adapters cannot resume. ONNX cannot be cancelled in the middle of a sentence; its thread is allowed to finish under the existing lock, with output discarded for the stale turn. Tool actions already committed remain visible in the interruption snapshot.

Stop / Escape / the native Conversation → Pause microphone and speech menu closes the microphone and cancels playback/generation. This pause survives restart until Start conversation, push-to-talk, or explicitly enabling wake listening. Spoken stop commands during capture or playback do the same. Typed messages inside an active conversation keep that session active; listening resumes after the reply drains. Every replacement turn resets pending interruption verification and deferred playback completion, so an old candidate cannot leave a newer reply stuck in Speaking. Typed submission also invalidates pending capture startup and checks its epoch after asynchronous speaker activation.

During thinking, microphone samples are ignored. During speech output, an active continuous session streams samples to a separate Silero interruption capture. Five strong frames above 0.8 trigger a provisional AudioContext suspension; ten quiet frames close the utterance for Whisper verification. Empty/unavailable transcripts resume output and clear the candidate. A transcript matching the assistant's response is rejected as speaker echo. Only an explicit stop or anchored “Jarvis” interruption is admitted during playback, even before echo is observed. Background speech cannot replace the answer. Interruption transcription is bounded to five seconds; failure resumes the current queue. This does not identify the owner or distinguish TV speech during an explicitly open ordinary listening session. No voice identity or owner verification is claimed.

Pause is distinct from cancellation: incoming old-turn audio may queue while verification runs but cannot resume a suspended AudioContext. A completed playback drain is deferred during verification. Accepted interruption stops all buffers and invalidates decode epochs; rejected interruption resumes the same queue. Generation cancellation never rolls back an already committed tool action. Push-to-talk is available at all times. Normal listening resumes after playback plus a 650 ms echo-tail delay. Actual microphone/speaker echo cancellation and room performance require the physical test; synthesized PCM does not prove acoustic behavior.

Wake mode reuses Silero plus native Whisper, rather than a separately licensed wake model. Non-wake speech is discarded without conversation persistence; Whisper may be invoked for any detected speech. Recognition adds STT latency. “Hey Jarvis” alone generates “I'm listening,” then opens a 45-second follow-up window. Every completed reply renews that window; follow-up utterances retain wake mode on the wire but the server accepts them without a repeated phrase until expiry. The UI returns to Waiting when the window expires. Interrupt revokes eligibility. “Hey Jarvis, what is the capital of France?” executes the recognized command immediately. Stop suspends the active session. On the next app launch, an explicitly enabled wake preference attempts to rearm only if microphone permission is available.

Raw microphone audio lives only in bounded memory buffers and HTTP request bodies. No audio recording is saved by default. `docs/smoke-answer.wav` is an explicitly generated test artifact, not a user recording. Engine logs may contain test transcripts; application data and logs are excluded from Git.


Optional Orpheus speech validates and rebuilds streaming WAV headers from actual PCM before sending the same ordered audio events. It accepts at most 200 characters per HTTPS call; complete sentences exceeding that size are split at word boundaries and normalized WAV PCM is joined. Pacing waits, requests and queued output are cancellable. Quota/service/silent audio failures produce one warning and preserve richer text; further speech for that turn is skipped. No implicit provider switch occurs. Long narration remains bounded by sentence count and the six-item speech queue. Native macOS voices produce normalized mono PCM16 WAV at their actual declared rate; the browser decodes WAV and schedules it through the same player.

Short, complete online speech sentences that are already queued are grouped up to 180 characters after a 40 ms collection window. This reduces separate rate-limited calls without waiting for the entire model response; order, bounded buffering, explicit fallback and cancellation remain enforced.

## Private phone companion

The HTTPS gateway `/phone/ws` uses the same session/turn/sequence and PCM/WAV contract as the desktop. It requires a secure HttpOnly approved-device cookie and exact private origin. Resume/session reassignment and unknown message types are rejected. Existing owner verification runs on the phone session's own lease. Revocation closes the socket and blocks output. Safari's actual AudioContext sample rate is detected and the existing mono FIR resampler feeds 16 kHz signed little-endian PCM, never MediaRecorder assumptions. Audio playback requires a user gesture. Capture stays on for the explicitly active session with echo cancellation; speaking feeds bounded interruption verification. Page visibility changes stop microphone and playback. iOS background capture/wake/push is not implemented.
