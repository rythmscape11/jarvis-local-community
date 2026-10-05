# ADR-0002: Durable local workflows with explicit external actions

Status: Accepted · 5 October 2026

Jarvis keeps its FastAPI, SQLite, bounded worker, typed tool registry and native speech architecture. Workflows reuse those boundaries rather than introducing a cloud orchestrator. Definitions, runs, step checkpoints, notifications, connector metadata and approval requests occupy separate SQLite tables. Secrets remain in OS keyring. Schedules run only while Jarvis runs; missed schedules coalesce to one run, and uncertain writes never replay after restart.

All ten workflow families use reusable steps: bounded local/connector reads, local-model generation, checked local exports, notifications, allowlisted application launches, and owner-reviewed external actions. Private workflow analysis defaults to native Ollama even when voice chat uses a hosted model. Cloud analysis needs a separate explicit opt-in. A foreground conversation preempts background generation; only that read-only generation can resume, never an uncertain write.

Google Desktop OAuth uses PKCE and separate read-mail, send-mail, Tasks and app-file scopes. Gmail drafts are local until owner review; no broad modify/delete mailbox permission is requested. Drive access is restricted to files created/opened with this app. Generic connectors are named, owner-configured GET operations; models cannot invent URLs, HTTP methods or purchase endpoints. Home Assistant accepts explicitly configured local server addresses and allowlisted light entities; every physical change needs review.

No billing account, purchase action, paid API upgrade, cloud speech deployment or always-on recording is part of setup. Google quota and account availability are prerequisites, not assumed. Windows and live account/hardware checks remain distinct from mocked contract tests and real local workflow tests.
