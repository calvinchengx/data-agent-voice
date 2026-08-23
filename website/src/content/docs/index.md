---
title: Overview
description: The Analyst Line — talk to your governed data, over a service that takes twenty-six seconds and a conversation that cannot wait.
editUrl: false
---

Talk to your governed data. Ask in English, out loud, and hear the answer with the
definition it applied and the caveat it raised — because you cannot skim audio, and a
number without its meaning is how the wrong team wins.

A voice front end over [data-agent-service](https://github.com/calvinchengx/data-agent-service),
built on the [TEN framework](https://github.com/TEN-framework/ten-framework). You sign in
once, and every question runs as you, all the way to the source.

:::caution[No audio has ever been through this]
The architecture is decided, the framework is pinned and read, the image and the graph
exist, and the configuration is held to itself by a test suite. Four extensions the graph
names are not written yet. [Parity](/data-agent-voice/docs/parity/) says which rows are green and which are
red, and none of them claims a working line.
:::

## Start here

- [The plan](/data-agent-voice/docs/00-plan/) — the architecture, the latency budget, the phases and the risks
- [TEN at 0.11.71](/data-agent-voice/docs/05-ten/) — what the framework actually does, read from its source,
  including what it does not do
- [Parity](/data-agent-voice/docs/parity/) — what is witnessed, and what is not

## The gap this is built around

A question to the service upstream takes **26 seconds at the median**. A conversation
reads as broken after about **one second** of silence. No faster model closes a gap of
thirty times, so this does not try to: the conversation stops waiting for the agent, and
the agent runs where nobody is waiting.
