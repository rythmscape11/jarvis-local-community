"""Isolated engine/controller regressions. No live inference in unit tests."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from jarvis.engines import KokoroSession
from jarvis.agent import requested_voice
from jarvis.config import Settings
from jarvis.local_voices import LocalVoiceWorkers, text_language, voice_languages
from jarvis.tools import VoiceChoice


def test_fractional_kokoro_speed_survives_upstream_integer_truncation():
    captured = []

    class Session:
        _model_path = "fixture"

        def get_inputs(self):
            return [SimpleNamespace(name="speed", type="tensor(float)")]

        def run(self, outputs, inputs):
            captured.append(inputs["speed"])

    adapter = KokoroSession(Session())
    adapter.requested_speed = 1 / 1.2
    adapter.run(None, {"speed": np.array([0], dtype=np.int32)})
    assert captured[0].dtype == np.float32
    assert captured[0][0] == pytest.approx(1 / 1.2)


@pytest.mark.parametrize(
    "command,name",
    [
        ("Change your voice to Heart", "Heart"),
        ("Jarvis, switch your voice to Qwen Serena", "Qwen Serena"),
        ("use Indic Aditi voice", "Indic Aditi"),
        ("Do not change your voice to Emma", None),
        ("She said change your voice to Heart", None),
        ("Can you change voices?", None),
        ("Change your voice to ../secret", None),
    ],
)
def test_only_direct_known_voice_commands_write(command, name):
    assert requested_voice(command) == name


def test_language_and_tool_validation():
    assert Settings(language="hi").language == "hi"
    with pytest.raises(ValueError):
        Settings(language="../../")
    with pytest.raises(ValueError):
        VoiceChoice(name="not-installed")
    assert text_language("নমস্কার", "en") == "bn"
    assert "bn" in voice_languages("indic-Aditi")
    assert "bn" not in voice_languages("qwen-Serena")
    assert "hi" in voice_languages("chatterbox-female")


@pytest.mark.asyncio
async def test_cancel_kills_owned_worker_and_no_stale_response(tmp_path, monkeypatch):
    from jarvis import local_voices

    worker = tmp_path / "voice_worker.py"
    worker.write_text(
        'import sys,time,json\nfor line in sys.stdin:\n r=json.loads(line);time.sleep(30);print(json.dumps({"id":r["id"],"ok":False}),flush=True)\n'
    )
    monkeypatch.setattr(local_voices, "__file__", str(tmp_path / "local_voices.py"))
    voices = LocalVoiceWorkers(lambda: Settings())
    monkeypatch.setattr(voices, "available", lambda: ["qwen-Serena"])
    monkeypatch.setattr(voices, "runtime", lambda _: Path(sys.executable))
    task = asyncio.create_task(voices.synthesize("Hello", "qwen-Serena"))
    for _ in range(100):
        if voices.process:
            break
        await asyncio.sleep(0.01)
    process = voices.process
    assert process and process.returncode is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode is not None
    assert voices.process is None
    assert voices.engine is None
    await voices.close()


@pytest.mark.asyncio
async def test_cancellation_during_startup_reaps_child(tmp_path, monkeypatch):
    from jarvis import local_voices

    worker = tmp_path / "voice_worker.py"
    worker.write_text("import time; time.sleep(30)\n")
    monkeypatch.setattr(local_voices, "__file__", str(tmp_path / "local_voices.py"))
    real_start = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    release = asyncio.Event()
    processes = []

    async def delayed_start(*args, **kwargs):
        child = await real_start(*args, **kwargs)
        processes.append(child)
        spawned.set()
        await release.wait()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_start)
    voices = LocalVoiceWorkers(lambda: Settings())
    monkeypatch.setattr(voices, "available", lambda: ["qwen-Serena"])
    monkeypatch.setattr(voices, "runtime", lambda _: Path(sys.executable))
    task = asyncio.create_task(voices.synthesize("Hello", "qwen-Serena"))
    await asyncio.wait_for(spawned.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None
    assert voices.process is None


def test_incomplete_indic_download_is_unavailable(tmp_path, monkeypatch):
    from jarvis import local_voices

    monkeypatch.setattr(local_voices, "MODELS", tmp_path)
    model = tmp_path / "indic-parler"
    (model / "description-tokenizer").mkdir(parents=True)
    for file in [
        "model.safetensors",
        "config.json",
        "description-tokenizer/tokenizer_config.json",
    ]:
        (model / file).touch()
    voices = LocalVoiceWorkers()
    monkeypatch.setattr(voices, "runtime", lambda _: Path(sys.executable))
    assert not voices.ready("indic")
