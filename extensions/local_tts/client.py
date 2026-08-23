"""The speech server, and the phrase shelf in front of it.

Two sources of audio behind one interface. A phrase that has been pre-rendered
is served from disk with no network at all; anything else is synthesized. The
caller cannot tell which happened, which is the point: the acknowledgement that
has to arrive in milliseconds and the answer that can take a moment are the
same code path to everything downstream.
"""

from __future__ import annotations

import pathlib
import re
import wave

from httpx import AsyncClient, Limits, Timeout
from ten_ai_base.const import LOG_CATEGORY_VENDOR
from ten_ai_base.struct import TTS2HttpResponseEventType
from ten_ai_base.tts2_http import AsyncTTS2HttpClient
from ten_runtime import AsyncTenEnv

from .config import LocalTTSConfig

CHUNK = 4096


def slug(text: str) -> str:
    """A phrase's file name, from what it says.

    Deliberately lossy -- punctuation and case do not change the audio, so
    "Let me work that out." and "let me work that out" are one recording."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")[:60]


class LocalTTSClient(AsyncTTS2HttpClient):
    def __init__(self, config: LocalTTSConfig, ten_env: AsyncTenEnv):
        super().__init__()
        self.config = config
        self.ten_env = ten_env
        self._cancelled = False
        self.base_url = str(config.params["base_url"]).rstrip("/")
        self.phrases = pathlib.Path(config.phrases_dir) if config.phrases_dir else None
        self.client = AsyncClient(
            timeout=Timeout(timeout=20.0),
            limits=Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=600.0),
        )

    async def cancel(self) -> None:
        self._cancelled = True

    async def stop(self) -> None:
        await self.client.aclose()

    def _prerendered(self, text: str) -> pathlib.Path | None:
        if not self.phrases:
            return None
        candidate = self.phrases / f"{slug(text)}.wav"
        return candidate if candidate.is_file() else None

    def _read_phrase(self, path: pathlib.Path) -> bytes:
        """The frames only. A WAV header inside a `pcm_frame` is 44 bytes of
        noise at the start of every acknowledgement."""
        with wave.open(str(path), "rb") as w:
            if (w.getnchannels(), w.getsampwidth()) != (1, 2):
                raise ValueError(f"{path.name} is not 16-bit mono")
            if w.getframerate() != int(self.config.params["sample_rate"]):
                raise ValueError(
                    f"{path.name} is {w.getframerate()}Hz, the graph expects "
                    f"{self.config.params['sample_rate']}Hz"
                )
            return w.readframes(w.getnframes())

    async def get(self, text: str, request_id: str):
        self._cancelled = False
        if not text.strip():
            yield None, TTS2HttpResponseEventType.END
            return

        shelf = self._prerendered(text)
        if shelf is not None:
            try:
                pcm = self._read_phrase(shelf)
            except (OSError, ValueError, wave.Error) as e:
                # A malformed recording must not silence the line: fall through
                # and synthesize. The log says which file, because a phrase that
                # silently stopped being pre-rendered is a latency regression
                # nobody would otherwise notice.
                self.ten_env.log_warn(f"local_tts: {e}; synthesizing instead")
            else:
                for i in range(0, len(pcm), CHUNK):
                    if self._cancelled:
                        yield None, TTS2HttpResponseEventType.FLUSH
                        return
                    yield pcm[i : i + CHUNK], TTS2HttpResponseEventType.RESPONSE
                yield None, TTS2HttpResponseEventType.END
                return

        payload = {
            "model": self.config.params.get("model", "kokoro"),
            "voice": self.config.params.get("voice", "af_heart"),
            "input": text,
            "response_format": "pcm",
        }
        try:
            async with self.client.stream(
                "POST", f"{self.base_url}/v1/audio/speech", json=payload
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")[:200]
                    raise RuntimeError(f"speech server returned {response.status_code}: {body}")
                async for chunk in response.aiter_bytes(chunk_size=CHUNK):
                    if self._cancelled:
                        yield None, TTS2HttpResponseEventType.FLUSH
                        return
                    if chunk:
                        yield bytes(chunk), TTS2HttpResponseEventType.RESPONSE
            yield None, TTS2HttpResponseEventType.END
        except Exception as e:  # the base class turns this into a tts_error
            self.ten_env.log_error(f"local_tts: {e}", category=LOG_CATEGORY_VENDOR)
            raise
