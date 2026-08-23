# tenapp — the Analyst Line graph

The TEN app this repo ships. `manifest.json` names its dependencies,
`property.json` defines the `analyst_line` graph, and `main.go` /
`scripts/start.py` are TEN's own app entrypoints, taken unchanged from the
pinned tag (`docs/05-ten.md`): they load `property.json` and start the
runtime, and nothing in this repo is written in Go.

## The graph

```
 client ──ws──► transport ──pcm──► vad ─────────┐
   ▲                   └───pcm──► stt ──asr────►│
   │                                  └────────►│ turn_detection ──flush──►│
   │                                            ▼                          ▼
   │                                          host ◄──────────────────────┘
   │                                         /  |  \
   │                       text_data ───────┘   |   └────── tts_text_input ──► tts
   │                            ▼               │                              │
   │                          llm ──tool_call──►tools ──ask_dispatched──► bridge
   │                            └──text_data────┘                          │
   └────────────────────── pcm / text_data ◄────────────────── tts ◄───────┘
```

* **transport** — `websocket_server`, base64 PCM in and out. Local, no
  account. Agora replaces this node in `ENV=prod` and nothing else changes.
* **vad / stt** — `ten_vad_python` for barge-in, `whisper_stt_python`
  (faster-whisper) for transcription. Both in-process, both local.
* **turn_detection** — only consulted when `DAV_EOU_MODE=semantic`, which
  needs the vLLM service (`make up PROFILE=semantic`, GPU). In `fixed` mode
  the node is inert and the host uses VAD plus ASR finality.
* **host** — `das_host`, the fork of TEN's `main_python`. Owns the turn and
  the tier policy; the only thing that decides whether a question is answered
  here, looked up, or dispatched.
* **llm** — `anthropic_llm2_python`, the host's model. Sees exactly three
  tools and no others.
* **tools** — a loader, not a fixed set. It reads the backend descriptors in
  `backends/` and registers one LLM tool per declared fast lookup plus one
  dispatch per backend, alongside `confirm`. With one backend that is
  `glossary_lookup`, `ask_data` and `confirm`; with two it is however many
  they declare, and the model routes between the dispatch tools by their
  descriptions (`docs/00-plan.md` §16).
* **bridge** — `das_bridge`, the SSE client on the ask contract — a backend
  at a time, keyed by ticket, not a singleton. Turns `milestone` and `answer`
  events into speech, and `refusal` / `abstention` into fixed phrases that the
  model never sees. It reads `path.speed` to know how an answer was reached
  and never `path.detail`, which is this backend's own vocabulary.
* **tts** — `local_tts` over the Kokoro service, and the server of
  pre-rendered acknowledgements.

## The prompt is a guard, not a personality

`llm.prompt` in `property.json` says the host never answers a data question
itself. That instruction is not what makes it true — the tool surface is:
the model can reach `glossary_lookup`, `dispatch` and `confirm`, and nothing
else. `mcp_client_python` exists in TEN and would hand `run_query` straight
to the conversational model; it is deliberately absent (`docs/05-ten.md` §5).

## Not yet buildable

`das_host`, `das_tools`, `das_bridge` and `local_tts` are named here and do
not exist yet. `make up` fails at `tman install` until they land — that is
the next commit, not an oversight. The four stock extensions and both
entrypoints are real and pinned.
