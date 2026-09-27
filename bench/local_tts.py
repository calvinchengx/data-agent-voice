"""Open TTS models, run natively on this machine, time to first audio in-process.

    uv run --no-project --python 3.12 --with mlx-audio --with sentencepiece \\
        --with 'misaki[en]' --with piper-tts --with numpy python -m bench.local_tts [label ...]

No network and no container: the value is generate() called -> first audio
chunk returned, so it is the model's own floor on this hardware. A deployment
adds its transport on top (tens of ms on a LAN, a round trip over a WAN).

Two numbers per model, because they answer different questions:

  ttfa_ms   what the caller waits for. For a model that synthesises a whole
            segment before returning, this is that segment's full synthesis
            time, which is exactly what sentence-chunked TTS pays today.
  rtf       synthesis time / audio duration. Below 1 is faster than real
            time; a model with RTF near 1 cannot keep up once it starts
            speaking, however quick its first chunk.

Models that need Apple Metal run through mlx-audio; Piper runs on CPU, which
is what a GPU-less container would get.
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
import time

from bench.common import CORPUS, Run, now_ms, save, summarize

# label: (backend, model id, voice, extra generate kwargs)
MODELS = {
    "kokoro-mlx": ("mlx", "prince-canuma/Kokoro-82M", "af_heart", {"lang_code": "a"}),
    "soprano-mlx": ("mlx", "mlx-community/Soprano-80M-bf16", None, {}),
    "kitten-mlx": ("mlx", "mlx-community/kitten-tts-nano-0.8", "expr-voice-5-m", {}),
    "pocket-mlx": ("mlx", "kyutai/pocket-tts", None, {}),
    "qwen3tts-mlx": ("mlx", "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16", None, {}),
    "moss-nano-mlx": ("mlx", "mlx-community/MOSS-TTS-Nano-100M", None, {"stream": False}),
    "piper-cpu": ("piper", "en_US-lessac-medium", None, {}),
}


def mlx_runner(model_id: str, voice: str | None, extra: dict):
    from mlx_audio.tts.utils import load_model

    model = load_model(model_id)
    sr = getattr(model, "sample_rate", 24000)
    params = inspect.signature(model.generate).parameters
    kwargs = dict(extra)
    if voice is not None:
        kwargs["voice"] = voice
    # Ask for incremental output where the model offers it: that is the mode a
    # live line would use, and without it the first chunk is the whole segment.
    if "stream" in params or any(p.kind == p.VAR_KEYWORD for p in params.values()):
        kwargs.setdefault("stream", True)

    def run(text: str) -> tuple[float, float, float]:
        t0 = now_ms()
        first, samples = None, 0
        for result in model.generate(text=text, **kwargs):
            audio = getattr(result, "audio", None)
            if audio is None:
                continue
            n = int(getattr(audio, "size", len(audio)))
            if n and first is None:
                first = now_ms() - t0
            samples += n
        total = now_ms() - t0
        if first is None:
            raise RuntimeError("no audio")
        return first, total, samples / sr * 1000.0

    return run


def piper_runner(voice_name: str, _voice, _extra):
    from pathlib import Path

    from piper import PiperVoice

    cache = Path.home() / ".cache" / "piper"
    onnx = cache / f"{voice_name}.onnx"
    if not onnx.exists():
        import urllib.request

        cache.mkdir(parents=True, exist_ok=True)
        lang, name, quality = voice_name.split("-")
        base = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"en/{lang}/{name}/{quality}/{voice_name}"
        )
        for suffix in (".onnx", ".onnx.json"):
            urllib.request.urlretrieve(base + suffix, cache / f"{voice_name}{suffix}")
    voice = PiperVoice.load(str(onnx))
    sr = voice.config.sample_rate

    def run(text: str) -> tuple[float, float, float]:
        t0 = now_ms()
        first, samples = None, 0
        for chunk in voice.synthesize(text):
            n = len(chunk.audio_int16_bytes) // 2
            if n and first is None:
                first = now_ms() - t0
            samples += n
        return first, now_ms() - t0, samples / sr * 1000.0

    return run


def bench(label: str, reps: int) -> list[Run]:
    backend, model_id, voice, extra = MODELS[label]
    try:
        t = time.perf_counter()
        run = (mlx_runner if backend == "mlx" else piper_runner)(model_id, voice, extra)
        load_s = time.perf_counter() - t
        run(CORPUS[0])  # warm-up: first call compiles kernels / fills caches
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"
        print(f"{label:<16} FAILED to load/run: {msg}")
        return [Run(label, model_id, "tts-local", "", True, None, error=msg)]
    runs = []
    for _ in range(reps):
        for text in CORPUS:
            try:
                ttfa, total, audio_ms = run(text)
                runs.append(
                    Run(
                        label,
                        model_id,
                        "tts-local",
                        text,
                        True,
                        ttfa,
                        extra={
                            "total_ms": round(total, 1),
                            "audio_ms": round(audio_ms, 1),
                            "rtf": round(total / audio_ms, 3) if audio_ms else None,
                        },
                    )
                )
            except Exception as e:
                runs.append(Run(label, model_id, "tts-local", text, True, None, error=str(e)[:160]))
    ok = [r for r in runs if r.value_ms is not None]
    s = summarize([r.value_ms for r in ok])
    rtf = summarize([r.extra["rtf"] for r in ok if r.extra.get("rtf")])
    print(
        f"{label:<16} load={load_s:5.1f}s  ttfa p50={s.get('p50')} p90={s.get('p90')} ms  "
        f"rtf p50={rtf.get('p50')}  errors={len(runs) - len(ok)}"
    )
    return runs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("models", nargs="*", default=list(MODELS))
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    runs = []
    for label in args.models:
        runs += bench(label, args.reps)
        sys.stdout.flush()
    print(f"\nwrote {save('tts-local', runs, {'reps': args.reps})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
