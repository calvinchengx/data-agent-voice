# Data Agent Voice — Architecture & Implementation Plan

Status: **DRAFT for review — no implementation started.** Last updated 2026-08-23.

Repo: `~/calvinchengx/emulators/data-agent-voice` · Family tier: **leaf / consumer** — it consumes `data-agent-service`, which consumes the emulators; it emulates nothing · License: Apache-2.0 · Product name inside the repo: **the Analyst Line**.

Goal: a person talks to their governed data. They sign in once, ask questions by voice, and hear answers that carry the definition applied and the caveat the catalog raised — spoken, not read. Every question runs as the person asking, all the way to the source, through `data-agent-service` unchanged. The demo shows three things at once: a conversation that feels live over an agent that takes 26 seconds; a supervisor with sub-agents working behind that conversation; and every latency optimization as a switch the audience can hear.

The thesis this repo exists to demonstrate: **a conversational surface over a slow, careful agent is an architecture problem, not a model-speed problem.** The agent never gets fast enough. The conversation stops waiting for it.

---

## 0. Implementation discipline (non-negotiable)

Inherited from `data-agent-service` and extended by one rule.

| Rule | Meaning | Enforcement |
|---|---|---|
| **Dependencies as-is** | `data-agent-service`, the emulators, OpenMetadata and the TEN framework are consumed by published image or package and never modified. A suspected bug is written up in `docs/upstream-issues.md`. Only `data-agent-voice` is built here. | Compose pins published images; TEN pinned by version; no forks |
| **Prod-identical** | No emulator-only code path. The voice stack reaches the data only through the gateway with the user's own token, exactly as any MCP client. `ENV=prod` swaps `.env` and nothing else — including the speech provider. | CI grep-gate for forbidden endpoints; `make test ENV=prod` runs unchanged |
| **Nothing voice-shaped leaks upstream** | Anything a Slack bot would also want belongs in `data-agent-service`'s ask contract and is proposed there. Anything only a voice client wants — caps, tiers, fillers, barge-in — lives here. | Review rule; `docs/20-ask-service.md` upstream names the test |
| **The guards are not here** | This repo holds no authority. It cannot refuse, scope, or admit anything; it can only ask. A refusal arrives as a `refusal` event and is spoken from a fixed phrase, never paraphrased by a model. | Witness: a refused question produces the refusal phrase verbatim |

---

## 1. Key criteria (acceptance)

| # | Criterion | How the plan meets it | Witness |
|---|---|---|---|
| 1 | **Conversational onset** — first audio under 900 ms at p95 regardless of what was asked | The host speaks before any tool resolves; pre-rendered acknowledgements; semantic end-of-utterance | Instrument panel p95 `time-to-first-audio`, gated in `make test` |
| 2 | **Honest about the slow path** — an analytical answer arrives in 8–25 s and the design says so | Tier 2 dispatches to the ask service and narrates milestones; no filler pretends otherwise | Panel shows both onset and completion; docs quote both |
| 3 | **Supervisor and sub-agents are real and visible** | `branch` events from the ask service rendered live; the roster is whatever `DAS_SOURCES` configures | Witness: a cross-source question shows N branches, N = configured sources |
| 4 | **Every optimization is a switch** | Each lever in §10 has an env flag, and the panel shows the delta | Witness per switch: off vs on, measured |
| 5 | **Refusals and abstentions are never narrated** | Fixed phrases bound to the event type; the host model never sees the refusal text as something to rewrite | Witness: `reader-only` persona asks a finance question, hears the refusal phrase verbatim |
| 6 | **ASR errors cannot become wrong answers silently** | High-stakes entities confirmed before dispatch; a seeded mis-transcription must produce a confirmation | Witness: "Building" for "Billing" yields a question, not an answer |
| 7 | **Barge-in cancels all the way down** | TTS flushed, host aborted, ask ticket cancelled | Witness: interrupt mid-answer; ask service emits `error{cancelled}` within 1 s |
| 8 | **Prod-identical speech** | Local models in CI; cloud provider by `.env` | `make test ENV=prod` with a cloud ASR/TTS, unchanged |
| 9 | **Runs on a laptop beside the family** | One compose file; `make up` brings TEN + local speech + the `data-agent-service` stack | `make doctor` / `make status` |

---

## 2. Findings that constrain the design

| Fact | Source | Consequence |
|---|---|---|
| A question takes **26 s p50, 39–48 s p95**, 6–8 tool calls, Opus 5 at effort `high` on every hop | `data-agent-service` eval reports | The analytical path cannot be on a voice turn. Two loops, async boundary (D1) |
| Gateway + executor: 23 ms p50 / 70 ms p95; catalog search 61 / 147 ms | `data-agent-service/docs/08-load-testing.md` | A definitional question can be answered in one catalog hop inside the conversational budget — the fast path is real (D3) |
| The ask contract exists: ticket before any tool call; lossless SSE; `milestone` is structured, not prose; `answer`/`abstention`/`refusal` are three terminal types; `path: catalog\|warehouse\|multi` on every answer; `branch` events from phase 1 | `data-agent-service/agent/contract/`, `docs/20-ask-service.md` | This repo renders; it does not decide. Tiering is a client policy over `path` |
| The ask service is **contract only** today — `agent/server.py` is not written | same | Phase 0 here builds against a stub; the witness suite is written to the contract |
| `DAS_RATE_CALLS=60/60s` per caller, and every sub-agent runs as the same user | `data-agent-service/.env.example` | A voice conversation plus fan-out can throttle itself. Rate tier for the voice caller, or the supervisor front-loads schema so branches do not rediscover it; decided upstream, tracked in §13 |
| Human turn gap ≈ 200 ms; > 800 ms reads as thinking; > 1.5 s reads as broken | conversation-design literature; **to be measured on this stack** | The budget in §9. Treated as a hypothesis until the panel confirms it |
| Fixed-silence end-of-utterance costs 500–800 ms; model-based EOU 200–400 ms | TEN turn-detection extension docs, **to confirm at the pinned version** | The single largest non-LLM lever (§10) |
| TEN models a graph of extensions passing `cmd` / `data` / `audio_frame` with interrupt propagation | TEN framework docs, **to confirm at the pinned version** | Two custom extensions (§5); everything else stock |
| ASR has no emulator. Speech in CI is either a paid cloud call or local weights | — | Local models (faster-whisper, Piper or Kokoro) in CI; cloud by `.env` (D5). The weights are the one large artefact this repo carries |
| `data-agent-service` has device-code sign-in in `agent/identity.py` | upstream | The person signs in before the call; the token is held for the session (D6) |
| The promoter's privacy argument: the only claim that survives is that the data is not there | `data-agent-service/promoter/__init__.py` | No transcript is stored. Audio is not retained. The question text exists in the ask service's `accepted` event and nowhere here (D7) |

---

## 3. Architecture

```
 browser (WebRTC)  ──────────────────────────────────────────────────────────────┐
                                                                                 │
 TEN graph  ────────────────────────────────────────────────────────────────     │
   audio in → VAD → streaming ASR → semantic EOU                                  │
                         ↓ partial + final transcript                            │
   [das_host]  Haiku 4.5 · streaming · effort low · cached prefix                 │
       tools:  glossary_lookup(term)   → catalog MCP through the gateway (147 ms) │
               dispatch(question)      → POST /ask …/asks   → ticket   (~5 ms)   │
               confirm(entity)         → local, no network                       │
       policy: tier 0 answer · tier 1 lookup then answer · tier 2 ack + dispatch  │
                         ↓ sentence chunks                                       │
   TTS (streaming) → jitter buffer → audio out ──────────────────────────────────┘
                         ↑
   [das_bridge]  SSE client on /ask/v1/asks/{ticket}/events
                 milestone → rendered sentence → host → TTS   (agent-initiated turn)
                 answer    → headline, definition, caveat → host → TTS
                 refusal / abstention → FIXED PHRASE → TTS   (host bypassed)
                 barge-in  → flush TTS, abort host, POST …/cancel

 data-agent-service (unchanged; consumed by image)  ── apim :8446 ──
   /ask        the ask service: supervisor + branches, Opus 5, effort high
   /om/mcp     the catalog, as the caller's role bot
   /warehouse  the executor, as the caller
```

Two loops, one async boundary:

* **The conversational loop** owns every turn and has a hard latency budget. It understands, acknowledges, answers what it can from the catalog, and dispatches the rest. It never blocks on anything slower than a catalog hop.
* **The deliberative loop** is `data-agent-service`'s ask service. It has no latency budget, runs the supervisor and its branches, and posts results back as events. This repo never calls the agent library directly; it speaks the ask contract, so it is one more client of the same surface the CLI and the evals use.

Everything in the data path — identity, guards, authorization, audit — is upstream and untouched. What this repo adds is the wait.

---

## 4. Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Where the agent runs | **Off the voice turn**, behind the ask contract | 26 s cannot be made 0.8 s; the conversation stops waiting instead |
| D2 | Who orchestrates sub-agents | **The ask service upstream**, never the host | A host that fans out becomes latency-bound and the two-loop design collapses |
| D3 | Turn policy | **Three tiers, decided by the host in its first tokens**: 0 conversational, 1 definitional (one catalog hop), 2 analytical (dispatch) | Definitional questions are a large share of what analysts ask and fit the budget; `path` on answers is the general signal this policy rides on |
| D4 | Host model | **Haiku 4.5, effort `low`, cached prefix, streaming** | The host speaks sentences; prefill is most of its time; caching is decisive here and not upstream |
| D5 | Speech | **Local in CI** (faster-whisper; Piper or Kokoro), **cloud by `.env`** | Hermetic CI, prod-identical by configuration — the family rule one level up |
| D6 | Identity | **Device-code sign-in before the call; token held for the session; refresh via upstream `identity.py`** | Every hop downstream is as the user. Re-auth mid-call is a known unsolved UX (§13) |
| D7 | Retention | **No audio, no transcript, no question stored here** | The promoter's argument. The panel records timings and event types only |
| D8 | Milestone rendering | **Templates from `milestone.{phase, subject, source}`**, never model prose | Bounded length, zero latency, no second place semantics can drift |
| D9 | Refusal and abstention | **Fixed phrases bound to the event type; the host never sees them as text to rewrite** | Criterion 5. A refusal smoothed into prose is the failure upstream exists to prevent |
| D10 | TEN placement | **Thin extensions speaking HTTP/SSE to the ask service** | Media pipeline and agent runtime scale, deploy and fail independently; a 26 s unit of work inside a graph node makes flush semantics unworkable |
| D11 | Transport | **Browser WebRTC first; telephony a later phase** | Hermetic and demo-able on a laptop; a phone number is a real external dependency |
| D12 | Entity confirmation | **Confirm before dispatch when the entity is high-stakes or ASR confidence is low** | ASR sits upstream of every guard; a correct query about the wrong team passes every check |

---

## 5. Components

| Path | What | Language | Notes |
|---|---|---|---|
| `graph/` | The TEN graph definition: VAD, ASR, EOU, host, TTS, bridge, their wiring | TEN manifest / JSON | Stock extensions pinned; two custom |
| `extensions/das_host/` | The conversational agent: tiering, tool calls, sentence chunking, barge-in abort | Python | Anthropic SDK, streaming, `cache_control` on the prefix |
| `extensions/das_bridge/` | SSE client to the ask service; renders milestones; injects agent-initiated turns; cancels on barge-in | Python | Speaks `events.schema.json`; validates every event |
| `phrases/` | Fixed phrases for refusal, abstention, error, and the acknowledgement set; pre-rendered audio built at `make up` | text + wav | D8, D9 |
| `panel/` | The instrument panel: per-turn spans, p95s, switch states, branch view | TypeScript | Reads the bridge's timing stream; stores no content |
| `speech/` | Provider adapters behind one interface: local (CI) and cloud (prod) | Python | D5 |
| `identity/` | Pre-call sign-in, token held per session, refresh | Python | Thin wrapper over upstream `agent/identity.py` |
| `e2e/` | Witnesses: scripted audio in, assertions on events and timings out | Python 3.12 stdlib | Family convention |
| `load/` | Concurrent conversations against the stack | k6 + asyncio | §11 |
| `docker-compose.yml` | TEN runtime, local speech, panel, and the upstream stack by image | — | `make up` |
| `docs/` | `00-plan` (this), `01-quickstart`, `02-architecture`, `03-latency`, `04-tiers`, `05-ten`, `06-witnesses`, `parity.md`, `upstream-issues.md` | md | Family convention |

---

## 6. Configuration (`DAV_*`; `.env.example` documents all)

| Setting | Default | Meaning |
|---|---|---|
| `DAV_ASK_BASE` | `https://apim:8446/ask` | The ask service through the gateway |
| `DAV_OM_MCP` | `https://apim:8446/om/mcp` | The catalog, for tier-1 lookups |
| `DAV_HOST_MODEL` / `DAV_HOST_EFFORT` | `claude-haiku-4-5` / `low` | D4 |
| `DAV_SPEECH_PROVIDER` | `local` | `local` \| a cloud provider name; the only line that changes for `ENV=prod` |
| `DAV_ASR_MODEL` / `DAV_TTS_VOICE` | pinned local | Overridden by the cloud provider's own settings |
| `DAV_EOU_MODE` | `semantic` | `fixed` \| `semantic` — switch §10-1 |
| `DAV_CACHE_PREFIX` | `true` | switch §10-2 |
| `DAV_TTS_CHUNK` | `sentence` | `sentence` \| `complete` — switch §10-4 |
| `DAV_PRERENDERED_ACK` | `true` | switch §10-5 |
| `DAV_SPECULATIVE_DISPATCH` | `false` | switch §10-6; off by default because it spends tokens on guesses |
| `DAV_CONFIRM_ENTITIES` | `true` | D12 |
| `DAV_PANEL` | `true` | The instrument panel |
| `DAV_USER` | — | Who signs in for the CLI and the witnesses |

---

## 7. The host's contract with the person

What the host may and may not do, because a voice surface makes the model's freedom the risk.

| The host may | The host may not |
|---|---|
| Answer tier-0 turns itself | Answer a data question itself — ever |
| Look up a glossary term and say what it says | Paraphrase a definition beyond its text |
| Acknowledge and dispatch | Promise a time |
| Render a milestone from its fields | Invent a milestone |
| Ask a confirming question | Guess an entity it did not hear clearly |
| Speak `headline`, then one definition, then every caveat | Skip a caveat, or reorder them after the headline |
| Say "I'll stop" on barge-in | Keep talking past an interruption |
| — | Speak a refusal or abstention in its own words (D9) |

These are the assertions in `e2e/`, not prompt guidance.

---

## 8. Identity

| Hop | Mechanism | Identity downstream |
|---|---|---|
| person → browser | device-code sign-in before the call, via upstream `identity.py` | the person |
| browser → TEN | WebRTC session bound to the signed-in token | the person |
| `das_host` → gateway `/om/mcp` | bearer | the person; the executor picks the role bot |
| `das_bridge` → gateway `/ask` | bearer | the person; every branch runs as them |
| refresh | upstream `identity.py` when the token nears expiry | the person |

Nothing here holds a secret of its own. A token that expires mid-call fails the next hop upstream, and the ask service reports it as `error{transport}`; the host says so and asks the person to sign in again. That UX is a known gap (§13).

---

## 9. The latency budget

Estimates, not measurements. The panel replaces every number here with a measured one, and this table is rewritten when it does.

| Segment | Estimate | Lever |
|---|---|---|
| WebRTC in | 20–40 ms | co-locate |
| End-of-utterance | 200–400 ms semantic; 500–800 fixed | §10-1 |
| ASR finalize (streaming) | 50–150 ms | local vs cloud |
| Host TTFT | 200–400 ms cached; 400–700 uncached | §10-2, D4 |
| TTS time-to-first-byte | 80–200 ms; **≈ 0 pre-rendered** | §10-4, §10-5 |
| Jitter + playback | 40–80 ms | — |

| Tier | First audio | Complete |
|---|---|---|
| 0 conversational | 600–900 ms | same |
| 1 definitional | 600–900 ms | 1.4–1.9 s |
| 2 analytical | 500–900 ms (pre-rendered ack) | 8–14 s p50 / 20–30 s p95, **after** upstream caching and tiering; 26 s today |

First audio is tier-independent by design: the host speaks before any tool resolves, so a person cannot tell from the onset which tier they hit. That is the whole trick, and criterion 1 is the test of it.

---

## 10. The switches

Every lever is an env flag and a panel delta, because "we optimized latency" is a claim and a switch the audience can hear is a witness.

| # | Switch | Off | On | What changes, and what it attacks |
|---|---|---|---|---|
| 1 | `DAV_EOU_MODE` | 700 ms fixed silence | semantic EOU | Dead air after every sentence. **Largest non-LLM lever**, every turn |
| 2 | `DAV_CACHE_PREFIX` | no `cache_control` | breakpoint after tools + system | Host TTFT; panel shows `cache_read_input_tokens`. Decisive here, marginal upstream |
| 3 | `DAV_HOST_MODEL` | Opus 5 / high | Haiku 4.5 / low | ~1 s → ~250 ms TTFT |
| 4 | `DAV_TTS_CHUNK` | wait for completion | first sentence boundary | Multi-second stall → immediate speech |
| 5 | `DAV_PRERENDERED_ACK` | synthesize live | pre-rendered wav | 120 ms TTS TTFB → 0 on tier 2 |
| 6 | `DAV_SPECULATIVE_DISPATCH` | wait for final ASR | dispatch on a confident partial, cancel if wrong | −300 to −500 ms on tier 2; costs tokens on misses |
| 7 | upstream `DAS_EFFORT` / model per hop | Opus 5 high, every hop | tiered | −8 to −12 s on tier 2 completion — **the biggest number, and not this repo's** |
| 8 | upstream caching | — | — | −1.5 to −4 s on tier 2; 4–5× input cost |
| 9 | upstream fan-out | one branch | one per source | Coverage and visibility, **not** speed; −1 to −3 s where discovery was serial |

Rows 7–9 are upstream and appear here so the panel can show them and the docs can be honest about where the seconds come from. The perceived-latency levers (1–6) are this repo's; the completion-latency levers (7–9) are not.

---

## 11. Evaluation and load

**Witnesses** (`e2e/`), scripted audio in, assertions out, in CI on every push:

| Group | Asserts |
|---|---|
| onset | p95 time-to-first-audio under budget across a scripted mix of tiers |
| tiers | a definitional question never dispatches; an analytical one always does; `path` on the answer agrees with the tier chosen |
| branches | a cross-source question renders N `branch` events, N = `DAS_SOURCES` |
| refusal | `reader-only` asks finance; the refusal phrase is spoken verbatim; the host's transcript contains no paraphrase |
| abstention | a question the catalog cannot ground produces the abstention phrase and no SQL |
| confirm | a seeded mis-transcription of a high-stakes entity produces a confirming question, not a dispatch |
| barge-in | interruption mid-answer flushes within 200 ms and `cancel` reaches the ask service within 1 s |
| retention | after a conversation, no file under the repo's volumes contains the question text or audio |
| switches | each row of §10 1–6, off vs on, with the measured delta recorded |
| prod | `make test ENV=prod` with a cloud speech provider, unchanged |

**Load** (`load/`): N concurrent conversations, each a scripted tier mix, against the full stack. Gates: onset p95 holds at N; no conversation's ask is throttled by `DAS_RATE_CALLS` at the demo's N (or the rate tier decision in §13 is forced); the ask service's concurrency holds.

**What is not evaluated here:** answer accuracy. That is upstream's suite, and this repo must not re-score it — an answer's correctness is not changed by being spoken.

---

## 12. Phases

| # | Phase | Delivers | Done when | Depends on |
|---|---|---|---|---|
| 0 | Contract stub + witnesses | A stub ask service emitting the phase-1 event sequence; the witness harness; the panel reading timings | witnesses run red against the stub | upstream contract (written) |
| 1 | Tier 0/1 line | TEN graph, host, local speech, catalog lookups; tier 2 says "I can't do that yet" | onset witness green; definitional answers in < 2 s | — |
| 2 | Tier 2 dispatch | `das_bridge`, milestones, answer rendering, fixed phrases | refusal + abstention + tiers witnesses green against the stub | — |
| 3 | Against the real ask service | Same, against upstream `agent/server.py` | the same witnesses green, no change here | **upstream `server.py`** |
| 4 | Barge-in + cancel | Flush, abort, `cancel` | barge-in witness green | upstream coarse cancellation |
| 5 | Switches + panel | Every §10 1–6 switch wired; deltas measured and written into §9 | switches witness green; §9 rewritten with measurements | — |
| 6 | Entity confirmation | D12 | confirm witness green | — |
| 7 | Fan-out visible | Branch view in the panel | branches witness green | upstream phase-2 fan-out |
| 8 | Prod | cloud speech by `.env`; `ENV=prod` run | prod witness green; `parity.md` Azure column | upstream prod |
| 9 | Telephony | a phone number in front of the same graph | same witnesses over PSTN | external provider |

Phases 0–2 are the demo. 3–6 make it the one described here. 7–9 are new scope.

---

## 13. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **ASR upstream of every guard**: a perfectly-formed query about the wrong entity passes every check | certain | D12; the confirm witness; say it in the docs as the new error class it is |
| The voice caller throttles itself on `DAS_RATE_CALLS` once fan-out lands | high at demo N | Decide upstream: a rate tier for the voice app role, or the supervisor front-loads schema. Tracked as an upstream proposal, not changed here |
| The 800 ms budget is literature, not this stack | medium | Phase 5 measures; §9 is rewritten from the panel, not defended |
| TEN extension API at the pinned version differs from what §5 assumes | medium | Pin first; `docs/05-ten.md` records what was actually true; findings here marked **to confirm** until then |
| Local speech models are the one large artefact | certain | Pulled at `make up`, cached, never committed; sizes in `make doctor` |
| Re-auth mid-call has no good UX | certain | Say so; the host asks for sign-in again; a long-session design is out of scope |
| Model-generated narration creeps back in because it sounds better | high | D8 and D9 are witnesses, not guidance; a template that sounds wrong is fixed in `phrases/` |
| Upstream `server.py` slips and phase 3 waits | medium | Phases 0–2 run against the stub and are a complete demo of the conversational design on their own |
| The demo's most compelling variant — "what does this look like to a reader-only?" — cannot be built, because the app holds one user's token and cannot obtain another's | certain | Documented as a feature of the design, not a gap: the demo that is impossible is the property being demonstrated |

---

## 14. Repo layout

```
data-agent-voice/
  docs/            00-plan.md  01-quickstart  02-architecture  03-latency  04-tiers  05-ten  06-witnesses  parity.md  upstream-issues.md
  graph/           the TEN graph
  extensions/      das_host/  das_bridge/
  phrases/         fixed phrases + pre-rendered audio (built, not committed)
  speech/          local + cloud adapters
  identity/        sign-in, session token
  panel/           the instrument panel
  e2e/             witnesses
  load/            concurrent conversations
  docker-compose.yml  .env.example  .env.prod.example  Makefile  README.md  LICENSE  SECURITY.md
```

---

## 15. What this repo asks of upstream

Proposed in `data-agent-service`, not built here, each one passing the "would a Slack bot want it" test:

| Ask | Why a voice client is merely the first to need it |
|---|---|
| `agent/server.py` — the ask service | Every asynchronous client |
| Coarse cancellation between hops | Any client whose user has gone |
| Prompt caching on the agent's prefix | Cost, for every client |
| Per-hop model and effort | Completion latency, for every client |
| A rate tier for an application role, or schema front-loading before fan-out | Any client that asks more than one question a minute |

Nothing else. In particular, no length caps, no tier policy, no rendered text, no speech-shaped field in any event.
