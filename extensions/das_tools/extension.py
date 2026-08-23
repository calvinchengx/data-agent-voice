"""The only tools the conversational model ever sees.

Three kinds, and the model cannot reach anything else -- no MCP client, no
`run_query`, no path to the data that does not go through a guard upstream.
That surface is what makes "the host never answers a data question itself" a
property of the graph rather than a line in a prompt (`docs/05-ten.md` §5).

    <fast lookup>   answered inside the turn, from the backend's metadata
    <dispatch>      hands the question to the ask service; returns a ticket
    confirm         asks the person to repeat a name that was not heard clearly

Their names come from `backends/*.json`, never from this file.
"""

from __future__ import annotations

import json
import pathlib

from ten_ai_base.llm_tool import AsyncLLMToolBaseExtension
from ten_ai_base.types import (
    LLMToolMetadata,
    LLMToolMetadataParameter,
    LLMToolResult,
    LLMToolResultLLMResult,
)
from ten_runtime import AsyncTenEnv, Cmd

from .client import AskClient
from .descriptor import Backend, DescriptorError, load

CONFIRM_TOOL = "confirm"
CMD_DISPATCHED = "ask_dispatched"


class DasToolsExtension(AsyncLLMToolBaseExtension):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.backends: list[Backend] = []
        self.by_tool: dict[str, Backend] = {}
        self.client: AskClient | None = None

    async def on_start(self, ten_env: AsyncTenEnv) -> None:
        directory, _ = await ten_env.get_property_string("backends_dir")
        names, _ = await ten_env.get_property_string("backends")
        insecure, _ = await ten_env.get_property_string("tls_insecure")

        try:
            self.backends = load(
                directory or str(pathlib.Path(__file__).parent.parent / "backends"),
                names or "",
            )
        except DescriptorError as e:
            # Refuse to start rather than come up with a missing tool. A line
            # whose dispatch never registered still talks -- and answers from
            # the model's own knowledge the questions it was meant to route.
            ten_env.log_error(f"das_tools: {e}")
            raise

        self.by_tool = {t: b for b in self.backends for t in b.tool_names}
        self.client = AskClient(insecure=str(insecure).lower() in ("1", "true", "yes"))
        ten_env.log_info(
            "das_tools: "
            + ", ".join(f"{b.name} ({', '.join(sorted(b.tool_names))})" for b in self.backends)
        )
        await super().on_start(ten_env)

    async def on_stop(self, ten_env: AsyncTenEnv) -> None:
        if self.client:
            await self.client.close()
        await super().on_stop(ten_env)

    async def on_cmd(self, ten_env: AsyncTenEnv, cmd: Cmd) -> None:
        await super().on_cmd(ten_env, cmd)

    # ------------------------------------------------------ what the model sees --
    def get_tool_metadata(self, ten_env: AsyncTenEnv) -> list[LLMToolMetadata]:
        tools: list[LLMToolMetadata] = []
        for backend in self.backends:
            for fast in backend.fast_tools:
                tools.append(
                    LLMToolMetadata(
                        name=fast.name,
                        description=fast.description,
                        parameters=[
                            LLMToolMetadataParameter(
                                name="query",
                                type="string",
                                description="The term or phrase to look up, in the caller's words.",
                                required=True,
                            )
                        ],
                    )
                )
            # One dispatch per backend, distinguished only by its description.
            # That is the router: with several backends the model picks between
            # them in the same turn it was already taking, so routing costs no
            # latency and there is no router to write (docs/00-plan.md §16).
            tools.append(
                LLMToolMetadata(
                    name=backend.dispatch_tool,
                    description=backend.dispatch_description,
                    parameters=[
                        LLMToolMetadataParameter(
                            name="question",
                            type="string",
                            description="The caller's question, as they asked it.",
                            required=True,
                        )
                    ],
                )
            )
        tools.append(
            LLMToolMetadata(
                name=CONFIRM_TOOL,
                description=(
                    "Ask the person to confirm a name you are not sure you heard correctly. "
                    "Use it before dispatching anything that turns on that name."
                ),
                parameters=[
                    LLMToolMetadataParameter(
                        name="heard",
                        type="string",
                        description="What you think you heard.",
                        required=True,
                    )
                ],
            )
        )
        return tools

    # ------------------------------------------------------------- running one --
    async def run_tool(self, ten_env: AsyncTenEnv, name: str, args: dict) -> LLMToolResult | None:
        if name == CONFIRM_TOOL:
            # Local, and deliberately not a question to the person: the model
            # asks it, in its own turn, with no round trip at all.
            return self._say(
                json.dumps(
                    {"confirm": args.get("heard", ""), "instruction": "Ask them to confirm."}
                )
            )

        backend = self.by_tool.get(name)
        if backend is None:
            return self._say(json.dumps({"error": f"no tool named {name}"}))

        if name == backend.dispatch_tool:
            return await self._dispatch(ten_env, backend, str(args.get("question", "")))
        return await self._lookup(ten_env, backend, name, str(args.get("query", "")))

    async def _lookup(
        self, ten_env: AsyncTenEnv, backend: Backend, name: str, query: str
    ) -> LLMToolResult:
        fast = next(t for t in backend.fast_tools if t.name == name)
        try:
            found = await self.client.lookup(backend, fast, query)
        except Exception as e:  # a lookup that fails is a turn, not an outage
            ten_env.log_warn(f"das_tools: {name} failed: {e}")
            return self._say(json.dumps({"error": "the lookup did not answer"}))
        return self._say(json.dumps(found))

    async def _dispatch(
        self, ten_env: AsyncTenEnv, backend: Backend, question: str
    ) -> LLMToolResult:
        """Hand the question over and return at once.

        The tool result deliberately carries no answer: the ask service takes
        twenty-six seconds at the median and this turn has under a second. What
        comes back is a ticket, and an instruction telling the model to
        acknowledge rather than narrate the ticket id -- the answer itself
        arrives later, spoken by the bridge.
        """
        try:
            ticket, conversation = await self.client.dispatch(backend, question)
        except Exception as e:
            ten_env.log_error(f"das_tools: dispatch to {backend.name} failed: {e}")
            return self._say(json.dumps({"error": "could not hand that over"}))

        # The bridge, not the model, follows the stream from here.
        cmd = Cmd.create(CMD_DISPATCHED)
        cmd.set_property_string("backend", backend.name)
        cmd.set_property_string("base_url", backend.base_url)
        cmd.set_property_string("ticket", ticket)
        cmd.set_property_string("conversation", conversation)
        await ten_env.send_cmd(cmd)

        return self._say(
            json.dumps(
                {
                    "dispatched": True,
                    "instruction": (
                        "Say briefly that you are working on it. Do not invent an answer, "
                        "do not promise a time, and do not read out any identifier."
                    ),
                }
            )
        )

    @staticmethod
    def _say(content: str) -> LLMToolResult:
        return LLMToolResultLLMResult(type="llmresult", content=content)
