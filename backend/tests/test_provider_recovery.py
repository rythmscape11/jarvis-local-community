"""Substituted HTTP failures, not live Gemini service availability."""

import asyncio
import httpx
import pytest
from jarvis.config import Settings
from jarvis.providers import Compatible


def adapter(monkeypatch, handle):
    cfg = Settings(
        provider="compatible",
        api_base="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-3.1-flash-lite",
    )
    value = Compatible(lambda: cfg)

    async def key(*args):
        return "fixture-key"

    monkeypatch.setattr(value, "async_credential", key)
    value.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return value, cfg


@pytest.mark.asyncio
async def test_rejected_server_request_retries_once_without_partial_output(monkeypatch):
    calls = []

    async def pause(delay):
        assert 1 <= delay <= 1.25

    monkeypatch.setattr("jarvis.providers.asyncio.sleep", pause)

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, text="private provider response")
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"Recovered."}}]}\ndata: [DONE]\n',
        )

    value, cfg = adapter(monkeypatch, handle)
    result = [
        p async for p in value.stream([{"role": "user", "content": "hello"}], [], cfg)
    ]
    assert len(calls) == 2 and result == [{"message": {"content": "Recovered."}}]
    await value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,attempts", [(503, 2), (500, 2), (429, 1), (403, 1), (404, 1)]
)
async def test_errors_are_bounded_and_hide_raw_http_details(
    monkeypatch, status, attempts
):
    calls = []

    async def pause(_):
        pass

    monkeypatch.setattr("jarvis.providers.asyncio.sleep", pause)

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="private prompt and credential")

    value, cfg = adapter(monkeypatch, handle)
    with pytest.raises(ValueError) as error:
        async for _ in value.stream([], [], cfg):
            pass
    assert len(calls) == attempts
    assert "https://" not in str(error.value) and "private" not in str(error.value)
    await value.close()


@pytest.mark.asyncio
async def test_cancellation_during_backoff_does_not_restart_request(monkeypatch):
    waiting = asyncio.Event()

    async def pause(_):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("jarvis.providers.asyncio.sleep", pause)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503)

    value, cfg = adapter(monkeypatch, handle)

    async def collect():
        return [p async for p in value.stream([], [], cfg)]

    task = asyncio.create_task(collect())
    await asyncio.wait_for(waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1
    await value.close()


@pytest.mark.asyncio
async def test_partial_stream_disconnect_never_replays(monkeypatch):
    calls = []

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Partial"}}]}\n'
            raise httpx.ReadError("private body")

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=Broken())

    value, cfg = adapter(monkeypatch, handle)
    seen = []
    with pytest.raises(ValueError, match="No partial reply was replayed"):
        async for packet in value.stream([], [], cfg):
            seen.append(packet)
    assert len(calls) == 1 and len(seen) == 1
    await value.close()


def test_bundled_timezone_works_without_os_database(monkeypatch):
    import os
    import subprocess
    import sys

    env = os.environ | {"PYTHONTZPATH": ""}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from zoneinfo import ZoneInfo; from datetime import datetime; assert datetime(2026,10,6,10,tzinfo=ZoneInfo('Asia/Kolkata')).isoformat() == '2026-10-06T10:00:00+05:30'",
        ],
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
