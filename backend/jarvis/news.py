"""Bounded source RSS cache. No user queries leave this computer."""

import asyncio
import time
import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from defusedxml import ElementTree
from .store import now, fts_query

FEEDS = {
    "world": ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "business": ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    "technology": (
        "BBC Technology",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    ),
    "science": (
        "BBC Science",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ),
    "politics": ("Guardian Politics", "https://www.theguardian.com/politics/rss"),
    "sport": ("Guardian Sport", "https://www.theguardian.com/sport/rss"),
    "culture": ("Guardian Culture", "https://www.theguardian.com/culture/rss"),
    "india": ("Indian Express", "https://indianexpress.com/section/india/feed/"),
    "india_guardian": ("Guardian India", "https://www.theguardian.com/world/india/rss"),
}


def clean(text):
    return html.unescape(re.sub("<[^>]+>", "", text or "")).strip()


class News:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self.refresh_lock = asyncio.Lock()
        self.last_attempt = 0.0

    async def refresh(self, cancelled=lambda: False):
        async with self.refresh_lock:
            return await self._refresh(cancelled)

    async def _refresh(self, cancelled=lambda: False):
        if not self.settings().news_enabled:
            raise ValueError("Network news refresh is disabled")
        count = 0
        failures = []

        async def guard(response):
            if response.is_redirect:
                from urllib.parse import urljoin, urlparse

                target = urlparse(
                    urljoin(str(response.url), response.headers.get("location", ""))
                )
                if target.scheme != "https" or target.hostname not in {
                    "feeds.bbci.co.uk",
                    "www.theguardian.com",
                    "www.bbc.co.uk",
                    "www.bbc.com",
                    "indianexpress.com",
                    "www.indianexpress.com",
                }:
                    raise ValueError("News redirect destination is not allowed")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(4, connect=2),
            trust_env=False,
            follow_redirects=True,
            max_redirects=3,
            event_hooks={"response": [guard]},
            headers={"User-Agent": "JarvisLocal/0.1 RSS reader"},
        ) as client:
            # Fixed source URLs; model/user text never controls fetch targets.
            async def fetch(feed_id, source, url):
                nonlocal count
                category = feed_id.split("_")[0]
                if cancelled():
                    raise InterruptedError("News refresh cancelled")
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        payload = bytearray()
                        async for part in response.aiter_bytes():
                            payload.extend(part)
                            if len(payload) > 2_000_000:
                                raise ValueError("Feed exceeded 2 MB limit")
                    root = ElementTree.fromstring(bytes(payload))
                    items = root.findall(".//item")[:40]
                    for item in items:
                        title = clean(item.findtext("title"))[:300]
                        link = item.findtext("link") or ""
                        if not title or not link.startswith("https://"):
                            continue
                        date = item.findtext("pubDate") or ""
                        try:
                            published = (
                                parsedate_to_datetime(date)
                                .astimezone(timezone.utc)
                                .isoformat()
                            )
                        except (ValueError, TypeError):
                            published = date[:100]
                        excerpt = clean(item.findtext("description"))[:500]
                        id = hashlib.sha256(link.encode()).hexdigest()[:24]
                        with self.store.lock:
                            self.store.db.execute(
                                "INSERT OR REPLACE INTO news VALUES(?,?,?,?,?,?,?,?)",
                                (
                                    id,
                                    category,
                                    source,
                                    title,
                                    link,
                                    published,
                                    now(),
                                    excerpt,
                                ),
                            )
                            self.store.db.execute(
                                "DELETE FROM news_fts WHERE id=?", (id,)
                            )
                            self.store.db.execute(
                                "INSERT INTO news_fts VALUES(?,?,?)",
                                (id, title, excerpt),
                            )
                            self.store.db.commit()
                        count += 1
                except Exception as error:
                    failures.append({"source": source, "error": type(error).__name__})

            await asyncio.gather(
                *(
                    fetch(feed_id, source, url)
                    for feed_id, (source, url) in FEEDS.items()
                )
            )
        if not count:
            raise ValueError(
                "News sources unavailable; existing cached items remain usable"
            )
        self.store.run(
            "INSERT OR REPLACE INTO news_meta VALUES(?,?)", ("last_refresh", now())
        )
        # Retain a bounded set; old cache is data, never implicitly current.
        self.store.run(
            "DELETE FROM news_fts WHERE id NOT IN (SELECT id FROM news ORDER BY published DESC LIMIT 1000)"
        )
        self.store.run(
            "DELETE FROM news WHERE id NOT IN (SELECT id FROM news ORDER BY published DESC LIMIT 1000)"
        )
        return {
            "items_refreshed": count,
            "failures": failures,
            "fetched_at": now(),
            "coverage": "Selected Indian Express, BBC and Guardian RSS headlines; not exhaustive worldwide coverage",
        }

    async def current(self, query="", category="all", limit=5):
        """Refresh stale headlines on demand; failure never turns cache into live data."""
        meta = self.store.all("SELECT value FROM news_meta WHERE key='last_refresh'")
        try:
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(meta[0]["value"])
            ).total_seconds()
        except (IndexError, ValueError, TypeError):
            age = float("inf")
        refresh_error = None
        if (
            self.settings().news_enabled
            and age >= 900
            and time.monotonic() - self.last_attempt >= 60
        ):
            self.last_attempt = time.monotonic()
            try:
                await asyncio.wait_for(self.refresh(), timeout=10)
            except (ValueError, TimeoutError):
                refresh_error = (
                    "Fresh sources unavailable; showing dated cached items only"
                )
        result = self.search(query, category, limit)
        result["refresh_error"] = refresh_error
        return result

    def search(self, query="", category="all", limit=10):
        # Recency words describe ordering, not a term required in every headline.
        query = re.sub(
            r"\b(today|latest|recent|headlines|news|updates)\b", "", query, flags=re.I
        ).strip(" ,?!.")
        if query:
            rows = self.store.all(
                "SELECT n.* FROM news_fts JOIN news n ON n.id=news_fts.id WHERE news_fts MATCH ? AND (?='all' OR category=?) ORDER BY published DESC LIMIT ?",
                (fts_query(query), category, category, limit),
            )
        elif category == "all":
            # A global briefing should not be dominated by one busy sports feed.
            rows = self.store.all(
                "SELECT * FROM (SELECT news.*, row_number() OVER (PARTITION BY category ORDER BY published DESC) position FROM news) ORDER BY position, CASE category WHEN 'world' THEN 0 WHEN 'india' THEN 1 WHEN 'politics' THEN 2 WHEN 'business' THEN 3 WHEN 'technology' THEN 4 ELSE 5 END, published DESC LIMIT ?",
                (limit,),
            )
            if getattr(self.settings(), "news_priority", "india") == "india":
                # Reserve the opening two slots for India, then vary global topics.
                india = self.store.all(
                    "SELECT * FROM news WHERE category='india' ORDER BY published DESC LIMIT 2"
                )
                rows = (india + [r for r in rows if r["category"] != "india"])[:limit]
        else:
            rows = self.store.all(
                "SELECT * FROM news WHERE (?='all' OR category=?) ORDER BY published DESC LIMIT ?",
                (category, category, limit),
            )
        meta = self.store.all("SELECT value FROM news_meta WHERE key='last_refresh'")
        try:
            age = max(
                0,
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(meta[0]["value"])
                ).total_seconds(),
            )
        except (IndexError, ValueError, TypeError):
            age = None
        item_ages = []
        for row in rows:
            try:
                item_ages.append(
                    max(
                        0,
                        (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(row["fetched"])
                        ).total_seconds(),
                    )
                )
            except (ValueError, TypeError):
                item_ages.append(float("inf"))
        recent_items = bool(item_ages) and max(item_ages) < 900
        return {
            "items": rows,
            "cache_age_seconds": round(age) if age is not None else None,
            "freshness": "recent_cache"
            if recent_items and self.settings().news_enabled
            else "stale_or_offline_cache",
            "retrieved": now(),
            "last_refresh": meta[0]["value"] if meta else None,
            "network_enabled": self.settings().news_enabled,
            "priority": getattr(self.settings(), "news_priority", "india"),
            "coverage": "RSS headlines and descriptions, not full articles. Cite links and dates; label analysis as inference. Offline items may be outdated.",
        }
