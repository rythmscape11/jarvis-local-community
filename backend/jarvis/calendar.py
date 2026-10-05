"""Optional Google Calendar read-only desktop OAuth, PKCE, loopback redirect."""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
import httpx
from .config import ORIGIN, DATA
from .credentials import credentials


class Calendar:
    def __init__(self):
        self.pending = {}
        self.account = "calendar-readonly"

    def client(self):
        file = os.getenv("GOOGLE_CLIENT_FILE") or DATA / "calendar-client.json"
        if not file:
            raise ValueError(
                "Not connected. Configure GOOGLE_CLIENT_FILE with a Google Desktop OAuth client JSON."
            )
        if not Path(file).exists():
            raise ValueError(
                "Not connected. Import your Google Desktop OAuth client JSON in Calendar settings."
            )
        data = json.loads(Path(file).read_text()).get("installed")
        if not data:
            raise ValueError("A Desktop OAuth client is required")
        return data

    def configured(self):
        try:
            self.client()
            return True
        except (ValueError, OSError):
            return False

    def configure(self, path):
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file() or source.stat().st_size > 65536:
            raise ValueError(
                "Select a Google Desktop OAuth JSON file smaller than 64 KB"
            )
        data = json.loads(source.read_text()).get("installed")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("client_id"), str)
            or not data["client_id"].endswith(".apps.googleusercontent.com")
        ):
            raise ValueError(
                "This file is not a Google Desktop OAuth client. Download a Desktop app client JSON from Google Cloud Console."
            )
        selected = {k: data[k] for k in ("client_id", "client_secret") if k in data}
        target = DATA / "calendar-client.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"installed": selected}))
        temporary.chmod(0o600)
        temporary.replace(target)
        return {"configured": True, "connected": False}

    async def connected(self, timeout=0.15):
        if not self.configured():
            return False
        try:
            return bool(await credentials.read(self.account, timeout=timeout))
        except Exception:
            return False

    def begin(self):
        client = self.client()
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        self.pending = {state: (verifier, time.monotonic())}
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": ORIGIN + "/api/calendar/callback",
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/calendar.readonly",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )

    async def finish(self, state, code):
        verifier, created = self.pending.pop(state, (None, 0))
        if not verifier or time.monotonic() - created > 600:
            raise ValueError("OAuth state expired or invalid")
        client = self.client()
        async with httpx.AsyncClient(trust_env=False) as http:
            response = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client["client_id"],
                    "client_secret": client.get("client_secret", ""),
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": ORIGIN + "/api/calendar/callback",
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            token = response.json().get("refresh_token")
        if not token:
            raise ValueError("No refresh token returned; reconnect with consent")
        import keyring

        await asyncio.to_thread(
            keyring.set_password, "Jarvis Local", self.account, token
        )
        credentials.invalidate(self.account)

    async def events(self):
        refresh = await credentials.read(self.account)
        if not refresh:
            raise ValueError("Not connected")
        client = self.client()
        from .store import now

        async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
            token = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client["client_id"],
                    "client_secret": client.get("client_secret", ""),
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
            token.raise_for_status()
            response = await http.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": "Bearer " + token.json()["access_token"]},
                params={
                    "timeMin": now(),
                    "maxResults": 20,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
            )
            response.raise_for_status()
            return [
                {
                    "id": e["id"],
                    "title": e.get("summary", "Untitled"),
                    "start": e.get("start"),
                    "end": e.get("end"),
                }
                for e in response.json().get("items", [])
            ]

    async def disconnect(self):
        import keyring

        try:
            await asyncio.to_thread(
                keyring.delete_password, "Jarvis Local", self.account
            )
        except keyring.errors.PasswordDeleteError:
            pass
        finally:
            credentials.invalidate(self.account)
