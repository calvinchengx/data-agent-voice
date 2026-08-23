# Data Agent Voice — the Analyst Line

[![CI](https://github.com/calvinchengx/data-agent-voice/actions/workflows/ci.yml/badge.svg)](https://github.com/calvinchengx/data-agent-voice/actions/workflows/ci.yml)
[![Docs](https://github.com/calvinchengx/data-agent-voice/actions/workflows/docs-site.yml/badge.svg)](https://calvinchengx.github.io/data-agent-voice/docs/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

[![witnesses](https://img.shields.io/endpoint?url=https%3A%2F%2Fcalvinchengx.github.io%2Fdata-agent-voice%2Fwitnesses.json)](https://calvinchengx.github.io/data-agent-voice/docs/parity/)
[![python coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fcalvinchengx.github.io%2Fdata-agent-voice%2Fcoverage-python.json)](https://calvinchengx.github.io/data-agent-voice/docs/parity/)

**Talk to your governed data. Hear the definition it applied and the caveat it raised.**

A voice front end over [data-agent-service](https://github.com/calvinchengx/data-agent-service):
you sign in once, ask in English, and every question runs as *you*, all the way
to the source. Built on the [TEN framework](https://github.com/TEN-framework/ten-framework).

📖 **[Documentation site](https://calvinchengx.github.io/data-agent-voice/docs/)** — also
browsable as Markdown in [`docs/`](docs/).

> **Status: plan and scaffolding.** The architecture is decided and written
> down, the framework is pinned and read, the image and the graph exist, and
> the configuration is held to itself by a test suite. **No audio has ever been
> through it** — four extensions the graph names are not written yet.
> [`docs/parity.md`](docs/parity.md) says exactly which rows are green and which
> are red, and none of them claims a working line.

## Why this exists

A question to `data-agent-service` takes **26 seconds at the median** — six to
eight model turns, each one careful. A conversation reads as broken after about
**one second of silence**.

That gap is 30×, and no faster model closes it. So this repository does not try:

* **The conversation never waits for the agent.** A small model owns the turn,
  speaks first, and answers definitional questions from the catalog in about a
  second. Anything needing the warehouse is acknowledged and dispatched.
* **The slow agent runs where nobody is waiting.** Its progress is narrated as
  it happens, and its answer arrives as a spoken turn when it is ready.
* **A refusal is never narrated.** The service says *refused*, *abstained* or
  *answered* as three distinct events, and the first two are spoken from fixed
  phrases the model never sees. Smoothing a refusal into plausible prose is the
  exact failure the service upstream exists to prevent.

The full argument, with the numbers behind it, is in
[`docs/00-plan.md`](docs/00-plan.md).

## What is here

| Path | Purpose |
|---|---|
| [`docs/00-plan.md`](docs/00-plan.md) | Architecture, decisions, phases, the latency budget, risks |
| [`docs/05-ten.md`](docs/05-ten.md) | TEN at the pinned tag, read from the source — including what it does *not* do |
| [`docs/parity.md`](docs/parity.md) | What is witnessed, and what is not |
| `tenapp/` | The TEN app: the `analyst_line` graph, and one descriptor per backend |
| `docker/ten/` | The image, multi-arch — arm64 from the release assets, since the registry has none |
| `tests/` | The configuration held to itself: 38 checks, run by `make test` |

## Quick start

```sh
make doctor   # toolchain, docker, and the upstream stack
make up       # ten + local tts   (PROFILE=semantic adds GPU turn detection)
make status   # is the line usable?
```

`make up` needs `data-agent-service` running first — this repository consumes
its gateway over the network and never runs it.

## Discipline

1. **Nothing voice-shaped goes upstream.** Anything a Slack bot would also want
   belongs in the ask contract; caps, tiers, fillers and phrases live here.
2. **A backend is a descriptor, not a code path.** This repository knows *kinds*
   of capability, never a capability's name — a second service is a file, not a
   change. Enforced by `make test`.
3. **The guards are not here.** This repository holds no authority: it cannot
   refuse, scope or admit anything, only ask.

## Family

Consumes [data-agent-service](https://github.com/calvinchengx/data-agent-service),
which is built on [entra-emulator](https://github.com/calvinchengx/entra-emulator),
[azure-keyvault-emulator](https://github.com/calvinchengx/azure-keyvault-emulator),
[arm-emulator](https://github.com/calvinchengx/arm-emulator),
[fabric-emulator](https://github.com/calvinchengx/fabric-emulator) and
[azure-apim-emulator](https://github.com/calvinchengx/azure-apim-emulator),
composed per [azure-emulators](https://github.com/calvinchengx/azure-emulators).
Tier: leaf / consumer — it emulates nothing.

## License

Apache-2.0.
