# Parity — what is witnessed, and where

Two columns, because they are different claims. **Witnessed locally** means a
check in this repo runs and passes; the check is named, so a green row can
always be re-run. **Witnessed running** means the same claim has been watched
holding with a person talking to the line.

> Every row in the second column reads `not yet`. Nothing in this repository
> has been run as a voice call: the graph names four extensions that do not
> exist, and no audio has been through it. The rows below describe a design
> and the checks that hold the design's own files to each other — which is a
> real thing to check, and is not the same thing as a working line.
>
> That distinction is the whole point of the ledger. `data-agent-service`
> spent a day discovering that a runbook naming three parameters which did not
> exist reads as deployable, and the fix was not a better runbook but a check
> that compares the runbook to the definition. These rows are that check's
> equivalent here, and they stop at exactly the line they can prove.

## The design, as configuration

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| Every addon the graph names is declared, and nothing installs at run time that was not pinned | 🟢 | `make test` | not yet |
| The host is the only node that reaches the model — there is no second path to an answer | 🟢 | `make test` | not yet |
| `mcp_client_python` is absent, so `run_query` can never reach the conversational model | 🟢 | `make test` | not yet |
| Barge-in reaches the model, the voice and the wire, not one of the three | 🟢 structurally | `make test` | not yet — an interrupt is a timing claim and only a call can make it |
| A backend is a descriptor: every configured backend has one, and each declares its dispatch and its fast tools | 🟢 | `make test` | not yet |
| No general layer carries the first backend's vocabulary | 🟢 | `make test` | not yet |
| Every setting the graph reads, and every switch the plan lists, is in the template | 🟢 | `make test` | not yet |
| The TEN pin is one version across the template, the compose file and the Dockerfile | 🟢 | `make test` | not yet |
| The upstream stack is reachable and its ask service is healthy before anything starts | 🟢 | `make doctor` | not yet |

## The line itself

| Capability | Witnessed locally | Check | Witnessed running |
|---|---|---|---|
| The image builds on amd64 | 🔴 **not run** | `docker buildx build --platform linux/amd64` | not yet |
| The image builds on arm64 from the release assets | 🔴 **not run** — and `ctranslate2` may have no aarch64 wheel (`05-ten.md` §8) | `docker buildx build --platform linux/arm64` | not yet |
| A person speaks and hears an answer | 🔴 **not run** — `das_host`, `das_tools`, `das_bridge` and `local_tts` do not exist | `make up && make call` | not yet |
| First audio under 900 ms at p95 | 🔴 **not run** | `make test` (phase 5 of the plan) | not yet |
| A definitional question is answered without dispatching | 🔴 **not run** | the tiers witness | not yet |
| A refusal is spoken from a fixed phrase and never paraphrased | 🔴 **not run** | the refusal witness | not yet |
| A mis-transcribed entity produces a confirmation, not an answer | 🔴 **not run** | the confirm witness | not yet |
| Semantic turn detection beats fixed silence | 🔴 **not run** — needs a GPU this machine does not have | switch #1, off vs on | not yet |

## Upstream, for reference

The ask contract this repo consumes is witnessed in `data-agent-service`:
24/24 direct and 24/24 through the gateway, with the model stubbed. Its four
behaviour checks have not run. See that repository's `docs/parity.md`.
