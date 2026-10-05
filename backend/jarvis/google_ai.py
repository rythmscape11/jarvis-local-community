"""Opt-in Google speech and cited search. Stateless REST; per-user keyring key."""

import asyncio
import base64
import json
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re
from .credentials import credentials
from .providers import credential_name
from .speech import normalize_wav
from .store import now

BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
VOICES = ("gemini-Kore", "gemini-Aoede", "gemini-Puck", "gemini-Charon")


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(
        min_length=2,
        max_length=500,
        description="Only the explicit public news/research topic; do not include private chat excerpts or account data",
    )

    @field_validator("query")
    @classmethod
    def public_topic(cls, value):
        if re.search(
            r"@|\b(password|secret|api key|access token|my email|my calendar|my account|my address|saved conversation|private memory)\b|(?:gsk_|AIza|ghp_)",
            value,
            re.I,
        ) or any(ord(c) < 32 for c in value):
            raise ValueError(
                "Search accepts public topics only; private records and credentials cannot be sent"
            )
        return value


class GoogleAI:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=5),
            trust_env=False,
            follow_redirects=False,
        )

    async def request(self, body, kind):
        key = await credentials.read(credential_name(BASE))
        if not key:
            raise ValueError(
                "Save your own Gemini key using the Google Gemini provider settings first"
            )
        with self.store.lock:
            day = now()[:10]
            profile = "google_" + kind
            rows = self.store.all(
                "SELECT count FROM connector_usage WHERE id=? AND day=?", (profile, day)
            )
            limit = 20 if kind == "voice" else 10
            if rows and rows[0]["count"] >= limit:
                raise ValueError(
                    f"Jarvis Google {kind} safety cap reached ({limit} attempts per UTC day); no automatic retry"
                )
            self.store.run(
                "INSERT INTO connector_usage VALUES(?,?,1) ON CONFLICT(id,day) DO UPDATE SET count=count+1",
                (profile, day),
            )
        async with self.client.stream(
            "POST", URL, headers={"x-goog-api-key": key}, json=body | {"store": False}
        ) as response:
            if response.status_code == 429:
                raise ValueError(
                    "Google temporarily rate-limited this request; account limits and Jarvis caps are separate"
                )
            if response.status_code != 200:
                raise ValueError(
                    f"Google {kind} unavailable (HTTP {response.status_code}); check model access, API key and account quota"
                )
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 10_000_000:
                    raise ValueError("Google response exceeded the bounded size")
        result = json.loads(data)
        if result.get("status") not in {None, "completed"}:
            raise ValueError("Google did not complete the request")
        return result

    async def synthesize(self, text, voice, style="natural"):
        if not self.settings().google_voice_enabled or voice not in VOICES:
            raise ValueError("Enable optional Google voices in Settings first")
        if not 0 < len(text) <= 800:
            raise ValueError("Google speech clause must contain 1–800 characters")
        directions = {
            "natural": "Calm, warm conversational English.",
            "story": "Warm expressive storytelling with natural pauses.",
            "poetry": "Read with gentle poetic rhythm.",
            "cheerful": "Cheerful conversational English.",
            "warm": "Warm, reassuring and composed.",
        }.get(style, "Natural conversational English.")
        body = {
            "model": self.settings().google_tts_model,
            "input": [
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": text,
                            "annotations": [
                                {"type": "speech_metadata", "style": directions}
                            ],
                        }
                    ],
                }
            ],
            "response_format": {"type": "audio", "mime_type": "audio/wav"},
            "generation_config": {"speech_config": [{"voice": voice[7:]}]},
        }
        async with self.lock:
            result = await self.request(body, "voice")
        audio = [
            b
            for step in result.get("steps", [])
            if step.get("type") == "model_output"
            for b in step.get("content", [])
            if b.get("type") == "audio"
        ]
        if not audio or not isinstance(audio[-1].get("data"), str):
            raise ValueError("Google returned no playable audio")
        return normalize_wav(base64.b64decode(audio[-1]["data"], validate=True))

    async def search(self, query):
        if not self.settings().google_search_enabled:
            raise ValueError("Enable optional Google cited search in Settings first")
        Search(query=query)
        priority = (
            "Prioritize India unless the user specifies another region. "
            if self.settings().news_priority == "india"
            else ""
        )
        result = await self.request(
            {
                "model": "gemini-2.5-flash-lite",
                "input": priority + "Find current factual reporting about: " + query,
                "system_instruction": "Use Google Search. Give up to three concise findings, distinguish reported facts from analysis, include publication dates where available. Public research only; no private account access.",
                "tools": [{"type": "google_search"}],
                "generation_config": {"max_output_tokens": 900},
            },
            "search",
        )
        blocks = [
            b
            for step in result.get("steps", [])
            if step.get("type") == "model_output"
            for b in step.get("content", [])
            if b.get("type") == "text"
        ]
        citations = []
        text = ""
        for block in blocks:
            content = block.get("text", "")
            offset = len(text)
            text += content + "\n"
            for c in block.get("annotations", []):
                if c.get("type") != "url_citation":
                    continue
                url = c.get("url", "")
                p = urlsplit(url)
                if p.scheme != "https" or not p.hostname or p.username or p.password:
                    continue
                citations.append(
                    {
                        "title": str(c.get("title", "Source"))[:200],
                        "url": url[:2000],
                        "excerpt": content[
                            max(0, int(c.get("start_index", 0))) : min(
                                len(content), int(c.get("end_index", 0))
                            )
                        ][:500],
                        "offset": offset,
                    }
                )
        if not text.strip() or not citations:
            raise ValueError(
                "Google returned no cited answer; no ungrounded news is reported as verified"
            )
        return {
            "text": text[:8000],
            "citations": citations[:12],
            "retrieved": now(),
            "provider": "Google Search through Gemini",
            "analysis_is_inference": True,
            "search_suggestions": next(
                (
                    str(row["search_suggestions"])[:20000]
                    for step in result.get("steps", [])
                    if step.get("type") == "google_search_result"
                    for row in step.get("result", [])
                    if row.get("search_suggestions")
                ),
                "",
            ),
        }

    async def close(self):
        await self.client.aclose()
