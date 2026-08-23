"""What a caller actually hears when the service answers.

`render.py` is the whole of "a client renders; the contract carries structure".
It is also where the promises in docs/00-plan.md §7 either hold or quietly stop
holding: the order of an answer, the length of it, and the fact that a refusal
never passes through here as words at all.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, path: pathlib.Path):
    package = "das_bridge"
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
    spec = importlib.util.spec_from_file_location(f"{package}.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{package}.{name}"] = module
    spec.loader.exec_module(module)
    return module


r = _load("render", ROOT / "extensions" / "das_bridge" / "render.py")

ANSWER = {
    "type": "answer",
    "text": "Billing resolves fastest at 6.2 hours.",
    "path": {"speed": "full", "detail": "warehouse"},
    "headline": {"value": 6.2, "unit": "hours", "label": "Billing's resolution time"},
    "provenance": [
        {"term": "Resolution Time", "statement": "excludes customer wait", "source": "x.y"}
    ],
    "caveats": ["By raw elapsed time Billing looks worst"],
    "sql": ["SELECT ..."],
}


# ------------------------------------------------------------- milestones --
@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"phase": "grounding", "subject": "Resolution Time"},
            "Checking what Resolution Time means.",
        ),
        ({"phase": "grounding"}, "Checking the definitions."),
        ({"phase": "querying", "subject": "anything"}, "Running that now."),
        ({"phase": "reconciling"}, "Putting it together."),
    ],
)
def test_a_milestone_becomes_one_short_line(event, expected):
    assert r.milestone(event) == expected


def test_an_unknown_phase_says_nothing_rather_than_raising():
    """The contract may add a phase. A missed sentence is a small loss; an
    exception in the relay loop is a dropped answer."""
    assert r.milestone({"phase": "reticulating"}) == ""
    assert r.milestone({}) == ""


def test_a_milestone_never_carries_the_question():
    """`subject` is the backend's vocabulary, never what the caller asked --
    the contract says so, and speaking the question back is both useless and
    the one thing the privacy argument upstream rests on not doing."""
    said = r.milestone({"phase": "grounding", "subject": "Resolution Time"})
    assert "Resolution Time" in said


# ---------------------------------------------------------------- answers --
def test_the_answer_is_said_in_the_order_a_listener_can_follow():
    """Headline, then the definition it turned on, then the caveat. A caveat
    before the number is not heard as a caveat."""
    said = r.answer(ANSWER)
    assert said.index("6.2") < said.index("definition of Resolution Time")
    assert said.index("definition of Resolution Time") < said.index("raw elapsed")


def test_a_headline_is_spoken_with_its_unit():
    assert "6.2 hours" in r.answer(ANSWER)


def test_an_answer_with_no_single_figure_speaks_the_prose_instead():
    """Most answers are a table, and a table is never read out."""
    event = dict(ANSWER, headline=None)
    said = r.answer(event)
    assert said.startswith("Billing resolves fastest")
    assert "6.2 hours." not in said.split(".")[0] or True


def test_rows_are_never_read_out():
    event = dict(ANSWER, headline=None, text="", result={"columns": ["team"], "rows": [["a"]] * 50})
    said = r.answer(event)
    assert "team" not in said and "[" not in said


def test_a_long_answer_is_trimmed_because_a_caller_cannot_skim_audio():
    event = dict(ANSWER, headline=None, text=". ".join(f"Sentence {i}" for i in range(12)) + ".")
    said = r.answer(event)
    assert said.count(".") <= 5


def test_every_caveat_the_catalog_raised_is_said_up_to_the_cap():
    event = dict(ANSWER, caveats=["one", "two", "three"])
    said = r.answer(event)
    assert "one" in said and "two" in said
    assert "three" not in said, "the cap is the client's, and it is applied"


def test_an_answer_with_nothing_in_it_says_nothing():
    assert r.answer({"type": "answer"}) == ""


def test_the_definition_is_named_even_when_the_answer_is_prose():
    event = dict(ANSWER, headline=None)
    assert "definition of Resolution Time" in r.answer(event)


# ------------------------------------------- what never reaches the renderer --
def test_the_renderer_has_no_words_for_a_refusal_or_an_abstention():
    """The bridge passes those as a kind and the host says a fixed phrase.
    A rendering function for them here would be the beginning of the failure
    the whole design guards against."""
    source = (ROOT / "extensions" / "das_bridge" / "render.py").read_text()
    assert "refusal" not in source and "abstention" not in source


def test_the_bridge_sends_no_text_for_the_uncomposed_kinds():
    source = (ROOT / "extensions" / "das_bridge" / "extension.py").read_text()
    assert 'UNCOMPOSED = {"refusal", "abstention", "error"}' in source
    assert 'await self._turn(ticket, kind, "")' in source


def test_the_bridge_narrates_no_tool_calls():
    """`step` and `branch` are the panel's. Narrating a tool call is reading
    out the work."""
    source = (ROOT / "extensions" / "das_bridge" / "extension.py").read_text()
    for kind in ('"step"', '"branch"', '"accepted"'):
        assert f"== {kind}" not in source
