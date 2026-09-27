"""Streaming STT: last speech frame sent -> final transcript received.

    uv run --group bench python -m bench.stt                     # every cloud provider with a key
    uv run --no-project --python 3.12 --with faster-whisper --with numpy \\
        python -m bench.stt whisper-base whisper-turbo            # local, CPU

Each fixture in bench/audio/ is streamed in 20 ms frames at real-time pace,
including its 1.5 s of trailing silence, because a provider's endpointing is
part of what the caller waits for and must not be skipped. The clock starts
when the frame holding the last speech sample is written and stops at the
provider's final/end-of-turn event. If no final arrives by the end of the
file, the provider is told to finalize and the row is marked `forced`.

Local Whisper is not a streaming model: it transcribes a finished segment.
Its row reports the decode time after speech ends, and `eou_ms` states the
fixed silence the graph waits before handing it the segment (DAV_EOU_MODE
=fixed), so the two are never added up silently or left out.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import pathlib
import re
import wave

from bench.common import ROOT, Run, load_env, now_ms, save, summarize, tcp_rtt_ms

AUDIO = ROOT / "audio"
FRAME_MS = 20
FIXED_EOU_MS = int(os.environ.get("BENCH_FIXED_EOU_MS", "500"))


def fixtures() -> list[dict]:
    index = json.loads((AUDIO / "index.json").read_text())
    for item in index:
        with wave.open(str(AUDIO / item["file"]), "rb") as w:
            item["pcm"] = w.readframes(w.getnframes())
            item["sr"] = w.getframerate()
    return index


def wer(ref: str, hyp: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9' ]", " ", s.lower()).split()  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


# ------------------------------------------------------------------- streaming


class Streamer:
    """Base for WebSocket providers: send frames in real time, await the final."""

    name = ""
    url = ""
    key_var = ""
    model = ""

    async def connect(self):
        raise NotImplementedError

    def frame(self, pcm: bytes):
        return pcm  # what one audio frame looks like on the wire

    async def finalize(self, ws) -> None:
        """Ask for a final now (only used if endpointing never fired)."""

    def final_text(self, msg) -> str | None:
        """The transcript if this message is the final/end-of-turn, else None."""
        raise NotImplementedError

    async def one(self, fx: dict) -> Run:
        pcm, sr = fx["pcm"], fx["sr"]
        step = sr * FRAME_MS // 1000 * 2
        end_byte = int(fx["speech_end_ms"] / 1000 * sr) * 2
        ws = await self.connect()
        t_end: list[float] = []
        final: list[tuple[float, str]] = []
        forced = False

        async def send():
            t0 = now_ms()
            for k, off in enumerate(range(0, len(pcm), step)):
                chunk = pcm[off : off + step]
                await ws.send(self.frame(chunk))
                if not t_end and off + len(chunk) >= end_byte:
                    t_end.append(now_ms())
                if final:
                    return
                # pace against the wall clock so drift does not accumulate
                await asyncio.sleep(max(0.0, (t0 + (k + 1) * FRAME_MS - now_ms()) / 1000))

        async def recv():
            async for msg in ws:
                text = self.final_text(msg)
                if text is not None:
                    final.append((now_ms(), text))
                    return

        rx = asyncio.create_task(recv())
        await send()
        if not final:
            forced = True
            await self.finalize(ws)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(rx, timeout=10)
        await ws.close()
        if not final:
            return Run(self.name, self.model, "stt", fx["text"], True, None, error="no final")
        t, text = final[0]
        return Run(
            self.name,
            self.model,
            "stt",
            fx["text"],
            True,
            t - t_end[0],
            extra={"forced": forced, "hyp": text, "wer": round(wer(fx["text"], text), 3)},
        )


class DeepgramFlux(Streamer):
    name, key_var, url = "deepgram-flux", "DEEPGRAM_API_KEY", "wss://api.deepgram.com"
    model = os.environ.get("BENCH_DEEPGRAM_STT_MODEL", "flux-general-en")

    async def connect(self):
        import websockets

        return await websockets.connect(
            f"wss://api.deepgram.com/v2/listen?model={self.model}&encoding=linear16"
            f"&sample_rate=16000&eot_threshold=0.7",
            additional_headers={"Authorization": f"Token {os.environ[self.key_var]}"},
        )

    def final_text(self, msg):
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("type") == "TurnInfo" and m.get("event") == "EndOfTurn":
            return m.get("transcript", "")
        return None


class DeepgramNova(Streamer):
    name, key_var, url = "deepgram-nova", "DEEPGRAM_API_KEY", "wss://api.deepgram.com"
    model = os.environ.get("BENCH_DEEPGRAM_NOVA_MODEL", "nova-3")

    async def connect(self):
        import websockets

        self.parts: list[str] = []
        return await websockets.connect(
            f"wss://api.deepgram.com/v1/listen?model={self.model}&encoding=linear16"
            f"&sample_rate=16000&interim_results=true&endpointing=300&smart_format=true",
            additional_headers={"Authorization": f"Token {os.environ[self.key_var]}"},
        )

    async def finalize(self, ws):
        await ws.send(json.dumps({"type": "Finalize"}))

    def final_text(self, msg):
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("type") != "Results" or not m.get("is_final"):
            return None
        alt = m["channel"]["alternatives"][0]["transcript"]
        if alt:
            self.parts.append(alt)
        return " ".join(self.parts) if m.get("speech_final") else None


class Soniox(Streamer):
    name, key_var = "soniox", "SONIOX_API_KEY"
    model = os.environ.get("BENCH_SONIOX_MODEL", "stt-rt-v5")
    host = os.environ.get("BENCH_SONIOX_HOST", "stt-rt.jp.soniox.com")

    @property
    def url(self):
        return f"wss://{self.host}"

    async def connect(self):
        import websockets

        ws = await websockets.connect(f"wss://{self.host}/transcribe-websocket")
        await ws.send(
            json.dumps(
                {
                    "api_key": os.environ[self.key_var],
                    "model": self.model,
                    "audio_format": "pcm_s16le",
                    "sample_rate": 16000,
                    "num_channels": 1,
                    "enable_endpoint_detection": True,
                }
            )
        )
        self.tokens: list[str] = []
        return ws

    async def finalize(self, ws):
        await ws.send(json.dumps({"type": "finalize"}))

    def final_text(self, msg):
        m = json.loads(msg) if isinstance(msg, str) else {}
        done = False
        for tok in m.get("tokens", []):
            if not tok.get("is_final"):
                continue
            if tok.get("text") in ("<end>", "<fin>"):
                done = True
            else:
                self.tokens.append(tok.get("text", ""))
        return "".join(self.tokens).strip() if done else None


class AssemblyAI(Streamer):
    name, key_var, url = "assemblyai", "ASSEMBLYAI_API_KEY", "wss://streaming.assemblyai.com"
    model = os.environ.get("BENCH_ASSEMBLYAI_MODEL", "universal-streaming-english")

    async def connect(self):
        import websockets

        return await websockets.connect(
            f"wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le"
            f"&speech_model={self.model}&format_turns=true",
            additional_headers={"Authorization": os.environ[self.key_var]},
        )

    async def finalize(self, ws):
        await ws.send(json.dumps({"type": "ForceEndpoint"}))

    def final_text(self, msg):
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("type") == "Turn" and m.get("end_of_turn"):
            return m.get("transcript", "")
        return None


class ElevenLabsScribe(Streamer):
    name, key_var, url = "elevenlabs-scribe", "ELEVENLABS_API_KEY", "wss://api.elevenlabs.io"
    model = os.environ.get("BENCH_ELEVENLABS_STT_MODEL", "scribe_v2_realtime")

    async def connect(self):
        import websockets

        return await websockets.connect(
            f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id={self.model}"
            f"&audio_format=pcm_16000&commit_strategy=vad",
            additional_headers={"xi-api-key": os.environ[self.key_var]},
        )

    def frame(self, pcm):
        return json.dumps(
            {
                "message_type": "input_audio_chunk",
                "audio_base_64": base64.b64encode(pcm).decode(),
                "sample_rate": 16000,
            }
        )

    async def finalize(self, ws):
        await ws.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": "",
                    "commit": True,
                    "sample_rate": 16000,
                }
            )
        )

    def final_text(self, msg):
        m = json.loads(msg) if isinstance(msg, str) else {}
        if m.get("message_type", "").startswith("committed_transcript"):
            return m.get("text", "")
        return None


STREAMERS = {c.name: c for c in (DeepgramFlux, DeepgramNova, Soniox, AssemblyAI, ElevenLabsScribe)}


# ----------------------------------------------------------------------- local

LOCAL = {
    "whisper-base": ("base", "int8"),  # the graph's default (tenapp/property.json)
    "whisper-small": ("small", "int8"),
    "whisper-turbo": ("large-v3-turbo", "int8"),
}


def local_whisper(label: str, fxs: list[dict], reps: int) -> list[Run]:
    import numpy as np
    from faster_whisper import WhisperModel

    size, compute = LOCAL[label]
    model = WhisperModel(size, device="cpu", compute_type=compute)
    runs = []

    def decode(fx):
        a = np.frombuffer(fx["pcm"], dtype="<i2").astype(np.float32) / 32768.0
        seg = a[: int(fx["speech_end_ms"] / 1000 * fx["sr"])]
        t0 = now_ms()
        segs, _ = model.transcribe(seg, language="en", beam_size=1, vad_filter=False)
        text = " ".join(s.text for s in segs).strip()
        return now_ms() - t0, text

    decode(fxs[0])  # warm-up
    for _ in range(reps):
        for fx in fxs:
            ms, text = decode(fx)
            runs.append(
                Run(
                    label,
                    f"faster-whisper {size} {compute} cpu",
                    "stt",
                    fx["text"],
                    True,
                    ms,
                    extra={
                        "eou_ms": FIXED_EOU_MS,
                        "hyp": text,
                        "wer": round(wer(fx["text"], text), 3),
                    },
                )
            )
    return runs


def local_parakeet(label: str, fxs: list[dict], reps: int) -> list[Run]:
    """NVIDIA Parakeet TDT on Apple Metal (parakeet-mlx), offline like Whisper."""
    import tempfile
    import wave as _wave

    from parakeet_mlx import from_pretrained

    repo = os.environ.get("BENCH_PARAKEET_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
    model = from_pretrained(repo)
    tmp = pathlib.Path(tempfile.mkdtemp())

    def decode(fx):
        seg = fx["pcm"][: int(fx["speech_end_ms"] / 1000 * fx["sr"]) * 2]
        path = tmp / fx["file"]
        with _wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fx["sr"])
            w.writeframes(seg)
        t0 = now_ms()
        text = model.transcribe(str(path)).text.strip()
        return now_ms() - t0, text

    decode(fxs[0])
    runs = []
    for _ in range(reps):
        for fx in fxs:
            ms, text = decode(fx)
            runs.append(
                Run(
                    label,
                    f"{repo} mlx",
                    "stt",
                    fx["text"],
                    True,
                    ms,
                    extra={
                        "eou_ms": FIXED_EOU_MS,
                        "hyp": text,
                        "wer": round(wer(fx["text"], text), 3),
                    },
                )
            )
    return runs


def report(label: str, runs: list[Run], rtt=None) -> None:
    ok = [r for r in runs if r.value_ms is not None]
    s = summarize([r.value_ms for r in ok])
    w = summarize([r.extra["wer"] for r in ok])
    forced = sum(1 for r in ok if r.extra.get("forced"))
    print(
        f"{label:<18} rtt={rtt and round(rtt)}  final p50={s.get('p50')} p90={s.get('p90')} ms  "
        f"wer p50={w.get('p50')}  forced={forced}  errors={len(runs) - len(ok)}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("providers", nargs="*", default=list(STREAMERS))
    ap.add_argument("--reps", type=int, default=2)
    args = ap.parse_args()
    load_env()
    fxs = fixtures()
    runs: list[Run] = []
    for name in args.providers:
        if name in LOCAL or name == "parakeet-mlx":
            r = (local_parakeet if name == "parakeet-mlx" else local_whisper)(name, fxs, args.reps)
            report(name, r)
            runs += r
            continue
        s = STREAMERS[name]()
        if not os.environ.get(s.key_var):
            print(f"{name:<18} skipped: {s.key_var} not set")
            runs.append(
                Run(name, s.model, "stt", "", True, None, error=f"skipped: {s.key_var} not set")
            )
            continue
        rtt = tcp_rtt_ms(s.url)
        r = []
        for _ in range(args.reps):
            for fx in fxs:
                try:
                    run = await s.one(fx)
                except Exception as e:
                    run = Run(name, s.model, "stt", fx["text"], True, None, error=str(e)[:200])
                run.extra["rtt_ms"] = rtt
                r.append(run)
        report(name, r, rtt)
        runs += r
    print(f"\nwrote {save('stt', runs, {'reps': args.reps, 'fixed_eou_ms': FIXED_EOU_MS})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
