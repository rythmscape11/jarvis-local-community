"""Isolated calendar/draft tests. All external writes here use substituted HTTP."""

import json
import pytest
from jarvis.calendar_actions import CalendarEvent, CalendarUpdate, prepare
from jarvis.connectors import Connectors
from jarvis.store import Store
from jarvis.tools import Tools
from jarvis.config import Settings
from jarvis.agent import relevant_tools
from jarvis.providers import inference_error

EVENT = dict(
    title="Synthetic roadmap review",
    start="2026-10-06T10:00:00+05:30",
    end="2026-10-06T10:30:00+05:30",
)


@pytest.fixture
def connector(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    c = Connectors(store)
    store.run("INSERT INTO connectors VALUES(?,?,1)", ("calendar_write", "{}"))
    yield c
    store.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"end": EVENT["start"]},
        {"start": "2026-10-06T10:00:00"},
        {"timezone": "America/New_York"},
        {"event_id": "../../secret"},
        {"title": " "},
    ],
)
def test_calendar_arguments(changes):
    with pytest.raises(ValueError):
        CalendarEvent.model_validate(EVENT | changes)


@pytest.mark.asyncio
async def test_calendar_create_requires_review_and_verifies_saved_record(
    connector, monkeypatch
):
    calls = []
    saved = {}

    async def request(profile, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            saved.update(kwargs["json"])
            return saved
        return saved

    monkeypatch.setattr(connector, "request", request)
    proposal = await prepare(connector, CalendarEvent(**EVENT))
    assert not calls
    result = await connector.review(proposal["action_id"], True)
    assert result["state"] == "succeeded" and result["result"]["verified"]
    assert [c[0] for c in calls] == ["POST", "GET"]
    assert calls[0][2]["params"]["sendUpdates"] == "none"
    with pytest.raises(ValueError):
        await connector.review(proposal["action_id"], True)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_calendar_update_uses_etag_and_displays_guests(connector, monkeypatch):
    saved = {
        "id": "fixture123",
        "etag": '"version1"',
        "organizer": {"self": True},
        "attendees": [{"email": "fixture@example.com"}],
        **CalendarEvent(**EVENT).payload(),
    }
    calls = []

    async def request(profile, method, path, **kwargs):
        calls.append((method, kwargs))
        if method == "PATCH":
            assert kwargs["headers"] == {"If-Match": '"version1"'}
            assert kwargs["params"] == {"sendUpdates": "all"}
            saved.update(kwargs["json"])
        return saved.copy()

    monkeypatch.setattr(connector, "request", request)
    proposal = await prepare(
        connector,
        CalendarUpdate(**(EVENT | {"title": "Updated fixture"}), event_id="fixture123"),
    )
    assert [c[0] for c in calls] == ["GET"]
    row = connector.store.all("SELECT args FROM external_actions")[0]
    assert json.loads(row["args"])["before"]["attendees"] == saved["attendees"]
    result = await connector.review(proposal["action_id"], True)
    assert result["result"]["status"] == "updated"
    assert [c[0] for c in calls] == ["GET", "PATCH", "GET"]


@pytest.mark.asyncio
async def test_uncertain_calendar_write_never_replays(connector, monkeypatch):
    async def request(profile, method, path, **kwargs):
        if method == "POST":
            return kwargs["json"]
        raise TimeoutError()

    monkeypatch.setattr(connector, "request", request)
    proposal = await prepare(connector, CalendarEvent(**EVENT))
    with pytest.raises(InterruptedError):
        await connector.review(proposal["action_id"], True)
    assert (
        connector.store.all("SELECT state FROM external_actions")[0]["state"]
        == "interrupted"
    )
    with pytest.raises(ValueError):
        await connector.review(proposal["action_id"], True)


@pytest.mark.asyncio
async def test_disconnected_calendar_and_email_draft(connector):
    connector.store.run("DELETE FROM connectors WHERE id='calendar_write'")
    with pytest.raises(ValueError, match="Not connected"):
        await prepare(connector, CalendarEvent(**EVENT))
    tools = Tools(connector.store, lambda: Settings())
    tools.connectors = connector
    draft = await tools.execute(
        "prepare_email",
        {
            "to": "fixture@example.com",
            "subject": "Test",
            "content": "Synthetic draft only",
        },
        "draft1",
    )
    assert draft["ok"] and draft["data"]["status"] == "awaiting_approval"
    assert len(connector.store.all("SELECT * FROM external_actions")) == 1
    again = await tools.execute(
        "prepare_email",
        {
            "to": "fixture@example.com",
            "subject": "Test",
            "content": "Synthetic draft only",
        },
        "draft1",
    )
    assert again == draft


def test_model_gets_calendar_email_tools_and_safe_errors():
    def names(text):
        return {s["function"]["name"] for s in relevant_tools(text)}

    assert {"read_calendar", "create_calendar_event", "update_calendar_event"} <= names(
        "Reschedule my meeting tomorrow"
    )
    assert {"read_email", "prepare_email", "prepare_email_reply"} <= names(
        "Read my email and draft a response"
    )
    assert "valid tool request" in inference_error(
        {"code": "tool_use_failed", "message": "private"}
    )
    assert "private" not in inference_error({"code": "unknown", "message": "private"})
