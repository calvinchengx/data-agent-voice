"""The host: it owns the turn, and it is the only thing that speaks.

A fork of TEN's `main_python` (`agent/` and `helper.py` beside this file are
taken from it unchanged). What is inherited: interrupt on new speech, sentence
chunking to TTS, turn and session ids, tool registration. What is added is the
part this project is about --

**One voice.** Every utterance goes out through `_say`, whether the model
composed it, the bridge brought it back from the ask service, or it is a fixed
phrase. Nothing else reaches TTS. That is what makes barge-in and turn-taking
one decision instead of three, and it is why the bridge speaks *through* here
rather than straight at the TTS node: two speakers with no arbiter talk over
each other, and a caller cannot tell which one to interrupt.

**A refusal is never composed.** `refusal`, `abstention` and `error` arrive
from the bridge as event types and leave as fixed phrases the model never saw.
The model cannot smooth what it is not shown.

**The floor.** While the caller is speaking, an answer that arrives from the
service waits. It is spoken at the next gap rather than over them, and if they
have moved on it is still spoken -- they asked for it.

There is no tier classifier in this file. Tiering is which tool the model
chose: a lookup answers inside the turn, a dispatch does not. Adding a
classifier would be a second model call on the one path that cannot afford it.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Literal

from ten_runtime import AsyncExtension, AsyncTenEnv, Cmd, Data

from .agent.agent import Agent
from .agent.decorators import agent_event_handler
from .agent.events import (
    ASRResultEvent,
    LLMResponseEvent,
    ToolRegisterEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from .config import HostConfig
from .helper import _send_cmd, _send_data, parse_sentences

# What the bridge sends back, and what each becomes when spoken.
FIXED = {"refusal": "refusal_phrase", "abstention": "abstention_phrase", "error": "error_phrase"}
# A partial transcript this short is a cough, not an interruption.
BARGE_IN_CHARS = 2


class DasHostExtension(AsyncExtension):
    def __init__(self, name: str):
        super().__init__(name)
        self.ten_env: AsyncTenEnv | None = None
        self.agent: Agent | None = None
        self.config = HostConfig()

        self.session_id = "0"
        self.turn_id = 0
        self.fragment = ""
        self.callers = 0

        # Turn-taking state. `speaking` is ours; `caller_speaking` is theirs.
        self.speaking = False
        self.caller_speaking = False
        # Answers that arrived while somebody was talking.
        self.held: list[tuple[str, str]] = []
        self.pending_asks: set[str] = set()
        # Held so the loop cannot collect a settle timer mid-flight, which
        # would silently drop whatever was waiting for the gap it was timing.
        self._timers: set[asyncio.Task] = set()

    # ------------------------------------------------------------ lifecycle --
    async def on_init(self, ten_env: AsyncTenEnv) -> None:
        self.ten_env = ten_env
        config_json, _ = await ten_env.get_property_to_json(None)
        self.config = HostConfig.model_validate_json(config_json)
        self.agent = Agent(ten_env)
        for attr in dir(self):
            handler = getattr(self, attr)
            if getattr(handler, "_agent_event_type", None):
                self.agent.on(handler._agent_event_type, handler)
        ten_env.log_info(
            f"das_host: eou={self.config.eou_mode} chunk={self.config.tts_chunk} "
            f"ack={'pre-rendered' if self.config.prerendered_ack else 'composed'}"
        )

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        for timer in list(self._timers):
            timer.cancel()
        if self.agent:
            await self.agent.stop()

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd) -> None:
        name = cmd.get_name()
        if name == "ask_dispatched":
            await self._on_dispatched(cmd)
            return
        if name == "flush":
            # Semantic turn detection decided the caller finished. Whatever we
            # were saying is now over them.
            await self._interrupt()
            return
        await self.agent.on_cmd(cmd)

    async def on_data(self, ten_env: AsyncTenEnv, data: Data) -> None:
        if data.get_name() == "agent_turn":
            await self._on_agent_turn(data)
            return
        await self.agent.on_data(data)

    # ------------------------------------------------------------- the turn --
    @agent_event_handler(UserJoinedEvent)
    async def _on_user_joined(self, event: UserJoinedEvent) -> None:
        self.callers += 1
        if self.callers == 1 and self.config.greeting:
            await self._say(self.config.greeting, final=True)

    @agent_event_handler(UserLeftEvent)
    async def _on_user_left(self, event: UserLeftEvent) -> None:
        self.callers -= 1
        # Anything still in flight is being computed for nobody.
        for ticket in list(self.pending_asks):
            await self._cancel(ticket)

    @agent_event_handler(ToolRegisterEvent)
    async def _on_tool_register(self, event: ToolRegisterEvent) -> None:
        await self.agent.register_llm_tool(event.tool, event.source)

    @agent_event_handler(ASRResultEvent)
    async def _on_asr_result(self, event: ASRResultEvent) -> None:
        self.session_id = event.metadata.get("session_id", "100")
        if not event.text:
            return

        # Barge-in. Anything past a syllable while we are talking means stop --
        # it must not wait for a final transcript, because by then we have said
        # another sentence over them.
        if event.final or len(event.text) > BARGE_IN_CHARS:
            self.caller_speaking = not event.final
            await self._interrupt()

        if event.final:
            self.caller_speaking = False
            # In semantic mode the turn-detection node decides when a turn has
            # ended, and a final transcript is only evidence. In fixed mode
            # this IS the decision (docs/00-plan.md §10-1).
            if not self.config.trust_turn_detection:
                await self._take_turn(event.text)
        await self._transcript("user", event.text, event.final, int(self.session_id))

    async def _take_turn(self, text: str) -> None:
        self.turn_id += 1
        await self.agent.queue_llm_input(text)

    @agent_event_handler(LLMResponseEvent)
    async def _on_llm_response(self, event: LLMResponseEvent) -> None:
        if event.type != "message":
            await self._transcript("assistant", event.text, event.is_final, 100, "reasoning")
            return
        if not event.is_final:
            if self.config.speak_per_sentence:
                sentences, self.fragment = parse_sentences(self.fragment, event.delta)
                for sentence in sentences:
                    await self._say(sentence, final=False)
            return
        # Final: whatever is left, or -- with chunking off -- the whole thing
        # at once, which is switch #4's audible "before".
        remainder = self.fragment or ("" if self.config.speak_per_sentence else event.text)
        self.fragment = ""
        await self._say(remainder, final=True)
        await self._transcript("assistant", event.text, True, 100)

    # ------------------------------------------- what comes back from a backend --
    async def _on_dispatched(self, cmd: Cmd) -> None:
        """A question was handed to a backend. Acknowledge it now."""
        ticket, _ = cmd.get_property_string("ticket")
        self.pending_asks.add(ticket)
        if self.config.prerendered_ack:
            # Said here rather than by the model: this is the one utterance
            # whose whole job is to arrive fast, and local_tts serves it from
            # disk at no synthesis cost (docs/00-plan.md §10-5).
            await self._say(self.config.ack_phrase, final=True)

    async def _on_agent_turn(self, data: Data) -> None:
        """The bridge, speaking for a backend.

        `kind` is the ask contract's terminal event type or `milestone`. The
        three in FIXED never carry model prose: the bridge sends the kind and
        the host says its phrase, so nothing the service refused can be
        rewritten into something that sounds like an answer.
        """
        payload, _ = data.get_property_to_json(None)
        event = json.loads(payload)
        kind = event.get("kind", "")
        ticket = event.get("ticket", "")

        if kind in FIXED:
            text = getattr(self.config, FIXED[kind])
            self.pending_asks.discard(ticket)
        elif kind == "answer":
            text = event.get("text", "")
            self.pending_asks.discard(ticket)
        else:
            text = event.get("text", "")  # a milestone the bridge rendered
        if not text:
            return

        # The floor. If they are mid-sentence this waits; it is not dropped,
        # because they asked for it.
        if self.caller_speaking or self.speaking:
            self.held.append((kind, text))
            return
        await self._say(text, final=True)

    async def release_held(self) -> None:
        """Speak what waited, at the next gap."""
        while self.held and not self.caller_speaking and not self.speaking:
            _, text = self.held.pop(0)
            await self._say(text, final=True)

    # ------------------------------------------------------------- speaking --
    async def _say(self, text: str, *, final: bool) -> None:
        if not text.strip():
            return
        self.speaking = not final
        await _send_data(
            self.ten_env,
            "tts_text_input",
            "tts",
            {
                "request_id": f"turn-{self.turn_id}-{uuid.uuid4().hex[:8]}",
                "text": text,
                "text_input_end": final,
                "metadata": {"session_id": self.session_id, "turn_id": self.turn_id},
            },
        )
        if final:
            self.speaking = False
            timer = asyncio.create_task(self._settle())
            self._timers.add(timer)
            timer.add_done_callback(self._timers.discard)

    async def _settle(self) -> None:
        """A gap, then anything that was waiting for one."""
        await asyncio.sleep(0.35)
        await self.release_held()

    async def _interrupt(self) -> None:
        """Stop the model, the voice and the wire -- all three or none.

        An interrupt that reaches only one leaves the caller talking over an
        answer that is still arriving from somewhere else.
        """
        self.fragment = ""
        self.speaking = False
        await self.agent.flush_llm()
        await _send_data(self.ten_env, "tts_flush", "tts", {"flush_id": str(uuid.uuid4())})
        await _send_cmd(self.ten_env, "flush", "transport")
        # Read-only work upstream, so abandoning it needs no compensation --
        # but it is still the caller's quota being spent on an answer nobody
        # is now waiting for.
        for ticket in list(self.pending_asks):
            await self._cancel(ticket)

    async def _cancel(self, ticket: str) -> None:
        self.pending_asks.discard(ticket)
        await _send_cmd(self.ten_env, "ask_cancel", "bridge", {"ticket": ticket})

    async def _transcript(
        self,
        role: str,
        text: str,
        final: bool,
        stream_id: int,
        kind: Literal["text", "reasoning"] = "text",
    ) -> None:
        await _send_data(
            self.ten_env,
            "text_data",
            "transport",
            {
                "data_type": "transcribe" if kind == "text" else "raw",
                "role": role,
                "text": text,
                "text_ts": int(time.time() * 1000),
                "is_final": final,
                "stream_id": stream_id,
            },
        )
