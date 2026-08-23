"""A voice that needs no account.

`AsyncTTS2HttpExtension` gives the queueing, the flush handling and the
time-to-first-byte metrics; this supplies the client and says what it emits.
"""

from __future__ import annotations

from ten_ai_base.tts2_http import (
    AsyncTTS2HttpClient,
    AsyncTTS2HttpConfig,
    AsyncTTS2HttpExtension,
)
from ten_runtime import AsyncTenEnv

from .client import LocalTTSClient
from .config import LocalTTSConfig


class LocalTTSExtension(AsyncTTS2HttpExtension):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.config: LocalTTSConfig | None = None
        self.client: LocalTTSClient | None = None

    async def create_config(self, config_json_str: str) -> AsyncTTS2HttpConfig:
        return LocalTTSConfig.model_validate_json(config_json_str)

    async def create_client(
        self, config: AsyncTTS2HttpConfig, ten_env: AsyncTenEnv
    ) -> AsyncTTS2HttpClient:
        return LocalTTSClient(config=config, ten_env=ten_env)

    def vendor(self) -> str:
        return "local"

    def synthesize_audio_sample_rate(self) -> int:
        """What is actually emitted, not a default. The gotcha list at the
        pinned tag records a provider whose 'pcm' was float32 at a rate nobody
        declared, and the result was noise."""
        return int(self.config.params.get("sample_rate", 24000))
