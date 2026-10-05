"""Regression checks with isolated records and mocked online speech; no owner data."""

import asyncio
import io
import json
import os
import time
import wave
import struct
import pytest
import httpx
from jarvis import config
from jarvis.config import Settings
from jarvis.store import Store
from jarvis.tools import Tools
from jarvis.exports import document_path
from jarvis.speech import GroqSpeech, normalize_wav, speech_parts, groq_limit_message
from jarvis.agent import Agent, relevant_tools


def test_document_conversion_keeps_note_retrieval():
    names = {
        t["function"]["name"]
        for t in relevant_tools("Create a Word document from my saved roadmap note")
    }
    assert {"create_document", "search_notes"} <= names
    assert "create_note" not in names


def wav_fixture():
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<h", 1200) * 2400)
    return out.getvalue()


def test_streaming_wav_sentinel_lengths():
    raw = bytearray(wav_fixture())
    raw[4:8] = b"\xff" * 4
    raw[40:44] = b"\xff" * 4
    result = normalize_wav(bytes(raw))
    with wave.open(io.BytesIO(result), "rb") as w:
        assert w.getnframes() == 2400
        assert w.getframerate() == 24000
    for raw in (b"not wav", b"RIFF" + b"\0" * 80):
        with pytest.raises((ValueError, wave.Error, EOFError)):
            normalize_wav(raw)
    parts = speech_parts(("A natural sentence with breathing room. " * 15), 190)
    assert all(len(p) <= 190 for p in parts)
    assert " ".join(parts) == ("A natural sentence with breathing room. " * 15).strip()


@pytest.mark.asyncio
async def test_online_opt_in_quota_and_cancel(monkeypatch):
    settings = Settings()
    g = GroqSpeech(lambda: settings)
    with pytest.raises(ValueError, match="Enable"):
        await g.synthesize("hello", "groq-hannah")
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *args: "synthetic-key")
    settings.online_voice_enabled = True
    await g.client.aclose()
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(429)

    g.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="rate-limited"):
        await g.synthesize("hello", "groq-hannah")
    assert len(requests) == 1
    g.last_request = time.monotonic()
    task = asyncio.create_task(g.synthesize("hello", "groq-hannah"))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(requests) == 1  # cancellation does not resume queued requests
    await g.close()


def test_voice_limits_are_specific_and_never_echo_raw_provider_data():
    body = json.dumps(
        {
            "error": {
                "message": "Rate limit reached for model on tokens per day (TPD): Limit 3600, Used 3590, Requested 50. Please try again in 2h. secret-org-id"
            }
        }
    ).encode()
    message = groq_limit_message(body, {"retry-after": "7200"})
    assert "tokens per day" in message and "7,200 seconds" in message
    assert "secret-org-id" not in message and "quota" not in message
    assert "tokens per minute" in groq_limit_message(
        b'{"error":{"message":"tokens per minute (TPM) exceeded"}}', {}
    )
    for body in (b"malformed", b"x" * 9000, b'{"error":{"message":["secret"]}}'):
        message = groq_limit_message(body, {"retry-after": "secret"})
        assert "rate-limited" in message and "secret" not in message


@pytest.mark.asyncio
async def test_natural_voice_has_no_direction_and_silent_output_is_rejected(
    monkeypatch,
):
    import keyring

    monkeypatch.setattr(keyring, "get_password", lambda *args: "synthetic-key")
    g = GroqSpeech(lambda: Settings(online_voice_enabled=True))
    await g.client.aclose()
    inputs = []

    def handler(request):
        inputs.append(json.loads(request.content)["input"])
        return httpx.Response(200, content=wav_fixture())

    g.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await g.synthesize("Paris.", "groq-hannah") == wav_fixture()
    assert inputs == ["Paris."]
    await g.close()
    silent = bytearray(wav_fixture())
    silent[44:] = bytes(len(silent) - 44)
    with pytest.raises(ValueError, match="silent audio"):
        normalize_wav(bytes(silent))


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", ["none", "kokoro-af_heart"])
async def test_online_failure_uses_only_explicit_local_fallback(tmp_path, fallback):
    class Model:
        async def stream(self, messages, tools, settings):
            yield {
                "message": {
                    "content": "The capital of France is Paris. It is in Europe."
                }
            }

    class Speech:
        calls = []

        def available(self, online_enabled=False):
            return ["kokoro-af_heart"]

        async def synthesize(self, text, voice):
            self.calls.append(voice)
            if voice.startswith("groq-"):
                raise ValueError("Speech service returned silent audio")
            return wav_fixture()

    settings = Settings(
        voice="groq-hannah", online_voice_enabled=True, online_voice_fallback=fallback
    )
    store = Store(tmp_path / "db.sqlite")
    speech = Speech()
    events = []

    async def send(kind, **data):
        events.append((kind, data))

    agent = Agent(
        store, Tools(store, lambda: settings), Model(), speech, lambda: settings
    )
    await agent.turn("s", "t", "What is the capital of France?", send)
    audio = [data for kind, data in events if kind == "audio"]
    assert speech.calls.count("groq-hannah") == 1
    assert settings.voice == "groq-hannah"
    if fallback == "none":
        assert not audio
        assert speech.calls == ["groq-hannah"]
    else:
        assert audio and all(data["voice"] == fallback for data in audio)
        assert any(
            "local fallback" in data["message"]
            for kind, data in events
            if kind == "warning"
        )
    store.close()


@pytest.mark.asyncio
async def test_unconfigured_calendar_does_not_request_keychain(monkeypatch):
    from jarvis.calendar import Calendar
    import keyring

    calendar = Calendar()
    monkeypatch.setattr(calendar, "configured", lambda: False)
    monkeypatch.setattr(
        keyring, "get_password", lambda *args: pytest.fail("Unexpected Keychain read")
    )
    assert await calendar.connected() is False


@pytest.mark.asyncio
async def test_calendar_keychain_prompt_does_not_block_local_service(monkeypatch):
    import asyncio
    import threading
    import keyring
    from jarvis.calendar import Calendar
    from jarvis.credentials import Credentials

    release = threading.Event()
    calls = []

    def blocked_read(*args):
        calls.append(args)
        release.wait(2)
        return "test-refresh-token"

    cache = Credentials()
    calendar = Calendar()
    monkeypatch.setattr(calendar, "configured", lambda: True)
    monkeypatch.setattr(keyring, "get_password", blocked_read)
    monkeypatch.setattr("jarvis.calendar.credentials", cache)
    try:
        assert await asyncio.wait_for(calendar.connected(timeout=0.02), 0.3) is False
        assert await asyncio.wait_for(calendar.connected(timeout=0.02), 0.3) is False
        assert len(calls) == 1
    finally:
        release.set()
        await asyncio.gather(*cache.reads.values())
    assert await calendar.connected(timeout=0.02) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("format", ["docx", "pdf", "md"])
async def test_verified_document_idempotency_and_restart(tmp_path, monkeypatch, format):
    monkeypatch.setattr(config, "DATA", tmp_path)
    store = Store(tmp_path / "db.sqlite")
    tools = Tools(store, lambda: Settings())
    args = {
        "title": "Roadmap draft",
        "content": "# Objective\nReview the Kinetivy roadmap.\n- Keep the supplied deadline.",
        "format": format,
    }
    results = await asyncio.gather(
        *(tools.execute("create_document", args, "doc-once") for _ in range(4))
    )
    assert all(r["ok"] for r in results)
    assert len(store.all("SELECT * FROM generated_documents")) == 1
    id = results[0]["data"]["id"]
    path = document_path(store, id)
    assert path.stat().st_size > 50
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    # Windows uses inherited user-profile ACLs rather than POSIX mode bits.
    assert (
        await tools.execute("create_document", args | {"title": "Other"}, "doc-once")
    )["ok"] is False
    store.close()
    store = Store(tmp_path / "db.sqlite")
    assert document_path(store, id) == path
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        document_path(store, id)
    store.close()


@pytest.mark.asyncio
async def test_document_argument_and_boundary_rejection(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(config, "DATA", private)
    (private / "generated-documents").symlink_to(outside, target_is_directory=True)
    store = Store(private / "db.sqlite")
    tools = Tools(store, lambda: Settings())
    args = {"title": "Draft", "content": "Sensitive draft", "format": "md"}
    assert not (await tools.execute("create_document", args, "escape"))["ok"]
    assert list(outside.iterdir()) == []
    for extra in ({"format": "exe"}, {"content": []}, {"path": "/tmp/secret"}):
        assert not (await tools.execute("create_document", args | extra, "invalid"))[
            "ok"
        ]
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("voice", ["kokoro-af_heart", "groq-hannah"])
@pytest.mark.parametrize(
    "answer",
    [
        "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence.",
        "Here are the steps:\n1. Open the document.\n2. Review the title.\n3. Save the file.\n4. Close the window.",
        "A calm explanation "
        + "with enough detail to remain useful " * 18
        + "ends here.",
    ],
)
async def test_ordinary_reply_speaks_every_safe_word(tmp_path, answer, voice):
    class Model:
        async def stream(self, messages, tools, settings):
            for i in range(0, len(answer), 7):
                yield {"message": {"content": answer[i : i + 7]}}

    spoken = []

    class Speech:
        async def synthesize(self, text, voice):
            spoken.append(text)
            return wav_fixture()

    store = Store(tmp_path / "db.sqlite")
    settings = Settings(voice=voice, online_voice_enabled=voice.startswith("groq-"))
    events = []

    async def send(kind, **data):
        events.append((kind, data))

    from jarvis.agent import speakable
    import re

    await Agent(
        store, Tools(store, lambda: settings), Model(), Speech(), lambda: settings
    ).turn("complete", "one", "Explain the next steps", send)
    expected = re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer)
    assert spoken
    assert " ".join(spoken) == speakable(expected)
    assert all(len(part) <= 400 for part in spoken)
    if voice.startswith("groq-"):
        assert all(len(part) <= 180 for part in spoken)
        if len(expected) < 180:
            assert len(spoken) == 1
    assert not any(re.fullmatch(r"\d+\.", part) for part in spoken)
    assert events[-1][0] == "done"
    assert events[-1][1]["audio_count"] == len(spoken)
    store.close()


@pytest.mark.asyncio
async def test_speech_safety_limit_reports_remaining_text(tmp_path):
    class Model:
        async def stream(self, messages, tools, settings):
            yield {"message": {"content": "A complete sentence. " * 7}}

    class Speech:
        async def synthesize(self, text, voice):
            return wav_fixture()

    store = Store(tmp_path / "db.sqlite")
    settings = Settings(long_speech_sentences=6)
    events = []

    async def send(kind, **data):
        events.append((kind, data))

    await Agent(
        store, Tools(store, lambda: settings), Model(), Speech(), lambda: settings
    ).turn("limit", "one", "Explain this", send)
    assert len([e for e in events if e[0] == "audio"]) == 6
    assert any(
        kind == "warning" and "remaining text" in data["message"]
        for kind, data in events
    )
    assert events[-1][1]["text"].count("A complete sentence.") == 7
    store.close()


@pytest.mark.asyncio
async def test_cancel_during_online_clause_collection_never_emits_audio(tmp_path):
    class Model:
        async def stream(self, messages, tools, settings):
            yield {"message": {"content": "A complete sentence. " * 8}}

    calls = []

    class Speech:
        async def synthesize(self, text, voice):
            calls.append(text)
            return wav_fixture()

    store = Store(tmp_path / "db.sqlite")
    settings = Settings(voice="groq-hannah", online_voice_enabled=True)
    events = []
    started = asyncio.Event()

    async def send(kind, **data):
        events.append((kind, data))
        if kind == "delta":
            started.set()

    task = asyncio.create_task(
        Agent(
            store, Tools(store, lambda: settings), Model(), Speech(), lambda: settings
        ).turn("cancel", "one", "Explain this", send)
    )
    await started.wait()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not calls
    assert not any(kind in ("audio", "done") for kind, _ in events)
    store.close()


@pytest.mark.asyncio
async def test_long_story_is_spoken_beyond_three_sentences_and_cancelled(tmp_path):
    class Model:
        async def stream(self, messages, tools, settings):
            assert settings.response_tokens == 2048
            assert "family-friendly" in messages[0]["content"]
            for i in range(10):
                yield {
                    "message": {"content": f"The little owl found star number {i}. "}
                }

    class Speech:
        async def synthesize(self, text, voice):
            return wav_fixture()

    s = Store(tmp_path / "db.sqlite")
    settings = Settings()
    events = []

    async def send(kind, **data):
        events.append((kind, data))

    agent = Agent(s, Tools(s, lambda: settings), Model(), Speech(), lambda: settings)
    await agent.turn("story", "one", "Tell kids a long story", send)
    assert len([e for e in events if e[0] == "audio"]) == 10

    class SlowSpeech:
        async def synthesize(self, text, voice):
            await asyncio.sleep(10)
            return wav_fixture()

    agent.tts = SlowSpeech()
    events.clear()
    task = asyncio.create_task(
        agent.turn("story", "two", "Tell kids a long story", send)
    )
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(e[0] in ("audio", "done") for e in events)
    s.close()


@pytest.mark.asyncio
async def test_keychain_read_does_not_block_loop_or_duplicate(monkeypatch):
    from jarvis.providers import Compatible

    adapter = Compatible(lambda: Settings(provider="compatible"))
    reads = []

    def slow_read(api_base=None):
        reads.append(1)
        time.sleep(0.1)
        return "synthetic-key"

    monkeypatch.setattr(adapter, "credential", slow_read)
    requests = [asyncio.create_task(adapter.async_credential()) for _ in range(3)]
    ticks = 0
    while not all(t.done() for t in requests):
        await asyncio.sleep(0.01)
        ticks += 1
    assert ticks >= 4
    assert len(reads) == 1
    assert await asyncio.gather(*requests) == ["synthetic-key"] * 3
    await adapter.close()
