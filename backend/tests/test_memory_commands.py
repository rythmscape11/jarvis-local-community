"""Real SQLite deletion and controller regressions; inference here is mocked."""

import pytest
from jarvis.agent import Agent, relevant_tools
from jarvis.config import Settings
from jarvis.current_data import current_request, knowledge_answer
from jarvis.store import Store
from jarvis.tools import Tools


@pytest.mark.asyncio
async def test_local_reminder_ack_does_not_invent_calendar_write(tmp_path):
    store = Store(tmp_path / "db")
    cfg = Settings()

    class Model:
        async def stream(self, messages, tools, settings):
            if tools:
                yield {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "create_reminder",
                                    "arguments": {
                                        "title": "review the roadmap",
                                        "datetime": "2035-10-07T10:00:00+05:30",
                                    },
                                }
                            }
                        ]
                    }
                }
            else:
                raise AssertionError("Do not let inference invent a calendar write")

    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(store, Tools(store, lambda: cfg), Model(), None, lambda: cfg).turn(
        "s", "t", "Create a reminder to review the roadmap", send, False
    )
    answer = next(body["text"] for kind, body in events if kind == "done")
    assert "7 October at 10:00 AM (Asia/Kolkata)" in answer
    assert "local reminders" in answer and "calendar" not in answer.lower()
    assert len(store.all("SELECT * FROM reminders")) == 1
    store.close()


@pytest.mark.asyncio
async def test_forget_wrong_fact_preserves_unrelated_history_and_idempotency(tmp_path):
    path = tmp_path / "memory.db"
    s = Store(path)
    cfg = Settings()
    t = Tools(s, lambda: cfg)
    await t.execute(
        "remember_this", {"key": "owner_name", "value": "Wrongname"}, "name-write"
    )
    note = await t.execute(
        "create_note", {"title": "Other", "content": "Keep this note"}, "note-write"
    )
    s.conversation("s", "bad", "user", "My name is Wrongname")
    s.conversation("s", "bad", "assistant", "Hello Wrongname")
    s.conversation("s", "good", "user", "Project Orbit uses teal")
    s.compact("s")
    result = await t.execute("forget_information", {"query": "Wrongname"}, "forget")
    assert result["ok"] and result["data"]["deleted_preferences"] == 1
    assert (
        await t.execute("forget_information", {"query": "Wrongname"}, "forget")
        == result
    )
    assert s.conversation_recall("Wrongname") == []
    assert s.conversation_recall("Orbit")
    assert not s.all("SELECT * FROM summaries")
    assert "Wrongname" not in str(s.all("SELECT * FROM executions"))
    # A forgotten write must never be replayed with its old key.
    assert not (
        await t.execute(
            "remember_this", {"key": "owner_name", "value": "Wrongname"}, "name-write"
        )
    )["ok"]
    assert (
        await t.execute(
            "create_note", {"title": "Other", "content": "Keep this note"}, "note-write"
        )
        == note
    )
    s.close()
    s = Store(path)
    assert s.conversation_recall("Wrongname") == [] and s.conversation_recall("Orbit")
    assert len(s.all("SELECT * FROM notes")) == 1
    s.close()


@pytest.mark.asyncio
async def test_in_turn_forgetting_acknowledges_without_resurrecting_context(tmp_path):
    s = Store(tmp_path / "db")
    cfg = Settings()
    s.conversation("s", "old", "user", "My name is Wrongname")

    class Model:
        async def stream(self, messages, tools, settings):
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "forget_information",
                                "arguments": {"query": "Wrongname"},
                            }
                        }
                    ]
                }
            }

    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(s, Tools(s, lambda: cfg), Model(), None, lambda: cfg).turn(
        "s", "new", "Forget Wrongname from memory", send, False
    )
    assert s.conversation_recall("Wrongname") == []
    assert any(k == "done" and "removed" in b["text"] for k, b in events)
    s.close()


@pytest.mark.parametrize("query", ["", "  ", "a", "***"])
@pytest.mark.asyncio
async def test_invalid_deletions_do_not_remove_records(tmp_path, query):
    s = Store(tmp_path / "db")
    cfg = Settings()
    s.conversation("s", "t", "user", "Keep this information")
    r = await Tools(s, lambda: cfg).execute(
        "forget_information", {"query": query}, "bad"
    )
    assert not r["ok"] and s.conversation_recall("information")
    s.close()


@pytest.mark.parametrize(
    "text",
    [
        "How can I delete memories?",
        "Don't forget my name",
        'The article says "forget Wrongname"',
        "Should I erase this memory?",
    ],
)
def test_memory_capability_questions_do_not_offer_destructive_tools(text):
    names = {t["function"]["name"] for t in relevant_tools(text)}
    assert not names & {"forget_this", "forget_information", "correct_conversation"}


@pytest.mark.parametrize(
    "text",
    [
        "Are you using the local model?",
        "Which model are you using right now?",
        "What provider is Jarvis using?",
    ],
)
def test_selected_model_answers_from_configuration_without_web_search(text):
    cfg = Settings(model="fixture-local")
    assert current_request(text) is None
    assert "fixture-local" in knowledge_answer(text, cfg)


def test_editing_preference_does_not_erase_unrelated_chat(tmp_path):
    s = Store(tmp_path / "db")
    s.run("INSERT INTO memory VALUES(?,?,?,?)", ("1", "project", "Oldname", "today"))
    s.conversation("s", "old", "user", "Oldname is my project")
    s.conversation("s", "keep", "user", "My colour is teal")
    s.update_memory("1", "project", "Newname")
    assert s.conversation_recall("Oldname") == []
    assert s.conversation_recall("teal")
    assert s.all("SELECT value FROM memory")[0]["value"] == "Newname"
    s.close()


@pytest.mark.asyncio
async def test_list_tool_result_is_not_treated_as_mapping(tmp_path):
    s = Store(tmp_path / "db")
    s.note("Orbit plan", "A real stored fixture")
    cfg = Settings()

    class Model:
        async def stream(self, messages, tools, settings):
            if tools:
                yield {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "search_notes",
                                    "arguments": {"query": "Orbit"},
                                }
                            }
                        ]
                    }
                }
            else:
                yield {"message": {"content": "I found your Orbit plan note."}}

    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(s, Tools(s, lambda: cfg), Model(), None, lambda: cfg).turn(
        "s", "t", "Find my Orbit note", send, False
    )
    assert any(k == "done" for k, _ in events)
    s.close()


@pytest.mark.asyncio
async def test_rejected_owner_name_is_removed_without_guessing_replacement(tmp_path):
    s = Store(tmp_path / "db")
    s.run(
        "INSERT INTO memory VALUES(?,?,?,?)", ("1", "owner_name", "Wrongname", "today")
    )
    cfg = Settings()

    class Model:
        async def stream(self, *args):
            raise AssertionError("Name correction should not be guessed by inference")
            yield

    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(s, Tools(s, lambda: cfg), Model(), None, lambda: cfg).turn(
        "s", "t", "I am not Wrongname", send, False
    )
    assert s.all("SELECT * FROM memory") == []
    assert any(k == "done" and "won't guess" in b["text"] for k, b in events)
    s.close()
