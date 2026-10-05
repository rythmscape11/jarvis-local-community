"""Deterministic controller/REST tests. These are not live Google inference."""

import base64
import io
import json
import wave
import httpx
import pytest
from jarvis.current_data import current_request
from jarvis.config import Settings
from jarvis.agent import Agent
from jarvis.tools import Tools
from jarvis.store import Store, now
from jarvis.news import News
from jarvis.google_ai import GoogleAI
from jarvis.credentials import credentials
from jarvis.engines import LocalSpeech


@pytest.mark.parametrize(
    "question,kind",
    [
        ("What are the latest headlines in India?", "news"),
        ("Who is the prime minister of India?", "web"),
        ("What is the current interest rate?", "web"),
        ("Search the web for current AI research", "web"),
        ("What is the capital of France?", None),
        ("What is my calendar today?", None),
        ("Create a note about latest news", None),
        ("Latest news for private@example.com", None),
        ("Your training data is from 2024", None),
    ],
)
def test_routing_excludes_private_records_and_actions(question, kind):
    assert current_request(question) == kind


@pytest.mark.asyncio
async def test_disabled_current_lookup_never_answers_from_old_model(tmp_path):
    class NeverModel:
        async def stream(self, *args):
            raise AssertionError("Must not guess current facts")
            yield

    store = Store(tmp_path / "data.db")
    cfg = Settings(google_search_enabled=False)
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(store, Tools(store, lambda: cfg), NeverModel(), None, lambda: cfg).turn(
        "s", "t", "Who is the current president of India?", send, False
    )
    done = next(b for k, b in events if k == "done")
    assert "can't verify" in done["text"] and "disabled" in done["text"]
    assert "model_ttft_ms" not in done["metrics"]
    store.close()


@pytest.mark.asyncio
async def test_current_question_retrieves_before_generation_not_old_context(tmp_path):
    store = Store(tmp_path / "data.db")
    cfg = Settings(google_search_enabled=True)
    store.conversation(
        "s", "old", "user", "Private saved context, never a search query"
    )

    class Search:
        async def search(self, query):
            assert query == "What is the latest AI research?"
            return {
                "text": "Fixture finding",
                "citations": [
                    {"title": "Primary source", "url": "https://example.org/research"}
                ],
                "retrieved": now(),
            }

    class Model:
        async def stream(self, messages, tools, settings):
            assert tools == [] and "Fixture finding" in messages[-1]["content"]
            assert "not instructions" in messages[-1]["content"]
            yield {
                "message": {"content": "The retrieved report says this is a fixture."}
            }

    tools = Tools(store, lambda: cfg)
    tools.google = Search()
    events = []

    async def send(kind, **body):
        events.append((kind, body))

    await Agent(store, tools, Model(), None, lambda: cfg).turn(
        "s", "t", "What is the latest AI research?", send, False
    )
    assert any(k == "tool" and b["status"] == "succeeded" for k, b in events)
    store.close()


@pytest.mark.asyncio
async def test_news_failure_preserves_dated_cache_and_offline_avoids_network(tmp_path):
    s = Store(tmp_path / "news.db")
    cfg = Settings(news_enabled=True)
    news = News(s, lambda: cfg)
    s.run(
        "INSERT INTO news_meta VALUES(?,?)",
        ("last_refresh", "2024-01-01T00:00:00+00:00"),
    )
    s.run(
        "INSERT INTO news VALUES(?,?,?,?,?,?,?,?)",
        (
            "a",
            "india",
            "Fixture",
            "Old story",
            "https://example.org/old",
            "2024-01-01",
            "2024-01-01",
            "Old excerpt",
        ),
    )
    calls = []

    async def fail():
        calls.append(1)
        raise ValueError("Unavailable")

    news.refresh = fail
    r = await news.current()
    assert r["items"][0]["title"] == "Old story" and r["refresh_error"]
    assert r["freshness"] == "stale_or_offline_cache"
    await news.current()
    assert len(calls) == 1  # no retry storm
    cfg.news_enabled = False
    await news.current()
    assert len(calls) == 1
    s.close()


@pytest.mark.asyncio
async def test_google_rest_citations_header_key_no_history_or_retained_interaction(
    tmp_path, monkeypatch
):
    s = Store(tmp_path / "api.db")
    cfg = Settings(google_search_enabled=True)
    ai = GoogleAI(s, lambda: cfg)

    async def key(_):
        return "fixture-not-a-real-key"

    monkeypatch.setattr(credentials, "read", key)

    def transport(r):
        body = json.loads(r.content)
        assert (
            "key=" not in str(r.url)
            and r.headers["x-goog-api-key"] == "fixture-not-a-real-key"
        )
        assert body["model"] == cfg.google_search_model
        assert body["store"] is False and body["tools"] == [{"type": "google_search"}]
        assert "Fixture public topic" in body["input"]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {
                        "type": "thought",
                        "summary": [{"type": "text", "text": "Never emit reasoning"}],
                    },
                    {
                        "type": "model_output",
                        "content": [
                            {
                                "type": "text",
                                "text": "Reported fixture",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "title": "Actual source",
                                        "url": "https://example.org/source",
                                        "start_index": 0,
                                        "end_index": 16,
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        )

    await ai.client.aclose()
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    r = await ai.search("Fixture public topic")
    assert (
        r["citations"][0]["title"] == "Actual source" and "reasoning" not in r["text"]
    )
    assert r["retrieved"]
    await ai.close()
    s.close()


@pytest.mark.asyncio
async def test_google_no_citations_and_rate_limit_fail_closed(tmp_path, monkeypatch):
    s = Store(tmp_path / "api.db")
    cfg = Settings(google_search_enabled=True)
    ai = GoogleAI(s, lambda: cfg)

    async def key(_):
        return "fixture"

    monkeypatch.setattr(credentials, "read", key)
    await ai.client.aclose()
    ai.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [{"type": "text", "text": "Uncited guess"}],
                        }
                    ]
                },
            )
        )
    )
    with pytest.raises(ValueError, match="no cited answer"):
        await ai.search("Current public topic")
    s.run(
        "INSERT OR REPLACE INTO connector_usage VALUES(?,?,?)",
        ("google_search", now()[:10], 10),
    )
    with pytest.raises(ValueError, match="safety cap"):
        await ai.search("Current public topic")
    await ai.close()
    s.close()


@pytest.mark.asyncio
async def test_google_speech_returns_complete_real_wav_contract(tmp_path, monkeypatch):
    s = Store(tmp_path / "api.db")
    cfg = Settings(google_voice_enabled=True)
    ai = GoogleAI(s, lambda: cfg)
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x10" * 2400)

    async def key(_):
        return "fixture"

    monkeypatch.setattr(credentials, "read", key)

    def transport(r):
        b = json.loads(r.content)
        assert b["response_format"]["mime_type"] == "audio/wav"
        assert b["generation_config"]["speech_config"] == [{"voice": "Kore"}]
        return httpx.Response(
            200,
            json={
                "steps": [
                    {
                        "type": "model_output",
                        "content": [
                            {
                                "type": "audio",
                                "data": base64.b64encode(wav.getvalue()).decode(),
                            }
                        ],
                    }
                ]
            },
        )

    await ai.client.aclose()
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    result = await ai.synthesize("Hello there.", "gemini-Kore")
    with wave.open(io.BytesIO(result)) as w:
        assert w.getnframes() == 2400
    await ai.close()
    s.close()


def test_google_enabled_does_not_enable_groq_or_remote_fallback(monkeypatch):
    cfg = Settings(google_voice_enabled=True, online_voice_enabled=False)
    speech = LocalSpeech(lambda: cfg)
    monkeypatch.setattr(speech.native, "available", lambda: [])
    assert "gemini-Kore" in speech.available(online_enabled=False, google_enabled=True)
    assert "groq-hannah" not in speech.available(
        online_enabled=False, google_enabled=True
    )
    assert not any(
        v.startswith(("groq-", "gemini-"))
        for v in speech.available(online_enabled=False)
    )
