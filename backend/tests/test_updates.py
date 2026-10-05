"""No user data in public release checks; mocked network, not an installation test."""

import json
import pytest
from jarvis.config import Settings
from jarvis.updates import Updates, release_status, API


def test_version_and_origin_validation():
    assert release_status({"tag_name": "v0.3.0"}, "0.2.0")["available"]
    assert not release_status({"tag_name": "v0.2.0"}, "0.2.0")["available"]
    for payload in [
        {"tag_name": "v99.0.0", "draft": True},
        {"tag_name": "v0.3.0-beta"},
        {"tag_name": "../../evil"},
        {"tag_name": {}},
        {"tag_name": "v0.3.0", "prerelease": True},
    ]:
        with pytest.raises(ValueError):
            release_status(payload)
    result = release_status(
        {"tag_name": "v0.3.0", "html_url": "https://malicious.example/secret"}
    )
    assert (
        result["url"]
        == "https://github.com/rythmscape11/jarvis-local-community/releases/tag/v0.3.0"
    )


@pytest.mark.asyncio
async def test_opt_out_offline_cache_and_privacy(tmp_path, monkeypatch):
    requests = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_bytes(self):
            yield json.dumps({"tag_name": "v9.0.0"}).encode()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            assert method == "GET" and url == API
            assert set(kwargs) == {"headers"}
            assert not any(
                k.lower() in {"authorization", "cookie"} for k in kwargs["headers"]
            )
            requests.append(url)
            return Response()

    monkeypatch.setattr("jarvis.updates.httpx.AsyncClient", Client)
    cfg = Settings(update_checks=False)
    updates = Updates(tmp_path, lambda: cfg)
    assert (await updates.check())["status"] == "disabled" and not requests
    assert (await updates.check(manual=True))["available"] and len(requests) == 1
    cfg.update_checks = True
    assert (await updates.check())["available"] and len(requests) == 1
    assert (await Updates(tmp_path, lambda: cfg).check())["available"] and len(
        requests
    ) == 1


@pytest.mark.asyncio
async def test_unavailable_metadata_does_not_break_core(tmp_path, monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            raise OSError("Offline")

    monkeypatch.setattr("jarvis.updates.httpx.AsyncClient", Client)
    updates = Updates(tmp_path, lambda: Settings())
    assert (await updates.check())["status"] == "unavailable"
    assert (await updates.check())["status"] == "unavailable"
