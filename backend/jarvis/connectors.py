"""Fixed-scope optional service adapters and reviewed writes. Secrets stay in OS keyring."""

import asyncio
import base64
import hashlib
import ipaddress
import json
import secrets
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Literal
from urllib.parse import urlencode, urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .calendar import Calendar
from .credentials import credentials
from .config import ORIGIN
from .exports import document_path
from .store import uid, now

SCOPES = {
    "mail_read": "https://www.googleapis.com/auth/gmail.readonly",
    "mail_send": "https://www.googleapis.com/auth/gmail.send",
    "tasks": "https://www.googleapis.com/auth/tasks",
    "drive": "https://www.googleapis.com/auth/drive.file",
    "calendar_write": "https://www.googleapis.com/auth/calendar.events.owned",
}


class HomeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(max_length=200)
    entities: list[str] = Field(min_length=1, max_length=30)
    token: str = Field(min_length=1, max_length=4000, repr=False)

    @field_validator("url")
    @classmethod
    def local_server(cls, value):
        parsed = urlsplit(value)
        try:
            ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            raise ValueError("Use an explicit local IPv4/IPv6 address") from None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not (ip.is_private or ip.is_loopback)
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                "Home Assistant must be an explicit local server; no credentials in URLs"
            )
        return value.rstrip("/")

    @field_validator("entities")
    @classmethod
    def light_entities(cls, values):
        import re

        if any(not re.fullmatch(r"light\.[a-z0-9_]{1,80}", v) for v in values):
            raise ValueError("Only explicit light.* entity identifiers are supported")
        return sorted(set(values))


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["send_email", "create_task", "upload_document", "home_light"]
    to: str = Field(default="", max_length=254)
    subject: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=20000)
    title: str = Field(default="", max_length=200)
    document_id: str = Field(default="", max_length=36)
    entity: str = Field(default="", max_length=100)
    service: Literal["turn_on", "turn_off"] = "turn_on"


class MailMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class MailReply(MailMessage):
    content: str = Field(min_length=1, max_length=20000)


class Connectors:
    def __init__(self, store):
        self.store = store
        self.client = Calendar()
        self.pending = {}
        self.access = {}
        self.workflows = None
        store.run(
            "UPDATE external_actions SET state='interrupted' WHERE state='running'"
        )

    def config(self, profile):
        rows = self.store.all("SELECT * FROM connectors WHERE id=?", (profile,))
        return rows[0] if rows else {"id": profile, "config": "{}", "connected": 0}

    async def configure_api(self, config):
        from .custom_api import public_address

        await public_address(urlsplit(config.url).hostname)
        if config.token:
            await self.save_secret("api:" + config.name, config.token)
        else:
            import keyring

            try:
                await asyncio.to_thread(
                    keyring.delete_password,
                    "Jarvis Local",
                    "connector:api:" + config.name,
                )
            except keyring.errors.PasswordDeleteError:
                pass
            credentials.invalidate("connector:api:" + config.name)
        self.store.run(
            "INSERT OR REPLACE INTO connectors VALUES(?,?,1)",
            (
                "api:" + config.name,
                json.dumps(
                    {
                        "name": config.name,
                        "url": config.url,
                        "has_token": bool(config.token),
                    }
                ),
            ),
        )
        return {"configured": True, "verified": False}

    def snapshot(self):
        from .phone import available

        return {
            "iphone": {
                "available": available(),
                "enabled": bool(self.config("iphone")["connected"]),
                "call_audio_agent": False,
            },
            "profiles": [
                {
                    "id": p,
                    "configured": self.client.configured(),
                    "connected": bool(self.config(p)["connected"]),
                    "scope": s,
                }
                for p, s in SCOPES.items()
            ],
            "home": {
                **json.loads(self.config("home")["config"]),
                "connected": bool(self.config("home")["connected"]),
            },
            "actions": self.store.all(
                "SELECT * FROM external_actions ORDER BY created DESC LIMIT 60"
            ),
            "apis": [
                {"id": r["id"], **json.loads(r["config"])}
                for r in self.store.all(
                    "SELECT * FROM connectors WHERE id LIKE 'api:%'"
                )
            ],
            "usage": self.store.all(
                "SELECT * FROM connector_usage WHERE day=?", (now()[:10],)
            ),
        }

    def begin(self, profile):
        if profile not in SCOPES:
            raise ValueError("Unknown Google connector")
        client = self.client.client()
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        self.pending[state] = (profile, verifier, time.monotonic())
        self.pending = {
            k: v for k, v in self.pending.items() if time.monotonic() - v[2] < 600
        }
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": ORIGIN + "/api/connectors/google/callback",
                "response_type": "code",
                "scope": SCOPES[profile],
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )

    async def finish(self, state, code):
        profile, verifier, created = self.pending.pop(state, (None, None, 0))
        if not verifier or time.monotonic() - created > 600:
            raise ValueError("Invalid or expired OAuth state")
        client = self.client.client()
        async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client["client_id"],
                    "client_secret": client.get("client_secret", ""),
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": ORIGIN + "/api/connectors/google/callback",
                    "grant_type": "authorization_code",
                },
            )
            if response.status_code != 200:
                raise ValueError("Google OAuth exchange failed; reconnect")
            result = response.json()
        refresh = result.get("refresh_token")
        if not refresh:
            raise ValueError(
                "Google did not return a refresh token; reconnect with consent"
            )
        await self.save_secret(profile, refresh)
        self.store.run(
            "INSERT OR REPLACE INTO connectors VALUES(?,?,?)", (profile, "{}", 1)
        )
        return {"connected": True, "profile": profile}

    @staticmethod
    async def save_secret(profile, value):
        import keyring

        await asyncio.to_thread(
            keyring.set_password, "Jarvis Local", "connector:" + profile, value
        )
        credentials.invalidate("connector:" + profile)

    async def disconnect(self, profile):
        if profile not in {*SCOPES, "home", "iphone"} and not profile.startswith(
            "api:"
        ):
            raise ValueError("Unknown connector")
        import keyring

        try:
            await asyncio.to_thread(
                keyring.delete_password, "Jarvis Local", "connector:" + profile
            )
        except keyring.errors.PasswordDeleteError:
            pass
        credentials.invalidate("connector:" + profile)
        self.access.pop(profile, None)
        self.store.run("DELETE FROM connectors WHERE id=?", (profile,))
        if profile == "calendar_write":
            self.store.run(
                "UPDATE external_actions SET state='rejected' WHERE state='pending' AND kind IN ('create_calendar_event','update_calendar_event')"
            )
        self.store.run(
            "UPDATE external_actions SET state='rejected' WHERE state='pending' AND kind=?",
            (
                {
                    "mail_send": "send_email",
                    "tasks": "create_task",
                    "drive": "upload_document",
                    "home": "home_light",
                    "iphone": "iphone_call",
                }.get(profile, ""),
            ),
        )

    def budget(self, profile):
        day = now()[:10]
        with self.store.lock:
            row = self.store.all(
                "SELECT count FROM connector_usage WHERE id=? AND day=?", (profile, day)
            )
            if row and row[0]["count"] >= 300:
                raise ValueError(
                    "Connector daily limit reached (300 requests); try tomorrow"
                )
            self.store.run(
                "INSERT INTO connector_usage VALUES(?,?,1) ON CONFLICT(id,day) DO UPDATE SET count=count+1",
                (profile, day),
            )

    async def token(self, profile):
        if not self.config(profile)["connected"]:
            raise ValueError(profile + ": Not connected")
        cached = self.access.get(profile)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        refresh = await credentials.read("connector:" + profile)
        if not refresh:
            raise ValueError("Reconnect Google " + profile)
        client = self.client.client()
        async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client["client_id"],
                    "client_secret": client.get("client_secret", ""),
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code != 200:
                raise ValueError("Google authorization expired or denied; reconnect")
            result = response.json()
        self.access[profile] = (
            result["access_token"],
            time.monotonic() + min(int(result.get("expires_in", 3600)), 3600) - 60,
        )
        return result["access_token"]

    async def request(self, profile, method, path, **kwargs):
        self.budget(profile)
        token = await self.token(profile)
        async with httpx.AsyncClient(
            timeout=15, trust_env=False, follow_redirects=False
        ) as http:
            async with http.stream(
                method,
                "https://www.googleapis.com/" + path,
                headers={
                    "Authorization": "Bearer " + token,
                    **kwargs.pop("headers", {}),
                },
                **kwargs,
            ) as response:
                # Never echo service error bodies containing private data or credentials.
                if response.status_code >= 500:
                    raise InterruptedError(
                        "Service failed; write may have taken effect. Inspect account before retry."
                    )
                if response.status_code >= 400:
                    raise ValueError(
                        f"Google {profile} request failed (HTTP {response.status_code}); check enabled API, consent and quotas"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise InterruptedError(
                            "Connector response exceeded 2 MB; inspect any write result before retry"
                        )
                return json.loads(body)

    async def read(self, profile):
        if profile == "calendar_write":
            from .calendar_actions import PATH

            result = await self.request(
                profile,
                "GET",
                PATH,
                params={
                    "timeMin": now(),
                    "maxResults": 30,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
            )
            return [
                {
                    k: e.get(k)
                    for k in (
                        "id",
                        "summary",
                        "start",
                        "end",
                        "description",
                        "location",
                        "organizer",
                        "recurringEventId",
                    )
                }
                for e in result.get("items", [])
            ]
        if profile == "tasks":
            result = await self.request(
                profile,
                "GET",
                "tasks/v1/lists/@default/tasks",
                params={"maxResults": 50, "showCompleted": "false"},
            )
            return [
                {
                    "id": v["id"],
                    "title": v.get("title", ""),
                    "notes": v.get("notes", "")[:2000],
                    "due": v.get("due"),
                }
                for v in result.get("items", [])
            ]
        if profile == "drive":
            result = await self.request(
                profile,
                "GET",
                "drive/v3/files",
                params={
                    "pageSize": 30,
                    "fields": "files(id,name,mimeType,webViewLink)",
                    "q": "trashed=false",
                },
            )
            return result.get("files", [])
        if profile == "mail_read":
            result = await self.request(
                profile,
                "GET",
                "gmail/v1/users/me/messages",
                params={"maxResults": 10, "q": "in:inbox newer_than:7d"},
            )
            output = []
            for message in result.get("messages", []):
                details = await self.request(
                    profile,
                    "GET",
                    "gmail/v1/users/me/messages/" + message["id"],
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["Subject", "From", "Date"],
                    },
                )
                output.append(
                    {
                        "id": message["id"],
                        "headers": details.get("payload", {}).get("headers", []),
                        "snippet": details.get("snippet", "")[:1500],
                    }
                )
            return output
        raise ValueError("This connector has no permitted read operation")

    async def read_message(self, message_id):
        MailMessage(message_id=message_id)
        details = await self.request(
            "mail_read",
            "GET",
            "gmail/v1/users/me/messages/" + message_id,
            params={"format": "full"},
        )
        headers = {
            h["name"].lower(): h["value"][:2000]
            for h in details.get("payload", {}).get("headers", [])
        }
        parts = []
        truncated = False

        def extract(part, depth=0):
            nonlocal truncated
            if depth > 8 or len(parts) > 30:
                truncated = True
                return
            if part.get("mimeType") == "text/plain" and not part.get("filename"):
                raw = part.get("body", {}).get("data", "")
                truncated = truncated or len(raw) > 26664
                encoded = raw[:40000]
                if encoded:
                    try:
                        parts.append(
                            base64.urlsafe_b64decode(
                                encoded + "=" * (-len(encoded) % 4)
                            ).decode("utf-8", errors="replace")[:20000]
                        )
                    except ValueError:
                        pass
            for child in part.get("parts", [])[:30]:
                extract(child, depth + 1)

        extract(details.get("payload", {}))
        combined = "\n".join(parts)
        truncated = truncated or len(combined) > 20000
        return {
            "id": details["id"],
            "thread_id": details.get("threadId"),
            "from": headers.get("from", ""),
            "reply_to": headers.get("reply-to", headers.get("from", "")),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "message_id_header": headers.get("message-id", ""),
            "text": combined[:20000] or details.get("snippet", "")[:2000],
            "body_complete": bool(parts) and not truncated,
            "truncated": truncated,
            "attachments_downloaded": False,
        }

    async def prepare_reply(self, message_id, content):
        MailReply(message_id=message_id, content=content)
        original = await self.read_message(message_id)
        recipient = parseaddr(original["reply_to"])[1]
        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        header = original["message_id_header"]
        if "\n" in header or "\r" in header or len(header) > 500:
            raise ValueError(
                "Unsafe source Message-ID header; draft a new message instead"
            )
        proposal = self.propose(
            "send_email",
            {"to": recipient, "subject": subject[:200], "content": content},
        )
        row = self.store.all(
            "SELECT args FROM external_actions WHERE id=?", (proposal["action_id"],)
        )[0]
        args = json.loads(row["args"])
        args["reply_message_id"] = message_id
        args["thread_id"] = original["thread_id"]
        args["in_reply_to"] = header
        self.store.run(
            "UPDATE external_actions SET args=? WHERE id=?",
            (json.dumps(args), proposal["action_id"]),
        )
        return proposal

    async def configure_home(self, config):
        await self.save_secret("home", config.token)
        self.store.run(
            "INSERT OR REPLACE INTO connectors VALUES(?,?,1)",
            ("home", json.dumps({"url": config.url, "entities": config.entities})),
        )
        return {"configured": True, "verified": False}

    def propose(self, kind, args, run_id=None):
        body = Action.model_validate({"kind": kind, **args})
        profile = {
            "send_email": "mail_send",
            "create_task": "tasks",
            "upload_document": "drive",
            "home_light": "home",
        }[kind]
        if kind != "send_email" and not self.config(profile)["connected"]:
            raise ValueError(profile + ": Not connected")
        if kind == "send_email":
            import re

            if (
                not re.fullmatch(
                    r"[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    body.to,
                )
                or not body.subject.strip()
                or not body.content.strip()
                or "\n" in body.subject
                or "\r" in body.subject
            ):
                raise ValueError("Provide one valid recipient, subject and body")
        elif kind == "create_task" and not body.title.strip():
            raise ValueError("Task title is required")
        elif kind == "upload_document":
            document_path(self.store, body.document_id)
        elif kind == "home_light" and body.entity not in json.loads(
            self.config("home")["config"]
        ).get("entities", []):
            raise ValueError("Light is not in the configured entity allowlist")
        if run_id:
            existing = self.store.all(
                "SELECT id FROM external_actions WHERE run_id=?", (run_id,)
            )
            if existing:
                return {"action_id": existing[0]["id"], "status": "awaiting_approval"}
        if (
            len(self.store.all("SELECT id FROM external_actions WHERE state='pending'"))
            >= 100
        ):
            raise ValueError("At most 100 pending actions")
        id = uid()
        self.store.run(
            "INSERT INTO external_actions VALUES(?,?,?,?,?,?,?,?)",
            (
                id,
                run_id,
                kind,
                body.model_dump_json(exclude={"kind"}),
                "pending",
                None,
                now(),
                now(),
            ),
        )
        return {
            "action_id": id,
            "status": "awaiting_approval",
            "message": "Review exact details in Automations. No external action has run.",
        }

    async def review(self, id, approve):
        with self.store.lock:
            rows = self.store.all("SELECT * FROM external_actions WHERE id=?", (id,))
            if not rows or rows[0]["state"] != "pending":
                raise ValueError("Action unavailable or already reviewed")
            row = rows[0]
            expired = (
                datetime.now(timezone.utc) - datetime.fromisoformat(row["created"])
            ).total_seconds() > 900
            if row["run_id"]:
                run = self.store.all(
                    "SELECT state FROM workflow_runs WHERE id=?", (row["run_id"],)
                )
                expired = expired or not run or run[0]["state"] != "awaiting_approval"
            if expired:
                self.store.run(
                    "UPDATE external_actions SET state='expired' WHERE id=?", (id,)
                )
                raise ValueError("Approval expired; create a fresh request")
            self.store.run(
                "UPDATE external_actions SET state=?,updated=? WHERE id=?",
                ("running" if approve else "rejected", now(), id),
            )
        if not approve:
            if row["run_id"]:
                self.store.run(
                    "UPDATE workflow_runs SET state='cancelled' WHERE id=?",
                    (row["run_id"],),
                )
            return {"state": "rejected"}
        try:
            result = await asyncio.wait_for(
                self.perform(row["kind"], json.loads(row["args"])), 30
            )
            state = "succeeded"
        except (
            TimeoutError,
            InterruptedError,
            httpx.TransportError,
            asyncio.CancelledError,
        ):
            self.store.run(
                "UPDATE external_actions SET state='interrupted',result=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "error": "Result uncertain; inspect the connected account/device. Never retried automatically."
                        }
                    ),
                    id,
                ),
            )
            if row["run_id"]:
                self.store.run(
                    "UPDATE workflow_runs SET state='interrupted' WHERE id=?",
                    (row["run_id"],),
                )
            raise
        except Exception as error:
            state = "failed"
            result = {"error": str(error)[:300]}
        self.store.run(
            "UPDATE external_actions SET state=?,result=?,updated=? WHERE id=?",
            (state, json.dumps(result), now(), id),
        )
        if row["run_id"]:
            self.store.run(
                "UPDATE workflow_runs SET state=?,result=?,updated=? WHERE id=?",
                (state, json.dumps(result), now(), row["run_id"]),
            )
        return {"state": state, "result": result}

    async def perform(self, kind, args):
        if kind == "iphone_call":
            from .phone import perform

            return await perform(self, args)
        if kind in {"create_calendar_event", "update_calendar_event"}:
            from .calendar_actions import perform

            return await perform(self, kind, args)
        if kind == "send_email":
            message = EmailMessage()
            message["To"] = args["to"]
            message["Subject"] = args["subject"]
            message.set_content(args["content"])
            if args.get("in_reply_to"):
                message["In-Reply-To"] = args["in_reply_to"]
                message["References"] = args["in_reply_to"]
            result = await self.request(
                "mail_send",
                "POST",
                "gmail/v1/users/me/messages/send",
                json={
                    "raw": base64.urlsafe_b64encode(message.as_bytes()).decode(),
                    **(
                        {"threadId": args["thread_id"]} if args.get("thread_id") else {}
                    ),
                },
            )
            if not result.get("id"):
                raise InterruptedError("No sent message ID returned; inspect Sent mail")
            return {
                "message_id": result["id"],
                "status": "accepted_by_gmail",
                "delivery_verified": False,
            }
        if kind == "create_task":
            result = await self.request(
                "tasks",
                "POST",
                "tasks/v1/lists/@default/tasks",
                json={"title": args["title"], "notes": args["content"]},
            )
            if not result.get("id"):
                raise InterruptedError("No task ID returned; inspect Google Tasks")
            return {
                "task_id": result["id"],
                "title": result.get("title"),
                "status": "created",
            }
        if kind == "upload_document":
            path = document_path(self.store, args["document_id"])
            import mimetypes

            boundary = "jarvis-" + secrets.token_hex(12)
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body = (
                (
                    f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                    + json.dumps({"name": path.name})
                    + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
                ).encode()
                + path.read_bytes()
                + f"\r\n--{boundary}--\r\n".encode()
            )
            result = await self.request(
                "drive",
                "POST",
                "upload/drive/v3/files",
                params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
                content=body,
                headers={"Content-Type": "multipart/related; boundary=" + boundary},
            )
            if not result.get("id"):
                raise InterruptedError("No Drive file ID returned; inspect Drive")
            return result
        if kind == "home_light":
            config = json.loads(self.config("home")["config"])
            if args["entity"] not in config.get("entities", []):
                raise ValueError("Light no longer allowlisted")
            self.budget("home")
            token = await credentials.read("connector:home")
            async with httpx.AsyncClient(
                timeout=15, trust_env=False, follow_redirects=False
            ) as http:
                response = await http.post(
                    config["url"] + "/api/services/light/" + args["service"],
                    headers={"Authorization": "Bearer " + token},
                    json={"entity_id": args["entity"]},
                )
                if response.status_code != 200:
                    raise InterruptedError(
                        "Device result uncertain; inspect Home Assistant before retry"
                    )
                check = await http.get(
                    config["url"] + "/api/states/" + args["entity"],
                    headers={"Authorization": "Bearer " + token},
                )
                if check.status_code != 200 or check.json().get("state") != (
                    "on" if args["service"] == "turn_on" else "off"
                ):
                    raise InterruptedError(
                        "Light service returned but state could not be verified"
                    )
                return {
                    "entity": args["entity"],
                    "state": check.json()["state"],
                    "verified": True,
                }
        raise ValueError("Action not permitted")
