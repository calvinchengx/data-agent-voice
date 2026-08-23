"""Can the image build yet?

`tenapp/manifest.json` names every extension the graph loads, and `tman
install` resolves each one. Stock extensions come from the pinned TEN tag; the
ones in `extensions/OWNED` come from this repository, and until every one of
them exists the build cannot succeed -- so CI skips it rather than going red on
every push, which is how people learn to stop reading CI.

Prints what is missing and exits non-zero, so the CI step can report a reason
instead of a boolean.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNED = ROOT / "extensions" / "OWNED"


def owned() -> list[str]:
    return [
        line.strip()
        for line in OWNED.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main() -> int:
    missing = [n for n in owned() if not (ROOT / "extensions" / n / "manifest.json").is_file()]
    if missing:
        print(f"not ready: {', '.join(missing)}")
        return 1
    print(f"ready: {', '.join(owned())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
