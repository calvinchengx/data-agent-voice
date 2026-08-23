# The extensions this repository writes

Four, named by `tenapp/property.json` and not yet written:

| Extension | Base class | What it is |
|---|---|---|
| `das_host` | fork of TEN's `main_python` | owns the turn and the tier policy |
| `das_tools` | `AsyncLLMToolBaseExtension` | a loader: one tool per backend descriptor |
| `das_bridge` | `AsyncExtension` | the SSE client on the ask contract |
| `local_tts` | `AsyncTTS2HttpExtension` | Piper/Kokoro, and the pre-rendered phrases |

Stock extensions are **not** vendored here — `docker/ten/Dockerfile` clones the
framework at the pinned tag and takes them from it, so the tag is the pin and a
diff against it is the review. `extensions/vendor/<name>/` holds only an
extension this repository has *patched*, each patch an upstream PR first and
named in a `VENDORED` file beside it (`docs/05-ten.md` §7).

Two patches are already known to be needed: a prompt-caching breakpoint in
`anthropic_llm2_python`, and there is no local TTS in the catalogue at all.

Until these exist, `make up` fails at `tman install` and the image job in CI
skips rather than failing — `docs/parity.md` records both as not run.
