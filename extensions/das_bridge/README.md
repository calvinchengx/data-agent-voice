# das_bridge

One ticket, followed to its end, spoken through the host.

`das_tools` dispatches a question and gets a ticket back in milliseconds. This
follows what happens next — eight to twenty-five seconds — and hands the host
something to say whenever the service has something worth saying.

## It speaks through the host, not at the voice

The host owns the floor. If this sent audio straight to the TTS node there
would be two speakers with nothing arbitrating between them, and a caller
could not tell which one to interrupt. So every utterance leaves as an
`agent_turn` and the host decides when it is said.

## It never words a refusal

| Contract event | What crosses this boundary |
|---|---|
| `refusal`, `abstention`, `error` | **the kind only** — no text at all |
| `answer` | rendered: headline, then the definition, then caveats |
| `milestone` | rendered from `{phase, subject}` by a template |
| `step`, `branch`, `accepted`, `done` | nothing — that is the panel's, not the caller's |

The model is not in this path. That is what makes *a refusal is never
narrated* a property of the graph rather than a hope about a prompt.

## Rendering is a client concern

The contract sends structure and no prose on purpose: a CLI logs a milestone,
a chat client formats it, this speaks it. `render.py` is templated rather than
model-composed — model prose here would be unbounded in length and latency and
a second place semantics could drift.

The answer order is not cosmetic. **Headline, definition, caveats**: a caveat
that arrives before the number is not heard as a caveat, and a definition that
arrives after the caller stopped listening was not applied as far as they know.
A table is never read out.

## The stream is lossless, and this takes that seriously

The contract numbers events and honours `Last-Event-ID`. A voice call outlives
more network blips than a CLI does, so a dropped connection reconnects and
resumes at the last `seq` — replaying nothing already seen, missing nothing
that happened meanwhile. A stream that closes without `done` is treated as
dropped however tidy it looked, because the contract promises `done` always
follows a terminal event.

## Cancel is best-effort, and that is fine here

Barge-in cancels the ticket. The contract guarantees no further events and
best-effort abort — a tool call already in flight completes. That is acceptable
**only** because everything upstream is read-only: there is nothing to
compensate. A failed cancel costs the caller's quota, not their conversation.
