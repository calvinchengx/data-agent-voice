"""Speech-to-speech: last user speech frame sent -> first reply audio received.

    uv run --group bench python -m bench.s2s                # every provider with a key

The user's turn is a corpus fixture streamed in 20 ms frames at real-time
pace, trailing silence included, with the provider's own server-side turn
detection on. That is voice-to-voice as a caller experiences it, network
included, measured from the moment they stop talking.

These systems replace the host as well as the speech stages, so the number is
compared against the SUM of the cascaded stages, not against any one of them.
None of these can be made to speak a fixed refusal verbatim (docs/00-plan.md
rule 4), which is recorded beside the latency rather than weighed into it.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os

from bench.common import Run, load_env, now_ms, save, summarize, tcp_rtt_ms
from bench.stt import FRAME_MS, fixtures

INSTRUCTIONS = ("You are a brief voice assistant for a data team. Answer in one short "
                "sentence.")


def upsample_16_to_24(pcm16: bytes) -> bytes:
    """OpenAI Realtime wants 24 kHz PCM16; a 3:2 linear resample is enough for timing."""
    import numpy as np

    a = np.frombuffer(pcm16, dtype="<i2").astype(np.float32)
    x = np.linspace(0, len(a) - 1, num=len(a) * 3 // 2)
    return np.interp(x, np.arange(len(a)), a).astype("<i2").tobytes()


class OpenAIRealtime:
    name, key_var, url = "openai-realtime", "OPENAI_API_KEY", "wss://api.openai.com"
    model = os.environ.get("BENCH_OPENAI_REALTIME_MODEL", "gpt-realtime")
    sr = 24000

    async def connect(self):
        import websockets
        ws = await websockets.connect(
            f"wss://api.openai.com/v1/realtime?model={self.model}",
            additional_headers={"Authorization": f"Bearer {os.environ[self.key_var]}"})
        await ws.send(json.dumps({"type": "session.update", "session": {
            "type": "realtime", "instructions": INSTRUCTIONS,
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                                "turn_detection": {"type": "server_vad"}},
                      "output": {"format": {"type": "audio/pcm", "rate": 24000}}}}}))
        return ws

    def frame(self, pcm16k: bytes):
        return json.dumps({"type": "input_audio_buffer.append",
                           "audio": base64.b64encode(upsample_16_to_24(pcm16k)).decode()})

    def is_first_audio(self, msg) -> bool:
        m = json.loads(msg)
        return m.get("type") in ("response.output_audio.delta", "response.audio.delta")


class GeminiLive:
    name, key_var = "gemini-live", "GEMINI_API_KEY"
    url = "wss://generativelanguage.googleapis.com"
    model = os.environ.get("BENCH_GEMINI_LIVE_MODEL", "gemini-live-2.5-flash-preview")

    async def connect(self):
        import websockets
        ws = await websockets.connect(
            "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
            f"GenerativeService.BidiGenerateContent?key={os.environ[self.key_var]}")
        await ws.send(json.dumps({"setup": {
            "model": f"models/{self.model}",
            "generationConfig": {"responseModalities": ["AUDIO"]},
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]}}}))
        await ws.recv()  # setupComplete
        return ws

    def frame(self, pcm16k: bytes):
        return json.dumps({"realtimeInput": {"audio": {
            "mimeType": "audio/pcm;rate=16000", "data": base64.b64encode(pcm16k).decode()}}})

    def is_first_audio(self, msg) -> bool:
        m = json.loads(msg)
        parts = (m.get("serverContent") or {}).get("modelTurn", {}).get("parts", [])
        return any("inlineData" in p for p in parts)


PROVIDERS = {c.name: c for c in (OpenAIRealtime, GeminiLive)}


async def one(p, fx: dict) -> Run:
    pcm, sr = fx["pcm"], fx["sr"]
    step = sr * FRAME_MS // 1000 * 2
    end_byte = int(fx["speech_end_ms"] / 1000 * sr) * 2
    ws = await p.connect()
    t_end: list[float] = []
    got: list[float] = []

    async def recv():
        async for msg in ws:
            if p.is_first_audio(msg):
                got.append(now_ms())
                return

    rx = asyncio.create_task(recv())
    t0 = now_ms()
    for k, off in enumerate(range(0, len(pcm), step)):
        chunk = pcm[off: off + step]
        await ws.send(p.frame(chunk))
        if not t_end and off + len(chunk) >= end_byte:
            t_end.append(now_ms())
        if got:
            break
        await asyncio.sleep(max(0.0, (t0 + (k + 1) * FRAME_MS - now_ms()) / 1000))
    try:
        await asyncio.wait_for(rx, timeout=15)
    except TimeoutError:
        pass
    await ws.close()
    if not got:
        return Run(p.name, p.model, "s2s", fx["text"], True, None, error="no reply audio")
    return Run(p.name, p.model, "s2s", fx["text"], True, got[0] - t_end[0])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("providers", nargs="*", default=list(PROVIDERS))
    ap.add_argument("--reps", type=int, default=2)
    args = ap.parse_args()
    load_env()
    fxs = fixtures()
    runs: list[Run] = []
    for name in args.providers:
        p = PROVIDERS[name]()
        if not os.environ.get(p.key_var):
            print(f"{name:<16} skipped: {p.key_var} not set")
            runs.append(Run(name, p.model, "s2s", "", True, None, error=f"skipped: {p.key_var} not set"))
            continue
        rtt = tcp_rtt_ms(p.url)
        r = []
        for _ in range(args.reps):
            for fx in fxs:
                try:
                    run = await one(p, fx)
                except Exception as e:
                    run = Run(name, p.model, "s2s", fx["text"], True, None, error=str(e)[:200])
                run.extra["rtt_ms"] = rtt
                r.append(run)
        s = summarize([x.value_ms for x in r if x.value_ms is not None])
        print(f"{name:<16} rtt={rtt and round(rtt)}  v2v p50={s.get('p50')} p90={s.get('p90')} ms  "
              f"errors={sum(1 for x in r if x.error)}")
        runs += r
    print(f"\nwrote {save('s2s', runs, {'reps': args.reps})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
