#!/usr/bin/env python3
"""Live inference test using synthesized speech, never claiming physical mic evidence."""

import asyncio
import base64
import io
import json
import math
import sys
import time
import uuid
import wave
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from jarvis.engines import Piper
from jarvis.config import ORIGIN, DATA


async def main():
    report = {
        "input": "Piper synthesized speech, not a physical microphone",
        "hardware": "Apple M5 MacBook Pro, 24 GB",
        "model": "configured at runtime",
        "stt": "whisper.cpp v1.8.3 multilingual small Metal",
        "tts": "configured at runtime",
        "context_tokens": "configured at runtime",
        "turns": [],
    }
    async with httpx.AsyncClient(base_url=ORIGIN, trust_env=False) as client:
        response = await client.post(
            "/api/session",
            headers={"Origin": ORIGIN},
            json={"token": (DATA / "auth.token").read_text().strip()},
        )
        response.raise_for_status()
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        report["health"] = (await client.get("/api/health")).json()
        active = report["health"]["settings"]
        report.update(model=active["model"], tts=active["voice"], context_tokens=active["context_tokens"])
        assert active["provider"] == "ollama", "This smoke test exercises native inference only"
        async with websockets.connect(
            ORIGIN.replace("http", "ws") + "/ws",
            origin=ORIGIN,
            additional_headers={"Cookie": cookie},
            max_size=8_000_000,
        ) as ws:
            await ws.recv()

            async def turn(text, voice_input=False):
                id = str(uuid.uuid4())
                started = time.perf_counter()
                result = {
                    "request": text,
                    "voice_input": voice_input,
                    "tools": [],
                    "audio_chunks": 0,
                }
                audio = []
                response_started = started
                if voice_input:
                    wav = await Piper().synthesize(text, "en_US-ljspeech-high")
                    with wave.open(io.BytesIO(wav)) as f:
                        pcm = np.frombuffer(
                            f.readframes(f.getnframes()), dtype="<i2"
                        ).astype(float)
                        rate = f.getframerate()
                    g = math.gcd(rate, 16000)
                    samples = (
                        resample_poly(pcm, 16000 // g, rate // g)
                        .clip(-32768, 32767)
                        .astype("<i2")
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "type": "capture_start",
                                "turn_id": id,
                                "mode": "ptt",
                                "sample_rate": 16000,
                                "encoding": "pcm_s16le",
                            }
                        )
                    )
                    for seq, start in enumerate(range(0, len(samples), 1024)):
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "audio",
                                    "turn_id": id,
                                    "seq": seq,
                                    "audio": base64.b64encode(
                                        samples[start : start + 1024].tobytes()
                                    ).decode(),
                                }
                            )
                        )
                        await asyncio.sleep(0.015)
                    response_started = time.perf_counter()
                    await ws.send(json.dumps({"type": "capture_stop", "turn_id": id}))
                else:
                    await ws.send(
                        json.dumps(
                            {"type": "text", "turn_id": id, "text": text, "voice": True}
                        )
                    )
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 180))
                    if event.get("turn_id") != id:
                        continue
                    if event["type"] == "error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "transcript":
                        result["transcript"] = event["text"]
                    if event["type"] == "tool" and event["status"] != "running":
                        result["tools"].append(event)
                    if event["type"] == "audio":
                        blob = base64.b64decode(event["audio"])
                        audio.append(blob)
                        if len(audio) == 1:
                            result["first_audio_after_input_ms"] = round((time.perf_counter() - response_started) * 1000, 1)
                        with wave.open(io.BytesIO(blob)) as f:
                            assert f.getnframes() > 0
                        result["audio_chunks"] += 1
                    if event["type"] == "metrics":
                        result.update(event["metrics"])
                    if event["type"] == "done":
                        result["answer"] = event["text"]
                        result.update(event["metrics"])
                        break
                result["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
                await ws.send(json.dumps({"type": "playback_done", "turn_id": id}))
                if audio and not (ROOT / "docs/current-answer.wav").exists():
                    (ROOT / "docs/current-answer.wav").write_bytes(audio[0])
                report["turns"].append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                (ROOT / "docs/current-live-smoke.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )

            await turn("What is the capital of France?", True)
            await turn(
                "Create a reminder tomorrow at 10 AM to review the Kinetivy roadmap."
            )
            await turn(
                "Create a note titled Smoke test with the content: Kinetivy roadmap has three priorities."
            )
            await turn("Search notes for Kinetivy.")
        report["records"] = (await client.get("/api/records")).json()
    (ROOT / "docs/current-live-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())
