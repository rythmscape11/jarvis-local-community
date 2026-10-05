# Owner voice verification — evaluation, not an active security feature

Jarvis currently transcribes speech but does not authenticate a speaker. Saying an owner's name or “Hey Jarvis” is not identity verification. Sensitive actions still need exact review, and an unlocked OS account shares its Jarvis workspace.

A local integration is feasible through [sherpa-onnx speaker embedding extraction](https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html), independent of Whisper recognition. Its supported speaker models are listed by the upstream project. Runtime/platform, model licence and model checksum must be verified for the selected release before adding a dependency.

The intended security boundary must combine local voice matching with owner-controlled PIN or OS authentication. Voice alone is vulnerable to recordings, synthetic imitation, background speech and false matches. Do not turn an embedding similarity threshold into authorization to read private mail/memory, send messages or place calls. Unknown speakers should receive a separate guest conversation with no private recall or connected tools; speaker verification must not reuse the owner's conversation as guest context.

Enrollment should be explicit: several microphone samples, distinct prompts, no silently captured bystander voices, a locally stored encrypted voiceprint, and a visible delete/reset control. Keep voiceprints out of Git, downloads, analytics, model prompts and cloud TTS. Test owner and consenting non-owner voices, silence/noise, playback/replay, device changes, failures, restart and rejection before enabling protection. Enrolment and physical false-accept/false-reject tests have not been performed, so this release makes no owner-recognition security claim.
