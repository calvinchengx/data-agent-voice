---
title: "Quickstart"
editUrl: "https://github.com/calvinchengx/data-agent-voice/edit/main/docs/01-quickstart.md"
---

```sh
make doctor   # toolchain, docker, and the upstream stack
make up       # the graph and a local voice
make status   # is the line usable?
make call     # open the browser client
```

`make doctor` is the one to read. It checks the things that actually stop a
first run: whether the upstream stack is up, whether its ask service is
healthy, whether this machine has a native leg for the image, whether there is
an NVIDIA runtime (there usually is not), and whether there is disk for the
models.

## What has to be running first

This repository **consumes** [`data-agent-service`](https://github.com/calvinchengx/data-agent-service)
and never runs it. In that checkout:

```sh
make up          # the emulator family, the gateway, the executor
make ask-serve   # the ask service, behind the gateway at /ask
```

`make doctor` here fails with the reason when either is missing, rather than
letting `make up` get halfway and time out against a name that does not
resolve.

## What comes up

| Service | Port | |
|---|---|---|
| `ten` | 8080 | the API server: `/start`, `/stop`, `/graphs` |
| | 8765 | the WebSocket the browser and the panel both use |
| `tts` | 8880 | a local voice, no account |
| `turn-detection` | 8000 | only with `PROFILE=semantic`, and only on a GPU |
| `panel` | 3100 | only with `PROFILE=panel` |

```sh
make up PROFILE=panel               # add the instrument panel
make up PROFILE="semantic panel"    # and GPU turn detection
```

## Talking to it

`make call` opens the browser client. Without a microphone you can drive the
socket directly — synthesize a question with the same voice the line speaks
with, and send it as 20 ms frames of 16 kHz mono PCM:

```python
import json, base64, urllib.request, audioop, asyncio, websockets

body = json.dumps({"model": "kokoro", "voice": "af_heart",
                   "input": "Which support team resolves tickets fastest?",
                   "response_format": "pcm"}).encode()
pcm = urllib.request.urlopen(urllib.request.Request(
    "http://localhost:8880/v1/audio/speech", data=body,
    headers={"Content-Type": "application/json"})).read()
pcm, _ = audioop.ratecv(pcm, 2, 1, 24000, 16000, None)
pcm += b"\x00\x00" * 32000        # trailing silence closes the turn

async def ask():
    async with websockets.connect("ws://localhost:8765") as ws:
        for i in range(0, len(pcm), 640):
            await ws.send(json.dumps({"audio": base64.b64encode(pcm[i:i+640]).decode()}))
            await asyncio.sleep(0.02)
        async for raw in ws:
            print(str(raw)[:120])

asyncio.run(ask())
```

The trailing silence matters: without it the recogniser never finalises and the
host never takes the turn.

## What you will and will not get

Transcripts come back. **An answer does not**, unless `ANTHROPIC_API_KEY` is set
in `.env` — the host's model call is the first thing that needs a real model,
and the upstream `llm-stub` answers plain JSON where the SDK streams.
[`parity.md`](/data-agent-voice/docs/parity/) is the authority on which of those rows are green.

## When something is wrong

| Symptom | Cause |
|---|---|
| `make up` exits, `AGORA_APP_ID invalid` | it is validated even for a graph with no RTC node, and the check is length ≠ 32 ([upstream 1](/data-agent-voice/docs/upstream-issues/)) |
| a session dies right after `/start` answered 200 | the worker, not the server. `docker compose logs ten` has the traceback |
| `Failed to load the addon … using all addon loaders`, no traceback | an extension whose `__init__.py` does not import its addon: present on disk, invisible to the runtime |
| `PROFILE=semantic` will not start | it needs a GPU. `DAV_EOU_MODE=fixed` is the default for that reason |
