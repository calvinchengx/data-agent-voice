"""Reaching a backend, as the person who is speaking.

Every call carries the caller's bearer -- the same token the sign-in acquired
before the call -- so the sources apply that user's permissions and the audit
line upstream names them. Nothing here holds a credential of its own.
"""

from __future__ import annotations

import json
import ssl

from httpx import AsyncClient, Limits, Timeout

from .descriptor import Backend, FastTool


class AskClient:
    def __init__(self, *, insecure: bool = False, token: str = "") -> None:
        ctx = ssl.create_default_context()
        if insecure:
            # The local gateway's certificate is self-signed; real Azure's is
            # not, and DAV_TLS_INSECURE is false there. A setting, never a
            # default.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.token = token
        self.client = AsyncClient(
            verify=ctx,
            timeout=Timeout(timeout=10.0),
            limits=Limits(max_connections=20, max_keepalive_connections=10),
        )

    def set_token(self, token: str) -> None:
        """The session's bearer, injected per call by the server's property
        pass so it never lives in a file (`docs/05-ten.md` §4)."""
        self.token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def close(self) -> None:
        await self.client.aclose()

    async def lookup(self, backend: Backend, tool: FastTool, query: str) -> dict:
        """One fast lookup, inside the conversational budget.

        The call shape comes from the descriptor, so this function knows it is
        making an MCP tool call and not what the tool is for.
        """
        path = tool.call.get("path", "")
        url = path if path.startswith("http") else f"{backend.base_url.rsplit('/', 1)[0]}{path}"
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool.call.get("tool", ""), "arguments": {"query": query}},
        }
        response = await self.client.post(
            url,
            json=body,
            headers={**self._headers, "Accept": "application/json, text/event-stream"},
            timeout=Timeout(timeout=max(2.0, tool.budget_ms / 1000 * 4)),
        )
        response.raise_for_status()
        payload = _parse(response.text)
        blocks = (payload.get("result") or {}).get("content") or []
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return {"found": text[:2000]} if text else {"found": None}

    async def dispatch(self, backend: Backend, question: str) -> tuple[str, str]:
        """Open a conversation and ask. Returns (ticket, conversation).

        Two round trips against a service whose p95 is 70 ms, and neither waits
        for the answer: the ticket comes back before any tool call runs, which
        is the ask contract's first promise.
        """
        opened = await self.client.post(
            f"{backend.base_url}/v1/conversations", headers=self._headers
        )
        opened.raise_for_status()
        conversation = opened.json()["conversation_id"]

        asked = await self.client.post(
            f"{backend.base_url}/v1/conversations/{conversation}/asks",
            json={"question": question},
            headers=self._headers,
        )
        asked.raise_for_status()
        return asked.json()["ticket"], conversation


def _parse(raw: str) -> dict:
    """A Streamable HTTP response is JSON, or SSE frames carrying it. Accept
    both rather than assume the server's choice."""
    raw = raw.strip()
    if raw.startswith(("{", "[")):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:") and line[5:].strip():
            return json.loads(line[5:].strip())
    raise ValueError(f"unparseable response: {raw[:200]}")
