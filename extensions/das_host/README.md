# das_host

The host owns the turn, and it is **the only thing that speaks**.

A fork of TEN's `main_python` — `agent/` and `helper.py` beside this file are
taken from it unchanged, and `agent/VENDORED` records the tag. What is
inherited: interrupt on new speech, sentence chunking to TTS, turn and session
ids, tool registration. What this fork adds is what the project is about.

## One voice

Everything spoken leaves through `_say`, whether the model composed it, the
bridge brought it back from a backend, or it is a fixed phrase. Nothing else
reaches the TTS node — which is why the bridge speaks *through* here rather
than straight at it. Two speakers with no arbiter talk over each other, and a
caller cannot tell which one to interrupt.

A test asserts there is exactly one `tts_text_input` send in the file.

## A refusal is never composed

`refusal`, `abstention` and `error` arrive from the bridge as **event types**
and leave as fixed phrases the model never saw:

| The service said | The caller hears |
|---|---|
| `refusal` | "You don't have access to that, so I can't answer it." |
| `abstention` | "I looked, and the data can't answer that one." |
| `error` | "Something went wrong on my side." |

The model cannot smooth what it is not shown. Phrases are node properties, so
a deployment can reword them and they are still fixed.

The one to get right is the refusal: it must not sound like the data was
missing. "I couldn't find that" where the truth is "you may not see it" is
the failure the whole design guards against, and a test asserts the default
phrasing says *access*.

## The floor

An answer that arrives while the caller is speaking **waits** and is spoken at
the next gap — not dropped, because they asked for it, and not spoken over
them. `_settle` times the gap; the timer is held in a set so the loop cannot
collect it mid-flight and silently lose what was waiting.

## There is no tier classifier here

Tiering is *which tool the model chose*: a lookup answers inside the turn, a
dispatch does not. A classifier would be a second model call on the one path
that cannot afford one (`docs/00-plan.md` §16, D3).

## Barge-in stops three things

The model, the voice and the wire — all of them, or the caller ends up talking
over an answer still arriving from whichever one was missed. In-flight asks are
cancelled too: the work upstream is read-only so abandoning it needs no
compensation, but it is still the caller's quota being spent on an answer
nobody is waiting for.

## Configuration

| Property | Default | |
|---|---|---|
| `greeting` | *(set in the graph)* | spoken once when the first caller joins |
| `eou_mode` | `fixed` | `semantic` defers the end of turn to the detector node |
| `tts_chunk` | `sentence` | `complete` waits for the whole response — switch #4's "before" |
| `prerendered_ack` | `true` | say the acknowledgement from disk the moment a question dispatches |
| `speculative_dispatch` | `false` | spends tokens on a guess; a demo switch, not a default |
| `confirm_entities` | `true` | confirm a name heard poorly before dispatching on it |
| `*_phrase` | see above | what is said for each outcome the model never composes |
