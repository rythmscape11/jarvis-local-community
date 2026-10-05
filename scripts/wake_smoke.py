import asyncio
import base64
import io
import json
import math
import re
import sys
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
    results = []
    async with httpx.AsyncClient(
        base_url=ORIGIN, trust_env=False, timeout=45
    ) as client:
        response = await client.post(
            "/api/session",
            headers={"Origin": ORIGIN},
            json={"token": (DATA / "auth.token").read_text().strip()},
        )
        response.raise_for_status()
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        async with websockets.connect(
            ORIGIN.replace("http", "ws") + "/ws",
            origin=ORIGIN,
            additional_headers={"Cookie": cookie},
            max_size=8_000_000,
        ) as ws:
            await ws.recv()
            for phrase, expected, answered in [
                ("What is the capital of France?", False, False),
                ("Hey Jarvis, what is the capital of France?", True, True),
                ("And what is the capital of Japan?", False, True),
                ("Stop listening.", False, False),
                ("What is the capital of France?", False, False),
                ("Hey Jarvis.", True, True),
                ("What is the capital of Italy?", False, True),
            ]:
                wav = await Piper().synthesize(phrase, "en_US-ljspeech-high")
                with wave.open(io.BytesIO(wav)) as f:
                    sr = f.getframerate()
                    pcm = np.frombuffer(
                        f.readframes(f.getnframes()), dtype="<i2"
                    ).astype(float)
                g = math.gcd(sr, 16000)
                samples = (
                    np.concatenate(
                        (
                            np.zeros(4000),
                            resample_poly(pcm, 16000 // g, sr // g),
                            np.zeros(20000),
                        )
                    )
                    .clip(-32768, 32767)
                    .astype("<i2")
                )
                id = str(uuid.uuid4())
                await ws.send(
                    json.dumps(
                        {
                            "type": "capture_start",
                            "turn_id": id,
                            "mode": "wake",
                            "sample_rate": 16000,
                            "encoding": "pcm_s16le",
                        }
                    )
                )
                for seq, start in enumerate(range(0, len(samples), 1024)):
                    chunk = samples[start : start + 1024]
                    if len(chunk) < 1024:
                        chunk = np.pad(chunk, (0, 1024 - len(chunk)))
                    await ws.send(
                        json.dumps(
                            {
                                "type": "audio",
                                "turn_id": id,
                                "seq": seq,
                                "audio": base64.b64encode(chunk.tobytes()).decode(),
                            }
                        )
                    )
                    await asyncio.sleep(0.03)
                detected = False
                answer = ""
                audio = 0
                metrics = {}
                transcript = ""
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 180))
                    if event.get("turn_id") != id:
                        continue
                    if event["type"] == "error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "wake_detected":
                        detected = True
                    if event["type"] == "audio":
                        audio += 1
                    if event["type"] == "transcript":
                        transcript = event["text"]
                    if event["type"] == "metrics":
                        metrics.update(event["metrics"])
                    if event["type"] == "done":
                        answer = event["text"]
                        metrics.update(event.get("metrics", {}))
                        break
                assert detected == expected, (phrase, detected)
                if not answered:
                    assert not answer and audio == 0
                if answered:
                    assert audio > 0
                city = next(
                    (
                        city
                        for country, city in [
                            ("France", "Paris"),
                            ("Japan", "Tokyo"),
                            ("Italy", "Rome"),
                        ]
                        if country in phrase
                    ),
                    None,
                )
                if answered and city:
                    assert re.search(rf"\b{city}\b", answer, re.I), (transcript, answer)
                results.append(
                    {
                        "phrase": phrase,
                        "detected": detected,
                        "followup_or_wake_answer_expected": answered,
                        "answer": answer,
                        "audio_chunks": audio,
                        "transcript": transcript,
                        "metrics": metrics,
                    }
                )
                await ws.send(json.dumps({"type": "playback_done", "turn_id": id}))
                print(json.dumps(results[-1]), flush=True)
    (ROOT / "docs/wake-followup-smoke.json").write_text(
        json.dumps(
            {
                "input": "Synthesized speech; physical owner voice unverified",
                "results": results,
            },
            indent=2,
        )
    )


asyncio.run(main())
