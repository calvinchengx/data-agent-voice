# Architecture

```
  browser ──── audio over WebSocket ────► TEN graph (one worker per session)
                                            │
   transport ──► stt ──► host ──► llm ──► tts ──► audio back
                          │  ▲      │
                          │  └── tools ─┬─ lookup   ─► gateway /om/mcp
                          │             └─ dispatch ─► gateway /ask ─► ticket
                          │                                             │
                          └──────── agent_turn ◄──── bridge ◄── SSE ────┘

  everything above reaches data-agent-service through the gateway,
  as the person who is speaking
```

## Two loops, one async boundary

**The conversational loop** owns every turn and has a hard budget. It
understands, acknowledges, answers what it can from metadata, and dispatches
the rest. It never blocks on anything slower than a catalog hop.

**The deliberative loop** is `data-agent-service`'s ask service. No latency
budget, its own model, its own tools, and it posts results back as events.

This repository never calls the agent library directly. It speaks the ask
contract, so it is one more client of the surface the CLI and the evals use —
and if this repository were rewritten tomorrow the service would not notice.

## The nodes

| Node | Addon | Whose |
|---|---|---|
| `transport` | `websocket_server` | TEN's |
| `stt` | `whisper_stt_python` | TEN's |
| `host` | `das_host` | **ours** — a fork of TEN's `main_python` |
| `llm` | `anthropic_llm2_python` | TEN's |
| `tools` | `das_tools` | **ours** |
| `bridge` | `das_bridge` | **ours** |
| `tts` | `local_tts` | **ours** |

Two graphs. `analyst_line` is the default and needs no GPU;
`analyst_line_semantic` adds the turn-detection node, which needs a served
model. They are separate because a node whose service is absent fails to
create, and that fails the *whole* graph — so a single graph containing it
could never start on a machine without a GPU.

There is no VAD node: `ten_vad` has no aarch64 build and one unsupported node
fails everything, so the recogniser's own `vad_filter` does the job
([upstream 6](upstream-issues.md)).

## The host owns the floor

Everything the caller hears leaves through one path in `das_host`, whether the
model composed it, the bridge brought it back, or it is a fixed phrase. That is
why the bridge speaks *through* the host rather than at the TTS node: two
speakers with nothing arbitrating between them talk over each other, and a
caller cannot tell which one to interrupt.

Barge-in stops three things — the model, the voice and the wire — and cancels
any ask in flight. All three or none: an interrupt that reaches one leaves the
caller talking over an answer still arriving from another.

## The tools are the boundary

The conversational model sees exactly three kinds of tool: a fast lookup, a
dispatch, and `confirm`. It cannot reach anything else — no MCP client, no
`run_query`, no path to the data that does not pass a guard upstream. That is
what makes *the host never answers a data question itself* a property of the
graph rather than a line in a prompt.

TEN ships an `mcp_client_python` extension that would hand the gateway's MCP
servers straight to the model. It is deliberately absent, and a test asserts
its absence.

## Identity, hop by hop

| Hop | Mechanism | Identity downstream |
|---|---|---|
| person → browser | device-code sign-in before the call | the person |
| browser → graph | the session's bearer, injected per session at `/start` | the person |
| tools → gateway `/om/mcp` | that bearer | the person; the executor picks the role bot |
| bridge → gateway `/ask` | that bearer | the person; every branch runs as them |

Nothing here holds a secret of its own beyond the host model's key. A token
that expires mid-call fails the next hop upstream and is reported as an error,
because authority expires where it always did.

## What this repository is not

It holds **no authority**. It cannot refuse, scope or admit anything — only
ask. Every guard, every rule, every audit line is upstream, and that is why a
voice client can be built at all without widening the surface that decides who
sees what.
