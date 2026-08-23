"""The configuration, held to itself.

There is no runtime here yet: the four extensions the graph names are the next
commit. What exists is a set of files that have to agree with each other -- a
graph naming addons, a manifest naming paths, descriptors naming env keys, a
plan naming phases -- and every one of those agreements has already been got
wrong once today in the repository next door. So they are asserted.

These are witnesses in the family's sense: each one names a claim the README
or the plan makes, and fails when the claim stops being true. What they cannot
do is tell you the line works; only a running graph does that, and
docs/parity.md says so rather than letting a green suite imply it.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TENAPP = ROOT / "tenapp"
GRAPH = json.loads((TENAPP / "property.json").read_text())["ten"]["predefined_graphs"][0]
NODES = {n["name"]: n for n in GRAPH["graph"]["nodes"]}
MANIFEST = json.loads((TENAPP / "manifest.json").read_text())
ENV_EXAMPLE = (ROOT / ".env.example").read_text()
PLAN = (ROOT / "docs" / "00-plan.md").read_text()

# The extensions this repository writes, as opposed to the ones it takes from
# the pinned tag. Read from the file the CI image gate also reads, so the two
# cannot drift into disagreeing about what "written" means.
OURS = {
    line.strip()
    for line in (ROOT / "extensions" / "OWNED").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}


def env_keys(text: str) -> set[str]:
    return {line.split("=", 1)[0] for line in text.splitlines() if line.startswith("DAV_")}


# ------------------------------------------------------------- the graph --
def test_every_addon_the_graph_names_is_declared_as_a_dependency():
    """A node naming an addon the manifest does not depend on installs nothing
    and fails at run time, which is the worst place to learn it."""
    declared = {pathlib.PurePath(d["path"]).name for d in MANIFEST["dependencies"] if "path" in d}
    named = {n["addon"] for n in NODES.values()}
    assert named <= declared, f"undeclared: {sorted(named - declared)}"


def test_the_graph_does_not_start_itself():
    """A session is created by POST /start, which injects the caller's token.
    An auto-started graph would run with no one signed in."""
    assert GRAPH["auto_start"] is False


@pytest.mark.parametrize("name", ["transport", "stt", "host", "llm", "tools", "bridge", "tts"])
def test_the_line_has_the_node_the_plan_describes(name):
    assert name in NODES


def test_the_host_is_the_only_node_that_reaches_the_model():
    """§7 of the plan: the host owns the turn. A second path to the LLM would
    be a second place a data question could be answered without a guard."""
    to_llm = [
        c
        for c in GRAPH["graph"]["connections"]
        for kind in ("data", "cmd")
        for entry in c.get(kind, [])
        for d in entry.get("dest", [])
        if d["extension"] == "llm"
    ]
    sources = {
        c["extension"]
        for c in GRAPH["graph"]["connections"]
        if any(
            d["extension"] == "llm"
            for kind in ("data", "cmd")
            for entry in c.get(kind, [])
            for d in entry.get("dest", [])
        )
    }
    assert to_llm, "nothing reaches the model at all"
    assert sources == {"host"}, f"these also reach the model: {sorted(sources - {'host'})}"


def test_the_mcp_client_extension_is_absent():
    """docs/05-ten.md §5: mcp_client_python would hand run_query to the
    conversational model. Its absence is a decision, so it is asserted."""
    named = {n["addon"] for n in NODES.values()}
    declared = {pathlib.PurePath(d["path"]).name for d in MANIFEST["dependencies"] if "path" in d}
    assert "mcp_client_python" not in named | declared


def test_barge_in_reaches_the_model_the_voice_and_the_wire():
    """An interrupt that stops only one of the three leaves the caller talking
    over an answer that is still arriving."""
    flush = [
        entry
        for c in GRAPH["graph"]["connections"]
        if c["extension"] == "host"
        for entry in c.get("cmd", [])
        if "flush" in entry.get("names", [])
    ]
    assert flush, "the host sends no flush"
    dests = {d["extension"] for d in flush[0]["dest"]}
    assert {"llm", "tts", "transport"} <= dests, (
        f"flush misses {sorted({'llm', 'tts', 'transport'} - dests)}"
    )


# -------------------------------------------------------------- backends --
def test_every_configured_backend_has_a_descriptor():
    names = [
        n.strip() for n in re.search(r"^DAV_BACKENDS=(.*)$", ENV_EXAMPLE, re.M).group(1).split(",")
    ]
    for name in names:
        assert (TENAPP / "backends" / f"{name}.json").exists(), name


@pytest.mark.parametrize("path", sorted((TENAPP / "backends").glob("*.json")), ids=lambda p: p.stem)
def test_a_descriptor_declares_what_the_loader_needs(path):
    d = json.loads(path.read_text())
    assert d["name"] == path.stem
    for field in ("display", "base_url", "audience", "contract_version", "dispatch"):
        assert field in d, field
    assert d["dispatch"]["tool"] and d["dispatch"]["description"]
    for tool in d.get("fast_tools", []):
        assert tool["budget_ms"] <= 1000, "a fast tool that is not fast is a tier-2 question"
        assert tool["name"] and tool["description"] and tool["call"]


@pytest.mark.parametrize("path", sorted((TENAPP / "backends").glob("*.json")), ids=lambda p: p.stem)
def test_a_descriptor_interpolates_only_declared_settings(path):
    """A descriptor naming a setting that is in no template is a runtime
    KeyError on the first call, in a graph node, in a container."""
    referenced = set(re.findall(r"\$\{(DAV_[A-Z0-9_]+)\}", path.read_text()))
    assert referenced <= env_keys(ENV_EXAMPLE), sorted(referenced - env_keys(ENV_EXAMPLE))


def test_nothing_in_this_repo_hardcodes_the_first_backend_s_vocabulary():
    """§16: would a ticketing agent want this? A graph or a template that says
    `catalog`, `warehouse` or `glossary` outside a descriptor has put one
    service's words in the general layer."""
    domain = re.compile(r"\b(catalog|warehouse|glossary|sql)\b", re.I)
    for f in (TENAPP / "property.json", ROOT / ".env.example"):
        hits = [line for line in f.read_text().splitlines() if domain.search(line)]
        assert not hits, f"{f.name}: {hits[:2]}"


# ----------------------------------------------------- settings and plan --
def test_every_setting_the_graph_reads_is_in_the_template():
    referenced = set(
        re.findall(r"\$\{env:(DAV_[A-Z0-9_]+)", (TENAPP / "property.json").read_text())
    )
    assert referenced <= env_keys(ENV_EXAMPLE), sorted(referenced - env_keys(ENV_EXAMPLE))


def test_the_switches_the_plan_lists_are_all_settings():
    """Each row of §10 is meant to be a flag someone can turn. A switch that is
    only prose is a claim the demo cannot make."""
    switches = set(re.findall(r"`(DAV_[A-Z0-9_]+)`", PLAN))
    assert switches <= env_keys(ENV_EXAMPLE), sorted(switches - env_keys(ENV_EXAMPLE))


def test_the_plan_sections_are_in_order():
    numbers = [int(m) for m in re.findall(r"^## (\d+)\.", PLAN, re.M)]
    assert numbers == sorted(numbers) and len(numbers) == len(set(numbers))


def test_the_plan_states_it_is_a_draft_until_something_is_built():
    assert PLAN.splitlines()[2].startswith("Status: **DRAFT")


def test_the_ten_pin_is_one_version_everywhere():
    """Three files name it: the template, the compose build arg and the
    Dockerfile default. A pin that disagrees with itself is not a pin."""
    pinned = re.search(r"^TEN_VERSION=(\S+)$", ENV_EXAMPLE, re.M).group(1)
    compose = (ROOT / "docker-compose.yml").read_text()
    dockerfile = (ROOT / "docker" / "ten" / "Dockerfile").read_text()
    assert f"TEN_VERSION:-{pinned}" in compose
    assert f"ARG TEN_VERSION={pinned}" in dockerfile
    assert pinned in (ROOT / "docs" / "05-ten.md").read_text()


# --------------------------------------------------------------- ledgers --
def test_the_ledger_claims_nothing_that_has_not_been_run():
    """The family rule: a row may describe what is designed, never assert what
    was never executed. Nothing here has run, so every row says so."""
    parity = (ROOT / "docs" / "parity.md").read_text()
    rows = [
        r
        for r in parity.splitlines()
        if r.startswith("| ") and "---" not in r and "Witnessed locally" not in r
    ]
    claims = [r for r in rows if "not yet" not in r and "n/a" not in r]
    assert rows, "the ledger has no rows"
    assert not claims, claims[0][:90]


def test_the_readme_points_at_a_plan_that_exists():
    readme = (ROOT / "README.md").read_text()
    for link in re.findall(r"\]\((docs/[^)#]+)", readme):
        assert (ROOT / link).exists(), link


def test_every_extension_this_repo_owns_is_named_by_the_graph():
    """A file in OWNED that the graph never loads is dead weight; an addon the
    graph names that is in neither OWNED nor the pinned tag fails at
    `tman install`, in a container, minutes into a build."""
    named = {n["addon"] for n in NODES.values()}
    assert not OURS - named, f"owned but unused: {sorted(OURS - named)}"


def test_the_image_gate_agrees_with_what_is_written():
    """`make test` passing while CI silently skips the image build would hide
    exactly the state this repository is in."""
    ready = importlib.util.spec_from_file_location(
        "image_ready", ROOT / "scripts" / "image_ready.py"
    )
    module = importlib.util.module_from_spec(ready)
    ready.loader.exec_module(module)
    written = {n for n in OURS if (ROOT / "extensions" / n / "manifest.json").is_file()}
    assert (module.main() == 0) == (written == OURS)


@pytest.mark.parametrize("name", sorted(OURS))
def test_an_extension_registers_its_addon_on_import(name):
    """An empty `__init__.py` leaves an extension present on disk, structurally
    identical to a working one, and invisible to the runtime: "Failed to load
    the addon using all addon loaders" with no traceback, because nothing was
    ever imported to fail. Cost an hour to find once."""
    init = (ROOT / "extensions" / name / "__init__.py").read_text()
    assert "from . import addon" in init, name
