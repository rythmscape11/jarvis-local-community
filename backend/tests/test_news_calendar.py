import json
import os
from jarvis.calendar import Calendar
from jarvis.news import News
from jarvis.store import Store
from jarvis.config import Settings


def test_recency_words_and_india_priority(tmp_path):
    store = Store(tmp_path / "news.db")
    for n, category in enumerate(
        ["sport", "world", "india", "india", "business", "politics"]
    ):
        store.run(
            "INSERT INTO news VALUES(?,?,?,?,?,?,?,?)",
            (
                str(n),
                category,
                "Fixture publisher",
                "Fixture headline " + str(n),
                "https://example.com/" + str(n),
                f"2026-10-04T12:0{n}:00+00:00",
                "2026-10-04T13:00:00+00:00",
                "Synthetic fixture",
            ),
        )
        store.run(
            "INSERT INTO news_fts VALUES(?,?,?)",
            (str(n), "Fixture headline " + str(n), "Synthetic fixture"),
        )
    news = News(store, lambda: Settings())
    result = news.search("latest news today", limit=5)
    assert len(result["items"]) == 5
    assert [r["category"] for r in result["items"][:2]] == ["india", "india"]
    assert result["priority"] == "india"
    assert news.search("nonexistentword")["items"] == []
    store.close()


def test_calendar_prerequisite_and_safe_import(tmp_path, monkeypatch):
    from jarvis import calendar as module

    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.delenv("GOOGLE_CLIENT_FILE", raising=False)
    connector = Calendar()
    assert not connector.configured()
    source = tmp_path / "client.json"
    source.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "synthetic.apps.googleusercontent.com",
                    "client_secret": "fixture-only",
                    "irrelevant": "not retained",
                }
            }
        )
    )
    assert connector.configure(str(source))["configured"]
    assert connector.configured()
    assert "irrelevant" not in connector.client()
    assert "code_challenge=" in connector.begin()
    # Windows reports synthetic mode bits; NTFS access uses profile ACLs.
    if os.name != "nt":
        assert (tmp_path / "calendar-client.json").stat().st_mode & 0o777 == 0o600
