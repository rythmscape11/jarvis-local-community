"""Anonymous, bounded release checks. No account or conversation data leaves here."""

import asyncio
import json
import time
from pathlib import Path
import re
import httpx

VERSION = "0.3.1"
REPOSITORY = "rythmscape11/jarvis-local-community"
RELEASES = "https://github.com/" + REPOSITORY + "/releases"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"v?\d{1,4}\.\d{1,4}\.\d{1,4}", value
    ):
        raise ValueError("Invalid stable release version")
    return tuple(int(v) for v in value.lstrip("v").split("."))


def release_status(payload, current=VERSION):
    if (
        not isinstance(payload, dict)
        or payload.get("draft")
        or payload.get("prerelease")
    ):
        raise ValueError("Release is not published and stable")
    tag = payload.get("tag_name")
    newest = version_tuple(tag)
    # Construct the destination ourselves; ignore arbitrary URLs in remote metadata.
    return {
        "current_version": current,
        "latest_version": tag.lstrip("v"),
        "available": newest > version_tuple(current),
        "url": RELEASES + "/tag/" + tag,
        "status": "available" if newest > version_tuple(current) else "up_to_date",
    }


class Updates:
    def __init__(self, data: Path, settings):
        self.path = data / "release-status.json"
        self.settings = settings
        self.lock = asyncio.Lock()
        self.last = 0
        self.status = {
            "current_version": VERSION,
            "available": False,
            "url": RELEASES,
            "status": "unchecked",
        }
        try:
            saved = json.loads(self.path.read_text())
            self.last = float(saved["checked_at"])
            if self.last <= time.time() and time.time() - self.last < 86400:
                self.status = release_status(saved["release"]) | {
                    "checked_at": self.last
                }
        except (OSError, ValueError, KeyError, TypeError):
            self.last = 0

    async def check(self, manual=False):
        if not manual and not self.settings().update_checks:
            return self.status | {"status": "disabled"}
        async with self.lock:
            if not manual and time.time() - self.last < 86400:
                return self.status
            self.last = time.time()
            try:
                async with httpx.AsyncClient(
                    timeout=8, trust_env=False, follow_redirects=False
                ) as client:
                    async with client.stream(
                        "GET",
                        API,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "User-Agent": "Jarvis-Local-Release-Check",
                        },
                    ) as response:
                        if response.status_code == 404:
                            self.status = {
                                "current_version": VERSION,
                                "available": False,
                                "url": RELEASES,
                                "status": "no_release",
                                "checked_at": self.last,
                            }
                            return self.status
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 256_000:
                                raise ValueError("Release metadata too large")
                payload = json.loads(body)
                self.status = release_status(payload) | {"checked_at": self.last}
                temp = self.path.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(
                        {
                            "checked_at": self.last,
                            "release": {
                                "tag_name": payload["tag_name"],
                                "draft": False,
                                "prerelease": False,
                            },
                        }
                    )
                )
                temp.replace(self.path)
            except (httpx.HTTPError, ValueError, OSError, KeyError, TypeError):
                self.status = {
                    "current_version": VERSION,
                    "available": False,
                    "url": RELEASES,
                    "status": "unavailable",
                    "checked_at": self.last,
                }
            return self.status
