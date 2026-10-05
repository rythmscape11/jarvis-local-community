#!/usr/bin/env python3
"""Exercise a real frozen backend in disposable data; no models or credentials.

This checks packaging, HTTP protection, exports, tools and restart persistence.
It does not test inference, microphone hardware, OS permissions or an installer UI.
"""

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx


def main():
    runtime = Path(sys.argv[1]).resolve(strict=True)
    report = {
        "os": platform.platform(),
        "runtime": runtime.name,
        "inference_tested": False,
        "microphone_tested": False,
        "installer_ui_tested": False,
        "document_formats": [],
    }
    with tempfile.TemporaryDirectory(prefix="jarvis-runtime-ci-") as temporary:
        data = Path(temporary)
        (data / "settings.json").write_text(json.dumps({"news_enabled": False}))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        env = os.environ | {
            "JARVIS_DATA": str(data),
            "JARVIS_MODELS": str(data / "models"),
            "JARVIS_PORT": str(port),
            "JARVIS_WARMUP": "0",
            "JARVIS_NEWS_SCHEDULER": "0",
        }
        for restart in (False, True):
            with (data / "runtime.log").open("w") as log:
                process = subprocess.Popen(
                    [str(runtime), "--serve"], env=env, stdout=log, stderr=log
                )
                try:
                    with httpx.Client(
                        base_url=origin,
                        trust_env=False,
                        timeout=5,
                        headers={"Origin": origin},
                    ) as client:
                        for _ in range(100):
                            if process.poll() is not None:
                                raise RuntimeError(
                                    "Frozen runtime exited before readiness"
                                )
                            try:
                                if client.get("/api/ready").json().get("ready"):
                                    break
                            except (httpx.HTTPError, ValueError):
                                pass
                            time.sleep(0.2)
                        else:
                            raise RuntimeError("Frozen runtime did not become ready")
                        assert client.get("/api/records").status_code == 401
                        token = (data / "auth.token").read_text().strip()
                        response = client.post("/api/session", json={"token": token})
                        response.raise_for_status()

                        def tool(name, arguments, key):
                            response = client.post(
                                "/api/tools",
                                json={
                                    "name": name,
                                    "arguments": arguments,
                                    "key": "ci-test:" + key,
                                },
                            )
                            response.raise_for_status()
                            result = response.json()
                            assert result["ok"], result
                            return result["data"]

                        assert (
                            len(client.get("/api/automations").json()["templates"])
                            == 10
                        )
                        if not restart:
                            response = client.post(
                                "/api/automations",
                                json={
                                    "title": "CI workflow fixture",
                                    "template": "voice_document",
                                    "inputs": {"content": "Explicit synthetic text."},
                                },
                            )
                            response.raise_for_status()
                            report["workflow_id"] = response.json()["id"]
                            args = {
                                "title": "CI fixture",
                                "content": "Synthetic roadmap example",
                            }
                            first = tool("create_note", args, "note-once")
                            assert (
                                tool("create_note", args, "note-once")["id"]
                                == first["id"]
                            )
                            due = (
                                datetime.now(timezone.utc) + timedelta(days=1)
                            ).isoformat()
                            tool(
                                "create_reminder",
                                {"title": "CI fixture reminder", "datetime": due},
                                "reminder-once",
                            )
                            tool(
                                "remember_this",
                                {"key": "ci_preference", "value": "Synthetic only"},
                                "memory-once",
                            )
                            for format in ("docx", "pdf", "md", "csv", "xlsx", "pptx"):
                                item = tool(
                                    "create_document",
                                    {
                                        "title": "CI draft",
                                        "content": "A synthetic document for packaging verification.",
                                        "format": format,
                                    },
                                    "document-" + format,
                                )
                                response = client.get(
                                    f"/api/generated-documents/{item['id']}/download"
                                )
                                response.raise_for_status()
                                assert len(response.content) > 20
                                assert (
                                    hashlib.sha256(response.content).hexdigest()
                                    == item["sha256"]
                                )
                                report["document_formats"].append(format)
                            assert (
                                client.post(
                                    "/api/tools",
                                    json={
                                        "name": "create_note",
                                        "arguments": {},
                                        "key": "wrong-origin",
                                    },
                                    headers={"Origin": "https://unrelated.example"},
                                ).status_code
                                == 403
                            )
                        records = client.get("/api/records").json()
                        assert len(records["notes"]) == len(records["reminders"]) == 1
                        assert len(records["generated_documents"]) == 6
                        if restart:
                            assert len(records["memory"]) == 1
                            definitions = client.get("/api/automations").json()[
                                "workflows"
                            ]
                            assert definitions[0]["id"] == report["workflow_id"]
                            assert (
                                definitions[0]["inputs"]["content"]
                                == "Explicit synthetic text."
                            )
                            report["workflow_persistence"] = True
                            client.delete(
                                "/api/automations/" + report["workflow_id"]
                            ).raise_for_status()
                            tool("forget_this", {"key": "ci_preference"}, "forget-once")
                            assert client.get("/api/records").json()["memory"] == []
                            report["restart_persistence"] = True
                            report["memory_deletion"] = True
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
    Path("docs/ci-runtime-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
