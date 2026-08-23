# The instrument panel

What the demo needs that a transcript cannot give: **where the time went**, per
turn, live, with the switches visible.

It is a static page. There is no backend, and that is deliberate — the TEN
graph already forwards every `data` message to WebSocket clients
(`docs/05-ten.md` §1), so the panel is one more client of the same socket the
browser client uses. A second server would be a second thing to keep running
and a second place the timings could disagree with what was said.

## What it shows

| Row | From | Why it is the one to watch |
|---|---|---|
| time to first audio | the gap between a final transcript and the first `tts_audio_start` | the number a caller actually feels |
| end of utterance | ASR finality, or the turn detector | the largest non-LLM lever |
| host TTFT | first `text_data` from the model | what caching moves |
| tier | which tool the model reached for | `fast` answers never dispatch |
| dispatch → answer | `agent_turn` kinds, in order | the 8–25 s nobody is waiting through |

p95, not mean. A mean hides the turn that made someone think it was broken.

## What it does not store

Nothing. It holds the current call in the browser tab and forgets it when the
tab closes: no audio, no transcript, no question (D7). The rows are timings and
event kinds, which is what the promoter's argument upstream requires — the only
privacy claim that survives is that the data is not there.
