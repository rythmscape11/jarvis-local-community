"""Network boundary and stale-turn checks with explicitly substituted engines."""

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from jarvis import main
from jarvis.config import ORIGIN
import asyncio
import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as value:
        yield value


def test_session_and_origin_protection(client):
    assert client.get("/api/records").status_code == 401
    assert (
        client.post(
            "/api/session",
            json={"token": main.secret},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    assert client.post("/api/session", json={"token": main.secret}).status_code == 403
    assert (
        client.post(
            "/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    assert client.get("/api/records").status_code == 200
    assert (
        client.post(
            "/api/tools",
            json={"name": "create_note", "arguments": {}, "key": "long-enough-key"},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws", headers={"Origin": "https://unrelated.example"}
        ):
            assert False, "Foreign origin accepted"
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json(
            {
                "type": "capture_start",
                "turn_id": "a" * 36,
                "encoding": "opus",
                "sample_rate": 48000,
                "mode": "ptt",
            }
        )
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["type"] == "error"


def test_superseded_turn_cannot_emit_stale_audio(monkeypatch, client):
    async def substitute(session, turn, text, send, voice):
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # Deliberately misbehaving adapter emits even after cancellation.
            await send("audio", seq=0, audio="STALE")
            return
        await send("delta", text=text)
        await send("done", text=text, metrics={}, audio_count=0)

    monkeypatch.setattr(main.agent, "turn", substitute)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "turn_id": "1" * 36, "text": "first"})
        ws.receive_json()
        ws.send_json({"type": "text", "turn_id": "2" * 36, "text": "second"})
        event = ws.receive_json()
        assert event["type"] == "interrupted"
        event = ws.receive_json()
        assert event["type"] == "delta"
        assert event["text"] == "second"
        assert ws.receive_json()["type"] == "done"


def test_interrupt_then_capture_accepts_new_speech_and_drops_old_turn(
    monkeypatch, client
):
    async def substitute(session, turn, text, send, voice):
        if text == "old":
            await send("state", state="speaking")
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await send("audio", seq=0, audio="STALE")
        else:
            await send("delta", text=text)
            await send("done", text=text, metrics={}, audio_count=0)

    async def transcribe(pcm, language):
        return "two plus two"

    monkeypatch.setattr(main.agent, "turn", substitute)
    monkeypatch.setattr(main.stt, "transcribe", transcribe)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "turn_id": "4" * 36, "text": "old"})
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["state"] == "speaking"
        ws.send_json({"type": "interrupt"})
        assert ws.receive_json()["cancelled_turn"] == "4" * 36
        ws.send_json(
            {
                "type": "capture_start",
                "turn_id": "5" * 36,
                "mode": "ptt",
                "sample_rate": 16000,
                "encoding": "pcm_s16le",
            }
        )
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["state"] == "listening"
        ws.send_json({"type": "capture_stop", "turn_id": "5" * 36})
        assert ws.receive_json()["state"] == "transcribing"
        assert ws.receive_json()["type"] == "metrics"
        assert ws.receive_json()["text"] == "two plus two"
        assert ws.receive_json()["type"] == "delta"
        assert ws.receive_json()["type"] == "done"


@pytest.mark.parametrize(
    "recognized,expected",
    [
        ("stop speaking", "barge_in"),
        ("Please stop speaking", "barge_in"),
        ("Could you stop talking please?", "barge_in"),
        ("A long sample answer stop speaking", "barge_in"),
        ("A long sample answer", "barge_rejected"),
        ("Don't stop speaking", "background_rejected"),
        ("A video is playing nearby", "background_rejected"),
    ],
)
def test_spoken_interrupt_cancels_but_speaker_echo_does_not(
    monkeypatch, client, recognized, expected
):
    class Detection:
        def __init__(self, turn, mode):
            self.turn = turn
            self.mode = mode
            self.seq = 0
            self.speech = False
            self.data = bytearray()

        def feed(self, chunk):
            self.speech = True
            self.data.extend(chunk)
            return True

    async def transcribe(pcm, language):
        return recognized

    async def speaking(session, turn, text, send, voice):
        await send("delta", text="A long sample answer")
        await send("state", state="speaking")
        await asyncio.sleep(30)

    monkeypatch.setattr(main, "Capture", Detection)
    monkeypatch.setattr(main.stt, "transcribe", transcribe)
    monkeypatch.setattr(main.agent, "turn", speaking)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "turn_id": "3" * 36, "text": "Speak to me"})
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["type"] == "delta"
        assert ws.receive_json()["type"] == "state"
        ws.send_json(
            {"type": "barge_audio", "turn_id": "3" * 36, "seq": 0, "audio": "AAA="}
        )
        assert ws.receive_json()["type"] == "barge_candidate"
        event = ws.receive_json()
        if expected == "barge_in":
            assert event["type"] == "interrupted"
            assert ws.receive_json()["type"] == "barge_in"
            assert ws.receive_json()["state"] == "idle"
        else:
            assert event["type"] == "barge_rejected" and event["reason"] == (
                "speaker_echo"
                if expected == "barge_rejected"
                else "requires_wake_or_stop"
            )


def test_barge_stop_ignores_quoted_commands_and_negation():
    assert (
        main.is_barge_stop("You can say stop speaking", "You can say stop speaking")
        is False
    )
    assert (
        main.is_barge_stop(
            "The answer is forty two stop speaking please", "The answer is forty two"
        )
        is True
    )
    assert main.is_barge_stop("Please don't stop speaking", "") is False
    assert main.is_barge_stop("Why did you stop speaking yesterday", "") is False


@pytest.mark.parametrize(
    "recognized",
    [
        "Stop speaking.",
        "Jarvis, stop listening",
        "End conversation",
        "Please stop talking",
        "Could you be quiet please?",
    ],
)
def test_stop_during_capture_does_not_call_agent(monkeypatch, client, recognized):
    async def transcribe(pcm, language):
        return recognized

    async def unexpected(*args):
        raise AssertionError("A stop command must not generate a reply")

    monkeypatch.setattr(main.stt, "transcribe", transcribe)
    monkeypatch.setattr(main.agent, "turn", unexpected)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "capture_start",
                "turn_id": "6" * 36,
                "mode": "ptt",
                "sample_rate": 16000,
                "encoding": "pcm_s16le",
            }
        )
        assert ws.receive_json()["type"] == "interrupted"
        assert ws.receive_json()["state"] == "listening"
        ws.send_json({"type": "capture_stop", "turn_id": "6" * 36})
        assert ws.receive_json()["state"] == "transcribing"
        assert ws.receive_json()["type"] == "metrics"
        assert ws.receive_json()["type"] == "stop_detected"
        assert ws.receive_json()["type"] == "done"


def test_workflow_routes_auth_origin_validation_and_idempotency(client):
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    value = client.get("/api/automations")
    assert value.status_code == 200
    assert len(value.json()["templates"]) == 10
    assert (
        client.post(
            "/api/automations",
            json={"title": "Fixture", "template": "voice_document"},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/automations",
            json={
                "title": "Fixture",
                "template": "voice_document",
                "schedule": {"timezone": "INVALID"},
            },
            headers={"Origin": ORIGIN},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/external-actions",
            json={"kind": "purchase"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/connectors/mail_send/connect", headers={"Origin": ORIGIN}
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/api/connectors/google/callback?state=wrong&code=fixture",
            headers={"Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 400
    )
    item = client.post(
        "/api/automations",
        json={
            "title": "Fixture",
            "template": "voice_document",
            "inputs": {"content": "Synthetic fact."},
        },
        headers={"Origin": ORIGIN},
    ).json()
    updated = client.put(
        "/api/automations/" + item["id"],
        json={"title": "Edited fixture", "template": "voice_document"},
        headers={"Origin": ORIGIN},
    )
    assert updated.status_code == 200
    assert client.delete(
        "/api/automations/" + item["id"], headers={"Origin": ORIGIN}
    ).json()["deleted"]


def test_wake_opens_followups_then_expires_and_interrupt_revokes(monkeypatch, client):
    recognized = iter(
        [
            "Hey Jarvis, what is two plus two?",
            "What is three plus three?",
            "Background television",
            "Hey Jarvis, are you there?",
            "Another background voice",
        ]
    )
    answered = []

    class Detection:
        def __init__(self, turn, mode):
            self.turn, self.mode, self.seq = turn, mode, 0
            self.data = bytearray()
            self.speech = False

        def feed(self, chunk):
            self.data.extend(chunk)
            self.speech = True
            return True

    async def transcribe(pcm, language):
        return next(recognized)

    async def respond(session, turn, text, send, voice):
        answered.append(text)
        await send("delta", text="Verified fixture reply.")
        await send("done", text="Verified fixture reply.", metrics={}, audio_count=0)

    monkeypatch.setattr(main, "Capture", Detection)
    monkeypatch.setattr(main.stt, "transcribe", transcribe)
    monkeypatch.setattr(main.agent, "turn", respond)
    monkeypatch.setattr(main, "WAKE_FOLLOWUP_SECONDS", 0.1)
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    with client.websocket_connect("/ws", headers={"Origin": ORIGIN}) as ws:
        ws.receive_json()

        def capture(index):
            turn = str(index) * 36
            ws.send_json(
                {
                    "type": "capture_start",
                    "turn_id": turn,
                    "mode": "wake",
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
                    "audio": "AAA=",
                    "voice": False,
                }
            )
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event["type"] == "done":
                    return events

        assert any(e["type"] == "wake_detected" for e in capture(1))
        assert any(e["type"] == "transcript" for e in capture(2))
        import time

        time.sleep(0.2)
        expired = capture(3)
        assert not any(e["type"] == "transcript" for e in expired)
        assert any(e["type"] == "wake_session" and not e["active"] for e in expired)
        capture(4)
        ws.send_json({"type": "interrupt"})
        assert ws.receive_json()["type"] == "interrupted"
        assert not any(e["type"] == "transcript" for e in capture(5))
    assert answered == [
        "what is two plus two?",
        "What is three plus three?",
        "are you there?",
    ]


def test_automatic_memory_routes_validate_and_apply_edits(client):
    client.post("/api/session", json={"token": main.secret}, headers={"Origin": ORIGIN})
    main.store.conversation(
        "archive-fixture", "archive-turn", "user", "Synthetic fixture brand is coral."
    )
    rows = client.get(
        "/api/conversations", params={"query": "Synthetic fixture brand"}
    ).json()
    row = next(r for r in rows if r["session"] == "archive-fixture")
    assert (
        client.get("/api/conversations", params={"query": "x" * 501}).status_code == 400
    )
    assert (
        client.put(
            "/api/conversations/" + str(row["id"]),
            json={"content": 12},
            headers={"Origin": ORIGIN},
        ).status_code
        == 422
    )
    response = client.put(
        "/api/conversations/" + str(row["id"]),
        json={"content": "Synthetic fixture brand is teal."},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert main.store.conversation_recall("teal")
    assert (
        client.delete(
            "/api/conversations/" + str(row["id"]), headers={"Origin": ORIGIN}
        ).status_code
        == 200
    )
    assert not any(
        r["id"] == row["id"]
        for r in main.store.conversation_recall("Synthetic fixture brand")
    )
