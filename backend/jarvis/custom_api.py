"""Owner-configured GET-only API reads with pinned public DNS and bounded bodies."""

import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .credentials import credentials


class APIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")
    url: str = Field(max_length=500)
    token: str = Field(default="", max_length=4000, repr=False)

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        p = urlsplit(value)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username
            or p.password
            or p.fragment
            or p.query
            or p.port not in {None, 443}
        ):
            raise ValueError(
                "Use one public HTTPS GET endpoint, without query, credentials or redirects"
            )
        if (
            "%" in p.netloc
            or p.hostname == "localhost"
            or p.hostname.endswith((".local", ".localhost"))
        ):
            raise ValueError("Local endpoints are not allowed")
        return value


class APIRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")


async def public_address(host):
    records = await asyncio.to_thread(
        socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM
    )
    addresses = sorted({r[4][0] for r in records})
    if not addresses or any(not ipaddress.ip_address(v).is_global for v in addresses):
        raise ValueError("API DNS resolved to a non-public address")
    return addresses[0]


async def read_api(connectors, name):
    APIRead(name=name)
    profile = "api:" + name
    rows = connectors.store.all("SELECT config FROM connectors WHERE id=?", (profile,))
    if not rows:
        raise ValueError("Named API not configured")
    saved = json.loads(rows[0]["config"])
    selected = APIConfig.model_validate(
        {k: v for k, v in saved.items() if k != "has_token"}
    )
    parsed = urlsplit(selected.url)
    address = await public_address(parsed.hostname)
    connectors.budget(profile)
    headers = {"Host": parsed.hostname, "Accept": "application/json"}
    token = (
        await credentials.read("connector:" + profile)
        if json.loads(rows[0]["config"]).get("has_token")
        else ""
    )
    if saved.get("has_token") and not token:
        raise ValueError("Named API credential missing; reconnect")
    if token:
        headers["Authorization"] = "Bearer " + token
    # Pin the connection to the vetted IP, while preserving TLS SNI/certificate verification.
    authority = "[" + address + "]" if ":" in address else address
    async with httpx.AsyncClient(
        timeout=15, trust_env=False, follow_redirects=False
    ) as http:
        async with http.stream(
            "GET",
            "https://" + authority + (parsed.path or "/"),
            headers=headers,
            extensions={"sni_hostname": parsed.hostname},
        ) as response:
            if response.status_code != 200:
                raise ValueError(
                    f"Named API failed (HTTP {response.status_code}); redirects are denied"
                )
            if "json" not in response.headers.get("content-type", ""):
                raise ValueError("Named API must return JSON")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 262144:
                    raise ValueError("Named API response exceeds 256 KB")
    result = json.loads(body)
    return {"name": name, "source": selected.url, "data": result}
