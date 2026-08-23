"""Record what the suite actually witnessed, for the badge to read back.

`docs/witnesses.json` is written from a real `pytest` run and `--check`
re-verifies it, so a badge can never advertise a number nobody proved. Same
convention as the family: the manifest is committed, CI re-runs the suite and
fails if the recorded figure has drifted.

Coverage is recorded the same way, and is deliberately measured over
`scripts/` alone. The extensions are not written yet; measuring a package that
does not exist would report 100% of nothing, which is the badge lying in the
flattering direction.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "witnesses.json"
COVERAGE = ROOT / "docs" / "coverage.json"
TOLERANCE = 0.5


def run_suite() -> tuple[int, int, float]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--cov=scripts", "--cov-report=term"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    tally = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    if not tally:
        print(out[-2000:])
        raise SystemExit("the suite reported no passing tests")
    passed = int(tally.group(1))
    total = passed + (int(failed.group(1)) if failed else 0)
    pct = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", out, re.M)
    return passed, total, float(pct.group(1)) if pct else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check", action="store_true", help="fail if the recorded figures have drifted"
    )
    args = ap.parse_args()

    passed, total, pct = run_suite()
    if args.check:
        recorded = json.loads(MANIFEST.read_text())
        if (recorded["passed"], recorded["total"]) != (passed, total):
            print(
                f"FAIL: manifest records {recorded['passed']}/{recorded['total']}, "
                f"the suite witnessed {passed}/{total}"
            )
            return 1
        was = float(json.loads(COVERAGE.read_text())["python"])
        if abs(was - pct) > TOLERANCE:
            print(f"FAIL: coverage recorded {was}%, measured {pct}%")
            return 1
        print(f"witnesses: {passed}/{total}, coverage {pct}% — the manifests agree")
        return 0

    MANIFEST.write_text(json.dumps({"passed": passed, "total": total}, indent=2) + "\n")
    COVERAGE.write_text(json.dumps({"python": pct}, indent=2) + "\n")
    print(f"witnesses: {passed}/{total}, coverage {pct}% → recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
