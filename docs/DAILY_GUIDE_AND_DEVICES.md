# Daily guide and connected devices

Jarvis uses actual records to explain priorities: saved reminders, connected calendar, Google Tasks and source-linked India-first news. Ask “What are my tasks today?” or “What meetings do I have?” Missing connections and records must remain explicit. A model's earlier invented statement is not a task. A reminder is durable; it can be inspected or cancelled. Its notification requires the app to run.

The morning-briefing routine can run once per local day at startup or at its daily time (default example 08:00 Asia/Kolkata). Updates opens its activity and checked local document. This is a quiet notification, not an automatic spoken greeting. Stop, Escape or Conversation → Pause microphone and speech cancels voice and closes the microphone. That pause survives restart. Start conversation begins hands-free follow-ups; wake mode uses an addressed “Hey Jarvis” command to open a 45-second follow-up window, then returns to wake-only waiting after inactivity. During playback address Jarvis or say Stop speaking. An ordinary listening session can capture nearby people or media: no owner voice identification is implemented. Pause it when not in use.

## iPhone and navigation: remaining integration

An iPhone companion is not implemented. Use a native app with Apple's [App Intents](https://developer.apple.com/documentation/appintents) for Siri/Shortcuts, a private authenticated pairing channel, and local notifications. The current backend binds to the Mac's loopback and cannot be reached by a phone. Do not publish its port. iOS [background execution limits](https://developer.apple.com/documentation/BackgroundTasks/choosing-background-strategies-for-your-app) mean a normal third-party app cannot promise a continuously active system-wide custom wake word. A shut-down Mac cannot serve requests; use an awake Mac or separately approved always-on host.

Live directions belong to the phone's navigation app, using current location and routing. [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started) can hand off destinations without an API key, or use Apple Maps/CarPlay. Jarvis has no live turn-by-turn connector yet.

Meeting reading works with the existing Calendar authorization. Creating meetings requires a separately configured calendar-write connector and exact owner review of title, time, timezone and attendees. Google's [events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert) supports events, and `sendUpdates` may send invitation emails. No meeting-write integration is claimed here.

## Google news and voice options: research, not connected features

Checked official documentation on 5 October 2026:

- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) lists free-tier speech generation for Gemini 3.8 Flash TTS. [Speech generation](https://ai.google.dev/gemini-api/docs/speech-generation) supports voice/style/pace controls. Availability and quotas depend on the account; this voice adapter and a live account test are not implemented. Free-tier input/output may be used by Google for product improvement.
- Some free-tier text models, including the listed Gemini 2.5 Flash-Lite tier, support limited [Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search). This could add current search-backed answers with actual citations. Model-specific limits apply; it is not unlimited Google News access. Jarvis currently uses its RSS adapter and cache, not a Google grounding connector.
- [Google Cloud Text-to-Speech setup](https://docs.cloud.google.com/text-to-speech/docs/get-started) requires billing even where a monthly allowance exists. No billing account or paid voice quota was enabled.
- [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) is closed to new customers and scheduled to end for existing users on 1 January 2027, so it is not a suitable new dependency.

Keep the free local Kokoro/Piper voices as the offline option. The latest installed check used the selected Heart local voice; Bella remains available. Optional hosted models/voices send their requested inputs to the configured provider and require internet. No purchase is permitted. Broader access needs specific typed connectors with bounded permissions, inspectable activity and reviewed consequential actions; unrestricted shell and arbitrary computer control remain outside the default tools.

## Local voice choices

The existing downloaded Kokoro bundle contains additional English voices. Jarvis exposes fourteen Kokoro choices, including newly enabled Aoede, Kore, Nova, Fenrir, Puck and Fable. The six new options generated non-silent 24 kHz WAV locally on the M5, without cloud requests. Voice-command aliases are validated. Use the voice picker previews or say Change your voice to Kore. Heart, Bella and Emma remain useful comparison choices; more choices do not guarantee more expressive prosody. The upstream [voice catalog](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) explicitly treats quality as subjective. Try Relaxed pacing in Settings if delivery feels rushed. Native Rishi and Tara provide the installed Indian English options.

[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) supports expressive speech and voice design, and [MLX Audio](https://github.com/Blaizzy/mlx-audio) provides an Apple Silicon implementation. This is an optional candidate requiring separate dependency/model downloads, an adapter and latency/quality checks on this Mac. It is not installed or benchmarked by this update. No claims of verified singing or Bengali output are added.
