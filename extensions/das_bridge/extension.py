"""The bridge: one ticket, followed to its end, spoken through the host.

`das_tools` dispatches a question and gets a ticket back in milliseconds. This
follows what happens next -- for as long as it takes, which is eight to
twenty-five seconds -- and hands the host something to say each time the
service has something worth saying.

It speaks **through** the host rather than at the TTS node, because the host
owns the floor. And it never renders a refusal or an abstention into words: it
passes the *kind*, and the host says its fixed phrase. The model is not in this
path at all, which is what makes "a refusal is never narrated" a property of
the graph rather than a hope about a prompt.
"""

from __future__ import annotations

import asyncio
import json
import ssl

import httpx
from ten_runtime import AsyncExtension, AsyncTenEnv, Cmd, Data

from . import render
from .stream import Stream

# Kinds the host turns into fixed phrases. The bridge sends no text for these.
UNCOMPOSED = {"refusal", "abstention", "error"}


class DasBridgeExtension(AsyncExtension):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.ten_env: AsyncTenEnv | None = None
        self.client: httpx.AsyncClient | None = None
        # Where each live ticket lives. Learned from the dispatch that opened
        # it rather than by loading descriptors: das_tools already resolved the
        # backend, and a second loader here would be a second place the
        # address could be wrong -- and a cross-extension import besides, which
        # TEN does not promise, since each extension is its own package.
        self.ticket_base: dict[str, str] = {}
        self.token = ""
        self.followers: dict[str, asyncio.Task] = {}
        self.streams: dict[str, Stream] = {}

    async def on_init(self, ten_env: AsyncTenEnv) -> None:
        self.ten_env = ten_env
        insecure, _ = await ten_env.get_property_string("tls_insecure")

        ctx = ssl.create_default_context()
        if str(insecure).lower() in ("1", "true", "yes"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.client = httpx.AsyncClient(verify=ctx)

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        for stream in self.streams.values():
            stream.cancel()
        for task in list(self.followers.values()):
            task.cancel()
        if self.client:
            await self.client.aclose()

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd) -> None:
        name = cmd.get_name()
        if name == "ask_dispatched":
            ticket, _ = cmd.get_property_string("ticket")
            base, _ = cmd.get_property_string("base_url")
            await self._follow(base, ticket)
        elif name == "ask_cancel":
            ticket, _ = cmd.get_property_string("ticket")
            await self._cancel(ticket)

    async def on_data(self, ten_env: AsyncTenEnv, data: Data) -> None:
        """The session's bearer, if the graph routes one here."""
        if data.get_name() == "session_token":
            payload, _ = data.get_property_to_json(None)
            self.token = json.loads(payload).get("token", "")

    # ---------------------------------------------------------- following --
    async def _follow(self, base: str, ticket: str) -> None:
        if not base:
            self.ten_env.log_error(f"das_bridge: {ticket} arrived with no address")
            return
        if ticket in self.followers:
            return
        self.ticket_base[ticket] = base
        stream = Stream(self.client, f"{base}/v1/asks/{ticket}/events", self.token)
        self.streams[ticket] = stream
        task = asyncio.create_task(self._drain(ticket, stream))
        self.followers[ticket] = task
        task.add_done_callback(lambda _t, k=ticket: self._forget(k))

    def _forget(self, ticket: str) -> None:
        self.followers.pop(ticket, None)
        self.streams.pop(ticket, None)
        self.ticket_base.pop(ticket, None)

    async def _cancel(self, ticket: str) -> None:
        """Barge-in reached us. Stop listening, and tell the service.

        Cancelling is best-effort by the contract: a tool call already in
        flight completes. That is acceptable only because everything upstream
        is read-only -- there is nothing to compensate.
        """
        stream = self.streams.get(ticket)
        if stream:
            stream.cancel()
        base = self.ticket_base.get(ticket, "")
        if base and self.client:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            try:
                await self.client.post(
                    f"{base}/v1/asks/{ticket}/cancel", headers=headers, timeout=5.0
                )
            except httpx.HTTPError as e:
                # The caller has already moved on; a failed cancel costs their
                # quota, not their conversation.
                self.ten_env.log_warn(f"das_bridge: cancel {ticket} failed: {e}")

    async def _drain(self, ticket: str, stream: Stream) -> None:
        try:
            async for event in stream.events():
                await self._relay(ticket, event)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # a broken stream must not take the call down
            self.ten_env.log_error(f"das_bridge: {ticket}: {e}")
            await self._turn(ticket, "error", "")

    async def _relay(self, ticket: str, event: dict) -> None:
        kind = str(event.get("type", ""))

        if kind in UNCOMPOSED:
            # No text crosses this line. The host says its phrase.
            await self._turn(ticket, kind, "")
        elif kind == "answer":
            await self._turn(ticket, "answer", render.answer(event))
        elif kind == "milestone":
            said = render.milestone(event)
            if said:
                await self._turn(ticket, "milestone", said)
        # `step`, `branch`, `accepted` and `done` are for the panel, not the
        # caller: narrating a tool call would be reading out the work.

    async def _turn(self, ticket: str, kind: str, text: str) -> None:
        data = Data.create("agent_turn")
        data.set_property_from_json(
            None, json.dumps({"ticket": ticket, "kind": kind, "text": text})
        )
        await self.ten_env.send_data(data)
