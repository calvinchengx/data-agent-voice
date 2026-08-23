---
title: "TEN, as it actually is at 0.11.71"
editUrl: "https://github.com/calvinchengx/data-agent-voice/edit/main/docs/05-ten.md"
---

Read from the tag, not the marketing. Every row names the file it came from, so
a claim here can be re-checked when the pin moves. Where a finding changes the
plan, the consequence is stated and `00-plan.md` is updated to match; where it
does not, nothing is claimed.

Pinned: **`TEN-framework/ten-framework` tag `0.11.71`** (2026-07-31, not a
prerelease; the same tag is mirrored as `ten_framework` and `TEN-Agent`).
Build image `ghcr.io/ten-framework/ten_agent_build:0.7.14`. The runtime and
`ten_ai_base` are **not in the repository** — they are fetched by `tman` from
the TEN package registry at install time, and the lock file at the tag resolves
them to `ten_runtime_go 0.11.48`, `ten_runtime_python 0.11`, `ten_ai_base
0.7.30`. Pinning TEN therefore means three things, not one: the git tag (for
extensions, which are vendored by path), the build image, and the
`manifest-lock.json` this repo commits for the registry packages.

## What TEN is

A graph runtime. An **app** (`tenapp/`) declares a set of **extensions** and
one or more **graphs** in `property.json`; a graph is nodes (extension
instances) and typed connections between them — `cmd`, `data`, `audio_frame`,
`video_frame`. A Go HTTP server (`:8080`) spawns one **worker process per
session** (`/start`, `/stop`, `/ping`) and injects per-session properties
into the graph. Extensions are Python classes with `on_init → on_start →
messages → on_stop → on_deinit`, registered by an `addon.py` whose name must
match `manifest.json` and the node's `addon` field exactly.

| | Source |
|---|---|
| Lifecycle, graph, connection types | `docs/ai/L1/02_architecture.md` |
| REST surface (`/start` body, `properties` override per node, `timeout`) | `docs/ai/L1/06_interfaces.md` |
| Base classes: `AsyncASRBaseExtension`, `AsyncTTS2BaseExtension`, `AsyncLLMBaseExtension`, `AsyncLLMToolBaseExtension`, `AsyncExtension` | same; implemented in `ten_ai_base` (registry package) |
| Property getters return `(value, err)` tuples; no signal handlers in extensions; `.env` read only at container start; Python deps not persisted across restarts; bare `tman install` can delete `bin/worker` | `docs/ai/L1/07_gotchas.md` — all of these will bite, all are documented |

**Language.** Every one of the ~90 extensions at the tag is Python, on
`ten_runtime_python` + `ten_ai_base`; there is no Go extension in the
catalogue. A tenapp does carry a `main.go` (~60 lines: load `property.json`,
start the runtime) and the API server is Go, but both are consumed unchanged.
Everything this repo authors is Python; Go is not written here. That differs
from `data-agent-service`, where a Go executor earns 8× throughput — here the
extensions are I/O glue and the hot path is inside the runtime, which is C.

## The findings that change the plan

### 1. TEN is RTC-first on Agora, and that is a cloud account

The default transport is Agora RTC; every `voice-assistant*` example's first
node is `agora_rtc`, and `AGORA_APP_ID` is listed as **required** in
`docs/ai/L1/01_setup.md`. There is no local WebRTC stack.

**What exists instead:** `ten_packages/extension/websocket_server` — a
WebSocket server extension that takes base64 PCM in JSON and emits `pcm_frame`
into the graph, and forwards TTS audio, `data` and `cmd` messages back to the
client as JSON (`examples/websocket-example`). It is local, needs no account,
and carries everything this demo needs: audio both ways, transcripts, and the
structured messages the panel reads.

**Consequence (D11 revised):** the hermetic transport is **WebSocket, not
WebRTC**. The plan's "browser WebRTC first" becomes "browser WebSocket first";
Agora is the `ENV=prod` transport by configuration, which is the same shape
as speech (D5). What is given up: Opus, FEC and the 50–150 ms UDP path. What
is kept: a laptop demo and a CI that can run. Telephony (phase 8) arrives via
the SIP examples (`voice-assistant-sip-{twilio,telnyx,plivo}`), which are also
cloud, and also later.

### 2. Semantic turn detection is a served LLM, not a small model

`ten_turn_detection` does not run a classifier in-process. Its config
(`ten_turn_detection/config.py`) is `base_url: http://localhost:8000/v1`,
`model: TEN_Turn_Detection` — an OpenAI-compatible chat endpoint, which the
example README pairs with **vLLM** serving the model from Hugging Face. It
sits between ASR and the host on `text_data`, decides *finished / unfinished /
wait*, and sends `flush` to the host on a new turn; `force_threshold_ms`
(default 5000) is the fallback when the model stays undecided.

**Consequence (§9, §10-1 revised):** the single largest non-LLM latency lever
costs a model server. Two modes, by configuration:

* `DAV_EOU_MODE=fixed` — `ten_vad_python` + ASR finality, no model. **CI runs
  this.** It is also the honest "off" state of switch #1.
* `DAV_EOU_MODE=semantic` — the turn-detection node plus a vLLM service in
  compose behind a profile. **The demo runs this.** The plan's 200–400 ms
  estimate is now explicitly *for a GPU-served model*; on a laptop CPU it may
  be slower than the silence it replaces, which the panel will show.

The witness for switch #1 is unchanged; which machine can run it is not.

### 3. Claude is native, with effort and refusal fallback — but no prompt caching

`anthropic_llm2_python` landed in this very release (PR #2249). It speaks the
Messages API directly (no OpenAI shim), streams, calls tools, surfaces
`thinking` as LLM2 reasoning events, takes `effort` (`low`…`max`, default
`low`), `thinking_display`, and routes safety refusals to a server-side
fallback so *"a voice agent never goes silent"* (`refusal_fallback: true`,
with a spoken `refusal_message` when nothing succeeds). Default model is
`claude-opus-5`; D4's Haiku 4.5 is a one-property change.

**What it does not do:** `anthropic_llm.py` has **zero** mentions of
`cache_control`. The system prompt and tools are sent uncached on every turn.

**Consequence (§10-2 revised):** switch #2, "prompt caching on the host", is
not a property toggle on a stock extension. Options, in order of preference:

1. Vendor `anthropic_llm2_python` by path (it is already path-vendored at the
   tag), add a breakpoint after `system` + `tools`, and propose it upstream.
   Small, and the upstream extension is days old and actively changing.
2. Leave switch #2 out of phase 1 and measure the host uncached first. The
   number is still real; it is just the "off" side only.

Option 1, as a phase-1 task. Until it lands, §9's "host TTFT 200–400 ms
cached" reads "400–700 ms uncached".

Also worth knowing: the extension's own `refusal_message` is a **second place a
refusal can be spoken**, and it is model-side (safety classifier), not
data-side (the executor's guard). D9 binds the *data* refusal to a fixed
phrase via the bridge; this one is the model declining to answer at all. They
are different events and must be spoken differently — the bridge owns one,
the LLM node owns the other, and neither paraphrases.

### 4. `main_python` is the host, already

Every example carries a `main_python` extension (~200 lines,
`examples/websocket-example/tenapp/ten_packages/extension/main_python/`) that
is precisely the seam the plan calls `das_host`:

| It does | In |
|---|---|
| receives `asr_result`; interrupts on any new speech; on a final transcript bumps `turn_id` and queues the LLM | `_on_asr_result` |
| streams LLM deltas, **chunks at sentence boundaries** and sends each to TTS as it completes | `_on_llm_response`, `parse_sentences` |
| interrupt = flush the LLM, `tts_flush` to TTS, `flush` to the transport | `_interrupt` |
| registers tools that arrive by `tool_register` cmd from tool extensions | `_on_tool_register` |
| greets on `on_user_joined` | `_on_user_joined` |

**Consequence (§5 revised):** `das_host` is a **fork of `main_python`**, not a
new extension. Sentence chunking to TTS (switch #4) and flush-on-barge-in are
stock behaviour; what is added is the tier policy, the `dispatch` path, the
fixed-phrase bypass, and the pre-rendered acknowledgements. The host's own
LLM stays a separate node (`anthropic_llm2_python`), which is how TEN wants it
and which keeps the model swappable by property.

### 5. Tools are extensions, registered by command

An LLM tool is a separate extension inheriting `AsyncLLMToolBaseExtension`
(`weatherapi_tool_python` is the template), which sends `tool_register`
(name, description, JSON-schema parameters) to the host at start, and answers
`tool_call` commands. The host forwards registrations to the LLM node.

**Consequence (§5 revised):** `glossary_lookup`, `dispatch` and `confirm` are
**three small tool extensions**, or one extension registering three tools.
The LLM node calls them; the host sees every call. That is the right shape for
D3's rule that the host *may not answer a data question itself*: the only
tools the host's LLM ever sees are the three this repo registers. There is an
`mcp_client_python` extension that could expose the gateway's MCP servers to
the LLM directly — **it must not be used on the host**, because it would hand
`run_query` to the conversational model. It is the right tool for a different
demo.

`dispatch` is where the bridge lives: it opens the ask ticket, returns
immediately, and `das_bridge` streams the events back in as agent-initiated
turns (TTS inputs with their own `request_id`, the mechanism the greeting
already uses).

### 6. Local speech: ASR exists, TTS does not

`whisper_stt_python` (`faster-whisper`, CPU or GPU, built-in VAD filter)
exists at the tag and is the hermetic ASR. Among ~45 TTS extensions **none is
local** — every one is a vendor API (ElevenLabs, Cartesia, Azure, Polly,
Rime, …).

**Consequence (D5 revised):** hermetic TTS is a **custom extension** on
`AsyncTTS2HttpExtension` (template: `rime_http_tts`) fronting a local Piper or
Kokoro HTTP server in compose. The deep dive (`docs/ai/L1/L2/extension_development.md`)
specifies the exact files, the five test property configs, and the guarder
tests an extension must pass, so this is a known-size task — and it should be
proposed upstream, since "a TTS that needs no account" is missing from the
catalogue. Note the gotcha there: the `pcm_frame` contract is **PCM16 mono**,
and `synthesize_audio_sample_rate()` must report what is actually emitted.

Pre-rendered acknowledgements (switch #5) are then trivially that same
extension serving a file when the text matches a phrase — no second path.

### 7. Pinning is by path for extensions and by lock file for the runtime

A tenapp's `manifest.json` lists dependencies two ways: registry packages with
a loose version (`ten_runtime_python 0.11`, `ten_ai_base 0.7`) resolved and
hashed into `manifest-lock.json`, and extensions by **relative path** into
the checkout. There is no `pip install ten-runtime`.

**Consequence (§0, §14):** this repo vendors the extensions it uses by copying
them from the tag into `extensions/vendor/<name>/` with the tag recorded in a
`VENDORED` file, commits `manifest-lock.json`, and pins the build image. A
bump is a diff against the tag, reviewable. It also means the discipline rule
"dependencies as-is" needs one stated exception: **vendored extensions may
carry patches, each one an upstream PR first**, because (3) and (6) require it.

### 8. arm64 is buildable, but not from the image or the registry

Two published paths are amd64-only, and one is not:

| Source | amd64 | arm64 |
|---|---|---|
| `ghcr.io/ten-framework/ten_agent_build:0.7.14` | yes | **no** — a single-arch image, no manifest list |
| the `tman` package registry | yes | **no** — `manifest-lock.json` at the tag records `supports: [linux/x64]` for `ten_runtime`, `ten_runtime_python` and `ten_runtime_go` |
| the **GitHub release assets at the same tag** | yes | **yes** — `ten_packages-linux-arm64-gcc-release.zip` (103 MB) and `tman-linux-release-arm64.zip` |

The arm64 bundle carries `ten_runtime`, `ten_runtime_python`
(`libten_runtime_python.so`), `ten_runtime_go` and `ten_runtime_nodejs`. So
arm64 is supported by the project; it is only unreachable through the two
distribution channels a Dockerfile would normally use. `tman install` on an
aarch64 host resolves nothing and fails, which reads as "arm64 unsupported"
and is not.

**Consequence:** `docker/ten/Dockerfile` has two builder stages selected by
`FROM builder-${TARGETARCH}` — amd64 takes TEN's published image and runs
`tman install`; arm64 takes `ubuntu:22.04`, installs the same toolchain
versions the published image uses, and unpacks the release assets into
`ten_packages/` before letting `tman` resolve only the pure-Python packages
(`ten_ai_base`, whose `supports` list at the tag is empty, so it is
arch-neutral). Both legs converge before the app is assembled, and
`docker buildx build --platform linux/amd64,linux/arm64` produces one manifest
list.

The amd64 leg is the one upstream tests. **When the two disagree, amd64 is
right and the difference is an upstream issue**, not something to work around
here.

**Still unproven on arm64:** `faster-whisper` depends on `ctranslate2`, whose
aarch64 Linux wheel availability this reading did not establish. If there is
no wheel, in-process ASR on arm64 either builds from source at image build
time or moves to a sidecar. A first `buildx` run on the arm64 leg answers it,
and until one has been done, **multi-arch is a claim this repo has not
witnessed** — `parity.md` says so.

## What did not change

* **D10 holds.** Thin extensions speaking HTTP/SSE to the ask service is
  exactly how TEN wants external systems reached: a tool extension and a data
  source, not a long-running unit of work inside a node.
* **The sentence-boundary streaming, barge-in and greeting mechanics exist
  stock** (§4 above). Switches #4 and the barge-in witness are cheaper than
  planned.
* **Telemetry is partly stock.** TTS extensions emit per-request TTFB metrics
  (`send_tts_ttfb_metrics`, PR #2260) and ASR emits connect-delay and vendor
  metrics. The panel reads those for two of its five spans.
* **Per-session properties at `/start`** mean the signed-in user's token can be
  injected into the `dispatch` and `glossary_lookup` tool nodes per session
  without it ever being in a file — D6 and D7 are satisfied by a mechanism TEN
  already has.

## Open questions this reading did not settle

| Question | Why it matters | How it gets answered |
|---|---|---|
| Does `websocket_server` carry `cmd`/`data` **into** the graph from the client, or only out? | the panel's switch toggles and the sign-in handoff want a path in | read `websocket_server/extension.py` fully in phase 0 |
| What is the wire contract of LLM2's `tool_call` result when a tool wants to **speak nothing** (dispatch returns a ticket, not an answer)? | `dispatch` must not make the LLM narrate a ticket id | `ten_ai_base` 0.7.30 source once installed; `LLMToolResult` types |
| Does `anthropic_llm2_python` honour a `flush` mid-stream by aborting the HTTP request, or only by dropping output? | barge-in cost: tokens and the rate limit | read `_chat_completion` and the base class's flush path |
| How large is `TEN_Turn_Detection` and what does vLLM need to serve it on this laptop? | whether semantic EOU is demo-able locally at all | Hugging Face card; a timed run |

These are phase-0 reading tasks, and each gets a row here when answered.
