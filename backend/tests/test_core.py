import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from jarvis.store import Store
from jarvis.tools import Tools
from jarvis.config import Settings
from jarvis.documents import index, permitted
from jarvis.agent import speakable
from jarvis.jobs import Jobs


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite")
    yield s
    s.close()


@pytest.fixture
def tools(store):
    return Tools(store, lambda: Settings())


@pytest.mark.asyncio
async def test_invalid_arguments_are_not_executed(store, tools):
    for name, args in [
        ("create_note", {"title": "x"}),
        ("create_reminder", {"title": 4, "datetime": "tomorrow"}),
        ("open_application", {"name": "Safari", "command": "rm -rf /"}),
        ("unknown_tool", {}),
    ]:
        assert not (await tools.execute(name, args, "invalid"))["ok"]
    assert store.all("SELECT * FROM notes") == []
    assert store.all("SELECT * FROM executions") == []


@pytest.mark.asyncio
async def test_idempotent_concurrent_writes_and_conflicting_key(store, tools):
    args = {"title": "Kinetivy", "content": "Review the roadmap"}
    results = await asyncio.gather(
        *(tools.execute("create_note", args, "same-key") for _ in range(8))
    )
    assert all(r["ok"] for r in results)
    assert len({r["data"]["id"] for r in results}) == 1
    assert len(store.all("SELECT * FROM notes")) == 1
    conflict = await tools.execute(
        "create_note", {"title": "Other", "content": "Changed"}, "same-key"
    )
    assert not conflict["ok"]
    assert store.search_notes("roadmap")[0]["title"] == "Kinetivy"


@pytest.mark.asyncio
async def test_reminder_timezone_and_persistence(store, tools, tmp_path):
    due = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=4, minute=30, second=0, microsecond=0
    )
    r = await tools.execute(
        "create_reminder",
        {"title": "Review the Kinetivy roadmap", "datetime": due.isoformat()},
        "reminder",
    )
    assert r["ok"]
    assert r["data"]["timezone"] == "Asia/Kolkata"
    assert r["data"]["local_datetime"].endswith("10:00:00+05:30")
    assert not (
        await tools.execute(
            "create_reminder",
            {"title": "Bad", "datetime": "2030-01-01T10:00:00"},
            "no-tz",
        )
    )["ok"]
    cancelled = await tools.execute(
        "cancel_reminder", {"id": r["data"]["id"]}, "cancel"
    )
    assert cancelled["data"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_forget_purges_context_and_search(store, tools):
    await tools.execute(
        "remember_this", {"key": "timezone", "value": "Asia/Kolkata"}, "remember"
    )
    store.conversation("s", "t", "user", "remember timezone")
    store.run("INSERT INTO summaries VALUES(?,?)", ("s", "timezone"))
    r = await tools.execute("forget_this", {"key": "timezone"}, "forget")
    assert r["ok"]
    assert store.all("SELECT * FROM memory") == []
    assert store.context("s") == []
    assert store.all("SELECT * FROM summaries") == []
    note = store.note("Private", "Delete this content")
    store.delete_record("notes", note["id"])
    assert store.search_notes("Delete") == []


def test_document_boundaries_incremental_and_removed_files(store, tmp_path):
    root = tmp_path / "selected"
    root.mkdir()
    outside = tmp_path / "private.md"
    outside.write_text("Outside secret text")
    (root / "escape.md").symlink_to(outside)
    (root / "good.md").write_text("Kinetivy roadmap milestones")
    (root / "credentials.md").write_text("never index")
    (root / "binary.txt").write_bytes(b"\x00Kinetivy")
    (root / "huge.txt").write_text("x" * 512001)
    store.run("INSERT INTO directories VALUES(?)", (str(root),))
    result = index(store, str(root))
    assert result["changed"] == 1
    assert not permitted(root / "escape.md", root)
    assert store.search_documents("roadmap")[0]["path"] == str(root / "good.md")
    assert index(store, str(root))["changed"] == 0
    (root / "good.md").write_text("New milestone plan")
    assert index(store, str(root))["changed"] == 1
    assert store.search_documents("roadmap") == []
    (root / "good.md").unlink()
    index(store, str(root))
    assert store.search_documents("milestone") == []
    with pytest.raises(ValueError):
        index(store, str(tmp_path))


def test_overdue_reminder_restart_without_duplicate(tmp_path):
    path = tmp_path / "persist.sqlite"
    s = Store(path)
    s.run(
        "INSERT INTO reminders VALUES(?,?,?,?,?,?,?)",
        (
            "id",
            "Review",
            "2020-01-01T00:00:00+00:00",
            "Asia/Kolkata",
            "pending",
            None,
            "created",
        ),
    )
    assert len(s.due_reminders()) == 1
    s.close()
    s = Store(path)
    assert len(s.due_reminders()) == 1
    s.acknowledge("id")
    s.close()
    s = Store(path)
    assert s.due_reminders() == []
    s.close()


def test_restart_does_not_replay_jobs_or_inflight_writes(tmp_path):
    path = tmp_path / "persist.sqlite"
    s = Store(path)
    for state in ["queued", "running", "succeeded", "failed", "cancelled"]:
        s.run(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
            (state, "index", "{}", state, None, None, "created", "updated"),
        )
    s.note("Persistent", "Still here")
    s.run("INSERT INTO memory VALUES(?,?,?,?)", ("id", "name", "Owner", "created"))
    s.run(
        "INSERT INTO executions VALUES(?,?,?,?,?,?)",
        ("key", "create_note", "{}", "running", None, "created"),
    )
    s.close()
    s = Store(path)
    states = {r["id"]: r["state"] for r in s.all("SELECT * FROM jobs")}
    assert states["queued"] == states["running"] == "interrupted"
    assert states["succeeded"] == "succeeded"
    assert len(s.search_notes("Persistent")) == 1
    assert len(s.all("SELECT * FROM memory")) == 1
    assert s.all("SELECT state FROM executions")[0]["state"] == "interrupted"
    s.close()


@pytest.mark.asyncio
async def test_tool_failure_propagates_and_launch_is_allowlisted(store, tools):
    r = await tools.execute(
        "open_application", {"name": "Terminal; arbitrary command"}, "launch"
    )
    assert not r["ok"]
    assert "allowlisted" in r["error"]
    assert store.all("SELECT state FROM executions")[0]["state"] == "failed"


def test_speech_never_contains_tool_json_or_code():
    assert speakable('{"tool":"open_application"}') == ""
    assert speakable("```sh\nrm -rf /\n```") == ""
    assert speakable("**Saved.**") == "Saved."
    assert speakable("[The source](https://example.com).") == "The source."


@pytest.mark.asyncio
async def test_job_worker_completes_and_cancels(store, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.md").write_text("Roadmap job")
    store.run("INSERT INTO directories VALUES(?)", (str(root),))
    jobs = Jobs(store)
    jobs.start()
    id = jobs.submit(str(root))
    await asyncio.wait_for(jobs.queue.join(), 5)
    assert (
        store.all("SELECT state FROM jobs WHERE id=?", (id,))[0]["state"] == "succeeded"
    )
    id = jobs.submit(str(root))
    jobs.cancel(id)
    await asyncio.wait_for(jobs.queue.join(), 5)
    assert (
        store.all("SELECT state FROM jobs WHERE id=?", (id,))[0]["state"] == "cancelled"
    )
    await jobs.close()


@pytest.mark.asyncio
async def test_chat_memory_survives_restart_retrieves_old_fact_and_forgets(tmp_path):
    db = tmp_path / "chat-memory.db"
    s = Store(db)
    t = Tools(s, lambda: Settings())
    first = await t.execute(
        "remember_this",
        {"key": "chat:fixture-turn", "value": "My project is called Kinetivy."},
        "chat-first",
    )
    duplicate = await t.execute(
        "remember_this",
        {"key": "chat:fixture-turn", "value": "My project is called Kinetivy."},
        "chat-first",
    )
    assert first == duplicate
    for n in range(12):
        await t.execute(
            "remember_this",
            {"key": f"unrelated {n}", "value": "I prefer calm voices."},
            f"other-{n}",
        )
    s.close()
    s = Store(db)
    assert (
        s.memory_context("What is my project called?")[0]["value"]
        == "My project is called Kinetivy."
    )
    assert len(s.all("SELECT * FROM memory WHERE key='chat:fixture-turn'")) == 1
    s.delete_record("memory", first["data"]["id"])
    assert not any("Kinetivy" in r["value"] for r in s.memory_context("my project"))
    s.close()
