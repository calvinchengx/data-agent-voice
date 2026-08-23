"""The loader that makes a backend configuration rather than code.

§16 rests entirely on this file behaving: if a descriptor can be malformed and
still load, the line comes up with a tool missing, and the model then answers
from its own knowledge the questions that tool existed to route. That is the
one thing the host must never do, so every way a descriptor can be wrong is
asserted to be an error at start-up rather than a surprise at run time.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_module(name: str, path: pathlib.Path):
    """Import one module of an extension without the TEN runtime.

    An extension is a package whose siblings import each other relatively, so
    a bare `spec_from_file_location` fails on `from .descriptor import ...`.
    Registering the package first is what lets the parts that do NOT need the
    runtime -- the descriptor rules §16 rests on, and the response parsing --
    be tested at all. `extension.py` and `addon.py` still cannot be, and
    pyproject.toml excludes them saying so.
    """
    package = "das_tools"
    if package not in sys.modules:
        # A bare module object with a __path__, NOT the real package: its
        # __init__.py now imports the addon (which is what registers the
        # extension with the runtime), and the runtime is not installed here.
        # Executing it would fail collection for every test in this file.
        module = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec(package, None, is_package=True)
        )
        module.__path__ = [str(ROOT / "extensions" / package)]
        sys.modules[package] = module
    full = f"{package}.{name}"
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


d = _load_module("descriptor", ROOT / "extensions" / "das_tools" / "descriptor.py")

ENV = {
    "DAV_APIM_BASE": "https://gateway:8445",
    "DAV_ASK_PATH": "/ask",
    "DAV_AGENT_AUDIENCE": "api://svc",
    "DAV_OM_MCP_PATH": "/om/mcp",
}

GOOD = {
    "name": "svc",
    "display": "a service",
    "base_url": "${DAV_APIM_BASE}${DAV_ASK_PATH}",
    "audience": "${DAV_AGENT_AUDIENCE}",
    "contract_version": "1",
    "fast_tools": [
        {
            "name": "term_lookup",
            "description": "What a term means.",
            "call": {"path": "${DAV_OM_MCP_PATH}", "tool": "search"},
            "budget_ms": 400,
        }
    ],
    "dispatch": {"tool": "ask_svc", "description": "Anything slower."},
}


def write(tmp_path, name, body) -> pathlib.Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(body))
    return path


# ------------------------------------------------------------ the happy one --
def test_a_descriptor_loads_and_interpolates(tmp_path):
    b = d.load_one(write(tmp_path, "svc", GOOD), ENV)
    assert b.base_url == "https://gateway:8445/ask"
    assert b.audience == "api://svc"
    assert b.dispatch_tool == "ask_svc"
    assert [t.name for t in b.fast_tools] == ["term_lookup"]
    assert b.fast_tools[0].call["path"] == "/om/mcp"


def test_a_backend_knows_every_tool_it_offers(tmp_path):
    """The host uses this to route a call back to the right backend."""
    b = d.load_one(write(tmp_path, "svc", GOOD), ENV)
    assert b.tool_names == {"ask_svc", "term_lookup"}


def test_the_real_descriptor_this_repository_ships_loads(tmp_path):
    """Not a fixture: the file that actually configures the line."""
    env = dict(ENV, DAV_APIM_BASE="https://apim-emulator:8445")
    b = d.load_one(ROOT / "tenapp" / "backends" / "data-agent.json", env)
    assert b.name == "data-agent"
    assert b.fast_tools and all(t.budget_ms <= 1000 for t in b.fast_tools)


# ------------------------------------------------------ every way to be wrong --
def test_an_unset_setting_is_an_error_not_an_empty_string(tmp_path):
    """An unresolved base URL becomes a request to nothing, which fails much
    later and reads as the service being down."""
    with pytest.raises(d.DescriptorError, match="DAV_AGENT_AUDIENCE"):
        d.load_one(
            write(tmp_path, "svc", GOOD), {k: v for k, v in ENV.items() if "AUDIENCE" not in k}
        )


@pytest.mark.parametrize("field", ["base_url", "audience", "contract_version", "dispatch"])
def test_a_descriptor_missing_a_required_field_is_refused(tmp_path, field):
    body = {k: v for k, v in GOOD.items() if k != field}
    with pytest.raises(d.DescriptorError, match=field):
        d.load_one(write(tmp_path, "svc", body), ENV)


def test_a_descriptor_whose_name_disagrees_with_its_filename_is_refused(tmp_path):
    """`DAV_BACKENDS` names files; the file names itself. Both are used, so
    they must agree or one of them is silently ignored."""
    with pytest.raises(d.DescriptorError, match="calls itself"):
        d.load_one(write(tmp_path, "svc", dict(GOOD, name="other")), ENV)


def test_a_fast_tool_missing_its_budget_is_refused(tmp_path):
    """`budget_ms` is what makes a tool tier-1 eligible. Without it the host
    has no way to know whether the lookup fits a conversational turn."""
    body = json.loads(json.dumps(GOOD))
    del body["fast_tools"][0]["budget_ms"]
    with pytest.raises(d.DescriptorError, match="budget_ms"):
        d.load_one(write(tmp_path, "svc", body), ENV)


def test_malformed_json_names_the_file(tmp_path):
    path = tmp_path / "svc.json"
    path.write_text("{ not json")
    with pytest.raises(d.DescriptorError, match=r"svc\.json"):
        d.load_one(path, ENV)


# ---------------------------------------------------------------- the set --
def test_several_backends_load_in_the_order_configured(tmp_path):
    write(tmp_path, "svc", GOOD)
    write(
        tmp_path,
        "other",
        dict(GOOD, name="other", fast_tools=[], dispatch={"tool": "ask_other", "description": "x"}),
    )
    assert [b.name for b in d.load(tmp_path, "other,svc", ENV)] == ["other", "svc"]


def test_a_configured_backend_with_no_descriptor_is_an_error(tmp_path):
    write(tmp_path, "svc", GOOD)
    with pytest.raises(d.DescriptorError, match="ticketing"):
        d.load(tmp_path, "svc,ticketing", ENV)


def test_no_backend_configured_is_an_error(tmp_path):
    with pytest.raises(d.DescriptorError, match="empty"):
        d.load(tmp_path, "  ", ENV)


def test_two_backends_claiming_one_tool_name_are_refused(tmp_path):
    """The model chooses by tool name. Two backends offering `ask_data` makes
    the choice ambiguous and the dispatch arbitrary."""
    write(tmp_path, "svc", GOOD)
    write(tmp_path, "other", dict(GOOD, name="other"))
    with pytest.raises(d.DescriptorError, match="both declare"):
        d.load(tmp_path, "svc,other", ENV)


# ------------------------------------------------------- reaching a backend --
c = _load_module("client", ROOT / "extensions" / "das_tools" / "client.py")


def test_a_streamable_http_response_is_read_as_json_or_as_sse():
    """MCP servers may answer either way and the client does not get to
    choose. Assuming one shape is how a working server reads as a broken one."""
    assert c._parse('{"result": 1}') == {"result": 1}
    assert c._parse('event: message\ndata: {"result": 2}\n\n') == {"result": 2}


def test_an_unreadable_response_says_so_rather_than_returning_nothing():
    with pytest.raises(ValueError, match="unparseable"):
        c._parse("<html>gateway error</html>")


def test_a_client_with_no_token_sends_no_authorization_header():
    """Every call runs as the person speaking. No token is a bug to surface,
    not a header to fake."""
    assert c.AskClient()._headers == {}
    assert c.AskClient(token="abc")._headers == {"Authorization": "Bearer abc"}
