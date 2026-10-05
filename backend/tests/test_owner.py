"""Deterministic security-boundary tests. Fake embeddings are not biometric validation."""

import asyncio
import base64
import json
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from jarvis.owner import OwnerLock, Speaker, normalize
from jarvis import main
from jarvis.config import ORIGIN


class FakeSpeaker:
    path = Path("missing-test-model")

    def extract(self, pcm):
        value = np.zeros(128, dtype=np.float32)
        value[0 if pcm[:1] == b"a" else 1] = 1
        return value


@pytest.mark.asyncio
async def test_enrollment_encrypted_restart_password_and_unknown_lock(tmp_path):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    assert owner.allowed("guest")  # off until explicit enrollment
    audio = b"a" * (8 * 32000)
    await owner.enroll("owner", "isolated-test-passphrase", [audio] * 4)
    persisted = json.loads(owner.path.read_text())
    assert (
        "prints" not in persisted
        and "isolated-test-passphrase" not in owner.path.read_text()
    )
    assert owner.path.stat().st_mode & 0o777 == 0o600
    restarted = OwnerLock(tmp_path, FakeSpeaker())
    assert not restarted.allowed("owner")
    with pytest.raises(ValueError):
        await restarted.unlock("guest", "incorrect-passphrase")
    await restarted.unlock("owner", "isolated-test-passphrase")
    assert await restarted.verify("owner", audio)
    assert not restarted.allowed("other-browser")
    assert not await restarted.verify("owner", b"b" * len(audio))
    assert not restarted.allowed("owner") and restarted.prints is None
    await restarted.unlock("owner", "isolated-test-passphrase")
    await restarted.remove("owner", "isolated-test-passphrase")
    assert not restarted.path.exists() and restarted.allowed("anyone")


@pytest.mark.asyncio
async def test_malformed_samples_and_rate_limit(tmp_path):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    with pytest.raises(ValueError):
        await owner.enroll("owner", "test-passphrase", [b"a"] * 4)
    with pytest.raises(ValueError):
        await owner.enroll(
            "owner", "test-passphrase", [b"a" * 128000, b"b" * 128000, b"a" * 128000]
        )
    assert not owner.enabled
    await owner.enroll("owner", "test-passphrase", [b"a" * 128000] * 4)
    owner.lock()
    for _ in range(5):
        with pytest.raises(ValueError):
            await owner.unlock("owner", "wrong-passphrase")
    with pytest.raises(ValueError, match="Wait one minute"):
        await owner.unlock("owner", "test-passphrase")
    assert not owner.allowed("owner")


@pytest.mark.asyncio
async def test_expiry_failure_and_corrupt_profile_fail_closed(tmp_path):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    await owner.enroll("owner", "test-passphrase", [b"a" * 128000] * 4)
    owner.leases["owner"] = time.monotonic() - 1
    assert not await owner.verify("owner", b"a" * 128000)
    owner.path.write_text("broken")
    assert owner.enabled and not owner.allowed("other")
    with pytest.raises(ValueError):
        await owner.unlock("owner", "test-passphrase")


def test_bad_embedding_and_audio():
    with pytest.raises(ValueError):
        normalize([float("nan")] * 128)
    with pytest.raises(ValueError):
        normalize([0] * 128)
    with pytest.raises(ValueError):
        Speaker(Path("missing")).extract(bytes(32000))
    with pytest.raises(ValueError):
        Speaker(Path("missing")).extract(bytes(5 * 32000))


def test_locked_api_and_websocket_cannot_read_or_execute(tmp_path, monkeypatch):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    owner.path.write_text("damaged enrollment must remain locked")
    monkeypatch.setattr(main, "owner", owner)
    client = TestClient(main.app)
    assert (
        client.post(
            "/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    assert client.get("/api/owner/status").json()["locked"]
    for path in (
        "/api/records",
        "/api/conversations",
        "/api/health",
        "/api/history/test",
    ):
        assert client.get(path).status_code == 423
    assert (
        client.post(
            "/api/tools",
            json={"name": "create_note", "arguments": {}, "key": "synthetic-key"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 423
    )
    assert (
        client.post(
            "/api/owner/remove",
            json={"password": "test-passphrase"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 423
    )
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": ORIGIN}):
            pytest.fail("Locked WebSocket accepted")


@pytest.mark.asyncio
async def test_enrollment_race_has_one_winner(tmp_path):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    results = await asyncio.gather(
        *(
            owner.enroll(str(i), "test-passphrase", [b"a" * 128000] * 4)
            for i in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len(owner.leases) == 1


def test_unknown_voice_never_reaches_agent_or_private_transcript(tmp_path, monkeypatch):
    owner = OwnerLock(tmp_path, FakeSpeaker())
    asyncio.run(owner.enroll("setup", "test-passphrase", [b"a" * 128000] * 4))
    monkeypatch.setattr(main, "owner", owner)
    invoked = []

    class Capture:
        def __init__(self, turn, mode):
            self.turn, self.mode, self.seq = turn, mode, 0
            self.data = bytearray()
            self.speech = False

        def feed(self, chunk):
            self.data.extend(chunk)
            self.speech = True
            return True

    async def transcribe(pcm, language):
        return "Jarvis, read the owner's private notes"

    async def respond(*args):
        invoked.append(True)

    monkeypatch.setattr(main, "Capture", Capture)
    monkeypatch.setattr(main.stt, "transcribe", transcribe)
    monkeypatch.setattr(main.agent, "turn", respond)
    client = TestClient(main.app)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/api/owner/unlock",
            json={"password": "test-passphrase"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "hello"
        turn = "b" * 36
        ws.send_json(
            {
                "type": "capture_start",
                "turn_id": turn,
                "mode": "ptt",
                "sample_rate": 16000,
                "encoding": "pcm_s16le",
            }
        )
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["state"] == "listening"
        ws.send_json(
            {
                "type": "audio",
                "turn_id": turn,
                "seq": 0,
                "audio": base64.b64encode(b"b" * 2048).decode(),
            }
        )
        events = []
        while True:
            message = ws.receive_json()
            events.append(message)
            if message["type"] == "owner_locked":
                break
        assert not any(
            event["type"] in {"transcript", "delta", "audio", "done"}
            for event in events
        )
    assert not invoked
    assert client.get("/api/records").status_code == 423
