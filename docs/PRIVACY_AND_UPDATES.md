# Private installations and public software updates

Each installation starts without API keys, Google OAuth credentials, tokens, conversations or memory. The offline core needs no API account. Optional services must be connected by the person using that installation, with their own account and quota.

The desktop app uses the current OS user's application-data directory, not a developer's database or a shared server. Credentials are saved in that user's OS credential store (macOS Keychain / Windows credential backend). Model/API keys and OAuth refresh tokens are not placed in React, Git, exported documents, release metadata or logs. Loopback session authentication and exact-origin checks protect local tools from unrelated websites. Never make the backend or Ollama public.

Chats are automatically saved locally and relevant **past user messages** can inform future replies. Assistant guesses are not indexed as personal knowledge. The Memory page supports search, correction, individual deletion and clearing chat history. Corrections remove the associated old answer and summaries. Questions or hypothetical messages remain statements made in a chat, not verified facts. Retrieval is keyword-based and bounded by the configured context; this is not model retraining or perfect recall.

## Shared computers

One signed-in OS account has one Jarvis workspace. Different people using that same unlocked account share its records. Use separate password-protected OS accounts for private workspaces. Optional experimental owner protection combines an encrypted local voiceprint with a passphrase, and locks unknown voices. It is off until explicit enrollment and is not anti-spoofing. See [setup, limitations and recovery](OWNER_VOICE_SECURITY.md). Do not leave an owner-authorized microphone session open for guests or children with access to connected services. Family-friendly mode changes responses; it is not an access-control boundary.

## Optional network use

A configured hosted model receives selected conversation excerpts and requested tool results. A hosted voice receives spoken response text. Google connectors send requests to the owner's authorized account. RSS news uses public feeds. Each provider's terms apply; do not assume a provider has no retention.

Automatic update checks are enabled by default and can be disabled in Settings. They request the fixed public GitHub latest-release endpoint, at most once per day per process/cache cycle. The request carries a generic app User-Agent and no API key, cookie, conversation, memory or installation identifier. GitHub necessarily receives the network IP as with any HTTPS request. Check now performs an explicit manual check. Offline/error responses do not block conversations.

A newer valid stable semantic version produces an in-app notice with Review & download. The destination is constructed from the fixed public repository and validated version, not accepted from arbitrary remote URLs. No binary is silently executed or installed. This unsigned development distribution uses owner-reviewed replacement; macOS automatic installation requires consistent application signing. See [Electron update requirements](https://www.electronjs.org/docs/latest/api/auto-updater).

For fully offline operation choose Ollama and a downloaded local voice, disable news networking and automatic update checks, and disconnect optional cloud connectors. Download models before disabling the network.

## Publishing a new version

Update the application version in `desktop/package.json`, its lockfile, and `backend/jarvis/updates.py`; run checks and rebuild. Audit the public source tree and bundle for credentials/private artefacts. Publish an accurate GitHub release with a stable `vMAJOR.MINOR.PATCH` tag, matching source and checksums. GitHub draft/prerelease entries are not stable update targets. The release check must never be repointed to a user-supplied server. Keep old personal/private repository history private.
