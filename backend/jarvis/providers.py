"""Explicit opt-in OpenAI-compatible provider. Credentials stay in OS keychain."""

import json
import asyncio
import random
from contextlib import asynccontextmanager
import hashlib
import ipaddress
from urllib.parse import urlparse
import httpx
from .engines import Ollama
from .credentials import credentials


def validate_endpoint(url):
    parsed = urlparse(url)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
    ):
        raise ValueError(
            "Use an API base URL without embedded credentials, queries or fragments"
        )
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.scheme == "http":
        return url.rstrip("/")
    if parsed.scheme != "https":
        raise ValueError(
            "Remote provider endpoints require HTTPS; HTTP is allowed only on loopback"
        )
    try:
        address = ipaddress.ip_address(parsed.hostname)
        if not address.is_global:
            raise ValueError(
                "Non-loopback private/link-local IP endpoints are not supported"
            )
    except ValueError as error:
        if "not supported" in str(error):
            raise
    return url.rstrip("/")


def credential_name(api_base):
    normalized = validate_endpoint(api_base)
    return "model-provider:" + hashlib.sha256(normalized.encode()).hexdigest()


def inference_error(error):
    """Provider bodies may contain private prompts; expose only known error categories."""
    code = error.get("code") if isinstance(error, dict) else None
    code = code if isinstance(code, str) else None
    return {
        "tool_use_failed": "The model couldn't form a valid tool request. Check tool activity for earlier actions, then rephrase your request.",
        "context_length_exceeded": "This discussion exceeds the selected model's context limit. Start a new chat or reduce its context in Settings.",
        "rate_limit_exceeded": "The model is temporarily rate-limited. Wait and retry, or select local Ollama in Settings.",
        "model_decommissioned": "The selected model is no longer available. Choose another model in Settings.",
    }.get(
        code,
        "The provider couldn't finish this reply. Check tool activity before retrying; try another model if it persists.",
    )


class Compatible:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=5),
            trust_env=False,
            follow_redirects=False,
        )

    def credential(self, api_base=None):
        import keyring

        return (
            keyring.get_password(
                "Jarvis Local", credential_name(api_base or self.settings().api_base)
            )
            or ""
        )

    async def async_credential(self, api_base=None):
        endpoint = validate_endpoint(api_base or self.settings().api_base)
        return await credentials.read(
            credential_name(endpoint), lambda: self.credential(endpoint)
        )

    async def available(self):
        settings = self.settings()
        url = validate_endpoint(settings.api_base)
        key = await self.async_credential(url)
        response = await self.client.get(
            url + "/models", headers={"Authorization": "Bearer " + key} if key else {}
        )
        response.raise_for_status()
        return [row["id"] for row in response.json().get("data", [])]

    async def stream(self, messages, tools, settings):
        url = validate_endpoint(settings.api_base)
        key = await self.async_credential(url)
        messages = json.loads(json.dumps(messages))
        messages = [
            {
                k: v
                for k, v in m.items()
                if k in {"role", "content", "tool_calls", "tool_call_id"}
            }
            for m in messages
        ]
        # Ollama-style function results are converted to the compatible tool-call protocol.
        last_calls = []
        for index, message in enumerate(messages):
            if message.get("tool_calls"):
                for number, call in enumerate(message["tool_calls"]):
                    call["id"] = call.get("id", f"call_{index}_{number}")
                    call["type"] = "function"
                    function = call["function"]
                    if not isinstance(function["arguments"], str):
                        function["arguments"] = json.dumps(function["arguments"])
                last_calls = list(message["tool_calls"])
            elif message["role"] == "tool":
                if last_calls:
                    message["tool_call_id"] = last_calls.pop(0)["id"]
        body = {
            "model": settings.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.3,
            "max_tokens": settings.response_tokens,
        }
        if urlparse(url).hostname == "api.groq.com":
            if not key:
                raise ValueError(
                    "Groq is not connected. Add your API key in Settings first."
                )
            if settings.model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
                body.pop("max_tokens")
                body.update(
                    max_completion_tokens=max(1024, settings.response_tokens),
                    reasoning_effort="low",
                    include_reasoning=False,
                )
        if urlparse(url).hostname == "generativelanguage.googleapis.com":
            if not key:
                raise ValueError(
                    "Gemini is not connected. Add your Google AI Studio key in Settings."
                )
            body["reasoning_effort"] = (
                "none"
                if settings.model.startswith("gemini-2.5")
                and "pro" not in settings.model
                else "minimal"
            )
        if tools:
            body["tools"] = tools
        calls = {}
        async with self.completion_response(url, key, body) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                event = json.loads(value)
                if "error" in event:
                    raise ValueError(inference_error(event["error"]))
                choices = event.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    yield {"message": {"content": delta["content"]}}
                for item in delta.get("tool_calls", []):
                    call = calls.setdefault(
                        item["index"],
                        {
                            "id": item.get("id", ""),
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if item.get("extra_content"):
                        call["extra_content"] = item["extra_content"]
                    if item.get("id"):
                        call["id"] = item["id"]
                    function = item.get("function", {})
                    call["function"]["name"] += function.get("name", "")
                    call["function"]["arguments"] += function.get("arguments", "")
                    if len(call["function"]["arguments"]) > 24000:
                        raise ValueError("Provider tool arguments exceed size limit")
            if calls:
                parsed = []
                for call in calls.values():
                    call["function"]["arguments"] = json.loads(
                        call["function"]["arguments"] or "{}"
                    )
                    parsed.append(call)
                yield {"message": {"tool_calls": parsed}}

    @asynccontextmanager
    async def completion_response(self, url, key, body):
        """Retry a rejected transient request once; never replay a partial stream."""
        label = {
            "generativelanguage.googleapis.com": "Gemini",
            "api.groq.com": "Groq",
        }.get(urlparse(url).hostname, "The selected provider")
        try:
            for attempt in range(2):
                async with self.client.stream(
                    "POST",
                    url + "/chat/completions",
                    json=body,
                    headers={"Authorization": "Bearer " + key} if key else {},
                ) as response:
                    transient = response.status_code in {500, 502, 503, 504}
                    if transient and attempt == 0:
                        # No response tokens or tool calls were accepted. Close the
                        # failed response before this cancellable, bounded delay.
                        pass
                    else:
                        if response.status_code == 429:
                            raise ValueError(
                                f"{label} rate limit reached. Wait and retry, or choose local Ollama in Settings. No tools were replayed."
                            )
                        if response.status_code in {401, 403}:
                            raise ValueError(
                                "API authentication failed. Check the key and model access in Settings."
                            )
                        if transient:
                            raise ValueError(
                                f"{label} is temporarily unavailable (HTTP {response.status_code}). Try again shortly or choose another model in Settings. Check tool activity before repeating an action."
                            )
                        if response.status_code >= 300:
                            raise ValueError(
                                f"{label} rejected the request (HTTP {response.status_code}). Check the model and connection in Settings."
                            )
                        yield response
                        return
                await asyncio.sleep(1 + random.uniform(0, 0.25))
        except httpx.TimeoutException as error:
            raise ValueError(
                f"{label} timed out. Check tool activity before retrying; choose local Ollama for offline use."
            ) from error
        except httpx.HTTPError as error:
            raise ValueError(
                f"{label} connection was interrupted. No partial reply was replayed. Check tool activity before retrying."
            ) from error

    async def close(self):
        await self.client.aclose()


class ModelRouter:
    def __init__(self, settings):
        self.settings = settings
        self.ollama = Ollama()
        self.compatible = Compatible(settings)

    @property
    def current(self):
        return self.ollama if self.settings().provider == "ollama" else self.compatible

    async def available(self):
        return await self.current.available()

    def stream(self, messages, tools, settings):
        adapter = self.ollama if settings.provider == "ollama" else self.compatible
        return adapter.stream(messages, tools, settings)

    async def close(self):
        await self.ollama.close()
        await self.compatible.close()
