# Jarvis workflows and connections

Open **Workspace → Automations**. The focused voice screen remains unchanged. Ten templates are available: morning briefing, voice-to-document, meeting follow-through, business report, research monitor, project coordination, email assistant, desktop routine, smart home and family routine.

## What executes

Local workflows use real native Ollama, SQLite, selected-directory search and verified local file exports. Voice-to-document uses explicitly dictated content or a saved note; meeting follow-through uses an explicitly supplied transcript, never covert meeting recording. Business reports require supplied facts or selected indexed sources. Family routines can prepare age-appropriate stories and activities. Desktop routines launch only configured applications. Research monitors compare actual cached source records and stay quiet when unchanged; this is not unrestricted web crawling. Morning briefings prioritize India and disclose news cache age.

Templates produce real DOCX, PDF, Markdown, CSV, XLSX or PPTX drafts. Spreadsheet cells are data, not executable formulas. PPTX is limited to 30 slides. Documents remain drafts for review; model prose or suggested actions are not established facts or completed actions. Meetings do not silently create commitments, calendar events or reminders.

Schedules support daily, weekly and bounded intervals (minimum 15 minutes), with Asia/Kolkata by default. Missed schedules coalesce to one durable run, rather than a burst. **Jarvis must be running**. Enable launch at login in desktop settings if desired; a separate system background service is not installed by this feature. Worker concurrency is one; queued jobs are limited to 16. Background analysis uses the separately configured `workflow_model` (default `qwen3:4b-instruct`) locally, even if conversation uses Groq or Gemini. A foreground conversation preempts read-only background generation; only that generation can resume, at most twice. Completed writes are never replayed. Unfinished jobs/runs become interrupted after restart.

## Google connection setup

1. In an isolated Google Cloud project, leave billing **unlinked**. Enable Gmail API, Google Tasks API, Google Drive API and Google Calendar API as needed. No Cloud Speech, Vertex AI or paid Maps API is required.
2. Configure OAuth branding and an External **Testing** audience. Add only your own Google account as a test user. Accept Google's User Data Policy yourself or explicitly approve that agreement.
3. Create a **Desktop app** OAuth client, designated for AI agent workflows where Google offers that option. Save the JSON outside Git. Import its private local path in Automations → Connections (or Calendar settings).
4. Connect only the profiles you need. Complete Google's real account/consent flow. Tokens are stored in OS credential storage, never the frontend or SQLite. PKCE, one-use state and a ten-minute callback deadline protect authorization. Testing-mode refresh tokens may expire; reconnect when Google requires it.

Profiles request separate scopes:

| Profile | Scope / access |
|---|---|
| Calendar read | `calendar.readonly`; upcoming primary-calendar events |
| Calendar edit | `calendar.events.owned`; owner-reviewed creation/editing of owned primary-calendar non-recurring events |
| Mail read | `gmail.readonly`; latest ten inbox messages from the past seven days and selected-message text |
| Mail send | `gmail.send`; exactly reviewed email or threaded reply |
| Tasks | `tasks`; read incomplete default-list tasks; reviewed task creation |
| Drive | `drive.file`; app-scoped file listing; reviewed upload of a checked Jarvis-generated file |

Gmail reading is optional and genuine OAuth is required. It does not download attachments or remote images. Plain text is bounded to 20,000 characters; HTML-only mail returns an explicitly incomplete snippet. Say **“Check my email”**, select an actual message, then **“Draft a reply…”**. Jarvis uses `read_email` and `prepare_email_reply`; recipients and thread references come from the real source message. Review exact recipients and complete text in **Automations → Review**. No automatic bulk response, deletion, mailbox modification, or reply-all is implemented.

An approval lasts 15 minutes. Duplicate approval is rejected atomically. If a service times out after a write starts, the result is marked interrupted and never retried automatically; inspect the account/device first. Gmail API acceptance is reported separately from actual inbox delivery. Task creation requires a returned task ID. Drive upload requires a returned file ID. Physical light changes require a subsequent matching device-state read. OAuth/account integrations remain “Not connected” until real authorization succeeds; scopes alone do not prove API access.

Connector requests have a local cap of 300 per profile per UTC day, in addition to Google's quotas. Google's current Calendar and Gmail documentation describes no-charge thresholds and changing quota rules; do not assume APIs are unlimited or perpetually free. Public distribution may require Google verification for sensitive/restricted Gmail scopes. This development client is for its configured test users, not a commercially verified OAuth app.

## Optional free-tier Google language model

Settings → AI provider → **Google Gemini** supplies the official OpenAI-compatible endpoint:

```
https://generativelanguage.googleapis.com/v1beta/openai
```

The initial configurable preset is `gemini-3.1-flash-lite`, listed with free-tier text input/output in Google's pricing documentation on 5 October 2026. Paste your own Google AI Studio key **only into Jarvis's password field**, then Test API connection. It is stored in OS keyring by endpoint. Model availability, rate limits and free quotas depend on the account and may change. Keep the project unbilled. Jarvis never upgrades billing or purchases quota. Free-tier Google prompts/results may be used to improve Google products. Online conversation sends the requested conversation/tool data to Google; keep sensitive commands on local Ollama. Private workflow analysis remains local. The adapter streams text, preserves tool-call metadata, and requests minimal supported reasoning. Real Gemini inference must be tested with a connected key before claiming speed or better quality.

## Named API reads

Automations → Connections → Named read-only APIs accepts an owner-configured name and one public HTTPS JSON endpoint, optionally with a bearer token stored in OS keyring. `read_custom_api(name)` accepts the name, never a model-generated URL or HTTP method. Requests are GET only, fixed path, no query secrets, no redirects, verified TLS, DNS pinned to a public address, timeout 15 seconds and 256 KB response cap. Private/link-local/metadata addresses are denied, including mixed public/private DNS answers. This is an extensible read adapter, not permission for arbitrary remote writes or purchases. Add future write adapters as typed operations with exact review and verification.

## Smart home

No Home Assistant server is bundled or assumed. Configure your own local server using an explicit local IP address, its long-lived token, and an allowlist of `light.*` entities. Only `turn_on` and `turn_off` are supported, each with owner review. No locks, alarms, appliances or arbitrary services. Configuration alone is not a live device test. Without a server, the feature correctly remains Not connected.

## Records, inspection and deletion

Definitions, frozen run inputs, step checkpoints, notifications, connector metadata, quotas and approvals occupy separate SQLite tables (migration 5). All inputs and results are inspectable. Delete a workflow to cancel pending work and remove its definition/activity. Exported files are retained and listed separately in Notes & documents. Cancelling an approved action already in flight cannot undo a real-world change; inspect its result. Existing note/memory deletion controls continue to purge conversation context; explicitly created documents and workflow inputs are separate owner-selected records, so remove them separately when needed.

No passwords, arbitrary shell, purchases, uncontrolled computer access, automatic message sending or billing changes are introduced.

## Extension / API contract

Authenticated loopback routes (exact local Origin on mutations):

- `GET/POST /api/automations`; `PUT/DELETE /api/automations/{id}`
- `POST /api/automations/{id}/run` with a client-generated idempotency `key`
- `POST /api/automation-runs/{id}/cancel`
- `POST /api/automation-notifications/{id}/read`
- `POST /api/connectors/{profile}/connect`; `DELETE /api/connectors/{profile}`
- `GET /api/connectors/{profile}/read`; `POST /api/connectors/home/configure`
- `GET /api/email/{message_id}`; `POST /api/email/reply`
- `POST /api/external-actions`; `POST /api/external-actions/{id}/review` with `{ "approve": true/false }`
- `POST /api/custom-apis`; `GET /api/custom-apis/{name}`

Only the one-use, state-validated Google OAuth callback is public. Existing voice WebSocket events and stale-turn/audio guards are unchanged. Tools are registered in `tools.py` with schemas, risk, timeout and structured results. To extend: add a validated schema and fixed service adapter, return actual verified IDs/states, then add permission, timeout, failure, duplicate and restart tests. Never let retrieved content expand permissions.

Official sources: [Google native OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [Drive uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads), [Tasks insert](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/insert), [Calendar quotas](https://developers.google.com/workspace/calendar/api/guides/quota), [Gmail quotas](https://developers.google.com/workspace/gmail/api/reference/quota), [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Home Assistant REST](https://developers.home-assistant.io/docs/api/rest/).

## Daily priority briefing

Morning briefing supports `run_on_startup: true` with an enabled definition. It shares a durable date slot with the daily schedule in its configured timezone, so a restart and scheduled trigger on the same day do not duplicate it. Only the read-only briefing template permits startup execution. It checks reminders, the configured read-only calendar and India-first news across available categories. Topic preferences are data. Missing connections, cache age and lack of personal finance data must be stated. Completed briefings appear through **Updates → Activity** and a checked local Markdown document; automatic spoken greetings are not implemented. The app must run and the Mac must be awake. Restart recovery never replays an uncertain action. Pause/disable a routine in Automations; cancel an active run in Activity.
