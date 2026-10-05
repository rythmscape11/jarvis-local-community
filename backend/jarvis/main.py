import asyncio
import base64
import contextlib
import json
import os
import secrets
import time
from collections import deque
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import config
from .config import Settings
from .store import Store, uid
from .tools import Tools
from .jobs import Jobs
from .engines import Whisper, LocalSpeech, Silero
from .agent import Agent, round_ms
from .providers import ModelRouter, credential_name
from .credentials import credentials
from .updates import Updates
from .owner import OwnerLock, Speaker
from .google_ai import GoogleAI
from .devices import Devices, GatewayServer, gateway, local_routes
from .calendar import Calendar
from .control import Control
from .news import News
from .workflows import Workflows
from .connectors import Connectors
from .workflow_api import routes

settings = config.read_settings()
WAKE_FOLLOWUP_SECONDS = 45


def is_voice_stop(text):
    words = " ".join(re.findall(r"[\w]+", (text or "").lower()))
    return bool(
        re.fullmatch(
            r"(?:(?:hey )?jarvis )?(?:please |(?:can|could|would) you )?"
            r"(?:please )?(?:stop(?: speaking| talking| listening| please| it)?|"
            r"end conversation|pause conversation|wait|hold on|be quiet|quiet)(?: now| please)?",
            words,
        )
    )


def is_barge_stop(spoken, assistant_text):
    """Accept explicit stops mixed with echo, without treating quoted speech as intent."""
    words = " ".join(re.findall(r"[\w]+", (spoken or "").lower()))
    answer = " ".join(re.findall(r"[\w]+", (assistant_text or "").lower()))
    if is_voice_stop(words):
        return True
    # A short command can be appended to captured speaker echo. Require a
    # terminal multiword stop, absent from the answer, and reject negations.
    match = re.search(r"\bstop (?:speaking|talking|listening)(?: now| please)?$", words)
    if not match or re.search(r"\b(?:don t|dont|do not|never|not) stop\b", words):
        return False
    return match.group(0) not in answer


store = Store(config.DB_PATH)
jobs = Jobs(store)
model = ModelRouter(lambda: settings)
stt = Whisper()
tts = LocalSpeech(lambda: settings)
calendar = Calendar()
tools = Tools(store, lambda: settings)
control = Control(store, lambda: settings)
news = News(store, lambda: settings)
tools.control = control
tools.news = news
tools.calendar = calendar
google_ai = GoogleAI(store, lambda: settings)
tools.google = google_ai
tts.google = google_ai


def select_voice(voice):
    global settings
    updated = Settings.model_validate(settings.model_dump() | {"voice": voice})
    config.save_settings(updated)
    settings = updated


tools.voice_adapter = tts
tools.on_voice_change = select_voice
jobs.news = news
agent = Agent(store, tools, model, tts, lambda: settings)
updates = Updates(config.DATA, lambda: settings)
connectors = Connectors(store)
workflows = Workflows(store, jobs, tools, model, lambda: settings, connectors)
tools.workflows = workflows
tools.connectors = connectors
connectors.workflows = workflows
secret_file = config.DATA / "auth.token"
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(48))
secret_file.chmod(0o600)
secret = secret_file.read_text().strip()
sessions = {}
connections = set()
owner = OwnerLock(config.DATA, Speaker(config.MODELS))
devices = Devices(store, config.DATA)


async def lock_owner_connections():
    owner.lock()
    for socket in list(connections):
        with contextlib.suppress(Exception):
            await socket.send_json({"type": "owner_locked"})
            await socket.close(code=4003)


@asynccontextmanager
async def lifespan(app):
    jobs.start()
    companion = None
    if os.getenv("JARVIS_COMPANION_SERVER", "1") != "0":
        companion = GatewayServer(
            devices,
            gateway(devices, owner, sessions, websocket, config.ROOT / "frontend/dist"),
        )
        await companion.start()
    # Queue startup briefs conservatively; a full queue must not prevent voice startup.
    with contextlib.suppress(ValueError):
        workflows.startup()

    async def warm_engines():
        if os.getenv("JARVIS_WARMUP", "1") == "0":
            return
        # Keep initialization away from the owner's first spoken request.
        if not settings.voice.startswith(("groq-", "gemini-")):
            with contextlib.suppress(Exception):
                await tts.synthesize("I'm here.", settings.voice)
        if settings.provider == "ollama":
            with contextlib.suppress(Exception):
                async with agent.inference:
                    async for _ in model.stream(
                        [{"role": "user", "content": "Say hello in two words."}],
                        [],
                        settings,
                    ):
                        pass

    warmup = asyncio.create_task(warm_engines())

    async def daily_news():
        if os.getenv("JARVIS_NEWS_SCHEDULER", "1") == "0":
            return
        from datetime import datetime, timezone

        while True:
            meta = store.all("SELECT value FROM news_meta WHERE key='last_refresh'")
            age = (
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(meta[0]["value"])
                ).total_seconds()
                if meta
                else 86401
            )
            busy = store.all(
                "SELECT id FROM jobs WHERE kind='news_refresh' AND state IN ('queued','running')"
            )
            if settings.news_enabled and age >= 86400 and not busy:
                with contextlib.suppress(ValueError):
                    jobs.submit(kind="news_refresh")
            await asyncio.sleep(3600)

    async def workflow_scheduler():
        while True:
            with contextlib.suppress(ValueError):
                workflows.tick()
            await asyncio.sleep(30)

    workflow_clock = asyncio.create_task(workflow_scheduler())
    scheduler = asyncio.create_task(daily_news())
    yield
    if companion:
        await companion.close()
    workflow_clock.cancel()
    await asyncio.gather(workflow_clock, return_exceptions=True)
    scheduler.cancel()
    warmup.cancel()
    await asyncio.gather(scheduler, return_exceptions=True)
    await asyncio.gather(warmup, return_exceptions=True)
    await jobs.close()
    await model.close()
    await stt.close()
    await tts.close()
    await google_ai.close()
    store.close()


app = FastAPI(title="Jarvis Local", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(routes(workflows, connectors))
app.include_router(local_routes(devices))
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
)


class OwnerPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=8, max_length=128)


class OwnerEnrollment(OwnerPassword):
    samples: list[Annotated[str, Field(max_length=700000)]] = Field(
        min_length=4, max_length=4
    )


@app.get("/api/owner/status")
async def owner_status(request: Request):
    return owner.status(request.cookies.get("jarvis_session", ""))


@app.post("/api/owner/unlock")
async def owner_unlock(request: Request, body: OwnerPassword):
    try:
        await owner.unlock(request.cookies.get("jarvis_session", ""), body.password)
    except ValueError as error:
        raise HTTPException(403, str(error)) from error
    return owner.status(request.cookies.get("jarvis_session", ""))


@app.post("/api/owner/enroll")
async def owner_enroll(request: Request, body: OwnerEnrollment):
    try:
        samples = [base64.b64decode(value, validate=True) for value in body.samples]
        await owner.enroll(
            request.cookies.get("jarvis_session", ""), body.password, samples
        )
    except Exception as error:
        # Never expose samples, embeddings or passphrases through exception text.
        raise HTTPException(
            400,
            "Enrollment failed. Use four 4–16 second recordings of the same voice and check the downloaded model",
        ) from error
    await lock_owner_connections()
    return owner.status(request.cookies.get("jarvis_session", ""))


@app.post("/api/owner/lock")
async def owner_lock_now():
    await lock_owner_connections()
    return {"locked": True}


@app.post("/api/owner/remove")
async def owner_remove(request: Request, body: OwnerPassword):
    try:
        await owner.remove(request.cookies.get("jarvis_session", ""), body.password)
    except ValueError as error:
        raise HTTPException(403, str(error)) from error
    await lock_owner_connections()
    return {"enabled": False, "locked": False}


@app.middleware("http")
async def local_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin != config.ORIGIN:
        return Response("Origin denied", status_code=403)
    if request.headers.get(
        "sec-fetch-site"
    ) == "cross-site" and request.url.path not in {
        "/api/calendar/callback",
        "/api/connectors/google/callback",
    }:
        return Response("Cross-site access denied", status_code=403)
    public = {
        "/api/ready",
        "/api/session",
        "/api/calendar/callback",
        "/api/connectors/google/callback",
    }
    if request.url.path.startswith("/api/") and request.url.path not in public:
        token = request.cookies.get("jarvis_session", "")
        if sessions.get(token, 0) < time.time():
            return Response(
                "Open Jarvis using ./start or enter your local access token",
                status_code=401,
            )
    if request.method not in {"GET", "HEAD"} and origin != config.ORIGIN:
        return Response("An exact local Origin is required", status_code=403)
    owner_public = {
        "/api/ready",
        "/api/session",
        "/api/owner/status",
        "/api/owner/unlock",
    }
    if request.url.path.startswith("/api/") and request.url.path not in owner_public:
        if not owner.allowed(request.cookies.get("jarvis_session", "")):
            return Response(
                "Owner locked. Enter your owner passphrase in Jarvis", status_code=423
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self' ws://127.0.0.1:%d; script-src 'self'; style-src 'self'; worker-src 'self'; img-src 'self' data:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'"
        % config.PORT
    )
    response.headers["Permissions-Policy"] = (
        "microphone=(self), camera=(), geolocation=()"
    )
    return response


class Login(BaseModel):
    token: str = Field(max_length=200)


class Directory(BaseModel):
    path: str = Field(min_length=1, max_length=2000)


class MemoryEdit(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


class Invoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=100)
    arguments: dict
    key: str = Field(min_length=10, max_length=200)


@app.get("/api/ready")
async def ready():
    return {"ready": True}


@app.post("/api/session")
async def login(body: Login, response: Response):
    if not secrets.compare_digest(body.token, secret):
        raise HTTPException(401, "Invalid local access token")
    expired = [k for k, v in sessions.items() if v < time.time()]
    for k in expired:
        del sessions[k]
    if len(sessions) > 32:
        sessions.clear()
    token = secrets.token_urlsafe(32)
    sessions[token] = time.time() + 12 * 3600
    response.set_cookie(
        "jarvis_session", token, httponly=True, samesite="strict", max_age=12 * 3600
    )
    return {"ok": True}


@app.get("/api/health")
async def health():
    try:
        models = await model.available()
        ollama = {
            "ok": True,
            "models": models,
            "selected_available": settings.model in models
            or settings.model + ":latest" in models,
        }
    except Exception as error:
        ollama = {
            "ok": False,
            "models": [],
            "selected_available": False,
            "message": str(error)[:300]
            if isinstance(error, ValueError)
            else "Model service unavailable. Check the provider and selected model.",
        }
    return {
        "backend": True,
        "provider": settings.provider,
        "ollama": ollama,
        "stt": await stt.health(),
        "tts": {"ok": settings.voice in tts.available(), "voices": tts.available()},
        "vad": config.VAD_PATH.exists(),
        "calendar": {
            "connected": await calendar.connected(),
            "writable_connected": connectors.config("calendar_write")["connected"],
            "configured": calendar.configured(),
            "network_required": True,
        },
        "settings": settings.model_dump(),
        "applications": list(config.APPS),
    }


class VoicePreview(BaseModel):
    voice: str = Field(max_length=100)


@app.post("/api/voice-preview")
async def voice_preview(body: VoicePreview):
    if body.voice not in tts.available():
        raise HTTPException(400, "Voice is not downloaded")
    try:
        output = await tts.synthesize(
            "Hello. I'm Jarvis. I can help you organize your day, find your notes, and think things through. Everything starts right here, on your computer.",
            body.voice,
        )
    except ValueError as error:
        raise HTTPException(503, str(error)[:300]) from error
    return Response(output, media_type="audio/wav")


@app.get("/api/records")
async def records():
    return store.snapshot()


@app.get("/api/generated-documents/{id}/download")
async def download_document(id: str):
    from .exports import document_path

    try:
        path = document_path(store, id)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return FileResponse(path, filename=path.name)


@app.get("/api/news")
async def news_read(query: str = "", category: str = "all"):
    return news.search(query[:500], category)


@app.post("/api/news/refresh")
async def news_refresh():
    if not settings.news_enabled:
        raise HTTPException(400, "Enable news networking in Settings")
    busy = store.all(
        "SELECT id FROM jobs WHERE kind='news_refresh' AND state IN ('queued','running')"
    )
    if busy:
        return {"job_id": busy[0]["id"], "state": "already_queued_or_running"}
    return {"job_id": jobs.submit(kind="news_refresh"), "state": "queued"}


class Approval(BaseModel):
    approved: bool


@app.post("/api/control/{id}/review")
async def control_review(id: str, body: Approval):
    try:
        return await control.approve(id, body.approved)
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.get("/api/control/snapshot")
async def control_snapshot():
    try:
        payload = await asyncio.to_thread(control.snapshot)
    except Exception as error:
        raise HTTPException(400, str(error)[:200])
    return Response(payload, media_type="image/png")


@app.get("/api/updates")
async def update_status():
    return await updates.check()


@app.post("/api/updates/check")
async def check_updates():
    return await updates.check(manual=True)


class ConversationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=20000)


@app.get("/api/conversations")
async def conversation_archive(query: str = ""):
    if len(query) > 500:
        raise HTTPException(400, "Search is limited to 500 characters")
    return store.conversation_archive(query)


@app.delete("/api/conversations")
async def clear_conversations():
    store.clear_conversations()
    return {"ok": True}


@app.delete("/api/conversations/{id}")
async def delete_conversation(id: int):
    try:
        store.edit_conversation(id)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return {"ok": True}


@app.put("/api/conversations/{id}")
async def edit_conversation(id: int, body: ConversationEdit):
    try:
        store.edit_conversation(id, body.content)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return {"ok": True}


@app.get("/api/history/{session}")
async def history(session: str):
    return store.all(
        "SELECT role,content,turn FROM conversations WHERE session=? ORDER BY id DESC LIMIT 50",
        (session,),
    )[::-1]


@app.put("/api/settings")
async def configure(body: Settings):
    global settings
    if (
        body.provider == "ollama"
        and body.model not in await model.ollama.available()
        and body.model + ":latest" not in await model.ollama.available()
    ):
        raise HTTPException(400, "Select a downloaded local model")
    if body.voice not in tts.available(
        online_enabled=body.online_voice_enabled,
        google_enabled=body.google_voice_enabled,
    ):
        raise HTTPException(
            400, "Select an available voice; online voices require explicit enablement"
        )
    if (
        body.online_voice_fallback != "none"
        and body.online_voice_fallback not in tts.available(online_enabled=False)
    ):
        raise HTTPException(400, "Download the selected local fallback voice first")
    config.save_settings(body)
    settings = body
    return body.model_dump()


class ProviderCredential(BaseModel):
    key: str = Field(max_length=1000)
    api_base: str = Field(max_length=2000)

    @field_validator("api_base")
    @classmethod
    def validate_base(cls, value):
        from .providers import validate_endpoint

        return validate_endpoint(value)


@app.put("/api/provider-credential")
async def provider_credential(body: ProviderCredential):
    import keyring

    if body.key:
        keyring.set_password("Jarvis Local", credential_name(body.api_base), body.key)
    else:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password("Jarvis Local", credential_name(body.api_base))
    credentials.invalidate(credential_name(body.api_base))
    return {"ok": True}


@app.post("/api/provider-test")
async def provider_test(body: Settings):
    if body.provider != "compatible":
        raise HTTPException(400, "Choose an API provider first")
    from .providers import Compatible

    credentials.retry(credential_name(body.api_base))

    adapter = Compatible(lambda: body)
    began = time.monotonic()
    first = None
    answer = ""
    try:
        async with asyncio.timeout(15):
            # Synthetic probe only: never send owner history during setup.
            async for packet in adapter.stream(
                [{"role": "user", "content": "Reply with only: Connection verified."}],
                [],
                body,
            ):
                fragment = packet.get("message", {}).get("content", "")
                if fragment and first is None:
                    first = round_ms(began)
                answer += fragment
        if not answer.strip():
            raise ValueError("Provider returned no answer")
        return {
            "ok": True,
            "model": body.model,
            "ttft_ms": first,
            "total_ms": round_ms(began),
        }
    except (ValueError, TimeoutError) as error:
        raise HTTPException(400, str(error)[:200])
    except Exception:
        raise HTTPException(
            400,
            "Provider connection failed. Check your API key, selected model, account access and network.",
        )
    finally:
        await adapter.close()


@app.post("/api/tools")
async def invoke(body: Invoke):
    return await tools.execute(body.name, body.arguments, "ui:" + body.key)


@app.delete("/api/records/{kind}/{id}")
async def delete(kind: str, id: str):
    try:
        store.delete_record(kind, id)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return {"ok": True}


@app.put("/api/memory/{id}")
async def edit(id: str, body: MemoryEdit):
    if not store.all("SELECT id FROM memory WHERE id=?", (id,)):
        raise HTTPException(404, "Memory not found")
    store.run("UPDATE memory SET key=?,value=? WHERE id=?", (body.key, body.value, id))
    store.clear_conversations()
    return {"ok": True}


@app.post("/api/directories")
async def directory(body: Directory):
    path = Path(body.path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(400, "Select an existing absolute directory")
    # No model tool can select a root. This endpoint is an explicit UI owner action.
    store.run("INSERT OR IGNORE INTO directories VALUES(?)", (str(path),))
    try:
        id = jobs.submit(str(path))
    except ValueError as error:
        raise HTTPException(400, str(error))
    return {"job_id": id, "state": "queued"}


@app.delete("/api/directories")
async def remove_directory(body: Directory):
    root = str(Path(body.path).expanduser().resolve())
    if any(
        json.loads(r["args"]).get("root") == root
        for r in store.all("SELECT args FROM jobs WHERE state IN ('queued','running')")
    ):
        raise HTTPException(
            409, "Cancel active indexing before removing this directory"
        )
    with store.lock:
        store.db.execute(
            "DELETE FROM document_fts WHERE path IN (SELECT path FROM documents WHERE root=?)",
            (root,),
        )
        store.db.execute("DELETE FROM documents WHERE root=?", (root,))
        store.db.execute("DELETE FROM directories WHERE path=?", (root,))
        store.db.commit()
    return {"ok": True}


@app.post("/api/jobs/{id}/cancel")
async def cancel_job(id: str):
    jobs.cancel(id)
    return {"ok": True}


@app.post("/api/reminders/{id}/ack")
async def ack(id: str):
    store.acknowledge(id)
    return {"ok": True}


@app.get("/api/calendar/connect")
async def calendar_connect():
    try:
        return {"url": calendar.begin()}
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.post("/api/calendar/configure")
async def configure_calendar(body: Directory):
    try:
        return calendar.configure(body.path)
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)[:200])


@app.get("/api/calendar/callback")
async def callback(state: str = "", code: str = ""):
    try:
        await calendar.finish(state, code)
    except Exception:
        return HTMLResponse(
            "Calendar connection failed. Check desktop OAuth configuration and retry from Jarvis.",
            status_code=400,
        )
    return HTMLResponse(
        "Calendar connected. You may close this window and return to Jarvis Local."
    )


@app.get("/api/calendar/events")
async def events():
    try:
        return await calendar.events()
    except Exception as error:
        raise HTTPException(400, "Calendar read failed: " + type(error).__name__)


@app.delete("/api/calendar")
async def disconnect_calendar():
    await calendar.disconnect()
    return {"ok": True}


class Capture:
    def __init__(self, turn, mode):
        self.turn = turn
        self.mode = mode
        self.seq = 0
        self.data = bytearray()
        self.pre = deque(maxlen=10)
        self.vad = Silero() if mode in {"handsfree", "wake", "barge"} else None
        self.speech = False
        self.silent = 0
        self.positive = 0
        self.frames = 0

    def feed(self, chunk):
        if self.mode == "ptt":
            self.data.extend(chunk)
        else:
            for offset in range(0, len(chunk), 1024):
                frame = chunk[offset : offset + 1024]
                if len(frame) != 1024:
                    continue
                probability = self.vad.probability(frame)
                self.positive = (
                    self.positive + 1
                    if probability > (0.8 if self.mode == "barge" else 0.55)
                    else 0
                )
                self.pre.append(frame)
                if not self.speech and self.positive >= (
                    5 if self.mode == "barge" else 3
                ):
                    self.speech = True
                    self.data.extend(b"".join(self.pre))
                    self.pre.clear()
                elif self.speech:
                    self.data.extend(frame)
                if self.speech:
                    self.silent = self.silent + 1 if probability < 0.35 else 0
        if len(self.data) > 16000 * 2 * 60:
            raise ValueError("Utterance exceeds 60 seconds")
        return self.speech and self.silent >= (10 if self.mode == "barge" else 25)


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    owner_token = ws.cookies.get("jarvis_session", "")
    if (
        ws.headers.get("origin") != config.ORIGIN
        or sessions.get(ws.cookies.get("jarvis_session", ""), 0) < time.time()
        or len(connections) >= 4
        or not owner.allowed(owner_token)
    ):
        await ws.close(code=1008)
        return
    await ws.accept()
    connections.add(ws)
    session = uid()
    current = None
    generation = None
    capture = None
    barge_capture = None
    barge_task = None
    barge_seq = 0
    speaking = False
    assistant_text = ""
    echo_detected = False
    wake_active_until = 0
    send_lock = asyncio.Lock()
    times = deque()

    async def send(event, turn=None, **payload):
        nonlocal speaking, assistant_text
        if not owner.allowed(owner_token):
            await ws.close(code=4003)
            raise asyncio.CancelledError
        if turn == current and event == "state" and payload.get("state") == "speaking":
            speaking = True
        if turn == current and event == "delta":
            assistant_text += payload.get("text", "")
        if turn is not None and turn != current:
            return
        async with send_lock:
            if turn is None or turn == current:
                await ws.send_json(
                    {"type": event, "session_id": session, "turn_id": turn, **payload}
                )

    async def cancel():
        nonlocal generation, current, capture, barge_capture, barge_task, speaking
        speaking = False
        barge_capture = None
        if barge_task and barge_task is not asyncio.current_task():
            barge_task.cancel()
            barge_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            barge_task = None
        interrupted = current
        current = None
        capture = None
        if generation:
            generation.cancel()
            # Await cancellation in the background; token guard invalidates old output immediately.
            generation.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            generation = None
        await send(
            "interrupted",
            cancelled_turn=interrupted,
            records=store.snapshot(),
            message="Playback cancelled. Inspect tool activity for actions already completed.",
        )

    async def run_turn(turn, text=None, pcm=None, voice=True, capture_mode=None):
        nonlocal wake_active_until
        workflows.voice_started()
        try:
            timings = {}

            async def emit(event, **data):
                await send(event, turn, **data)

            if pcm is not None:
                followup_allowed = time.monotonic() < wake_active_until
                await emit("state", state="transcribing")
                start = time.perf_counter()
                text = await stt.transcribe(pcm, settings.language)
                if turn != current:
                    return
                timings["stt_ms"] = round_ms(start)
                await emit("metrics", metrics=timings)
                if is_voice_stop(text):
                    wake_active_until = 0
                    await emit("stop_detected")
                    await emit("done", text="", audio_count=0, metrics=timings)
                    return
                if not await owner.verify(owner_token, pcm):
                    await lock_owner_connections()
                    return
                if turn != current:
                    return
                if capture_mode == "wake":
                    import re

                    matched = re.match(
                        r"^\s*(?:hey[,.! ]+)?jarvis[,.!?: ]*(.*)$",
                        text or "",
                        re.I | re.S,
                    )
                    if not matched and not followup_allowed:
                        await emit("wake_session", active=False, timeout_ms=0)
                        await emit("done", text="", audio_count=0, metrics=timings)
                        return
                    if matched:
                        text = matched.group(1).strip()
                        await emit("wake_detected", has_command=bool(text))
                    wake_active_until = time.monotonic() + WAKE_FOLLOWUP_SECONDS
                    await emit(
                        "wake_session",
                        active=True,
                        timeout_ms=WAKE_FOLLOWUP_SECONDS * 1000,
                    )
                    if not text:
                        wav = await tts.synthesize("I'm listening.", settings.voice)
                        await emit("state", state="speaking")
                        await emit(
                            "audio",
                            seq=0,
                            encoding="wav",
                            audio=base64.b64encode(wav).decode(),
                        )
                        await emit("done", text="", audio_count=1, metrics=timings)
                        return
                if is_voice_stop(text):
                    await emit("stop_detected")
                    await emit("done", text="", audio_count=0, metrics=timings)
                    return
                await emit("transcript", text=text)
            if not text or not text.strip():
                await emit(
                    "warning",
                    message="No speech recognized. Try a quieter room or push-to-talk.",
                )
                await emit("done", text="", audio_count=0, metrics=timings)
                return
            await agent.turn(session, turn, text, emit, voice)
        except asyncio.CancelledError:
            return
        except Exception as error:
            await send("error", turn, message=str(error)[:300])
        finally:
            workflows.voice_finished()

    async def verify_barge(turn, pcm):
        nonlocal \
            current, \
            generation, \
            barge_capture, \
            barge_task, \
            barge_seq, \
            echo_detected, \
            assistant_text
        try:
            text = await asyncio.wait_for(stt.transcribe(pcm, settings.language), 5)
            if current != turn:
                return
            import re

            def normalized(value):
                return " ".join(re.findall(r"[\w]+", value.lower()))

            spoken = normalized(text or "")
            stopped = is_barge_stop(spoken, assistant_text)
            echo = spoken and spoken in normalized(assistant_text)
            if not spoken or (echo and not stopped):
                echo_detected = bool(echo)
                barge_capture = None
                await send(
                    "barge_rejected",
                    turn,
                    reason="speaker_echo" if echo else "empty_speech",
                )
                return
            # Background voices and imperfect AEC must not replace a spoken reply.
            # Address Jarvis explicitly, or use a stop command, during playback.
            if not stopped and not await owner.verify(owner_token, pcm):
                await lock_owner_connections()
                return
            if not stopped and not re.match(r"^(?:hey )?jarvis\b", spoken):
                barge_capture = None
                await send("barge_rejected", turn, reason="requires_wake_or_stop")
                return
            await cancel()
            new_turn = uid()
            current = new_turn
            assistant_text = ""
            barge_seq = 0
            echo_detected = False
            await send("barge_in", new_turn=new_turn, stopped=stopped)
            if stopped:
                await send("state", new_turn, state="idle")
            else:
                await send("transcript", new_turn, text=text)
                generation = asyncio.create_task(run_turn(new_turn, text=text))
        except asyncio.CancelledError:
            return
        except Exception:
            if current == turn:
                barge_capture = None
                await send("barge_rejected", turn, reason="transcription_unavailable")
        finally:
            if barge_task is asyncio.current_task():
                barge_task = None

    await send("hello")
    try:
        while True:
            raw = await ws.receive_text()
            if not owner.allowed(owner_token):
                await ws.close(code=4003)
                break
            if len(raw) > 32_000:
                raise ValueError("Message exceeds 32 KB")
            stamp = time.monotonic()
            times.append(stamp)
            while times and stamp - times[0] > 1:
                times.popleft()
            if len(times) > 100:
                raise ValueError("Message rate exceeded")
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                raise ValueError("Expected a JSON object")
            type = msg.get("type")
            if type == "resume":
                candidate = msg.get("session_id")
                if isinstance(candidate, str) and len(candidate) == 36:
                    session = candidate
                    await send("hello")
            elif type == "interrupt":
                wake_active_until = 0
                await cancel()
            elif type in {"text", "capture_start"}:
                await cancel()
                turn = msg.get("turn_id")
                if not isinstance(turn, str) or len(turn) != 36:
                    raise ValueError("turn_id must be a UUID")
                current = turn
                barge_seq = 0
                assistant_text = ""
                echo_detected = False
                if type == "text":
                    text = msg.get("text")
                    if not isinstance(text, str) or not 0 < len(text) <= 10_000:
                        raise ValueError("Text must contain 1–10000 characters")
                    generation = asyncio.create_task(
                        run_turn(turn, text=text, voice=msg.get("voice", True) is True)
                    )
                else:
                    if (
                        msg.get("sample_rate") != 16000
                        or msg.get("encoding") != "pcm_s16le"
                        or msg.get("mode") not in {"ptt", "handsfree", "wake"}
                    ):
                        raise ValueError(
                            "Use mono 16 kHz PCM s16le with ptt or handsfree mode"
                        )
                    capture = Capture(turn, msg["mode"])
                    if msg["mode"] != "wake":
                        wake_active_until = 0
                    await send("state", turn, state="listening")
            elif type == "barge_audio":
                if not speaking or msg.get("turn_id") != current:
                    continue
                if msg.get("seq") != barge_seq:
                    raise ValueError("Interruption audio sequence mismatch")
                barge_seq += 1
                encoded = msg.get("audio", "")
                if not isinstance(encoded, str) or len(encoded) > 5500:
                    raise ValueError("Interruption audio chunk too large")
                chunk = base64.b64decode(encoded, validate=True)
                if not chunk or len(chunk) > 4096 or len(chunk) % 2:
                    raise ValueError("Invalid interruption PCM chunk")
                if barge_task is not None:
                    continue
                if barge_capture is None:
                    barge_capture = Capture(current, "barge")
                already_speech = barge_capture.speech
                ended = barge_capture.feed(chunk)
                if barge_capture.speech and not already_speech and not echo_detected:
                    await send("barge_candidate", current)
                if ended:
                    barge_task = asyncio.create_task(
                        verify_barge(current, bytes(barge_capture.data))
                    )
            elif type == "audio":
                if not capture or msg.get("turn_id") != capture.turn:
                    continue
                if msg.get("seq") != capture.seq:
                    raise ValueError("Audio sequence mismatch")
                encoded = msg.get("audio", "")
                if not isinstance(encoded, str) or len(encoded) > 5500:
                    raise ValueError("Audio chunk too large")
                chunk = base64.b64decode(encoded, validate=True)
                if not chunk or len(chunk) > 4096 or len(chunk) % 2:
                    raise ValueError("Invalid PCM chunk")
                capture.seq += 1
                if capture.feed(chunk):
                    pcm = bytes(capture.data)
                    turn = capture.turn
                    capture_mode = capture.mode
                    capture = None
                    await send("capture_ended", turn)
                    generation = asyncio.create_task(
                        run_turn(
                            turn,
                            pcm=pcm,
                            voice=msg.get("voice", True) is True,
                            capture_mode=capture_mode,
                        )
                    )
            elif type == "capture_stop":
                if capture and msg.get("turn_id") == capture.turn:
                    pcm = bytes(capture.data)
                    turn = capture.turn
                    capture_mode = capture.mode
                    capture = None
                    generation = asyncio.create_task(
                        run_turn(
                            turn,
                            pcm=pcm,
                            voice=msg.get("voice", True) is True,
                            capture_mode=capture_mode,
                        )
                    )
            elif type == "playback_done":
                if (
                    msg.get("turn_id") == current
                    and barge_task is None
                    and not (barge_capture and barge_capture.speech)
                ):
                    speaking = False
                    if wake_active_until:
                        wake_active_until = time.monotonic() + WAKE_FOLLOWUP_SECONDS
                        await send(
                            "wake_session",
                            current,
                            active=True,
                            timeout_ms=WAKE_FOLLOWUP_SECONDS * 1000,
                        )
                    await send("state", current, state="idle")
            elif type == "ping":
                await send("pong")
            else:
                raise ValueError("Unknown WebSocket event")
    except WebSocketDisconnect:
        pass
    except Exception as error:
        with contextlib.suppress(Exception):
            await send("error", message="Connection reset: " + str(error)[:200])
            await ws.close(code=1008)
    finally:
        connections.discard(ws)
        current = None
        if generation:
            generation.cancel()
            await asyncio.gather(generation, return_exceptions=True)
        if barge_task:
            barge_task.cancel()
            await asyncio.gather(barge_task, return_exceptions=True)


built = config.ROOT / "frontend" / "dist"
if built.exists():
    app.mount("/", StaticFiles(directory=built, html=True), name="dashboard")
