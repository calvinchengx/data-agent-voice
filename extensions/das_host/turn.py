"""Deciding what the host is unsure it heard.

ASR sits upstream of every guard this system has. The SQL guard catches a
malformed or over-broad query; it cannot catch a perfectly correct query about
the wrong team, because "Billing" misheard as "Building" produces a valid
question with a wrong subject. Nothing downstream can detect that, and the
answer that comes back will be confidently wrong.

So the check happens here, before dispatch, and it costs about four hundred
milliseconds against an answer that would take twenty-six seconds to be wrong
in (docs/00-plan.md D12, §13).

Pure functions on purpose: this is the one piece of the turn policy that can be
tested without a running graph, and it is the piece most worth testing.
"""

from __future__ import annotations

import re

# Below this, a word is a guess. ASR engines disagree about scale, so this is
# a property rather than a constant and the default is deliberately cautious:
# a confirmation the caller did not need costs a second, a wrong answer costs
# their trust in every answer after it.
DEFAULT_FLOOR = 0.6

# A word worth confirming looks like a name. Three shapes, and the reason for
# each is a different way a mishearing stays invisible:
#
#   Capitalised      "Billing" for "Building" -- a valid question, wrong subject
#   Contains a digit "Q4" for "Q3" -- two characters, an entirely different answer
#   Contains - or _  "team-a" -- an identifier, and identifiers are not guessable
#
# Deliberately not a list of business terms: this repository must not know one
# service's vocabulary (§16), so it asks about the SHAPE of a word and lets the
# recogniser's confidence decide the rest.
NAMEISH = re.compile(r"^[A-Z][A-Za-z0-9_-]+$|^\w*\d[\w-]*$|^[A-Za-z]+[_-][\w-]+$")

# Words that are capitalised because a sentence starts, not because they name
# anything.
OPENERS = frozenset(
    {
        "What",
        "Which",
        "Who",
        "When",
        "Where",
        "Why",
        "How",
        "Show",
        "Tell",
        "Give",
        "Can",
        "Could",
        "Is",
        "Are",
        "Do",
        "Does",
        "Did",
        "The",
        "A",
        "An",
        "I",
        "We",
    }
)


def nameish(word: str) -> bool:
    """Does this word look like something whose mishearing would matter?"""
    return bool(NAMEISH.match(word.strip(".,?!;:'\"")))


def uncertain_terms(
    text: str, confidences: dict[str, float] | None = None, *, floor: float = DEFAULT_FLOOR
) -> list[str]:
    """The name-shaped words the recogniser was not sure about, in order.

    With no per-word confidence -- most engines do not offer it -- this returns
    nothing rather than guessing. A host that confirmed every capitalised word
    would be unusable, and one that confirmed at random would be worse than
    one that never confirmed at all.
    """
    if not confidences:
        return []
    seen: list[str] = []
    for raw in text.split():
        word = raw.strip(".,?!;:'\"")
        if not word or word in OPENERS or not nameish(word):
            continue
        score = confidences.get(word, confidences.get(word.lower(), 1.0))
        if score < floor and word not in seen:
            seen.append(word)
    return seen


def confirmation_hint(terms: list[str]) -> str:
    """What the host adds to the turn so the model knows to ask.

    A hint, not an instruction to speak: the model already knows it has a
    `confirm` tool and when to use it. Putting words in its mouth here would
    be composing the question, which is the model's job -- this only supplies
    the fact it could not otherwise have.
    """
    if not terms:
        return ""
    heard = ", ".join(f"'{t}'" for t in terms)
    return f"(the recogniser was unsure of {heard}; confirm before acting on it)"


def is_confident_partial(text: str, *, minimum_words: int = 4) -> bool:
    """Is this partial transcript worth dispatching on before it is final?

    Speculative dispatch spends tokens on a guess to save three or four hundred
    milliseconds. It is off by default and it should be: a guess that is wrong
    costs a cancelled ask and a confused turn. A partial that is already a
    whole question is the only kind worth guessing on.
    """
    words = text.split()
    if len(words) < minimum_words:
        return False
    return text.rstrip().endswith(("?", ".")) or words[0].strip("'\"").capitalize() in OPENERS
