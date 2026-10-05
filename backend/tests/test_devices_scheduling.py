"""Isolated security and integration contract tests; Google HTTP is substituted."""

import json
import pytest
from fastapi.testclient import TestClient
from jarvis.devices import Devices, DeviceConfig, Claim, VoiceSocket, gateway
from jarvis.scheduling import Availability, suggest
from jarvis.navigation import Directions, directions, AppointmentBrief, brief
from jarvis.calendar_actions import (
    CalendarEvent,
    prepare,
    CalendarCancel,
    prepare_cancel,
)
from jarvis.connectors import Connectors
from jarvis.store import Store
from jarvis import config

ORIGIN = "https://mac.private-test.ts.net"
EVENT = {
    "title": "Synthetic review",
    "start": "2026-10-06T10:00:00+05:30",
    "end": "2026-10-06T10:30:00+05:30",
}


@pytest.fixture
def devices(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    d = Devices(store, tmp_path)
    d.configure(DeviceConfig(enabled=True, origin=ORIGIN))
    yield d
    store.close()


class Owner:
    def allowed(self, token):
        return True

    def status(self, token):
        return {"enabled": False, "locked": False}


@pytest.mark.parametrize(
    "url",
    [
        "http://mac.private-test.ts.net",
        "https://evil.example",
        "https://mac.private-test.ts.net.evil.example",
        "https://a@mac.test.ts.net",
        "https://mac.test.ts.net/path",
    ],
)
def test_private_origins_only(url):
    with pytest.raises(ValueError):
        DeviceConfig(origin=url, enabled=True)


def test_code_not_enough_and_secret_never_stored(devices):
    code = devices.begin()["code"]
    token = devices.claim(Claim(code=code, name="Synthetic iPhone"), "peer")
    assert not devices.resolve(token)
    assert devices.resolve(token, approved=False)["state"] == "pending"
    assert token not in json.dumps(devices.snapshot())
    assert (
        token
        not in devices.store.all("SELECT token_hash FROM paired_devices")[0][
            "token_hash"
        ]
    )
    with pytest.raises(ValueError):
        devices.claim(Claim(code=code, name="Second device"), "peer")
    id = devices.snapshot()["devices"][0]["id"]
    devices.review(id, True)
    assert devices.resolve(token)
    restored = Devices(devices.store, devices.data)
    assert restored.resolve(token)
    devices.revoke(id)
    assert not restored.resolve(token)


def test_pair_limit_expiry_and_disable(devices):
    for _ in range(5):
        with pytest.raises(ValueError):
            devices.claim(Claim(code="00000000", name="Wrong"), "peer")
    with pytest.raises(ValueError, match="limited"):
        devices.claim(Claim(code=devices.begin()["code"], name="Wrong"), "peer")
    devices.code = ("12345678", 0)
    with pytest.raises(ValueError):
        devices.claim(Claim(code="12345678", name="Expired"), "other")
    devices.configure(DeviceConfig(enabled=False, origin=ORIGIN))
    with pytest.raises(ValueError):
        devices.begin()


def test_gateway_no_backend_or_private_access_without_approval(devices, tmp_path):
    (tmp_path / "companion.html").write_text("Synthetic companion")
    app = gateway(devices, Owner(), {}, None, tmp_path)
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    assert client.get("/phone/status").status_code == 401
    assert client.get("/api/records").status_code == 404
    assert client.get("/").status_code == 200
    assert (
        client.post(
            "/phone/pair",
            json={"code": devices.begin()["code"], "name": "Fixture"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    code = devices.begin()["code"]
    response = client.post("/phone/pair", json={"code": code, "name": "Fixture"})
    assert response.status_code == 200
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "Secure" in response.headers["set-cookie"]
    )
    assert client.get("/phone/status").json()["status"] == "pending_desktop_approval"
    assert client.get("/phone/reminders").status_code == 403
    id = devices.snapshot()["devices"][0]["id"]
    devices.review(id, True)
    assert client.get("/phone/status").json()["status"] == "approved"
    assert client.get("/phone/reminders").json() == []
    assert client.post("/phone/pair", content="x" * 12001).status_code == 413
    devices.revoke(id)
    assert client.get("/phone/reminders").status_code == 401


@pytest.mark.asyncio
async def test_socket_revocation_and_no_session_hijacking(devices):
    token = devices.claim(Claim(code=devices.begin()["code"], name="Fixture"), "peer")
    devices.review(devices.snapshot()["devices"][0]["id"], True)

    class Socket:
        cookies = {"jarvis_device": token}
        closed = False

        async def receive_text(self):
            return json.dumps({"type": "resume", "session_id": "another-owner-session"})

        async def close(self, code):
            self.closed = True

    ws = Socket()
    socket = VoiceSocket(ws, devices, "internal", Owner(), {"internal": 10**12})
    with pytest.raises(ValueError, match="Unsupported"):
        await socket.receive_text()
    devices.revoke(devices.snapshot()["devices"][0]["id"])
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        await socket.check()
    assert ws.closed


@pytest.fixture
def connector(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    c = Connectors(store)
    store.run("INSERT INTO connectors VALUES(?,?,1)", ("calendar_write", "{}"))
    yield c
    store.close()


@pytest.mark.asyncio
async def test_meeting_invitation_and_link_exact_review(connector, monkeypatch):
    saved = {}
    calls = []

    async def request(profile, method, path, **kw):
        calls.append((method, kw))
        if method == "POST":
            saved.update(kw["json"])
            saved["conferenceData"]["createRequest"]["status"] = {
                "statusCode": "pending"
            }
        return saved

    monkeypatch.setattr(connector, "request", request)
    proposal = await prepare(
        connector,
        CalendarEvent(**EVENT, attendees=["fixture@example.com"], google_meet=True),
    )
    assert not calls
    args = json.loads(
        connector.store.all("SELECT args FROM external_actions")[0]["args"]
    )
    assert (
        args["event"]["attendees"] == [{"email": "fixture@example.com"}]
        and args["notify_guests"]
    )
    result = await connector.review(proposal["action_id"], True)
    assert (
        result["result"]["verified"]
        and result["result"]["conference_status"] == "pending"
    )
    assert (
        result["result"]["meeting_url"] is None
        and not result["result"]["invitation_delivery_verified"]
    )
    assert calls[0][1]["params"] == {"sendUpdates": "all", "conferenceDataVersion": 1}


@pytest.mark.parametrize(
    "attendees",
    [
        ["bad"],
        ["a@example.com", "A@example.com"],
        ["a@example.com\nBcc: other@example.com"],
    ],
)
def test_attendee_validation(attendees):
    with pytest.raises(ValueError):
        CalendarEvent(**EVENT, attendees=attendees)


@pytest.mark.asyncio
async def test_cancel_review_etag_and_no_replay(connector, monkeypatch):
    calls = []

    async def request(profile, method, path, **kw):
        calls.append((method, kw))
        if method == "GET" and not kw.get("allow_not_found"):
            return {
                "id": "fixture123",
                "etag": '"v1"',
                "organizer": {"self": True},
                "summary": "Fixture",
                "attendees": [{"email": "fixture@example.com"}],
            }
        if method == "GET":
            return {"not_found": True}
        return {}

    monkeypatch.setattr(connector, "request", request)
    p = await prepare_cancel(connector, CalendarCancel(event_id="fixture123"))
    assert [c[0] for c in calls] == ["GET"]
    r = await connector.review(p["action_id"], True)
    assert r["result"]["verified"] and r["result"]["status"] == "cancelled"
    assert calls[1][1]["headers"] == {"If-Match": '"v1"'}
    assert calls[1][1]["params"] == {"sendUpdates": "all"}
    with pytest.raises(ValueError):
        await connector.review(p["action_id"], True)


@pytest.mark.asyncio
async def test_availability_respects_all_day_conflicts_and_pagination(
    connector, monkeypatch
):
    calls = []

    async def request(profile, method, path, **kw):
        calls.append(kw)
        if "pageToken" not in kw["params"]:
            return {
                "items": [
                    {"start": {"date": "2026-10-06"}, "end": {"date": "2026-10-07"}}
                ],
                "nextPageToken": "second",
            }
        return {
            "items": [
                {
                    "start": {"dateTime": "2026-10-07T09:00:00+05:30"},
                    "end": {"dateTime": "2026-10-07T10:00:00+05:30"},
                }
            ]
        }

    monkeypatch.setattr(connector, "request", request)
    result = await suggest(
        connector,
        Availability(
            start="2026-10-06T09:00:00+05:30", end="2026-10-07T11:00:00+05:30"
        ),
    )
    assert len(calls) == 2
    assert result["slots"][0]["start"] == "2026-10-07T10:00:00+05:30"
    assert not result["other_attendees_checked"]


@pytest.mark.asyncio
async def test_availability_fails_on_truncation(connector, monkeypatch):
    async def request(*args, **kw):
        return {"items": [], "nextPageToken": "more"}

    monkeypatch.setattr(connector, "request", request)
    with pytest.raises(ValueError, match="400 events"):
        await suggest(connector, Availability(start=EVENT["start"], end=EVENT["end"]))


def test_navigation_has_no_fabricated_route_or_url_injection():
    result = directions(Directions(destination="Pune &query=other", mode="cycling"))
    assert "Pune+%26query%3Dother" in result["google_maps_url"]
    assert "travelmode=bicycling" in result["google_maps_url"]
    assert (
        not result["route_verified"] and not result["apple_cycling_supported_by_link"]
    )


def test_appointment_brief_is_local_and_not_a_booking(devices, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA", tmp_path)
    result = brief(
        devices.store,
        AppointmentBrief(
            recipient="Fixture clinic",
            purpose="Routine appointment",
            preferred_times=["Tomorrow 10 AM Asia/Kolkata"],
        ),
    )
    assert not result["appointment_booked"] and not result["call_placed"]
    assert (tmp_path / "generated-documents" / result["filename"]).exists()
