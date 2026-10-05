"""Controller regression tests with fake model and speech, not live inference."""

import uuid
import pytest
from jarvis.agent import Agent, relevant_tools, personal_agenda_request
from jarvis.config import Settings
from jarvis.store import Store
from jarvis.tools import Tools


class Voice:
    async def synthesize(self, text, voice):
        return b"fixture wav"


@pytest.mark.asyncio
async def test_personal_agenda_reads_real_records_before_answering(tmp_path):
    class Model:
        async def stream(self, messages, tools, settings):
            assert tools == []
            supplied = messages[-1]["content"]
            assert "Actual agenda records" in supplied
            assert "Review real roadmap" in supplied
            assert '"ok": false' in supplied  # unavailable Calendar/Tasks are explicit
            assert "never repeat an unverified task" in supplied
            yield {
                "message": {
                    "content": "Your saved reminder is to review the real roadmap."
                }
            }

    store = Store(tmp_path / "agenda.db")
    settings = Settings()
    tools = Tools(store, lambda: settings)
    created = await tools.execute(
        "create_reminder",
        {"title": "Review real roadmap", "datetime": "2099-10-06T10:00:00+05:30"},
        "agenda-fixture-write",
    )
    assert created["ok"]
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(store, tools, Model(), Voice(), lambda: settings).turn(
        "agenda-session",
        str(uuid.uuid4()),
        "You know what is my task today?",
        send,
        False,
    )
    assert {body["name"] for kind, body in events if kind == "tool"} == {
        "list_reminders",
        "read_calendar",
        "read_connector",
    }
    assert len(store.all("SELECT * FROM reminders")) == 1
    store.close()


def test_personal_agenda_does_not_intercept_a_write_request():
    assert personal_agenda_request("What are my priorities today?")
    assert not personal_agenda_request("Create a reminder for my tasks today")


@pytest.mark.asyncio
async def test_chat_streams_once_without_tool_schema(tmp_path):
    class Model:
        calls = 0

        async def stream(self, messages, tools, settings):
            self.calls += 1
            assert tools == []
            yield {"message": {"content": "Paris. "}}

    store = Store(tmp_path / "chat.db")
    settings = Settings()
    model = Model()
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(
        store, Tools(store, lambda: settings), model, Voice(), lambda: settings
    ).turn("session", str(uuid.uuid4()), "What is the capital of France?", send)
    assert model.calls == 1
    assert [body["text"] for kind, body in events if kind == "delta"] == ["Paris. "]
    assert len([e for e in events if e[0] == "audio"]) == 1
    store.close()


@pytest.mark.asyncio
async def test_note_uses_verified_result_and_no_extra_rewrite(tmp_path):
    class Model:
        calls = 0

        async def stream(self, messages, tools, settings):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "create_note",
                                    "arguments": {
                                        "title": "Ideas",
                                        "content": "Take a walk",
                                    },
                                }
                            }
                        ]
                    }
                }
            else:
                assert tools == []
                assert "Take a walk" in messages[-1]["content"]
                yield {"message": {"content": "Saved your Ideas note. "}}

    store = Store(tmp_path / "notes.db")
    settings = Settings()
    model = Model()
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(
        store, Tools(store, lambda: settings), model, Voice(), lambda: settings
    ).turn(
        "session", str(uuid.uuid4()), "Create a note titled Ideas: Take a walk", send
    )
    # The verified local write now supplies its acknowledgement directly.
    assert model.calls == 1
    assert store.search_notes("walk")[0]["title"] == "Ideas"
    assert any(
        kind == "tool" and body["status"] == "succeeded" for kind, body in events
    )
    store.close()


def test_schema_retrieval_for_followup():
    selected = relevant_tools("something on politics", [])
    assert [t["function"]["name"] for t in selected] == ["get_news"]
    assert relevant_tools("Hey, how are you?") == []


@pytest.mark.asyncio
async def test_voice_change_is_verified_and_ack_uses_new_voice(tmp_path):
    from jarvis.tools import VOICE_NAMES

    active = Settings()
    said = []

    class Speech:
        def available(self):
            return list(VOICE_NAMES.values())

        async def synthesize(self, text, voice):
            said.append(voice)
            return b"fixture wav"

    class Model:
        calls = 0

        async def stream(self, messages, tools, settings):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "set_voice",
                                    "arguments": {"name": "Emma"},
                                }
                            }
                        ]
                    }
                }
            else:
                yield {"message": {"content": "I'm using Emma's voice now. "}}

    store = Store(tmp_path / "voice.db")
    tools = Tools(store, lambda: active)
    tools.voice_adapter = Speech()

    def change(voice):
        nonlocal active
        active = Settings.model_validate(active.model_dump() | {"voice": voice})

    tools.on_voice_change = change

    async def send(kind, **body):
        pass

    await Agent(store, tools, Model(), tools.voice_adapter, lambda: active).turn(
        "voice-session", str(uuid.uuid4()), "Change your voice to Emma", send
    )
    assert active.voice == "kokoro-bf_emma"
    assert said == ["kokoro-bf_emma"]
    assert not (await tools.execute("set_voice", {"name": "Unknown"}, "invalid-voice"))[
        "ok"
    ]
    original = active.voice
    tools.voice_adapter.available = lambda: ["kokoro-am_michael"]
    assert not (await tools.execute("set_voice", {"name": "George"}, "missing-voice"))[
        "ok"
    ]
    assert active.voice == original
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Are you storing our conversations locally?",
        "Do you keep a local copy of our chats?",
        "Basically you don't store anything on your site is it?",
    ],
)
async def test_storage_answer_reports_actual_local_and_online_behavior(
    tmp_path, question
):
    class NeverModel:
        async def stream(self, *args):
            raise AssertionError("Privacy behavior must not be guessed by the model")
            yield

    s = Store(tmp_path / "privacy.db")
    s.conversation("privacy", "prior", "user", "Are our chats saved?")
    cfg = Settings(
        provider="compatible",
        api_base="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
    )
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(s, Tools(s, lambda: cfg), NeverModel(), Voice(), lambda: cfg).turn(
        "privacy", str(uuid.uuid4()), question, send, False
    )
    done = next(body for kind, body in events if kind == "done")
    assert "SQLite" in done["text"] and "across restarts" in done["text"]
    assert "Groq" in done["text"] and "isn't fully offline" in done["text"]
    assert "model_ttft_ms" not in done["metrics"]
    assert s.context("privacy")[-1]["content"] == done["text"]
    s.close()
