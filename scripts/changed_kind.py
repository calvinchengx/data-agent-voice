"""Does this change need the expensive jobs?

The two image jobs cost about nine minutes of runner time between them, and a
typo in a document cannot break an image. This decides, and CI hangs the image
matrix off the answer.

    python3 scripts/changed_kind.py <base-sha>      # or read paths on stdin

**It fails open.** Anything it cannot classify counts as code, and no base
commit at all means everything runs. A gate that guesses "documentation only"
when it does not know is a gate that skips the build on the one commit that
needed it -- which is worse than never having had a gate, because it looks
like it ran.

Here rather than inline in the workflow because a regex nobody can run is a
regex nobody checks: tests/test_ci_gate.py runs this one over the paths that
actually matter, including the ones that look like documentation and are not.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Paths that cannot change what the image contains or how it behaves. Note
# what is NOT here: extensions/, tenapp/, docker/, scripts/, tests/, the
# Makefile, the compose file and the workflows -- all of which can.
DOCS_ONLY = re.compile(r"^(docs/|website/|site/|README\.md$|SECURITY\.md$|LICENSE$)")


def is_docs_only(paths: list[str]) -> bool:
    """True only when every changed path is one that cannot affect the image."""
    real = [p for p in (p.strip() for p in paths) if p]
    return bool(real) and all(DOCS_ONLY.match(p) for p in real)


def changed_since(base: str) -> list[str] | None:
    """The paths changed since `base`, or None when that cannot be established."""
    if not base or set(base) == {"0"}:
        return None
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{base}^{{commit}}"], check=True, capture_output=True
        )
        out = subprocess.run(
            ["git", "diff", "--name-only", base, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.splitlines()


def main() -> int:
    paths = sys.stdin.read().splitlines() if len(sys.argv) < 2 else changed_since(sys.argv[1])
    if paths is None:
        print("code  (no usable base commit)")
        return 0
    for p in paths:
        print(f"  {p}", file=sys.stderr)
    print("docs" if is_docs_only(paths) else "code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
