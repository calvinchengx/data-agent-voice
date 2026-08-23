"""Turning the ask contract's events into something a person could be told.

The contract sends structure and no prose, deliberately: a `milestone` is
`{phase, subject, source}` so that a CLI can log it, a chat client can format
it and this can speak it, each in its own words. Rendering is therefore a
client concern and lives here -- and it is templated rather than composed by a
model, because model prose on the voice path is unbounded in both length and
latency and is a second place semantics can drift (docs/00-plan.md D8).

Nothing here knows what a warehouse is. The phases are the contract's four,
and the subject is whatever vocabulary the backend used.
"""

from __future__ import annotations

# One line per phase, with and without a subject. A phase the contract adds
# later renders as nothing rather than crashing: an unknown milestone is a
# missed sentence, and a raised exception is a dropped answer.
PHASES = {
    "grounding": ("Checking what {subject} means.", "Checking the definitions."),
    "discovering": ("Looking at {subject}.", "Finding where that lives."),
    "querying": ("Running that now.", "Running that now."),
    "reconciling": ("Putting it together.", "Putting it together."),
}


def milestone(event: dict) -> str:
    """A progress line, or empty for a phase this client has no words for."""
    template = PHASES.get(str(event.get("phase", "")))
    if not template:
        return ""
    with_subject, without = template
    subject = str(event.get("subject") or "").strip()
    return with_subject.format(subject=subject) if subject else without


def answer(event: dict, *, max_caveats: int = 2) -> str:
    """The answer, in the order a listener can follow.

    Headline, then the one definition it turned on, then the caveats. That
    order is not cosmetic: a caveat that arrives before the number is not
    heard as a caveat, and a definition that arrives after the caller has
    stopped listening was not applied as far as they know.

    A table is never read out. If there is no single figure, the prose the
    service already wrote is what gets spoken -- trimmed, because a caller
    cannot skim audio.
    """
    parts: list[str] = []

    headline = event.get("headline") or {}
    if headline.get("value") is not None:
        unit = f" {headline['unit']}" if headline.get("unit") else ""
        parts.append(f"{headline.get('label', 'It')} is {headline['value']}{unit}.")
    else:
        text = str(event.get("text") or "").strip()
        if text:
            parts.append(_trim(text))

    provenance = event.get("provenance") or []
    if provenance:
        first = provenance[0]
        parts.append(f"That uses your definition of {first.get('term', 'it')}.")

    for caveat in (event.get("caveats") or [])[:max_caveats]:
        if str(caveat).strip():
            parts.append(_sentence(str(caveat)))

    return " ".join(p for p in parts if p)


def _trim(text: str, *, sentences: int = 3) -> str:
    """The first few sentences. A voice client caps its own length -- the
    contract deliberately does not, because a chat client should not be capped
    by what a speaker can say (docs/00-plan.md §16)."""
    out, count = [], 0
    for chunk in text.replace("\n", " ").split(". "):
        chunk = chunk.strip()
        if not chunk:
            continue
        out.append(chunk)
        count += 1
        if count >= sentences:
            break
    joined = ". ".join(out)
    return joined if joined.endswith((".", "!", "?")) else joined + "."


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."
