---
title: Overview
description: The Analyst Line — talk to your governed data, over a service that takes twenty-six seconds and a conversation that cannot wait.
editUrl: false
---

Talk to your governed data. Ask out loud, and hear the answer with the definition it
applied and the caveat it raised — because you cannot skim audio, and a number without
its meaning is how the wrong team wins.

A voice front end over [data-agent-service](https://github.com/calvinchengx/data-agent-service),
built on the [TEN framework](https://github.com/TEN-framework/ten-framework). You sign in
once, and every question runs as you, all the way to the source.

:::caution[No one has heard an answer from this]
The architecture is decided, the framework is pinned and read from its source, both
image legs build, all seven nodes load, and speech has been recognised end to end. What
has never happened is a reply coming back as sound. [Parity](/data-agent-voice/docs/parity/) says which rows
are green and which are red, and none of them claims a working line.
:::

## Getting started

- [Quickstart](/data-agent-voice/docs/01-quickstart/) — run it, and what you will and will not get
- [Architecture](/data-agent-voice/docs/02-architecture/) — the two loops, the nodes, and where authority is not

## Using it

- [Tiers](/data-agent-voice/docs/04-tiers/) — the three tiers, and what the host may never say
- [Latency](/data-agent-voice/docs/03-latency/) — the budget, the switches, and where the seconds actually are

## Proving it

- [Witnesses](/data-agent-voice/docs/06-witnesses/) — what is checked, and what that is worth
- [CI](/data-agent-voice/docs/07-ci/) — what runs when; a documentation change skips the image builds

## Reference

- [The plan](/data-agent-voice/docs/00-plan/) — the long-form argument: decisions, phases, risks
- [TEN at 0.11.71](/data-agent-voice/docs/05-ten/) — read from source, including what it does not do
- [Parity](/data-agent-voice/docs/parity/) — what is witnessed, and what is not
- [Upstream issues](/data-agent-voice/docs/upstream-issues/) — seven defects, found by running it

## The gap this is built around

A question to the service upstream takes **26 seconds at the median**. A conversation
reads as broken after about **one second** of silence. No faster model closes a gap of
thirty times, so this does not try to: the conversation stops waiting for the agent,
and the agent runs where nobody is waiting.
