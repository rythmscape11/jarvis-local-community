import asyncio
import time
import pytest
import httpx
from jarvis.credentials import Credentials
from jarvis.providers import Compatible
from jarvis.speech import GroqSpeech
from jarvis.config import Settings
from test_documents_speech import wav_fixture


@pytest.mark.asyncio
async def test_model_and_speech_share_approved_key_without_reprompt(monkeypatch):
    import keyring

    reads = []
    monkeypatch.setattr(
        keyring, "get_password", lambda *args: reads.append(args) or "synthetic-key"
    )
    settings = Settings(
        provider="compatible",
        api_base="https://api.groq.com/openai/v1",
        online_voice_enabled=True,
    )
    model = Compatible(lambda: settings)
    speech = GroqSpeech(lambda: settings)
    await speech.client.aclose()
    speech.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=wav_fixture())
        )
    )
    assert await model.async_credential() == "synthetic-key"
    assert await speech.synthesize("A complete conversational sentence.", "groq-hannah")
    assert await model.async_credential() == "synthetic-key"
    assert len(reads) == 1
    await model.close()
    await speech.close()


@pytest.mark.asyncio
async def test_rejected_keychain_does_not_repeat_until_explicit_retry():
    manager = Credentials()
    reads = []

    def denied():
        reads.append(1)
        raise RuntimeError("synthetic denial")

    for _ in range(3):
        with pytest.raises(ValueError, match="wasn't approved"):
            await manager.read("account", denied)
    assert len(reads) == 1
    manager.invalidate("account")
    with pytest.raises(ValueError):
        await manager.read("account", denied)
    assert len(reads) == 2


@pytest.mark.asyncio
async def test_endpoint_changes_cannot_forward_old_credentials(monkeypatch):
    settings = Settings(provider="compatible", api_base="https://first.example/v1")
    model = Compatible(lambda: settings)

    def read(endpoint=None):
        time.sleep(0.04)
        return "key-for:" + endpoint

    monkeypatch.setattr(model, "credential", read)
    first = asyncio.create_task(model.async_credential())
    await asyncio.sleep(0.01)
    settings.api_base = "https://second.example/v1"
    second = asyncio.create_task(model.async_credential())
    assert await first == "key-for:https://first.example/v1"
    assert await second == "key-for:https://second.example/v1"
    await model.close()


@pytest.mark.asyncio
async def test_timeout_and_cancellation_keep_one_pending_os_read():
    manager = Credentials()
    reads = []

    def slow():
        reads.append(1)
        time.sleep(0.08)
        return "synthetic-key"

    with pytest.raises(ValueError, match="Approve"):
        await manager.read("account", slow, timeout=0.01)
    manager.retry("account")
    task = asyncio.create_task(manager.read("account", slow))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await manager.read("account", slow) == "synthetic-key"
    assert len(reads) == 1


@pytest.mark.asyncio
async def test_removing_key_invalidates_inflight_results():
    manager = Credentials()

    def slow():
        time.sleep(0.04)
        return "synthetic-old-key"

    task = asyncio.create_task(manager.read("account", slow))
    await asyncio.sleep(0.01)
    manager.invalidate("account")
    with pytest.raises(ValueError, match="changed"):
        await task
    assert await manager.read("account", lambda: "") == ""
