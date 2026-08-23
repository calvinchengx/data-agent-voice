"""Configuration for the local voice.

An OpenAI-compatible `/v1/audio/speech` server — Kokoro or Piper — reached over
plain HTTP with no account and no key. That is the whole reason this extension
exists: TEN ships thirty-five TTS extensions at the pinned tag and every one of
them is a vendor API (`docs/05-ten.md` §6), so a hermetic CI could not speak.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pydantic import Field
from ten_ai_base.tts2_http import AsyncTTS2HttpConfig


class LocalTTSConfig(AsyncTTS2HttpConfig):
    dump: bool = Field(default=False, description="write the synthesized PCM to disk")
    dump_path: str = Field(
        default_factory=lambda: str(Path(__file__).parent / "local_tts_out.pcm"),
        description="where, when dump is on",
    )
    # Pre-rendered audio, matched by the text a client asks for. An
    # acknowledgement the caller hears on every tier-2 turn should not cost a
    # synthesis round trip -- it is the same six words every time, and 120ms of
    # time-to-first-byte on the one utterance whose whole job is to arrive fast
    # is the wrong 120ms to spend (docs/00-plan.md §10-5).
    phrases_dir: str = Field(default="", description="directory of pre-rendered .wav phrases")
    params: dict[str, Any] = Field(default_factory=dict)

    def update_params(self) -> None:
        self.params.setdefault("base_url", "http://tts:8880")
        self.params.setdefault("voice", "af_heart")
        self.params.setdefault("sample_rate", 24000)
        self.params.setdefault("model", "kokoro")
        # The TEN `pcm_frame` contract is signed 16-bit mono. A vendor's "pcm"
        # is not always that -- the gotcha list at the tag names a provider
        # streaming float32 -- so the format is stated rather than defaulted,
        # and synthesize_audio_sample_rate() reports what is actually emitted.
        self.params["response_format"] = "pcm"

    def validate(self) -> None:
        if not str(self.params.get("base_url", "")).strip():
            raise ValueError("local_tts needs a base_url to reach the speech server")

    def to_str(self, sensitive_handling: bool = True) -> str:
        """Nothing here is secret -- a local server takes no key -- but the
        signature is the base class's and a future cloud fallback would."""
        return f"{copy.deepcopy(self)}" if sensitive_handling else f"{self}"
