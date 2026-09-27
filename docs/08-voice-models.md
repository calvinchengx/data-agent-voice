# Voice models

Which speech models can hit **100–200 ms**, per stage and end to end, for a
caller in Singapore. Researched and measured on 2026-09-27; the harness that
measured it is `bench/` and reruns in one command.

## The answer first

**Per stage, 100–200 ms is reachable, but only when the model runs near the
caller.** One round trip to a US-hosted vendor is 170–250 ms from Singapore
(measured below), which spends the whole budget before the model starts. So
the choice is mostly *where* the model runs, and only then *which* model.

**Voice to voice, 100–200 ms is not reachable** by any hosted system with
usable reasoning. The fastest measured hosted speech-to-speech models take
0.6–1.3 s to their first audio (Artificial Analysis), and none of the big
three can speak a fixed phrase verbatim, which the refusal rule
([`00-plan.md`](00-plan.md) rule 4) requires. The cascaded design stays; the
levers are inside it.

**The three changes worth making,** in order of effect:

1. **End-of-turn detection inside the ASR.** The fixed silence wait
   (`DAV_EOU_MODE=fixed`, 500–800 ms) is the largest single delay in the
   budget. Deepgram Flux and Soniox detect end of turn themselves, and both
   already have TEN extensions at 0.11.71 (`deepgram_ws_asr_python`,
   `soniox_asr_python`).
2. **Speak clauses, not sentences.** Every local model measured here returns a
   whole segment at once, so time to first audio grows with segment length:
   Kokoro takes 206–258 ms for a five-word acknowledgement and 500–750 ms for
   a full sentence (table below). Cutting at the first clause is worth more
   than any model swap. Vendors with streaming text input (ElevenLabs,
   Cartesia, Deepgram, Inworld) do this for you.
3. **Pre-render the fixed phrases.** Refusals and acknowledgements are known
   in advance; playing them from disk is 0 ms and guaranteed verbatim.
   `DAV_PRERENDERED_ACK` already exists; extend it to every fixed phrase.

## The network floor, measured from Singapore

TCP and TLS handshakes from this machine (Singapore, MyRepublic), median of
five. A TCP handshake is one round trip.

| Endpoint | TCP | What it tells you |
|---|---|---|
| `api.deepgram.com` | 238 ms | US origin, direct: this is the real WAN cost |
| `api.eu.deepgram.com` / `api.au.deepgram.com` | 181 / 283 ms | no Asian region |
| `streaming.assemblyai.com` | 250 ms | US origin, direct |
| `users-ws.rime.ai` | 244 ms | US origin, direct |
| `eu2.rt.speechmatics.com` | 170 ms | EU origin, direct |
| `bedrock-runtime.ap-northeast-1` (Nova Sonic) | 92 ms | Tokyo |
| ElevenLabs, Cartesia, Inworld, Soniox, Hume, OpenAI, Google, Azure SEA | 7–18 ms | **a CDN edge**, not the model |

**The last row is not a result.** Those hostnames answer from a nearby edge
(Cloudflare, Google's global load balancer, CloudFront), which then forwards
to wherever the model runs. Only a real request shows the true figure, which
is why the cloud leg of the benchmark needs keys. ElevenLabs is the one
vendor that documents routing Southeast Asia to a Singapore cluster; Soniox
documents in-region processing in Japan.

## TTS: time to first audio

### Cloud

Independent figures are Coval's, run from AWS us-east-1 with connection setup
excluded (30-day means to 2026-09-27). Vendor figures are model time and sit
100–300 ms below what a client sees. **From Singapore, add the round trip to
wherever the vendor serves you.**

| Model | Vendor claim | Coval (us-east-1) | Quality (AA arena) | APAC | TEN extension |
|---|---|---|---|---|---|
| Inworld TTS-2 Flash | 25 ms server | **80 ms** | #8 | not documented | `inworld_tts_python` |
| Inworld TTS-2 | <100 ms server | 180 ms | #4 | not documented | same |
| ElevenLabs Flash v2.5 | ~75 ms model; 100–150 ms from SE Asia | 189 ms | not top 10 | **Singapore routing** | `elevenlabs_tts2_python` |
| Deepgram Flux TTS | 80 ms | 207 ms | n/a | US/EU/AU, self-host | `deepgram_tts` (Aura) |
| Soniox TTS | n/a | 253 ms | n/a | **Japan** | none |
| Rime Mist v3 | <100 ms | 259 ms | n/a | US, self-host | `rime_tts` |
| Cartesia Sonic 3.6 | sub-90 ms | 386 ms | **#1** | not documented | `cartesia_tts` |
| Deepgram Aura-2 | ~90 ms | 303 ms | n/a | US/EU/AU, self-host | `deepgram_tts` |
| Google Chirp 3 HD | ~200 ms | 539 ms | n/a | `asia-southeast1` | `google_tts_python` |
| OpenAI gpt-4o-mini-tts | n/a | 1,043 ms | n/a | US | `openai_tts2_python` |

Measured from Singapore by `bench/tts.py`: **pending keys** (see below).

### Local, measured here

`bench/local_tts.py`, in-process on an Apple M4 Max, no network. Time to the
first audio chunk, three passes over the corpus.

**Provisional:** the machine was carrying a load average of 31–41 on 14 cores
from unrelated work while these ran, so absolute values are inflated. The
ordering is sound; rerun on a quiet machine before quoting a number.

| Model | Runs on | 5-word ack | Full sentence | Real-time factor | Verdict |
|---|---|---|---|---|---|
| Kitten TTS nano 0.8 | Metal | **180 ms** | 320–460 ms | 0.1 | fastest, quality to be judged by ear |
| Kokoro-82M (current) | Metal | 206–258 ms | 500–750 ms | 0.1 | the baseline; fine with clause chunking |
| Piper lessac-medium | CPU | 254–284 ms | 620–810 ms | 0.2 | the GPU-less option |
| Qwen3-TTS 0.6B | Metal | 1,215 ms | ~1,600 ms | 0.8 | too slow |
| Soprano-80M | Metal | unstable | | | produced 22 s of audio for five words |
| Pocket TTS (Kyutai) | | | | | gated; access granted, but the local token lacks gated-repo read scope |
| MOSS-TTS-Nano | | | | | needs a reference voice clip |

Two larger open models were measured later, when the load average had
climbed past 100, so only their ratio to Kokoro **in the same run** means
anything:

| Model | Licence | First audio vs Kokoro, same run | Real-time factor | Vendor figure (their hardware) |
|---|---|---|---|---|
| Voxtral 4B TTS 2603 (Mistral) | **CC BY-NC 4.0** | 9.1× slower (8.7 s vs 0.96 s) | 4.5, slower than real time | 70 ms at concurrency 1 on an H200 (vLLM-Omni) |
| VoxCPM2 2B (OpenBMB) | Apache-2.0 | 7.7× slower (8.2 s vs 1.07 s) | 1.9, slower than real time | RTF 0.3 on an RTX 4090, 0.13 with Nano-vLLM; no first-audio figure |

Neither is a laptop model: both are built to be served by vLLM on a data
centre GPU, and Metal cannot show what they do there. Voxtral's licence also
rules out self-hosting it in a product without a separate licence from
Mistral (its hosted API is the commercial route, served from the EU).
VoxCPM2 is the one to measure on a Singapore GPU if voice cloning or its 30
languages matter.

Kokoro through Kokoro-FastAPI in Docker (what compose runs today) measured
tens of seconds on this machine, because another container was using 250% of
the Docker VM's CPU. That is contention, not Kokoro, and is not reported as a
Kokoro number.

## STT: last word spoken to final transcript

### Cloud

| Model | Built-in end of turn | Independent | APAC | TEN extension |
|---|---|---|---|---|
| Soniox stt-rt-v5 | **yes** (`<end>`) | 55 ms finalize (Coval); 249–260 ms from end of speech (Pipecat) | **Japan** | `soniox_asr_python` |
| Deepgram Flux | **yes**, with early end of turn | 84–98 ms finalize (Coval) | US/EU/AU | `deepgram_ws_asr_python` |
| Deepgram Nova-3 | endpointing only | ~220–260 ms from end of speech (Pipecat) | US/EU/AU | same |
| AssemblyAI Universal-3.x Pro | yes | best accuracy, 2.7% WER (Coval) | US | `assemblyai_asr_python` |
| ElevenLabs Scribe v2 Realtime | VAD commit | 130 ms | Singapore routing | ElevenLabs ASR |
| Speechmatics | end-of-utterance | ~500 ms (Pipecat) | EU/US/AU | yes |

Measured from Singapore by `bench/stt.py`: **pending keys**.

### Local, measured here (provisional, same load caveat)

Offline models: the value is decode time after speech ends, and the graph
waits a fixed 500 ms of silence before handing the segment over, on top.

| Model | Runs on | Decode after speech end | Word error rate |
|---|---|---|---|
| Parakeet TDT 0.6B v3 | Metal | **354 ms** p50 | 0 on the fixtures |
| faster-whisper base int8 (current) | CPU | 2,593 ms p50 | 0 |
| faster-whisper small int8 | CPU | 8,215 ms | 0 |
| faster-whisper large-v3-turbo int8 | CPU | 23,028 ms | 0 |

The fixtures are Kokoro-rendered speech, so a zero error rate here is a floor,
not a forecast. The Whisper figures are the ones the load inflates most, being
CPU-bound; Parakeet on Metal was roughly seven times faster than the current
default under the same conditions.

## Speech to speech

| System | Voice to voice | Tool calls | Verbatim fixed phrase | APAC |
|---|---|---|---|---|
| Gemini 2.5 Flash native audio | 0.63 s (AA) | yes | no | Google global |
| Gemini 3.8 Live | 1.18 s (AA) | yes | no | Google global |
| OpenAI GPT-Realtime-2.1 | 1.21 s (AA) | yes | no | US |
| Amazon Nova 2 Sonic | n/a | yes | no | **Tokyo** |
| Ultravox | n/a | yes (strong multi-turn) | **yes** (`ForcedAgentMessage`) | n/a |
| Hume EVI | n/a | yes | **yes** (`assistant_input`) | n/a |
| ElevenLabs Agents | n/a | yes | only with a custom LLM | Singapore routing |

Measured from Singapore by `bench/s2s.py`: **pending keys**.

Replacing the cascade would give up the host (Claude Haiku 4.5, and the prompt
cache planned for it) and, for all but Ultravox and Hume, the verbatim
refusal. Neither is worth an end-to-end number that still does not reach the
target.

## What to deploy

| Stage | Laptop / CI | Production, Singapore |
|---|---|---|
| ASR + end of turn | Parakeet on Metal, or faster-whisper on CPU | **Soniox (Japan) or Deepgram Flux**, both with built-in end of turn; self-hosted Parakeet/Nemotron on a Singapore GPU if audio must not leave |
| TTS | Kokoro with clause chunking; Kitten if its voice passes | **ElevenLabs Flash v2.5** (Singapore routing) over its WebSocket; Kokoro on a Singapore GPU if audio must not leave |
| Fixed phrases | pre-rendered | pre-rendered |

The cloud rows are provisional until `bench/` has measured them from here.

## Running the benchmarks

```sh
# local TTS, on Apple Metal and CPU
uv run --no-project --python 3.12 --with mlx-audio --with sentencepiece \
    --with 'misaki[en]' --with piper-tts --with numpy python -m bench.local_tts

# local STT
uv run --no-project --python 3.12 --with faster-whisper --with parakeet-mlx \
    --with numpy --with websockets python -m bench.stt whisper-base parakeet-mlx

# cloud: every provider whose key is in .env (see .env.example)
uv run --group bench python -m bench.tts
uv run --group bench python -m bench.stt
uv run --group bench python -m bench.s2s
```

A provider with no key is reported as skipped, never as fast. Results land in
`bench/results/` (not committed); this page carries the numbers.
