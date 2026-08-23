"""The code that keeps the badges honest, kept honest.

`badges.py` exists to stop a badge advertising a number nobody proved, and
`witnesses.py` exists to stop the recorded number drifting from the suite. Both
are small, both are the last thing between a green shield and a false claim,
and neither had a test until this file -- which is the same shape of gap they
were written to close.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


badges = load("badges")
witnesses = load("witnesses")


@pytest.fixture
def ledgers(tmp_path, monkeypatch):
    """A manifest pair the module reads, isolated from the real one."""
    manifest, coverage = tmp_path / "witnesses.json", tmp_path / "coverage.json"
    monkeypatch.setattr(badges, "MANIFEST", manifest)
    monkeypatch.setattr(badges, "COVERAGE", coverage)
    return manifest, coverage


def emit(tmp_path, argv) -> int:
    sys.argv = ["badges.py", *argv]
    return badges.main()


# ------------------------------------------------------------- the scale --
@pytest.mark.parametrize(
    ("pct", "colour"),
    [(100, "brightgreen"), (90, "brightgreen"), (89, "green"), (75, "yellowgreen"), (0, "red")],
)
def test_the_colour_scale_is_not_flattering(pct, colour):
    """A repository that fails its own build under 90% must not paint 75%
    green. The scale is asserted so a later kindness to it is deliberate."""
    assert badges.colour_for(pct) == colour


# ------------------------------------------------------- refusing to lie --
def test_a_missing_manifest_is_an_error_not_a_zero(tmp_path, ledgers):
    """0/0 looks like a project with no tests, which is a lie of a different
    shape from a stale number."""
    assert emit(tmp_path, ["--out", str(tmp_path / "out")]) == 1


def test_a_manifest_recording_nothing_is_refused(tmp_path, ledgers):
    manifest, coverage = ledgers
    manifest.write_text(json.dumps({"passed": 0, "total": 0}))
    coverage.write_text(json.dumps({"python": 90.0}))
    assert emit(tmp_path, ["--out", str(tmp_path / "out")]) == 1


def test_a_landing_page_claiming_the_wrong_count_fails(tmp_path, ledgers):
    """The number in prose on the most-read page is exactly the claim that
    goes quietly stale."""
    manifest, coverage = ledgers
    manifest.write_text(json.dumps({"passed": 23, "total": 23}))
    coverage.write_text(json.dumps({"python": 90.0}))
    page = tmp_path / "index.html"
    page.write_text("<p><b>11</b><span>end-to-end witnesses</span></p>")
    assert emit(tmp_path, ["--out", str(tmp_path / "out"), "--landing", str(page)]) == 1


def test_a_landing_page_that_stopped_stating_a_count_fails(tmp_path, ledgers):
    manifest, coverage = ledgers
    manifest.write_text(json.dumps({"passed": 23, "total": 23}))
    coverage.write_text(json.dumps({"python": 90.0}))
    page = tmp_path / "index.html"
    page.write_text("<p>lots of witnesses</p>")
    assert emit(tmp_path, ["--out", str(tmp_path / "out"), "--landing", str(page)]) == 1


def test_the_real_landing_page_and_manifest_agree(tmp_path):
    """Not a fixture: the files this repository actually publishes."""
    assert (
        emit(
            tmp_path,
            ["--out", str(tmp_path / "out"), "--landing", str(ROOT / "site" / "index.html")],
        )
        == 0
    )
    out = tmp_path / "out"
    witness = json.loads((out / "witnesses.json").read_text())
    recorded = json.loads((ROOT / "docs" / "witnesses.json").read_text())
    assert witness["message"] == f"{recorded['passed']}/{recorded['total']}"
    assert (out / "coverage-python.json").exists()


def test_no_go_badge_is_emitted(tmp_path):
    """Nothing here is written in Go (docs/05-ten.md). A badge whose endpoint
    nothing writes is a broken image on the front page."""
    emit(tmp_path, ["--out", str(tmp_path / "out")])
    assert not (tmp_path / "out" / "coverage-go.json").exists()


def test_a_failing_suite_paints_the_witness_badge_red(tmp_path, ledgers):
    manifest, coverage = ledgers
    manifest.write_text(json.dumps({"passed": 20, "total": 23}))
    coverage.write_text(json.dumps({"python": 90.0}))
    assert emit(tmp_path, ["--out", str(tmp_path / "out")]) == 0
    assert json.loads((tmp_path / "out" / "witnesses.json").read_text())["color"] == "red"


# -------------------------------------------------------------- the drift --
def test_a_recorded_count_that_drifted_from_the_suite_fails(monkeypatch, tmp_path):
    manifest, coverage = tmp_path / "w.json", tmp_path / "c.json"
    manifest.write_text(json.dumps({"passed": 11, "total": 11}))
    coverage.write_text(json.dumps({"python": 50.0}))
    monkeypatch.setattr(witnesses, "MANIFEST", manifest)
    monkeypatch.setattr(witnesses, "COVERAGE", coverage)
    monkeypatch.setattr(witnesses, "run_suite", lambda: (23, 23, 50.0))
    sys.argv = ["witnesses.py", "--check"]
    assert witnesses.main() == 1


def test_coverage_inside_the_tolerance_is_not_drift(monkeypatch, tmp_path):
    """Coverage moves by rounding; the count does not. They get different
    rules on purpose."""
    manifest, coverage = tmp_path / "w.json", tmp_path / "c.json"
    manifest.write_text(json.dumps({"passed": 23, "total": 23}))
    coverage.write_text(json.dumps({"python": 90.0}))
    monkeypatch.setattr(witnesses, "MANIFEST", manifest)
    monkeypatch.setattr(witnesses, "COVERAGE", coverage)
    monkeypatch.setattr(witnesses, "run_suite", lambda: (23, 23, 90.3))
    sys.argv = ["witnesses.py", "--check"]
    assert witnesses.main() == 0
    monkeypatch.setattr(witnesses, "run_suite", lambda: (23, 23, 85.0))
    assert witnesses.main() == 1


def test_a_suite_that_reported_nothing_is_an_error(monkeypatch):
    monkeypatch.setattr(
        witnesses.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"stdout": "no tests ran", "stderr": ""})(),
    )
    with pytest.raises(SystemExit):
        witnesses.run_suite()
