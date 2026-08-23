"""What a backend declares about itself.

The whole of §16 lives in this file's shape. Nothing here names a catalog, a
warehouse or a glossary: it knows that a backend has *fast lookups* and a
*dispatch*, and it learns their names from a JSON file. A second service is a
descriptor, not a code path -- and `tests/test_structure.py` fails if any
general layer starts carrying one service's vocabulary.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re

# `${DAV_X}` in a descriptor is filled from the environment at load. A missing
# one is an error rather than an empty string: an unresolved base URL becomes a
# request to `/ask` on nothing, which fails much later and reads as the service
# being down.
INTERPOLATE = re.compile(r"\$\{(DAV_[A-Z0-9_]+)\}")


class DescriptorError(Exception):
    pass


def expand(value: str, env: dict[str, str]) -> str:
    def one(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in env or not env[key]:
            raise DescriptorError(f"{key} is referenced but not set")
        return env[key]

    return INTERPOLATE.sub(one, value)


@dataclasses.dataclass(frozen=True)
class FastTool:
    """A lookup answerable inside a conversational turn.

    `budget_ms` is the claim that makes it fast, and it is the client's tier-1
    test -- not the tool's name. A lookup that stops being quick stops being
    tier 1 by changing one number.
    """

    name: str
    description: str
    call: dict
    budget_ms: int


@dataclasses.dataclass(frozen=True)
class Backend:
    name: str
    display: str
    base_url: str
    audience: str
    contract_version: str
    dispatch_tool: str
    dispatch_description: str
    fast_tools: tuple[FastTool, ...]
    phrases: str

    @property
    def tool_names(self) -> set[str]:
        return {self.dispatch_tool} | {t.name for t in self.fast_tools}


def load_one(path: pathlib.Path, env: dict[str, str] | None = None) -> Backend:
    env = dict(os.environ if env is None else env)
    try:
        raw = json.loads(expand(path.read_text(), env))
    except json.JSONDecodeError as e:
        raise DescriptorError(f"{path.name} is not JSON: {e}") from None

    missing = [
        f for f in ("name", "base_url", "audience", "contract_version", "dispatch") if f not in raw
    ]
    if missing:
        raise DescriptorError(f"{path.name} declares no {', '.join(missing)}")
    if raw["name"] != path.stem:
        raise DescriptorError(f"{path.name} calls itself {raw['name']!r}")

    tools = []
    for t in raw.get("fast_tools", []):
        for field in ("name", "description", "call", "budget_ms"):
            if field not in t:
                raise DescriptorError(f"{path.name}: a fast tool declares no {field}")
        tools.append(FastTool(t["name"], t["description"], t["call"], int(t["budget_ms"])))

    return Backend(
        name=raw["name"],
        display=raw.get("display", raw["name"]),
        base_url=raw["base_url"].rstrip("/"),
        audience=raw["audience"],
        contract_version=str(raw["contract_version"]),
        dispatch_tool=raw["dispatch"]["tool"],
        dispatch_description=raw["dispatch"]["description"],
        fast_tools=tuple(tools),
        phrases=raw.get("phrases", ""),
    )


def load(
    directory: str | pathlib.Path, names: str, env: dict[str, str] | None = None
) -> list[Backend]:
    """Every backend named in `names`, in that order.

    A name with no descriptor is an error at start-up, not a tool that
    silently never appears: the model would then answer from its own knowledge
    the questions that tool existed to route, which is the one thing the host
    must never do.
    """
    directory = pathlib.Path(directory)
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    if not wanted:
        raise DescriptorError("no backend is configured; DAV_BACKENDS is empty")

    backends = []
    for name in wanted:
        path = directory / f"{name}.json"
        if not path.is_file():
            raise DescriptorError(f"backend {name!r} is configured but {path} does not exist")
        backends.append(load_one(path, env))

    # Two backends offering the same tool name would make the model's choice
    # ambiguous and the router's dispatch arbitrary.
    seen: dict[str, str] = {}
    for b in backends:
        for tool in b.tool_names:
            if tool in seen:
                raise DescriptorError(f"{b.name} and {seen[tool]} both declare a tool {tool!r}")
            seen[tool] = b.name
    return backends
