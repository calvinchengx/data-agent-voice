# Tiers, and what the host may say

Three tiers, decided by **which tool the model reached for** — not by a
classifier. A classifier would be a second model call on the one path that
cannot afford one.

| Tier | Example | Path | First audio | Complete |
|---|---|---|---|---|
| conversational | "wait, go back" | the host alone | ~600 ms | ~600 ms |
| definitional | "what does resolution time mean?" | one catalog hop | ~600 ms | **~1.5 s** |
| analytical | "which team resolves fastest?" | acknowledge, dispatch | ~600 ms | 8–25 s |

A lookup is tier 1 because its descriptor declares a `budget_ms` inside the
conversational budget — not because of its name. A lookup that stops being
quick stops being tier 1 by changing one number.

## What the host may and may not do

Written as assertions, not guidance, because on a voice surface the model's
freedom is the risk.

| May | May not |
|---|---|
| answer a conversational turn itself | answer a data question itself — ever |
| look up a term and say what it says | paraphrase a definition beyond its text |
| acknowledge and dispatch | promise a time |
| render a milestone from its fields | invent a milestone |
| ask a confirming question | guess a name it did not hear clearly |
| speak headline, then definition, then caveats | skip a caveat, or reorder it before the number |
| stop on interruption | keep talking past one |
| — | **speak a refusal or abstention in its own words** |

## The last row is the important one

`answer`, `abstention` and `refusal` are three distinct events upstream. The
last two cross into this repository as a **kind with no text at all**, and the
host says a fixed phrase:

| Event | Spoken |
|---|---|
| `refusal` | "You don't have access to that, so I can't answer it." |
| `abstention` | "I looked, and the data can't answer that one." |
| `error` | "Something went wrong on my side." |

The model is not in that path. It cannot smooth what it is not shown.

The refusal phrasing is the one to get right: it must not sound like the data
was missing. **"I couldn't find that" where the truth is "you may not see it"**
is the failure the whole design guards against, and a test asserts the default
says *access* and never *not found*.

Phrases are node properties, so a deployment can reword them — and a reworded
refusal is still a fixed phrase.

## Confirming what was misheard

Speech sits upstream of every guard. A misheard name produces a valid question
about the wrong subject, every check downstream passes it, and the answer comes
back confidently wrong.

So name-shaped words the recogniser was unsure of are flagged to the model,
which has a `confirm` tool and decides. Three shapes count, each a different
way a mishearing stays invisible:

| Shape | Example | Why |
|---|---|---|
| capitalised | `Billing` → `Building` | a valid question, wrong subject |
| contains a digit | `Q4` → `Q3` | two characters, an entirely different answer |
| contains `-` or `_` | `team-a` | identifiers are not guessable |

Never a list of business terms: this repository must not know one service's
vocabulary, so it asks about the **shape** of a word and lets the recogniser's
confidence decide.

Most of the tests are about what is *not* flagged. Sentence openers never are,
and with no per-word confidence nothing is — a host that confirmed every
capitalised word would be unusable, and one that confirmed at random trains the
caller to ignore confirmations.

Four hundred milliseconds of confirmation beats twenty-six seconds of being
wrong.
