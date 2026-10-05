"""JSON-lines worker: local models only; no credentials, raw audio or text logs."""

import base64
import contextlib
import io
import json
import sys
from pathlib import Path


def main():
    # The adjacent calendar.py must not shadow Python standard library calendar.
    if sys.path and Path(sys.path[0]).resolve() == Path(__file__).parent.resolve():
        sys.path.pop(0)
    engine, root = sys.argv[1], Path(sys.argv[2]).resolve()
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import soundfile as sf

        if engine in {"qwen", "chatterbox"}:
            if engine == "chatterbox":
                # mlx-audio's hook requests this fixed auxiliary repository. Resolve
                # only that dependency to its pinned local copy, never to the network.
                import huggingface_hub

                def local_snapshot(repo_id, **kwargs):
                    if repo_id != "mlx-community/S3TokenizerV2":
                        raise ValueError("Unexpected model dependency")
                    return str(root / "s3-tokenizer")

                huggingface_hub.snapshot_download = local_snapshot
            from mlx_audio.tts.utils import load_model

            model = load_model(
                root / ("qwen-tts" if engine == "qwen" else "chatterbox")
            )
        elif engine == "indic":
            import torch
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer

            torch.set_num_threads(4)
            # CPU is the supported baseline. Do not assume CUDA or MPS compatibility.
            model = ParlerTTSForConditionalGeneration.from_pretrained(
                root / "indic-parler", local_files_only=True
            ).to("cpu")
            tokenizer = AutoTokenizer.from_pretrained(
                root / "indic-parler", local_files_only=True
            )
            description = AutoTokenizer.from_pretrained(
                root / "indic-parler/description-tokenizer", local_files_only=True
            )
        else:
            raise ValueError("Unknown voice engine")
    for line in sys.stdin:
        request = {}
        try:
            if len(line.encode()) > 8192:
                raise ValueError("Request too large")
            request = json.loads(line)
            text, voice = request["text"], request["voice"]
            if not isinstance(text, str) or not 1 <= len(text) <= 800:
                raise ValueError("Invalid speech text")
            style = request.get("style", "natural")
            direction = {
                "natural": "Speak calmly, warmly and conversationally.",
                "story": "Tell the story warmly with expressive but natural pacing.",
                "poetry": "Recite the poem with gentle expression and natural pauses.",
            }.get(style, "Speak warmly and naturally.")
            with contextlib.redirect_stdout(sys.stderr):
                if engine == "qwen":
                    names = {
                        "en": "English",
                        "zh": "Chinese",
                        "ja": "Japanese",
                        "ko": "Korean",
                        "de": "German",
                        "fr": "French",
                        "ru": "Russian",
                        "pt": "Portuguese",
                        "es": "Spanish",
                        "it": "Italian",
                    }
                    results = model.generate_custom_voice(
                        text,
                        speaker=voice.removeprefix("qwen-"),
                        language=names[request["language"]],
                        instruct=direction,
                        max_tokens=2048,
                        verbose=False,
                    )
                    chunks = list(results)
                    audio, rate = (
                        np.concatenate(
                            [np.asarray(r.audio).reshape(-1) for r in chunks]
                        ),
                        chunks[0].sample_rate,
                    )
                elif engine == "chatterbox":
                    speaker = voice.removeprefix("chatterbox-")
                    if speaker not in {"female", "male"}:
                        raise ValueError("Invalid synthetic voice preset")
                    reference, sample_rate = sf.read(
                        root / "chatterbox" / (speaker + ".wav"), dtype="float32"
                    )
                    import mlx.core as mx

                    results = list(
                        model.generate(
                            text,
                            audio_prompt=mx.array(reference),
                            audio_prompt_sr=sample_rate,
                            lang_code=request["language"],
                            max_new_tokens=1000,
                            verbose=False,
                            exaggeration=0.3 if style == "story" else 0.1,
                        )
                    )
                    audio, rate = (
                        np.concatenate(
                            [np.asarray(r.audio).reshape(-1) for r in results]
                        ),
                        results[0].sample_rate,
                    )
                else:
                    speaker = voice.removeprefix("indic-")
                    if speaker not in {
                        "Aditi",
                        "Arjun",
                        "Divya",
                        "Rohit",
                        "Mary",
                        "Thoma",
                    }:
                        raise ValueError("Invalid Indic voice preset")
                    ids = description(
                        f"{speaker} speaks with a clear recording and no background noise. {direction}",
                        return_tensors="pt",
                    )
                    prompt = tokenizer(text, return_tensors="pt")
                    with torch.inference_mode():
                        audio = (
                            model.generate(
                                input_ids=ids.input_ids,
                                attention_mask=ids.attention_mask,
                                prompt_input_ids=prompt.input_ids,
                                prompt_attention_mask=prompt.attention_mask,
                                max_new_tokens=2048,
                            )
                            .cpu()
                            .numpy()
                            .squeeze()
                        )
                    rate = model.config.sampling_rate
                if (
                    audio.size == 0
                    or not np.isfinite(audio).all()
                    or audio.size / rate > 120
                ):
                    raise ValueError("Invalid speech audio")
                buffer = io.BytesIO()
                sf.write(buffer, audio, rate, format="WAV", subtype="PCM_16")
                wav = buffer.getvalue()
                if len(wav) > 8_000_000:
                    raise ValueError("Audio too large")
            result = {
                "id": request["id"],
                "ok": True,
                "audio": base64.b64encode(wav).decode(),
            }
        except Exception:
            result = {"id": request.get("id"), "ok": False}
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
