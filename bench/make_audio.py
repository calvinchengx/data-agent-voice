"""Render the corpus to 16 kHz mono s16le WAVs, the STT benchmarks' fixed input.

    uv run --no-project --python 3.12 --with mlx-audio --with scipy python -m bench.make_audio

Each file is 300 ms of silence, the sentence, then 1500 ms of silence: enough
trailing quiet for a provider's own endpointing to fire, which is what the
final-transcript latency has to include. The speech end is recorded in
bench/audio/index.json so the benchmark knows when "the caller stopped".

Synthetic speech is clean and flatters accuracy, so these fixtures are for
LATENCY. Word error rate from them is a floor, not a forecast.
"""

from __future__ import annotations

import json
import wave

import numpy as np

from bench.common import CORPUS, ROOT

AUDIO = ROOT / "audio"
SR = 16000
LEAD_MS, TAIL_MS = 300, 1500


def main() -> int:
    from mlx_audio.tts.utils import load_model
    from scipy.signal import resample_poly

    model = load_model("prince-canuma/Kokoro-82M")
    src_sr = getattr(model, "sample_rate", 24000)
    AUDIO.mkdir(parents=True, exist_ok=True)
    index = []
    for i, text in enumerate(CORPUS):
        chunks = [np.asarray(r.audio, dtype=np.float32)
                  for r in model.generate(text=text, voice="af_heart", lang_code="a")]
        speech = resample_poly(np.concatenate(chunks), SR, src_sr)
        # Trim the model's own leading/trailing near-silence so "speech end" is
        # where the voice actually stops, not where the model padded.
        voiced = np.flatnonzero(np.abs(speech) > 0.01)
        speech = speech[voiced[0]: voiced[-1] + 1]
        pcm = np.concatenate([np.zeros(SR * LEAD_MS // 1000), speech,
                              np.zeros(SR * TAIL_MS // 1000)])
        pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
        name = f"{i:02d}.wav"
        with wave.open(str(AUDIO / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm16.tobytes())
        index.append({"file": name, "text": text,
                      "speech_end_ms": round((SR * LEAD_MS // 1000 + len(speech)) / SR * 1000, 1),
                      "duration_ms": round(len(pcm16) / SR * 1000, 1)})
    (AUDIO / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"wrote {len(index)} files to {AUDIO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
