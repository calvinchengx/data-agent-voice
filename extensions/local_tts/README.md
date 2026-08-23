# local_tts

A voice that needs no account: an OpenAI-compatible `/v1/audio/speech` server
(Kokoro or Piper) over plain HTTP, plus a shelf of pre-rendered phrases served
from disk.

It exists because **TEN ships thirty-five TTS extensions at 0.11.71 and every
one of them is a vendor API** (`docs/05-ten.md` §6). A hermetic CI could not
speak, and neither could a laptop with no keys. This is the missing one, and it
is an upstream candidate for exactly that reason.

## The two sources, one path

| Text | Source | Time to first byte |
|---|---|---|
| matches a file in `phrases_dir` | that `.wav`, read from disk | ~0 |
| anything else | the speech server | ~80–200 ms |

Nothing downstream can tell which happened. That is deliberate: the
acknowledgement on a tier-2 turn is the same six words every time, and its
whole job is to arrive fast — spending a synthesis round trip on it is the
wrong 120 ms (`docs/00-plan.md` §10-5).

A phrase file is named by what it says, lowercased and hyphenated:
`Let me work that out.` → `let-me-work-that-out.wav`. It must be **16-bit mono
PCM at the graph's sample rate**; a file that is not is logged by name and
synthesized instead, because a bad recording must not silence the line.

## Configuration

| Property | Default | |
|---|---|---|
| `params.base_url` | `http://tts:8880` | the speech server |
| `params.voice` | `af_heart` | |
| `params.model` | `kokoro` | |
| `params.sample_rate` | `24000` | reported by `synthesize_audio_sample_rate()` |
| `phrases_dir` | — | the shelf; unset disables it |
| `dump` / `dump_path` | `false` | write the emitted PCM for inspection |

## The one thing to get wrong

The `pcm_frame` contract is **signed 16-bit mono**. A vendor's `"pcm"` is not
always that — the gotcha list at the pinned tag records one streaming float32
at an undeclared rate, and the result was noise. So the format is stated in
`update_params()` rather than defaulted, and the sample rate reported is the
one actually emitted.
