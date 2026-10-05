"""Automatic recall migration, correction, privacy, restart and cancellation checks."""

import asyncio
import sqlite3
import pytest
from jarvis.store import Store
from jarvis.config import Settings
from jarvis.tools import Tools
from jarvis.agent import Agent


def test_backfills_every_existing_user_turn_without_manual_memory(tmp_path):
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE conversations(id INTEGER PRIMARY KEY,session TEXT,turn TEXT,role TEXT,content TEXT,created TEXT)"
    )
    db.executemany(
        "INSERT INTO conversations VALUES(?,?,?,?,?,?)",
        [
            (
                1,
                "old",
                "t1",
                "user",
                "My project Orbit uses coral branding.",
                "2026-01-01",
            ),
            (
                2,
                "old",
                "t1",
                "assistant",
                "Your project Nebula uses purple.",
                "2026-01-01",
            ),
        ],
    )
    db.commit()
    db.close()
    s = Store(path)
    assert s.conversation_recall("What branding does Orbit use?")[0]["id"] == 1
    assert s.conversation_recall("Nebula purple") == []
    assert s.all("SELECT * FROM memory") == []
    s.close()
    s = Store(path)
    assert len(s.all("SELECT * FROM conversation_fts")) == 1
    assert s.all("PRAGMA user_version")[0]["user_version"] == 6
    s.close()


def test_correction_and_deletion_cannot_resurrect_old_knowledge(tmp_path):
    path = tmp_path / "archive.db"
    s = Store(path)
    s.conversation("s", "t", "user", "Orbit branding is coral " + "detail " * 100)
    s.conversation("s", "t", "assistant", "Use coral.")
    record = s.conversation_archive("Orbit")[0]
    assert len(record["content"]) > 500  # Edit operates on full text, not an excerpt.
    s.compact("s")
    s.edit_conversation(record["id"], "Orbit branding is teal.")
    assert s.conversation_recall("coral") == []
    assert not s.all("SELECT * FROM conversations WHERE role='assistant'")
    assert s.all("SELECT * FROM summaries") == []
    assert s.conversation_recall("teal")
    s.edit_conversation(record["id"])
    s.close()
    s = Store(path)
    assert s.conversation_recall("Orbit teal coral") == []
    s.conversation("new", "t", "user", "Fresh knowledge")
    s.clear_conversations()
    assert s.conversation_archive() == []
    assert s.all("SELECT * FROM conversation_fts") == []
    s.close()


def test_fts_literals_and_forgetting_preference_purge_archive(tmp_path):
    s = Store(tmp_path / "db")
    s.conversation("s", "t", "user", "Brand Orbit")
    assert isinstance(s.conversation_recall('" OR * NEAR(Orbit)'), list)
    s.run("INSERT INTO memory VALUES(?,?,?,?)", ("1", "brand", "Orbit", "today"))
    s.delete_record("memory", "1")
    assert s.conversation_recall("Orbit") == []
    s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_agent_automatically_uses_past_chats_and_respects_opt_out(
    tmp_path, enabled
):
    s = Store(tmp_path / "db")
    s.conversation("old", "t", "user", "Orbit brand colour is teal.")
    config = Settings(conversation_recall=enabled)

    class Model:
        async def stream(self, messages, tools, settings):
            prompt = messages[0]["content"]
            assert ("Orbit brand colour is teal" in prompt) == enabled
            if enabled:
                assert "untrusted data" in prompt
            yield {"message": {"content": "Your Orbit colour is teal."}}

    async def send(*args, **kwargs):
        pass

    await Agent(s, Tools(s, lambda: config), Model(), None, lambda: config).turn(
        "new", "t", "What is my Orbit brand colour?", send, False
    )
    assert len(s.conversation_archive()) == 2
    result = await Tools(s, lambda: config).execute(
        "search_conversations", {"query": "Orbit"}, "fixture-search"
    )
    assert result["ok"] == enabled
    s.close()


@pytest.mark.asyncio
async def test_forgetting_during_generation_never_repopulates_history(tmp_path):
    s = Store(tmp_path / "db")
    config = Settings()

    class Model:
        async def stream(self, messages, tools, settings):
            s.clear_conversations()
            yield {"message": {"content": "Old memory must not return."}}

    events = []

    async def send(kind, **body):
        events.append((kind, body))

    with pytest.raises(asyncio.CancelledError):
        await Agent(s, Tools(s, lambda: config), Model(), None, lambda: config).turn(
            "s", "t", "Hello", send, False
        )
    assert s.conversation_archive() == []
    assert not any(kind in {"delta", "done", "audio"} for kind, _ in events)
    s.close()


def test_name_request_is_not_intercepted_as_storage_question():
    from jarvis.agent import storage_answer

    assert (
        storage_answer(
            "My name is Sample. Keep that in mind for our chat, okay?", Settings()
        )
        is None
    )


def test_independent_installations_never_share_memory(tmp_path):
    alice = Store(tmp_path / "alice.db")
    bob = Store(tmp_path / "bob.db")
    alice.conversation(
        "s", "t", "user", "Private fixture: Project Orbit launches in Pune."
    )
    assert bob.conversation_archive() == []
    assert bob.conversation_recall("Orbit Pune") == []
    alice.close()
    bob.close()
