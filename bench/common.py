"""Shared pieces for the latency benchmarks: the corpus, timing, and the result record.

Every number the benchmarks report is one of these, measured on the client:

  ttfa_ms    TTS: request written -> first non-empty audio byte received.
  final_ms   STT: last speech frame written -> final transcript received.
  v2v_ms     speech-to-speech: last user frame written -> first reply audio byte.
  rtt_ms     TCP connect to the provider's host, the network floor under all
             three. From Singapore a US-hosted vendor pays ~180-230 ms of this
             before its model does anything, so it is recorded beside every run
             rather than folded into a "model latency" nobody can act on.

"warm" means the connection (WebSocket or HTTP keep-alive) was already open;
"cold" includes DNS, TCP and TLS. A live line holds its connections open, so
warm is the number that matters for T_first; cold is what the first turn of a
call pays.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

# What the host actually says: short acknowledgements first (the T_first path),
# then a headline and a definition. Fixed, so every provider speaks the same
# words and the numbers are comparable.
CORPUS = [
    "Sure, let me check that.",
    "One moment while I look it up.",
    "Revenue last quarter was four point two million dollars.",
    "Active customers are counted by at least one order in the last ninety days.",
    "That figure excludes refunds, which the catalog flags as a known caveat.",
    "I can't answer that one, because you don't have access to the payroll tables.",
]


def load_env(path: Path | None = None) -> None:
    """Read KEY=value lines from the repo's .env without printing anything.

    Values already in the environment win, so a key exported in the shell is
    never overridden by the file.
    """
    path = path or ROOT.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def tcp_rtt_ms(url: str, samples: int = 5) -> float | None:
    """Median TCP connect time to the URL's host: the network round trip.

    A TCP handshake is one round trip, so this is RTT without TLS or any
    server work. None if the host cannot be reached.
    """
    u = urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme in ("https", "wss") else 80)
    try:
        addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4]
    except OSError:
        return None
    out = []
    for _ in range(samples):
        t = now_ms()
        try:
            with socket.create_connection(addr[:2], timeout=5):
                out.append(now_ms() - t)
        except OSError:
            return None
    return statistics.median(out)


@dataclass
class Run:
    provider: str
    model: str
    kind: str  # tts | stt | s2s
    text: str
    warm: bool
    value_ms: float | None
    error: str | None = None
    extra: dict = field(default_factory=dict)


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)

    def pct(p: float) -> float:
        return v[min(len(v) - 1, round(p * (len(v) - 1)))]

    return {
        "n": len(v),
        "p50": round(pct(0.5), 1),
        "p90": round(pct(0.9), 1),
        "min": round(v[0], 1),
        "max": round(v[-1], 1),
    }


def machine() -> dict:
    return {
        "host": platform.node(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def save(kind: str, runs: list[Run], meta: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {"machine": machine(), "meta": meta, "runs": [asdict(r) for r in runs]}, indent=1
        )
        + "\n"
    )
    return path
