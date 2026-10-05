import pytest
from jarvis.config import Settings
from jarvis.store import Store
from jarvis.tools import Tools


@pytest.mark.asyncio
async def test_settings_validate_persist_verify_and_deny_security_changes(tmp_path):
    s = Store(tmp_path / "db")
    current = Settings()
    t = Tools(s, lambda: current)

    def save(updated):
        nonlocal current
        current = updated

    t.on_settings_change = save
    result = await t.execute(
        "update_settings",
        {"language": "hi", "voice_pace": 1.2, "news_priority": "india"},
        "set",
    )
    assert result["ok"] and current.language == "hi" and current.voice_pace == 1.2
    assert (
        await t.execute(
            "update_settings",
            {"language": "hi", "voice_pace": 1.2, "news_priority": "india"},
            "set",
        )
        == result
    )
    for i, changes in enumerate(
        [
            {},
            {"language": "unknown"},
            {"voice_pace": 0},
            {"timezone": "not/a/zone"},
            {"computer_control": True},
            {"api_base": "https://example.org"},
            {"provider": "compatible"},
            {"model": "missing"},
        ]
    ):
        assert not (await t.execute("update_settings", changes, f"bad-{i}"))["ok"]
    assert current.language == "hi"
    s.close()
