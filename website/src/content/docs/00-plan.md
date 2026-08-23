---
title: "Data Agent Voice — Architecture & Implementation Plan"
editUrl: "https://github.com/calvinchengx/data-agent-voice/edit/main/docs/00-plan.md"
---

Status: **DRAFT for review — no implementation started.** Last updated 2026-08-23 (TEN pinned at 0.11.71 — see `docs/05-ten.md`; §16 added: backends are configuration, not code).

Repo: `~/calvinchengx/emulators/data-agent-voice` · Family tier: **leaf / consumer** — it consumes `data-agent-service`, which consumes the emulators; it emulates nothing · License: Apache-2.0 · Product name inside the repo: **the Analyst Line**.

Goal: a person talks to their governed data. They sign in once, ask questions by voice, and hear answers that carry the definition applied and the caveat the catalog raised — spoken, not read. Every question runs as the person asking, all the way to the source, through `data-agent-service` unchanged. The demo shows three things at once: a conversation that feels live over an agent that takes 26 seconds; a supervisor with sub-agents working behind that conversation; and every latency optimization as a switch the audience can hear.

The thesis this repo exists to demonstrate: **a conversational surface over a slow, careful agent is an architecture problem, not a model-speed problem.** The agent never gets fast enough. The conversation stops waiting for it.

---

## 0. Implementation discipline (non-negotiable)

Inherited from `data-agent-service` and extended by one rule.

| Rule | Meaning | Enforcement |
|---|---|---|
| **Dependencies as-is** | `data-agent-service`, the emulators, OpenMetadata and the TEN framework are consumed by published image or package and never modified. A suspected bug is written up in `docs/upstream-issues.md`. Only `data-agent-voice` is built here. **One stated exception:** TEN extensions are vendored by path (that is how TEN pins them), and a vendored extension may carry a patch — each patch is an upstream PR first, and `extensions/vendor/<name>/VENDORED` names the tag and the PR. | Compose pins published images; TEN pinned by tag + build image + `manifest-lock.json`; a patch without a PR link fails a check |
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
| The ask service **exists and is witnessed**: `make conformance-ask` passes 24/24 direct and 24/24 through the gateway's `/ask` route with the model stubbed — tickets, lossless replay, 404-not-403 ownership, idempotent cancel, `done`, and **SSE surviving the gateway** | `data-agent-service` `a9ff497`; `docs/20-ask-service.md` | No stub to build. Phase 0 here targets the real service from the first line. What is *not* yet witnessed upstream: the four behaviour checks (refusal, abstention, `path`, conversation memory) and keep-alives across the gateway's idle timeout on a long stream — both need a model run |
| Upstream already carries: structured `step`/`milestone` events, conversation `history`, coarse cancellation between hops, prompt caching on the agent's prefix with a rolling breakpoint, and `cache_read_tokens`/`hops` in `done` | same commit | Three of the five asks in §15 are done; the host's TTFT and the panel's cache-hit view have real numbers to read |
| `DAS_RATE_CALLS=60/60s` per caller, and every sub-agent runs as the same user | `data-agent-service/.env.example` | A voice conversation plus fan-out can throttle itself. Rate tier for the voice caller, or the supervisor front-loads schema so branches do not rediscover it; decided upstream, tracked in §13 |
| Human turn gap ≈ 200 ms; > 800 ms reads as thinking; > 1.5 s reads as broken | conversation-design literature; **to be measured on this stack** | The budget in §9. Treated as a hypothesis until the panel confirms it |
| **TEN 0.11.71 read from the tag** (`docs/05-ten.md`): RTC-first on Agora (cloud account); `websocket_server` is the local transport; `main_python` is ~200 lines and already does sentence-chunked TTS and flush-on-barge-in; tools are extensions registered by `tool_register`; `anthropic_llm2_python` landed in this release with effort and refusal fallback but **no prompt caching**; semantic turn detection is a **vLLM-served model**, not a classifier; `whisper_stt_python` exists, **no local TTS exists** | `ten-framework@0.11.71` | D4, D5, D10, D11 and §5, §9, §10 revised below. Everything marked "to confirm" in the first draft is now either confirmed or corrected |
| Fixed-silence EOU vs model-based EOU: the model-based path needs a served LLM | `ten_turn_detection/config.py` at the tag | CI runs fixed; the demo runs semantic behind a compose profile (§10-1) |
| ASR has no emulator; local ASR exists in TEN, local TTS does not | `whisper_stt_python`; the TTS catalogue at the tag | faster-whisper stock; **a custom TTS extension** fronting Piper/Kokoro, proposed upstream (D5) |
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
| D4 | Host model | **Haiku 4.5, effort `low`, streaming, via `anthropic_llm2_python`; cached prefix once the vendored extension carries a breakpoint** | The host speaks sentences; prefill is most of its time; caching is decisive here and not upstream. The stock extension has no `cache_control`; that patch is a phase-1 task and an upstream PR (`05-ten.md` §3) |
| D5 | Speech | **Local in CI** — `whisper_stt_python` stock; **a custom `AsyncTTS2HttpExtension` fronting Piper or Kokoro** because no local TTS exists at the tag — **cloud by `.env`** | Hermetic CI, prod-identical by configuration. The TTS extension is proposed upstream: "a TTS that needs no account" is missing from the catalogue |
| D6 | Identity | **Device-code sign-in before the call; token held for the session; refresh via upstream `identity.py`** | Every hop downstream is as the user. Re-auth mid-call is a known unsolved UX (§13) |
| D7 | Retention | **No audio, no transcript, no question stored here** | The promoter's argument. The panel records timings and event types only |
| D8 | Milestone rendering | **Templates from `milestone.{phase, subject, source}`**, never model prose | Bounded length, zero latency, no second place semantics can drift |
| D9 | Refusal and abstention | **Fixed phrases bound to the event type; the host never sees them as text to rewrite** | Criterion 5. A refusal smoothed into prose is the failure upstream exists to prevent |
| D10 | TEN placement | **Thin extensions speaking HTTP/SSE to the ask service**: `das_host` is a fork of TEN's own `main_python`; `dispatch`/`glossary_lookup`/`confirm` are tool extensions; `das_bridge` injects agent-initiated turns | Confirmed at the tag: this is the shape TEN wants for external systems. `mcp_client_python` exists and **must not** be on the host — it would hand `run_query` to the conversational model |
| D11 | Transport | **Browser over `websocket_server` first** (local, no account); **Agora RTC by `.env` for prod**; telephony via the SIP examples later | TEN is RTC-first on Agora and has no local WebRTC. WebSocket gives up Opus/FEC/UDP and keeps a laptop demo and a CI that runs |
| D13 | Backends | **A backend is a descriptor, not a code path.** This repo knows *kinds* of capability — a fast lookup, a dispatch, a terminal outcome — and never a capability's name. `data-agent-service` is the first descriptor, not the only shape supported | §16. The cost of this is near zero while nothing is written and a rewrite once four extensions hardcode one backend |
| D12 | Entity confirmation | **Confirm before dispatch when the entity is high-stakes or ASR confidence is low** | ASR sits upstream of every guard; a correct query about the wrong team passes every check |

---

## 5. Components

| Path | What | Language | Notes |
|---|---|---|---|
| `graph/` | The TEN graph definition: VAD, ASR, EOU, host, TTS, bridge, their wiring | TEN manifest / JSON | Stock extensions pinned; two custom |
| `extensions/das_host/` | Fork of TEN's `main_python`: tier policy, dispatch path, fixed-phrase bypass, pre-rendered acks; sentence chunking and flush are inherited | Python | the host's LLM is a separate `anthropic_llm2_python` node |
| `extensions/das_tools/` | A loader: one LLM tool per `fast_tool` each backend declares, plus one dispatch per backend, plus `confirm` | Python | the only tools the host's LLM ever sees (§16) |
| `extensions/local_tts/` | `AsyncTTS2HttpExtension` over a local Piper/Kokoro server; serves pre-rendered phrases by match | Python | D5; upstream candidate |
| `extensions/vendor/` | Extensions copied from the tag, with a `VENDORED` file naming it and every patch an upstream PR | — | `05-ten.md` §7 |
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
| `DAV_APIM_BASE` + `DAV_ASK_PATH` | `https://apim-emulator:8445` + `/ask` | The ask service through the gateway |
| `DAV_BACKENDS` | `data-agent` | Which descriptors in `tenapp/backends/` the line loads (§16). A fast lookup's address lives in its descriptor, not here |
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
| End-of-utterance | 500–800 ms fixed (CI); 200–400 ms semantic **on a GPU-served model** (demo) | §10-1 |
| ASR finalize (streaming) | 50–150 ms | local vs cloud |
| Host TTFT | 400–700 ms uncached (stock); 200–400 ms once the cache patch lands | §10-2, D4 |
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
| 1 | `DAV_EOU_MODE` | fixed silence (VAD + ASR finality; **CI**) | `ten_turn_detection` + a vLLM service behind a compose profile (**demo**) | Dead air after every sentence. **Largest non-LLM lever**, and the most expensive to run |
| 2 | `DAV_CACHE_PREFIX` | no `cache_control` (stock extension) | breakpoint after tools + system (vendored patch) | Host TTFT; panel shows `cache_read_input_tokens`. Decisive here, marginal upstream. Off until the patch lands |
| 3 | `DAV_HOST_MODEL` | Opus 5 / high | Haiku 4.5 / low | ~1 s → ~250 ms TTFT |
| 4 | `DAV_TTS_CHUNK` | wait for completion | first sentence boundary | Multi-second stall → immediate speech |
| 5 | `DAV_PRERENDERED_ACK` | synthesize live | pre-rendered wav | 120 ms TTS TTFB → 0 on tier 2 |
| 6 | `DAV_SPECULATIVE_DISPATCH` | wait for final ASR | dispatch on a confident partial, cancel if wrong | −300 to −500 ms on tier 2; costs tokens on misses |
| 7 | upstream `DAS_EFFORT` / model per hop | Opus 5 high, every hop | tiered | −8 to −12 s on tier 2 completion — **the biggest number, and not this repo's** |
| 8 | upstream caching (landed; `done.cache_read_tokens` reports it) | — | — | −1.5 to −4 s on tier 2; 4–5× input cost |
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
| 0 | Stack + witnesses | Compose consuming `data-agent-service` by image with the `ask` profile on; the witness harness; the panel reading timings; `make up` / `make doctor` / `make status` | witnesses run red against the real service | upstream `a9ff497` (landed) |
| 1 | Tier 0/1 line | TEN graph, host, local speech, catalog lookups; tier 2 says "I can't do that yet" | onset witness green; definitional answers in < 2 s | — |
| 2 | Tier 2 dispatch | `das_bridge` on the real `/ask` route, milestones, answer rendering, fixed phrases | refusal + abstention + tiers witnesses green | upstream behaviour checks green (a model run) |
| 3 | Barge-in + cancel | Flush, abort, `cancel` | barge-in witness green | upstream coarse cancellation (landed) |
| 4 | Switches + panel | Every §10 1–6 switch wired; deltas measured and written into §9 | switches witness green; §9 rewritten with measurements | — |
| 5 | Entity confirmation | D12 | confirm witness green | — |
| 6 | Fan-out visible | Branch view in the panel | branches witness green | upstream phase-2 fan-out |
| 7 | Prod | cloud speech by `.env`; `ENV=prod` run | prod witness green; `parity.md` Azure column | upstream prod |
| 8 | Telephony | a phone number in front of the same graph | same witnesses over PSTN | external provider |

Phases 0–2 are the demo. 3–5 make it the one described here. 6–8 are new scope.

---

## 13. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **ASR upstream of every guard**: a perfectly-formed query about the wrong entity passes every check | certain | D12; the confirm witness; say it in the docs as the new error class it is |
| The voice caller throttles itself on `DAS_RATE_CALLS` once fan-out lands | high at demo N | Decide upstream: a rate tier for the voice app role, or the supervisor front-loads schema. Tracked as an upstream proposal, not changed here |
| The 800 ms budget is literature, not this stack | medium | Phase 4 measures; §9 is rewritten from the panel, not defended |
| Semantic turn detection needs a served LLM and may be slower than silence on a laptop CPU | high | CI runs fixed; the demo machine runs vLLM on a GPU or the switch stays off and the panel says so |
| The cache patch to `anthropic_llm2_python` drifts from an upstream that is days old and moving | medium | Small patch, PR first, re-based on each pin bump; switch #2 reads "off" until merged |
| Local speech models are the one large artefact | certain | Pulled at `make up`, cached, never committed; sizes in `make doctor` |
| Re-auth mid-call has no good UX | certain | Say so; the host asks for sign-in again; a long-session design is out of scope |
| Model-generated narration creeps back in because it sounds better | high | D8 and D9 are witnesses, not guidance; a template that sounds wrong is fixed in `phrases/` |
| Upstream's behaviour checks have not run, so `definitions_applied` may arrive empty and the refusal/abstention split is proved only in-process | medium | Phase 2 waits for that run; phase 1 does not depend on it. A field the bridge renders must be one upstream has witnessed |
| A long stream's keep-alives across the gateway's idle timeout are unwitnessed | medium | The first real-model run upstream shows it; if the gateway drops a quiet stream, the bridge's lossless reconnect (`Last-Event-ID`) is the designed answer, not a workaround |
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
  backends/        one descriptor per service the line can talk to (§16)
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
| ~~`agent/server.py` — the ask service~~ **landed** | Every asynchronous client |
| ~~Coarse cancellation between hops~~ **landed** | Any client whose user has gone |
| ~~Prompt caching on the agent's prefix~~ **landed** | Cost, for every client |
| Per-hop model and effort | Completion latency, for every client |
| A rate tier for an application role, or schema front-loading before fan-out | Any client that asks more than one question a minute |

Nothing else. In particular, no length caps, no tier policy, no rendered text, no speech-shaped field in any event.

---

## 16. Backends are configuration

The line talks to `data-agent-service` today. It should talk to a second
service — a ticketing agent, an ops agent, or a new surface `data-agent-service`
itself grows — without a code change here. That is cheap to arrange now,
because none of the four extensions exist yet, and expensive once they do.

**Most of the coupling was already gone.** The ask contract was deliberately
stripped of anything voice-shaped, and a contract that is not voice-shaped
turns out not to be warehouse-shaped either. `das_bridge` handles
`accepted`/`branch`/`step`/`milestone`/`answer`/`abstention`/`refusal`/`error`/`done`
and none of those name a warehouse. The tier policy — answer, look up,
dispatch — is about latency, not about data. What was coupled was small and
specific:

| Was | Now |
|---|---|
| `glossary_lookup` as *the* fast tool, in `das_tools` | one tool per `fast_tool` a backend declares |
| `om_mcp_path` wired into the graph | a field in the backend's descriptor |
| `path: catalog\|warehouse\|multi` | **amended upstream** to `{speed, detail}`; policy keys on `speed` |
| `definitions_applied` | **amended upstream** to `provenance` — `{term, statement, source, kind}` |
| one backend, one audience, in `.env` | `DAV_BACKENDS=data-agent,…`, one descriptor each |

Both amendments landed in `data-agent-service` while the contract had one
consumer and no released client. That was the whole reason to do it now.

### The descriptor

```json
// backends/data-agent.json
{
  "name": "data-agent",
  "display": "your data",
  "base_url": "${DAV_APIM_BASE}/ask",
  "audience": "api://data-agent-service",
  "contract_version": "1",
  "fast_tools": [
    { "name": "glossary_lookup",
      "description": "What a business term means, from the catalog.",
      "call": { "path": "/om/mcp", "tool": "search_metadata" },
      "budget_ms": 400 }
  ],
  "dispatch": {
    "tool": "ask_data",
    "description": "Any question about numbers, tables, metrics or reports."
  },
  "phrases": "phrases/data-agent/"
}
```

Four consequences, none of which is extra machinery:

* **`das_tools` becomes a loader.** It registers one LLM tool per declared
  `fast_tool` plus one dispatch per backend, and holds no tool of its own.
* **Routing is free.** With N backends there are N dispatch tools with
  distinct descriptions and the host's model picks between them in the same
  turn. No router, no added latency — that is what tool descriptions are for.
* **Tier 1 stops meaning "the catalog".** It means *any declared fast tool
  whose `budget_ms` fits the conversational budget*. `glossary_lookup` is one
  service's instance of a general thing.
* **`das_bridge` takes a backend, not a base URL** — a map of ticket to
  backend rather than a singleton. It already speaks a neutral contract.

Phrases are `phrases/default/` with `phrases/<backend>/` overriding only where
a backend's refusal genuinely reads differently. Identity is per descriptor:
`audience` names what the sign-in acquires a token for.

### What is deliberately not generalized

* **The tier policy.** Three tiers is the design, not a plugin point. A
  backend needing a fourth is a change to this plan.
* **Speech, transport, models.** Already `.env`; a second mechanism would be
  worse than the first.
* **A capability *discovery* endpoint** — `GET /ask/v1/capabilities`, so a new
  surface in a backend appears here with no file edit at all. That is the
  strongest version and it waits for a real second backend. Static descriptors
  already buy the decoupling; discovery only removes a file edit, and it costs
  an upstream contract addition that cannot be validated against one case.

### The test

The rule that has been working — *would a Slack bot want this?* — extended by
**would a ticketing agent want this?** Anything in this repo that mentions a
warehouse, a catalog or SQL is in the wrong repo or the wrong layer.
