# Latency

Four numbers, and only one of them is felt.

| | |
|---|---|
| `T_first` | time to the first audible thing |
| `T_useful` | time to something the caller can act on |
| `T_complete` | total |
| `T_perceived` | what they would say afterwards |

Almost every optimization attacks `T_complete`. Callers feel `T_first` and
remember `T_perceived`, which tracks **silence and variance**, not duration. A
twelve-second answer narrated every three seconds feels responsive; four
seconds of nothing feels broken.

## The budget

Estimates, not measurements. The panel replaces each one with a measured
number, and this table is rewritten when it does.

| Segment | Estimate |
|---|---|
| WebSocket in | 20–40 ms |
| End of utterance | 500–800 ms fixed; 200–400 semantic, **on a GPU-served model** |
| ASR finalize | 50–150 ms |
| Host TTFT | 400–700 ms uncached; 200–400 once the cache patch lands |
| TTS time-to-first-byte | 80–200 ms; **≈ 0** pre-rendered |
| Playback | 40–80 ms |

| Tier | First audio | Complete |
|---|---|---|
| conversational | 600–900 ms | same |
| definitional | 600–900 ms | 1.4–1.9 s |
| analytical | 500–900 ms | 8–14 s p50 |

**First audio is tier-independent, and that is the whole trick.** The host
speaks before any tool resolves, so a caller cannot tell from the onset which
tier they hit.

## The switches

Each is a setting the graph reads and a delta the panel shows. A lever an
audience cannot hear is a claim, not a demonstration.

| # | Setting | Off | On |
|---|---|---|---|
| 1 | `DAV_EOU_MODE` | fixed silence (CI) | the turn detector, on a GPU |
| 2 | `DAV_CACHE_PREFIX` | no breakpoint | cached prefix, once the patch lands |
| 3 | `DAV_HOST_MODEL` | Opus | Haiku |
| 4 | `DAV_TTS_CHUNK` | wait for the whole response | speak each sentence |
| 5 | `DAV_PRERENDERED_ACK` | synthesize live | served from disk |
| 6 | `DAV_SPECULATIVE_DISPATCH` | wait for a final transcript | guess on a confident partial |

Defaults are the CI shape, because a default nobody exercises is not a default.

## Where the seconds actually are

Worth stating plainly, because it is easy to spend effort in the wrong place:

| Lever | Effect on the analytical path | Whose |
|---|---|---|
| Model and effort per hop | **−8 to −12 s** | upstream's |
| Prompt caching | −1.5 to −4 s | upstream's |
| Parallel tool calls | 7 hops → 4–5 | upstream's |
| Sub-agent fan-out | −1 to −3 s | upstream's |
| Everything in this repository | **0 s** | ours |

Nothing here makes the agent faster. What it changes is `T_first` and
`T_perceived` — from twenty-six seconds of silence to under a second of
acknowledgement, followed by narration. That is the entire contribution, and
it is worth more than any of the rows above.

## Two things that are easy to get wrong

**Speaking per sentence beats every token-level optimization.** The caller
hears the first clause, not the last token. Total generation time is nearly
irrelevant to how it feels.

**Tokens not generated are the cheapest latency win there is.** The answer is
spoken as headline, then definition, then caveats — so the useful part arrives
first and the rest can be interrupted without loss.
