"""Revocable, owner-approved phone pairing. The main backend stays loopback-only."""

import asyncio
import contextlib
import hashlib
import json
import secrets
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import config
from .store import now, uid


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeviceConfig(Strict):
    enabled: bool = False
    origin: str = ""

    @field_validator("origin")
    @classmethod
    def private_https(cls, value):
        if not value:
            return value
        p = urlsplit(value)
        if (
            p.scheme != "https"
            or not p.hostname
            or not p.hostname.endswith(".ts.net")
            or p.username
            or p.password
            or p.port not in {None, 443}
            or p.path not in {"", "/"}
            or p.query
            or p.fragment
        ):
            raise ValueError(
                "Use your exact private Tailscale HTTPS origin, without path, credentials or query"
            )
        return "https://" + p.hostname


class Claim(Strict):
    code: str = Field(pattern=r"^\d{8}$")
    name: str = Field(min_length=1, max_length=60)


class Review(Strict):
    approve: bool


class Password(Strict):
    password: str = Field(min_length=8, max_length=128, repr=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Devices:
    def __init__(self, store, data):
        self.store, self.data = store, Path(data)
        self.code = None
        self.failures = {}
        self.leases = {}
        self.gateway_running = False
        self.gateway_error = None
        store.run(
            "CREATE TABLE IF NOT EXISTS paired_devices(id TEXT PRIMARY KEY,name TEXT,token_hash TEXT UNIQUE,state TEXT,created TEXT,expires REAL)"
        )
        store.run("INSERT OR IGNORE INTO migrations VALUES(7)")

    def config(self):
        path = self.data / "companion.json"
        return (
            DeviceConfig.model_validate_json(path.read_text())
            if path.exists()
            else DeviceConfig()
        )

    def configure(self, body):
        if body.enabled and not body.origin:
            raise ValueError("Configure the private HTTPS origin before enabling")
        path = self.data / "companion.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(body.model_dump_json())
        temporary.chmod(0o600)
        temporary.replace(path)
        if not body.enabled:
            self.code = None
            self.store.run("UPDATE paired_devices SET state='revoked'")
        return self.snapshot()

    def snapshot(self):
        return {
            "config": self.config().model_dump(),
            "gateway_running": self.gateway_running,
            "gateway_error": self.gateway_error,
            "devices": self.store.all(
                "SELECT id,name,state,created,expires FROM paired_devices ORDER BY created DESC"
            ),
            "phone_background_wake": False,
            "remote_action_approval": False,
        }

    def begin(self):
        if not self.config().enabled:
            raise ValueError("Enable the private companion first")
        self.code = (f"{secrets.randbelow(100000000):08d}", time.monotonic() + 120)
        return {
            "code": self.code[0],
            "expires_seconds": 120,
            "url": self.config().origin,
            "desktop_approval_required": True,
        }

    def claim(self, body, peer):
        with self.store.lock:
            stamp = time.monotonic()
            self.failures = {
                k: v for k, v in self.failures.items() if stamp - v[1] < 60
            }
            count, _ = self.failures.get(peer, (0, stamp))
            if count >= 5 or len(self.failures) > 100:
                raise ValueError("Pairing temporarily limited; wait one minute")
            if (
                not self.code
                or stamp > self.code[1]
                or not secrets.compare_digest(body.code, self.code[0])
            ):
                self.failures[peer] = (count + 1, stamp)
                raise ValueError("Invalid or expired pairing code")
            if (
                len(
                    self.store.all(
                        "SELECT id FROM paired_devices WHERE state IN ('pending','approved') AND expires>?",
                        (time.time(),),
                    )
                )
                >= 8
            ):
                raise ValueError("At most eight paired devices; revoke an old device")
            self.code = None
            token = secrets.token_urlsafe(32)
            id = uid()
            self.store.run(
                "INSERT INTO paired_devices VALUES(?,?,?,?,?,?)",
                (
                    id,
                    body.name,
                    digest(token),
                    "pending",
                    now(),
                    time.time() + 30 * 86400,
                ),
            )
            return token

    def resolve(self, token, approved=True):
        if not self.config().enabled or not token or len(token) > 100:
            return None
        rows = self.store.all(
            "SELECT * FROM paired_devices WHERE token_hash=? AND expires>?",
            (digest(token), time.time()),
        )
        if not rows or rows[0]["state"] not in (
            {"approved"} if approved else {"approved", "pending"}
        ):
            return None
        return rows[0]

    def review(self, id, approve):
        with self.store.lock:
            rows = self.store.all(
                "SELECT * FROM paired_devices WHERE id=? AND state='pending' AND expires>?",
                (id, time.time()),
            )
            if not rows:
                raise ValueError("Pairing unavailable, expired or already reviewed")
            # Approval is a desktop action; a pending browser has no access to history or tools.
            self.store.run(
                "UPDATE paired_devices SET state=? WHERE id=?",
                ("approved" if approve else "revoked", id),
            )
        return self.snapshot()

    def revoke(self, id):
        self.store.run("UPDATE paired_devices SET state='revoked' WHERE id=?", (id,))
        return self.snapshot()

    def lease(self, device, sessions):
        previous = self.leases.get(device["id"])
        if previous and sessions.get(previous, 0) > time.time():
            return previous
        token = secrets.token_urlsafe(32)
        sessions[token] = min(device["expires"], time.time() + 12 * 3600)
        self.leases[device["id"]] = token
        return token


def local_routes(devices):
    api = APIRouter()

    @api.get("/api/devices")
    async def snapshot():
        return devices.snapshot()

    @api.put("/api/devices/config")
    async def configure(body: DeviceConfig):
        try:
            return devices.configure(body)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @api.post("/api/devices/pair")
    async def begin():
        try:
            return devices.begin()
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @api.post("/api/devices/{id}/review")
    async def review(id: str, body: Review):
        try:
            return devices.review(id, body.approve)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @api.delete("/api/devices/{id}")
    async def revoke(id: str):
        return devices.revoke(id)

    return api


class VoiceSocket:
    """Adapt an approved TLS phone socket to the existing validated voice controller."""

    def __init__(self, ws, devices, owner_token, owner, sessions):
        self.ws, self.devices, self.owner = ws, devices, owner
        self.token = ws.cookies.get("jarvis_device", "")
        self.cookies = {"jarvis_session": owner_token}
        self.headers = {"origin": config.ORIGIN}
        self.owner_token, self.sessions = owner_token, sessions

    async def accept(self):
        await self.ws.accept()

    async def close(self, code=1000):
        await self.ws.close(code=code)

    async def check(self):
        if (
            not self.devices.resolve(self.token)
            or not self.owner.allowed(self.owner_token)
            or self.sessions.get(self.owner_token, 0) < time.time()
        ):
            await self.close(4003)
            raise WebSocketDisconnect(4003)

    async def send_json(self, body):
        await self.check()
        await self.ws.send_json(body)

    async def receive_text(self):
        while True:
            await self.check()
            try:
                raw = await asyncio.wait_for(self.ws.receive_text(), 2)
            except TimeoutError:
                continue
            if len(raw) > 32000:
                raise ValueError("Companion message exceeds 32 KB")
            body = json.loads(raw)
            if not isinstance(body, dict) or body.get("type") not in {
                "text",
                "capture_start",
                "audio",
                "capture_stop",
                "interrupt",
                "barge_audio",
                "playback_done",
                "ping",
            }:
                raise ValueError("Unsupported companion event")
            # A phone never selects another device's conversation session.
            return raw


def gateway(devices, owner, sessions, voice_handler, built):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def origin_ok(headers):
        selected = devices.config()
        return selected.enabled and headers.get("origin") == selected.origin

    @app.middleware("http")
    async def security(request, call_next):
        selected = devices.config()
        if not selected.enabled:
            return Response("Companion disabled", 503)
        if request.headers.get("host") != urlsplit(selected.origin).netloc:
            return Response("Host denied", 403)
        if request.method not in {"GET", "HEAD"} and not origin_ok(request.headers):
            return Response("Origin denied", 403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 12000:
            return Response("Body too large", 413)
        if (
            request.url.path.startswith("/phone/")
            and request.url.path != "/phone/pair"
            and not devices.resolve(
                request.cookies.get("jarvis_device", ""), approved=False
            )
        ):
            return Response("Pair this device first", 401)
        if request.method not in {"GET", "HEAD"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 12000:
                    return Response("Body too large", 413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; worker-src 'self'; img-src 'self' data:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'",
                "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
            }
        )
        return response

    @app.post("/phone/pair")
    async def pair(body: Claim, request: Request, response: Response):
        try:
            token = devices.claim(body, request.client.host)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        response.set_cookie(
            "jarvis_device",
            token,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=30 * 86400,
            path="/",
        )
        return {"status": "pending_desktop_approval"}

    @app.get("/phone/status")
    async def status(request: Request):
        device = devices.resolve(
            request.cookies.get("jarvis_device", ""), approved=False
        )
        if device["state"] != "approved":
            return {"status": "pending_desktop_approval"}
        token = devices.lease(device, sessions)
        return {
            "status": "approved",
            "owner": owner.status(token),
            "background_wake": False,
        }

    @app.post("/phone/unlock")
    async def unlock(body: Password, request: Request):
        device = devices.resolve(request.cookies.get("jarvis_device", ""))
        if not device:
            raise HTTPException(403, "Desktop approval required")
        token = devices.lease(device, sessions)
        try:
            await owner.unlock(token, body.password)
        except ValueError:
            raise HTTPException(403, "Owner unlock failed") from None
        return {"status": "unlocked"}

    @app.get("/phone/reminders")
    async def reminders(request: Request):
        device = devices.resolve(request.cookies.get("jarvis_device", ""))
        if not device:
            raise HTTPException(403, "Desktop approval required")
        token = devices.lease(device, sessions)
        if not owner.allowed(token):
            raise HTTPException(423, "Owner locked")
        return devices.store.all(
            "SELECT id,title,due,timezone,state FROM reminders WHERE state IN ('pending','delivered') ORDER BY due LIMIT 50"
        )

    @app.websocket("/phone/ws")
    async def voice(ws: WebSocket):
        if (
            not origin_ok(ws.headers)
            or ws.headers.get("host") != urlsplit(devices.config().origin).netloc
        ):
            await ws.close(1008)
            return
        device = devices.resolve(ws.cookies.get("jarvis_device", ""))
        if not device:
            await ws.close(1008)
            return
        await voice_handler(
            VoiceSocket(ws, devices, devices.lease(device, sessions), owner, sessions)
        )

    @app.get("/")
    async def index():
        return FileResponse(built / "companion.html")

    @app.get("/capture-worklet.js")
    async def worklet():
        return FileResponse(built / "capture-worklet.js")

    if (built / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=built / "assets"))
    return app


class GatewayServer:
    def __init__(self, devices, app, port=8770):
        self.devices, self.app, self.port = devices, app, port
        self.server = self.task = self.socket = None

    async def start(self):
        import uvicorn

        class Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):
                yield

        self.socket = socket.socket()
        try:
            self.socket.bind(("127.0.0.1", self.port))
        except OSError:
            self.socket.close()
            self.socket = None
            self.devices.gateway_error = (
                "Companion port in use; no existing process was stopped"
            )
            return
        self.server = Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                access_log=False,
                ws_max_size=32000,
            )
        )
        self.task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
        for _ in range(100):
            if self.server.started:
                self.devices.gateway_running = True
                return
            if self.task.done():
                self.devices.gateway_error = "Companion gateway could not start"
                await self.close()
                return
            await asyncio.sleep(0.02)
        self.devices.gateway_error = "Companion gateway startup timed out"
        await self.close()

    async def close(self):
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(self.task, 5)
            except TimeoutError:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.socket:
            self.socket.close()
        self.devices.gateway_running = False
