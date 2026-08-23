"""The panel's arithmetic, run through node.

A browser is a bad place to discover that a percentile was wrong, and these
numbers are the demo's actual claim -- "first audio under 900 ms" is either
true or it is a slide. So the pure functions are exercised here, in the same
suite as everything else, rather than trusted because they look right.

Skipped, visibly, where node is absent.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = ROOT / "panel"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(body: str):
    """Evaluate an expression against panel/spans.js and return its JSON."""
    script = f"""
      import {{ newTurn, mark, spans, summarise, percentile, tierOf }} from '{PANEL / "spans.js"}';
      console.log(JSON.stringify((() => {{ {body} }})()));
    """
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


# ------------------------------------------------------------- percentiles --
def test_p95_is_nearest_rank_not_interpolated():
    """With five turns in a demo the honest report is the worst one. An
    interpolated p95 reports a number no turn actually took."""
    assert run("return percentile([100,200,300,400,500]);") == 500
    assert run("return percentile([100,200,300,400,500], 50);") == 300


def test_a_percentile_of_nothing_is_nothing_not_zero():
    """Zero would render as a very fast call that never happened."""
    assert run("return percentile([]);") is None
    assert run("return percentile([null, undefined]);") is None


def test_a_missing_span_does_not_drag_the_percentile_down():
    assert run("return percentile([null, 400, null, 800]);") == 800


# ------------------------------------------------------------------ spans --
def test_a_span_needs_both_of_its_marks():
    """A turn interrupted before it was answered has no answer time -- and
    must not report one."""
    assert (
        run("""
      const t = newTurn(1, 0);
      mark(t, 'transcript final', 100);
      return spans(t)['first audio'];
    """)
        is None
    )


def test_the_first_mark_wins():
    """A model streaming twenty deltas must not move 'first token' to the
    last one -- that is exactly the number caching is supposed to move."""
    assert (
        run("""
      const t = newTurn(1, 0);
      mark(t, 'transcript final', 100);
      mark(t, 'model first token', 400);
      mark(t, 'model first token', 900);
      return spans(t)['host TTFT'];
    """)
        == 300
    )


def test_first_audio_is_measured_from_the_end_of_the_question():
    """Not from the start of it: a caller who spoke for ten seconds did not
    wait ten seconds for a reply."""
    assert (
        run("""
      const t = newTurn(1, 0);
      mark(t, 'speech end', 0);
      mark(t, 'transcript final', 300);
      mark(t, 'audio out', 1100);
      return spans(t)['first audio'];
    """)
        == 800
    )


def test_end_of_utterance_is_its_own_span():
    """The largest non-LLM lever, and it must be visible separately or
    switching it off changes a total nobody can attribute."""
    assert (
        run("""
      const t = newTurn(1, 0);
      mark(t, 'speech end', 0);
      mark(t, 'transcript final', 700);
      return spans(t)['end of utterance'];
    """)
        == 700
    )


# ------------------------------------------------------------------ tiers --
def test_the_tier_is_which_tool_was_reached_for_not_an_announcement():
    assert run("const t=newTurn(1,0); t.kinds.push('dispatched'); return tierOf(t);") == 2
    assert run("const t=newTurn(1,0); t.kinds.push('looked up'); return tierOf(t);") == 1
    assert run("const t=newTurn(1,0); return tierOf(t);") == 0


def test_a_summary_reports_every_phase_even_when_empty():
    """A missing row would read as a phase that did not happen rather than one
    not yet measured."""
    summary = run("return summarise([]);")
    assert set(summary) == {"end of utterance", "host TTFT", "first audio", "answer"}
    assert all(v is None for v in summary.values())


def test_a_summary_over_real_turns_reports_the_worst():
    assert (
        run("""
      const mk = (eou) => { const t = newTurn(1,0);
        mark(t,'speech end',0); mark(t,'transcript final',eou); return t; };
      return summarise([mk(300), mk(400), mk(1200)])['end of utterance'];
    """)
        == 1200
    )


# ------------------------------------------------------------- the promise --
def test_the_panel_stores_nothing():
    """D7. A panel that kept a transcript would put the question in a second
    place, and the privacy argument upstream is that it is in no place."""
    page = (PANEL / "index.html").read_text()
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "fetch("):
        assert forbidden not in page, forbidden
