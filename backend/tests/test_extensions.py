import json
import pytest
import httpx
from jarvis.config import Settings
from jarvis.store import Store
from jarvis.control import Control, SystemAction
from jarvis.providers import Compatible, validate_endpoint
from jarvis.news import News


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "extensions.sqlite")
    yield s
    s.close()


def test_provider_endpoints_and_opt_in():
    assert Settings().provider == "ollama"
    assert validate_endpoint("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    assert validate_endpoint("https://example.com/v1") == "https://example.com/v1"
    for url in [
        "http://example.com",
        "https://user:secret@example.com/v1",
        "https://169.254.169.254/v1",
        "file:///private/key",
    ]:
        with pytest.raises(ValueError):
            validate_endpoint(url)


@pytest.mark.asyncio
async def test_compatible_sse_and_tool_fragment_validation(monkeypatch):
    settings = Settings(
        provider="compatible", model="local/test", api_base="http://127.0.0.1:1234/v1"
    )
    adapter = Compatible(lambda: settings)
    monkeypatch.setattr(adapter, "credential", lambda api_base=None: "")
    packets = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "create_note",
                                    "arguments": '{"title":"Test",',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '"content":"Validated"}'},
                            }
                        ]
                    }
                }
            ]
        },
    ]
    payload = "\n".join("data: " + json.dumps(p) for p in packets) + "\ndata: [DONE]\n"

    async def handle(request):
        body = json.loads(request.content)
        assert body["model"] == "local/test"
        assert body["stream"] is True
        return httpx.Response(
            200, text=payload, headers={"content-type": "text/event-stream"}
        )

    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    events = [
        e
        async for e in adapter.stream(
            [{"role": "user", "content": "Save a note"}], [], settings
        )
    ]
    assert (
        events[0]["message"]["tool_calls"][0]["function"]["arguments"]["content"]
        == "Validated"
    )
    await adapter.close()


@pytest.mark.asyncio
async def test_model_service_error_is_not_a_success(monkeypatch):
    settings = Settings(provider="compatible")
    adapter = Compatible(lambda: settings)
    monkeypatch.setattr(adapter, "credential", lambda api_base=None: "")
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    with pytest.raises(httpx.HTTPStatusError):
        async for event in adapter.stream(
            [{"role": "user", "content": "hello"}], [], settings
        ):
            pass
    await adapter.close()


@pytest.mark.asyncio
async def test_system_actions_require_enable_approval_and_do_not_replay(
    store, monkeypatch
):
    settings = Settings()
    control = Control(store, lambda: settings)
    action = SystemAction(
        action="hotkey",
        application="TextEdit",
        purpose="Select existing text",
        keys=["command", "a"],
    )
    with pytest.raises(ValueError):
        control.propose(action)
    settings.computer_control = True
    request = control.propose(action)
    calls = []
    monkeypatch.setattr(
        control,
        "execute",
        lambda action: calls.append(action) or {"ok": True, "state": "input_delivered"},
    )
    assert not calls
    result = await control.approve(request["request_id"], False)
    assert result["state"] == "rejected"
    assert not calls
    with pytest.raises(ValueError):
        await control.approve(request["request_id"], True)
    request = control.propose(action)
    result = await control.approve(request["request_id"], True)
    assert result["ok"]
    assert len(calls) == 1
    with pytest.raises(ValueError):
        await control.approve(request["request_id"], True)
    pending = control.propose(action)
    Control(store, lambda: settings)
    assert (
        store.all(
            "SELECT state FROM control_requests WHERE id=?", (pending["request_id"],)
        )[0]["state"]
        == "expired"
    )


def test_system_argument_constraints():
    for data in [
        {"action": "shell", "application": "TextEdit", "purpose": "Bad"},
        {
            "action": "hotkey",
            "application": "TextEdit",
            "purpose": "Bad",
            "keys": ["powershell.exe"],
        },
        {"action": "click", "application": "Terminal", "purpose": "Bad"},
    ]:
        with pytest.raises(ValueError):
            SystemAction.model_validate(data)


def test_cached_news_are_labelled_and_never_current_without_dates(store):
    news = News(store, lambda: Settings(news_enabled=False))
    assert news.search()["last_refresh"] is None
    store.run(
        "INSERT INTO news VALUES(?,?,?,?,?,?,?,?)",
        (
            "id",
            "world",
            "Fixture Source",
            "Synthetic headline",
            "https://example.com/article",
            "2000-01-01",
            "2000-01-02",
            "Fixture excerpt",
        ),
    )
    store.run(
        "INSERT INTO news_fts VALUES(?,?,?)",
        ("id", "Synthetic headline", "Fixture excerpt"),
    )
    result = news.search("Synthetic")
    assert result["network_enabled"] is False
    assert result["items"][0]["published"] == "2000-01-01"
    assert "outdated" in result["coverage"]


@pytest.mark.asyncio
async def test_news_offline_refresh_preserves_cache(store):
    news = News(store, lambda: Settings(news_enabled=False))
    with pytest.raises(ValueError):
        await news.refresh()
    assert news.search()["items"] == []


@pytest.mark.asyncio
async def test_groq_voice_request_hides_reasoning_and_handles_limits(monkeypatch):
    settings = Settings(
        provider="compatible",
        api_base="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-20b",
    )
    adapter = Compatible(lambda: settings)
    monkeypatch.setattr(adapter, "credential", lambda api_base=None: "synthetic-key")
    await adapter.client.aclose()

    def handle(request):
        body = json.loads(request.content)
        assert body["include_reasoning"] is False
        assert body["reasoning_effort"] == "low"
        assert body["max_completion_tokens"] == 1024
        assert "max_tokens" not in body
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"reasoning":"private","content":"Hello."}}]}\n\ndata: [DONE]\n',
        )

    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    events = [
        e
        async for e in adapter.stream(
            [{"role": "user", "content": "Hello"}], [], settings
        )
    ]
    assert events == [{"message": {"content": "Hello."}}]
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429))
    )
    with pytest.raises(ValueError, match="rate limit"):
        async for _ in adapter.stream(
            [{"role": "user", "content": "Hello"}], [], settings
        ):
            pass
    await adapter.close()


def test_credentials_are_scoped_to_exact_provider_endpoint():
    from jarvis.providers import credential_name

    assert credential_name("https://api.groq.com/openai/v1/") == credential_name(
        "https://api.groq.com/openai/v1"
    )
    assert credential_name("https://api.groq.com/openai/v1") != credential_name(
        "https://example.com/v1"
    )
