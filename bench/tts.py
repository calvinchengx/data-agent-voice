"""TTS time-to-first-audio, per provider, warm and cold.

    uv run --group bench python -m bench.tts                  # every provider with a key
    uv run --group bench python -m bench.tts kokoro elevenlabs --reps 5

Each provider streams the corpus sentence by sentence. The measured value is
request written -> first non-empty audio byte, on the client. A provider whose
key is not in the environment (or .env) is reported as skipped, never as fast.

Model and voice defaults are overridable per provider by environment, e.g.
BENCH_ELEVENLABS_MODEL, BENCH_ELEVENLABS_VOICE, so a newer model is measured
without editing this file.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import uuid

import httpx
import websockets

from bench.common import CORPUS, Run, load_env, now_ms, save, summarize, tcp_rtt_ms


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Provider:
    name = ""
    url = ""          # for the RTT probe
    key_var: str | None = None

    def model(self) -> str:
        return ""

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def ttfa(self, text: str) -> tuple[float, int]:
        """(ms to first audio byte, total audio bytes)."""
        raise NotImplementedError


# ------------------------------------------------------------------ HTTP family

class HttpStream(Provider):
    """A provider that answers one POST with a chunked audio body."""

    client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        self.client = httpx.AsyncClient(http2=False, timeout=30.0)

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()

    def request(self, text: str) -> tuple[str, dict, dict]:
        raise NotImplementedError

    async def ttfa(self, text: str) -> tuple[float, int]:
        url, headers, body = self.request(text)
        t0 = now_ms()
        first, total = None, 0
        async with self.client.stream("POST", url, headers=headers, json=body) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {(await r.aread())[:200]!r}")
            async for chunk in r.aiter_raw():
                if chunk and first is None:
                    first = now_ms() - t0
                total += len(chunk)
        if first is None:
            raise RuntimeError("no audio")
        return first, total


class Kokoro(HttpStream):
    """The repo's own local TTS: Kokoro-FastAPI, OpenAI-compatible, in compose."""

    name, key_var = "kokoro", None

    @property
    def url(self) -> str:
        return env("DAV_TTS_BASE_URL_HOST", "http://localhost:8880")

    def model(self) -> str:
        return "kokoro:" + env("BENCH_KOKORO_VOICE", "af_heart")

    def request(self, text):
        return (f"{self.url}/v1/audio/speech", {},
                {"model": "kokoro", "input": text, "voice": env("BENCH_KOKORO_VOICE", "af_heart"),
                 "response_format": "pcm", "stream": True})


class ElevenLabsHttp(HttpStream):
    name, key_var = "elevenlabs", "ELEVENLABS_API_KEY"

    @property
    def url(self) -> str:
        return env("BENCH_ELEVENLABS_BASE", "https://api.elevenlabs.io")

    def model(self) -> str:
        return env("BENCH_ELEVENLABS_MODEL", "eleven_flash_v2_5")

    def request(self, text):
        voice = env("BENCH_ELEVENLABS_VOICE", "21m00Tcm4TlvDq8ikWAM")
        return (f"{self.url}/v1/text-to-speech/{voice}/stream?output_format=pcm_16000",
                {"xi-api-key": os.environ[self.key_var]},
                {"text": text, "model_id": self.model()})


class OpenAITTS(HttpStream):
    name, key_var, url = "openai", "OPENAI_API_KEY", "https://api.openai.com"

    def model(self) -> str:
        return env("BENCH_OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

    def request(self, text):
        return ("https://api.openai.com/v1/audio/speech",
                {"Authorization": f"Bearer {os.environ[self.key_var]}"},
                {"model": self.model(), "input": text,
                 "voice": env("BENCH_OPENAI_VOICE", "alloy"), "response_format": "pcm"})


# -------------------------------------------------------------- WebSocket family

class ElevenLabsWS(Provider):
    """stream-input: text in, audio out, one connection per utterance.

    ElevenLabs closes a stream-input socket at the end of each generation, so
    "warm" here still pays the WebSocket handshake; the multi-context endpoint
    is what a live line would hold open. Measured separately from the HTTP path
    so the two are not averaged into a number neither produces.
    """

    name, key_var = "elevenlabs-ws", "ELEVENLABS_API_KEY"
    url = "wss://api.elevenlabs.io"

    def model(self) -> str:
        return env("BENCH_ELEVENLABS_MODEL", "eleven_flash_v2_5")

    async def ttfa(self, text):
        voice = env("BENCH_ELEVENLABS_VOICE", "21m00Tcm4TlvDq8ikWAM")
        uri = (f"wss://api.elevenlabs.io/v1/text-to-speech/{voice}/stream-input"
               f"?model_id={self.model()}&output_format=pcm_16000")
        t0 = now_ms()
        first, total = None, 0
        async with websockets.connect(
                uri, additional_headers={"xi-api-key": os.environ[self.key_var]}) as ws:
            await ws.send(json.dumps({"text": " "}))
            await ws.send(json.dumps({"text": text + " ", "flush": True}))
            await ws.send(json.dumps({"text": ""}))
            async for msg in ws:
                m = json.loads(msg)
                if m.get("audio"):
                    if first is None:
                        first = now_ms() - t0
                    total += len(base64.b64decode(m["audio"]))
                if m.get("isFinal"):
                    break
        if first is None:
            raise RuntimeError("no audio")
        return first, total


class Cartesia(Provider):
    name, key_var = "cartesia", "CARTESIA_API_KEY"
    url = "wss://api.cartesia.ai"
    ws = None

    def model(self) -> str:
        return env("BENCH_CARTESIA_MODEL", "sonic-2")

    async def open(self):
        uri = (f"wss://api.cartesia.ai/tts/websocket?api_key={os.environ[self.key_var]}"
               f"&cartesia_version={env('BENCH_CARTESIA_VERSION', '2025-04-16')}")
        self.ws = await websockets.connect(uri)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def ttfa(self, text):
        ctx = str(uuid.uuid4())
        req = {"model_id": self.model(), "transcript": text, "context_id": ctx,
               "voice": {"mode": "id", "id": env("BENCH_CARTESIA_VOICE",
                                                 "a0e99841-438c-4a64-b679-ae501e7d6091")},
               "output_format": {"container": "raw", "encoding": "pcm_s16le",
                                 "sample_rate": 16000},
               "language": "en", "continue": False}
        t0 = now_ms()
        await self.ws.send(json.dumps(req))
        first, total = None, 0
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("context_id") != ctx:
                continue
            if m.get("type") == "chunk" and m.get("data"):
                if first is None:
                    first = now_ms() - t0
                total += len(base64.b64decode(m["data"]))
            elif m.get("type") == "error":
                raise RuntimeError(str(m)[:200])
            if m.get("done"):
                break
        if first is None:
            raise RuntimeError("no audio")
        return first, total


class DeepgramAura(Provider):
    name, key_var = "deepgram", "DEEPGRAM_API_KEY"
    url = "wss://api.deepgram.com"
    ws = None

    def model(self) -> str:
        return env("BENCH_DEEPGRAM_TTS_MODEL", "aura-2-thalia-en")

    async def open(self):
        uri = (f"wss://api.deepgram.com/v1/speak?model={self.model()}"
               f"&encoding=linear16&sample_rate=16000")
        self.ws = await websockets.connect(
            uri, additional_headers={"Authorization": f"Token {os.environ[self.key_var]}"})

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def ttfa(self, text):
        t0 = now_ms()
        await self.ws.send(json.dumps({"type": "Speak", "text": text}))
        await self.ws.send(json.dumps({"type": "Flush"}))
        first, total = None, 0
        while True:
            m = await self.ws.recv()
            if isinstance(m, bytes):
                if m and first is None:
                    first = now_ms() - t0
                total += len(m)
                continue
            if json.loads(m).get("type") == "Flushed":
                break
        if first is None:
            raise RuntimeError("no audio")
        return first, total


PROVIDERS: dict[str, type[Provider]] = {
    p.name: p for p in (Kokoro, ElevenLabsHttp, ElevenLabsWS, Cartesia, DeepgramAura, OpenAITTS)
}


async def bench(name: str, reps: int) -> list[Run]:
    p = PROVIDERS[name]()
    if p.key_var and not os.environ.get(p.key_var):
        print(f"{name:<14} skipped: {p.key_var} not set")
        return [Run(name, "", "tts", "", True, None, error=f"skipped: {p.key_var} not set")]
    rtt = tcp_rtt_ms(p.url)
    runs: list[Run] = []
    # COLD: a fresh client per utterance, handshake included.
    for text in CORPUS:
        q = PROVIDERS[name]()
        try:
            # COLD includes opening the connection, wherever the provider opens
            # it: in open() for the socket family, inside ttfa() for HTTP.
            t0 = now_ms()
            await q.open()
            opened = now_ms() - t0
            ms, n = await q.ttfa(text)
            runs.append(Run(name, q.model(), "tts", text, False, opened + ms,
                            extra={"bytes": n, "rtt_ms": rtt, "open_ms": round(opened, 1)}))
        except Exception as e:  # a failed run is a row, not a crash
            runs.append(Run(name, q.model(), "tts", text, False, None, error=str(e)[:200]))
        finally:
            await q.close()
    # WARM: one connection, the corpus `reps` times, first pass discarded.
    try:
        await p.open()
        await p.ttfa(CORPUS[0])
        for _ in range(reps):
            for text in CORPUS:
                try:
                    ms, n = await p.ttfa(text)
                    runs.append(Run(name, p.model(), "tts", text, True, ms,
                                    extra={"bytes": n, "rtt_ms": rtt}))
                except Exception as e:
                    runs.append(Run(name, p.model(), "tts", text, True, None, error=str(e)[:200]))
    finally:
        await p.close()
    warm = summarize([r.value_ms for r in runs if r.warm and r.value_ms is not None])
    cold = summarize([r.value_ms for r in runs if not r.warm and r.value_ms is not None])
    errs = sum(1 for r in runs if r.error)
    print(f"{name:<14} {p.model():<28} rtt={rtt and round(rtt)}ms  warm p50={warm.get('p50')} "
          f"p90={warm.get('p90')}  cold p50={cold.get('p50')}  errors={errs}")
    return runs


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("providers", nargs="*", default=list(PROVIDERS))
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    load_env()
    runs: list[Run] = []
    for name in args.providers:
        runs += await bench(name, args.reps)
    print(f"\nwrote {save('tts', runs, {'reps': args.reps})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
