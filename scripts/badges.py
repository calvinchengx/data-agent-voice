"""Shields.io endpoint JSON, generated from what actually ran.

The docs site publishes these files; README.md reads them back through
shields.io. The number therefore comes from `docs/witnesses.json`, which
`scripts/witnesses.py` writes from a real `pytest` run and re-verifies in CI —
so a badge that disagrees with the suite fails the build rather than
advertising a number nobody proved.

A missing or unparseable manifest is an error here, not a zero: a badge
reading 0/0 looks like a project with no tests, which would be a lie of a
different shape.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "witnesses.json"
COVERAGE = ROOT / "docs" / "coverage.json"

# This repository is Python only -- nothing here is written in Go
# (docs/05-ten.md). A go badge would be an endpoint nothing writes.

# Not flattering on purpose. A repo that fails its build under 90% should not
# paint 75% green.
SCALE = ((90, "brightgreen"), (80, "green"), (70, "yellowgreen"), (60, "yellow"), (40, "orange"))


def colour_for(pct: float) -> str:
    for floor, name in SCALE:
        if pct >= floor:
            return name
    return "red"


def badge(label: str, message: str, colour: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": colour,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory to write the badge JSON into")
    ap.add_argument(
        "--landing",
        help="a landing page whose stated witness count must match the manifest",
    )
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"FAIL: {MANIFEST} does not exist — run `make witnesses`.")
        return 1
    try:
        data = json.loads(MANIFEST.read_text())
        passed, total = int(data["passed"]), int(data["total"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"FAIL: {MANIFEST} is not a witness manifest ({e}).")
        return 1
    if total <= 0:
        print(f"FAIL: {MANIFEST} records {total} witnesses, so the badge would lie.")
        return 1

    # The front page READS the count; it does not state it. Checking a typed
    # number against the manifest was the previous design, and it fails in two
    # ways this does not: the number goes stale between the run and the edit,
    # and the check only ever saw ONE of the two places this page states the
    # total -- the stat tile was unguarded and could drift freely.
    #
    # So the check is now about the mechanism, not the value: no typed number,
    # and the page must still read the manifest published beside it.
    if args.landing:
        page = pathlib.Path(args.landing)
        if not page.exists():
            print(f"FAIL: {page} does not exist.")
            return 1
        text = page.read_text()
        typed = re.search(
            r"<b>(\d+)</b><span>\s*(?:end-to-end witnesses|checks on the design)", text
        )
        if typed:
            print(
                f"FAIL: {page} hardcodes {typed.group(1)} witnesses. The page reads "
                f"witnesses-manifest.json at run time; a typed number goes stale."
            )
            return 1
        if "data-witness-total" not in text or "witnesses-manifest.json" not in text:
            print(
                f"FAIL: {page} no longer reads witnesses-manifest.json — the front page "
                f"would show an em dash and never fill it."
            )
            return 1

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    colour = "brightgreen" if passed == total else "red"
    (out / "witnesses.json").write_text(
        json.dumps(badge("witnesses", f"{passed}/{total}", colour)) + "\n"
    )
    # The manifest itself, beside the badge. The badge is shields.io's schema --
    # a label and a message string -- and a page parsing "130/130" out of it
    # would break silently the day the label changed. The landing page reads
    # this instead, where `total` means what it says.
    (out / "witnesses-manifest.json").write_text(MANIFEST.read_text())

    # The coverage badges README.md points at. They are emitted here, from a
    # committed manifest, because the docs site never runs a test suite -- and
    # a badge whose endpoint nothing writes is a broken image on the front
    # page, which is how these two spent their first day.
    if not COVERAGE.exists():
        print(f"FAIL: {COVERAGE} does not exist — run `make witnesses`.")
        return 1
    try:
        numbers = json.loads(COVERAGE.read_text())
        python_pct = float(numbers["python"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"FAIL: {COVERAGE} is not a coverage manifest ({e}).")
        return 1

    (out / "coverage-python.json").write_text(
        json.dumps(badge("python coverage", f"{python_pct:.0f}%", colour_for(python_pct))) + "\n"
    )

    print(f"badges: witnesses={passed}/{total} python={python_pct}% → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
