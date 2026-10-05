# Daily guide and connected devices

Ask “What are my tasks today?” for actual reminders, Calendar and connected Tasks. Missing connections remain explicit. The morning-briefing workflow can run once per local day when Jarvis starts or at its configured time. Its Updates notice is quiet; it does not automatically speak private records. The app must run for notifications. A shut-down or sleeping Mac cannot serve a phone. Login startup is separate from microphone consent.

## Meetings, email and calls

Calendar editing is an optional owner OAuth connection. `find_meeting_slots` checks the owner's actual primary-calendar events in a bounded seven-day window, including all-day blocks. It does not check attendees' calendars or reserve time. Event creation/update supports actual attendee emails and an optional Google Meet request. The exact date/time/timezone, recipients and guest notifications require desktop review. Invitations are not claimed delivered from a Calendar API result. Meet can be pending/unavailable; only an actual returned URL is displayed. Cancellation checks the read event's ETag and verifies deletion. Recurring events are outside this adapter.

Email reading, draft creation and replies use the connected account. Sending requires review of the actual recipients, subject and body. No real email was sent as a setup test. iPhone calls use an owner-reviewed macOS Phone app handoff to an actual number; you conduct the call. `prepare_appointment_call` creates a local call brief and confirmation checklist. Jarvis cannot speak/listen through cellular call audio or claim an appointment was booked from opening a call.

## Private iPhone web companion

Implemented: an owner-approved private web companion with text/voice turns, reminders, hands-free endpointing, ordered audio, interruption and revocable pairing. Desktop review remains required for external writes. It is a web companion, not a signed iOS app, CarPlay integration, background wake word or push service. These need separate native implementation and device testing.

1. Install [Tailscale](https://tailscale.com/download) from its official source on the Mac and iPhone, and sign in to your own private tailnet. Check its current free-plan terms; Jarvis does not create an account or enable billing.
2. With Jarvis running, enable HTTPS for your tailnet according to [Tailscale Serve](https://tailscale.com/kb/1312/serve), then run:
   ```sh
   tailscale serve --bg http://127.0.0.1:8770
   ```
   Use private Serve, never public Funnel. Keep tailnet access limited to your own devices. Do not forward backend port 8765 or Ollama.
3. In Automations → Devices enter the exact `https://your-mac.your-tailnet.ts.net` origin and enable the companion. Open that private address in iPhone Safari.
4. Generate the desktop pairing code (one use, two minutes), enter it on the phone, and approve the named device on the desktop. Until desktop approval, no private records or voice access is granted.
5. If owner lock is enrolled, unlock the phone's separate session with your private Jarvis passphrase. Start conversation and grant Safari microphone access. Keep the page foreground. Add to Home Screen if desired.
6. Revoke a device or disable the companion on the desktop. Tokens are stored as hashes, expire after 30 days, and are rechecked during active sockets. Changing/closing the page stops capture. Pairing secrets, private messages and passphrases are never included in public releases.

The separate gateway binds only to 127.0.0.1:8770 and checks host, origin, body limits, approved-device cookie, revocation and owner lock. It exposes no main REST API, connector authorization or write-review endpoints. Ports in use fail without killing another service. No remote gateway is enabled on a new installation. Tailscale setup and an actual iPhone microphone/route test remain prerequisites, not completed tests on this Mac.

`get_directions` creates encoded Apple/Google Maps handoff links using the owner's explicit destination. Native Maps supplies location, real route steps and ETA; Jarvis does not invent them. Cycling uses the Google bicycling link; no driving route is presented as cycling. Do not interact with screens while riding/driving; use the navigation app's supported hands-free controls.

## Voice and fresh data

Start conversation automatically ends a speech turn on silence. Stop/Escape immediately clears playback and queues. Wake mode still requires explicitly activated listening and microphone permission. Optional owner recognition remains off until your enrollment; it is experimental and replay is a known limitation.

Fourteen Kokoro voices and installed macOS Indian-English voices remain local. Heart is the default. Google and Groq voices require explicit opt-in and your own API. See [current facts, citations, quota boundaries and offline behavior](LIVE_DATA.md) and [owner protection](OWNER_VOICE_SECURITY.md). Genuine singing is not implemented or verified.
