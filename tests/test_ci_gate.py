"""The gate that decides whether the expensive jobs run.

Nine minutes of runner time hangs off this, and both ways of being wrong are
bad in different ways: too eager wastes the time the gate exists to save, too
lax skips the build on a commit that needed it and reports green. The second
is much worse, so the rule is that anything unclassifiable counts as code —
and these tests are mostly about the paths that LOOK like documentation.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("changed_kind", ROOT / "scripts" / "changed_kind.py")
gate = importlib.util.module_from_spec(spec)
sys.modules["changed_kind"] = gate
spec.loader.exec_module(gate)


# ------------------------------------------------------------- docs only --
@pytest.mark.parametrize(
    "paths",
    [
        ["docs/00-plan.md"],
        ["README.md"],
        ["docs/parity.md", "docs/upstream-issues.md"],
        ["website/astro.config.ts"],
        ["site/index.html"],
        ["SECURITY.md"],
        ["LICENSE"],
        ["docs/05-ten.md", "README.md", "website/package.json"],
    ],
)
def test_a_documentation_change_does_not_need_an_image(paths):
    assert gate.is_docs_only(paths)


# ------------------------------------------------- looks like docs, is not --
@pytest.mark.parametrize(
    ("path", "why"),
    [
        ("extensions/das_host/README.md", "inside the build context, and manifests package it"),
        ("panel/README.md", "the panel image copies its directory"),
        ("docker/ten/README.md", "next to the Dockerfile"),
        ("tenapp/backends/data-agent.json", "configuration the graph loads"),
        ("Makefile", "how the image is built"),
        ("docker-compose.yml", "what runs and on which platform"),
        (".github/workflows/ci.yml", "the gate itself"),
        ("scripts/changed_kind.py", "the gate itself"),
        ("tests/test_turn.py", "a test is not documentation"),
        ("pyproject.toml", "lint and coverage rules"),
        (".env.example", "what the graph reads"),
    ],
)
def test_a_path_that_looks_like_documentation_but_is_not(path, why):
    """Every one of these has a README-ish or config-ish name and every one can
    change what the image does. The regex is anchored so `docs/` means the
    directory at the root, never `extensions/x/docs/`."""
    assert not gate.is_docs_only([path]), why


def test_one_code_path_among_many_documents_still_means_code():
    """The common shape: a change that updates the plan AND the thing the plan
    describes."""
    assert not gate.is_docs_only(["docs/00-plan.md", "README.md", "extensions/das_host/turn.py"])


# ------------------------------------------------------------ failing open --
def test_no_changed_paths_at_all_is_not_docs_only():
    """An empty diff means the gate learned nothing, not that nothing needs
    building."""
    assert not gate.is_docs_only([])
    assert not gate.is_docs_only(["", "  "])


def test_an_unusable_base_commit_yields_no_paths_rather_than_an_empty_diff():
    """A first push, a force push or a re-run. `None` is the signal the caller
    turns into "run everything"; an empty list would be indistinguishable from
    a diff with nothing in it."""
    assert gate.changed_since("") is None
    assert gate.changed_since("0" * 40) is None
    assert gate.changed_since("not-a-sha") is None


def test_the_workflow_treats_only_the_word_docs_as_a_skip():
    """The script prints `docs` or `code`, and the workflow skips only on an
    exact `docs`. Anything else -- an error, an empty line, a future third
    answer -- runs the build."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert 'if [ "$kind" = "docs" ]; then' in workflow
    assert 'echo "code=false"' in workflow
    assert "needs.changes.outputs.code == 'true'" in workflow


def test_the_gate_runs_against_this_repository_without_error():
    """It shells out to git; a signature change or a missing binary would fail
    here rather than in CI."""
    assert gate.changed_since("HEAD~1") is not None
