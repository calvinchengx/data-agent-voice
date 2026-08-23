"""Following one ticket's event stream, losslessly.

The ask contract promises the stream can be resumed with `Last-Event-ID` and
that `seq` is contiguous. This takes it at its word and reconnects on a dropped
connection, because a voice call outlives more network blips than a CLI does
and a lost `answer` event is a lost answer.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

TERMINAL = ("answer", "abstention", "refusal", "error")
# Long enough to survive a gateway's idle timeout on a quiet stream; the
# service sends a keep-alive comment every 15s, so silence past this is a
# dropped connection rather than a slow answer.
READ_TIMEOUT = 90.0
MAX_RECONNECTS = 5


class Stream:
    def __init__(self, client: httpx.AsyncClient, url: str, token: str) -> None:
        self.client = client
        self.url = url
        self.token = token
        self.seq = 0
        self._stop = asyncio.Event()

    def cancel(self) -> None:
        self._stop.set()

    async def events(self) -> AsyncIterator[dict]:
        """Every event until `done`, across reconnects.

        Resumes at `seq`, so a reconnect replays nothing already seen and
        misses nothing that happened while disconnected -- which is the whole
        reason the contract numbers events.
        """
        attempts = 0
        while not self._stop.is_set():
            try:
                async for event in self._once():
                    yield event
                    if event.get("type") == "done":
                        return
                # The stream closed without `done`: the contract says one
                # always follows a terminal event, so this is a dropped
                # connection however tidy it looked.
                attempts += 1
            except (httpx.HTTPError, json.JSONDecodeError):
                attempts += 1
            if attempts > MAX_RECONNECTS:
                yield {
                    "type": "error",
                    "kind": "transport",
                    "detail": f"lost the stream after {attempts} attempts",
                }
                return
            await asyncio.sleep(min(0.25 * attempts, 2.0))

    async def _once(self) -> AsyncIterator[dict]:
        headers = {
            "Accept": "text/event-stream",
            "Last-Event-ID": str(self.seq),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with self.client.stream(
            "GET", self.url, headers=headers, timeout=httpx.Timeout(READ_TIMEOUT)
        ) as response:
            response.raise_for_status()
            data: list[str] = []
            async for line in response.aiter_lines():
                if self._stop.is_set():
                    return
                line = line.rstrip("\n")
                if line.startswith(":"):
                    continue  # keep-alive
                if line:
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    continue
                if not data:
                    continue
                event = json.loads("".join(data))
                data = []
                seq = int(event.get("seq", 0))
                if seq <= self.seq:
                    continue  # a replay of something already handled
                self.seq = seq
                yield event
