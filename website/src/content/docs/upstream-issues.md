---
title: "Upstream issues"
editUrl: "https://github.com/calvinchengx/data-agent-voice/edit/main/docs/upstream-issues.md"
---

Suspected bugs and rough edges in dependencies, written up rather than worked
around silently. The family rule is that dependencies are used as-is; this file
is where the cost of that shows.

Each entry names what was observed, what was expected, and what this repository
does in the meantime.

---

## 1. The API server requires `AGORA_APP_ID` for graphs that have no RTC node

**Project** TEN framework · **Version** 0.11.71 · **Status** worked around

**Observed.** The Go API server refuses to start:

```
ERROR environment AGORA_APP_ID invalid
```

**Expected.** A graph whose transport is `websocket_server` contains no
`agora_rtc` node and needs no Agora account. The `websocket-example` shipped at
the same tag is exactly such a graph, so the validation contradicts one of the
project's own examples.

**Repro.** Build any tenapp whose graph has no `agora_rtc` node and run the
server with `AGORA_APP_ID` unset. The check is `main.go:54`:

```go
agoraAppId := os.Getenv("AGORA_APP_ID")
if len(agoraAppId) != 32 { ... os.Exit(1) }
```

Length, and nothing else — so any 32 characters pass and a real app id of a
different length would not.

**Meanwhile.** `docker/ten/Dockerfile` sets a 32-character placeholder that
says what it is: `noagorartcnodeinthisgraph0000000`. Nothing reads it. If a
future version validates the *format*, the placeholder would have to look like
a real app id rather than announce itself, which would be worse — a fake
credential that reads as real is the thing this family's discipline exists to
prevent.

**Proposed fix.** Validate the variable when a node that needs it is present,
not at start-up.

---

## 2. The arm64 runtime is published in the release but not in the package registry

**Project** TEN framework · **Version** 0.11.71 · **Status** worked around

**Observed.** `tman install` on aarch64 resolves nothing: `manifest-lock.json`
records `supports: [linux/x64]` for `ten_runtime`, `ten_runtime_python` and
`ten_runtime_go`, and `ghcr.io/ten-framework/ten_agent_build` is a single-arch
amd64 image with no manifest list.

**Expected.** The same tag's GitHub release **does** publish
`ten_packages-linux-arm64-gcc-release.zip` and `tman-linux-release-arm64.zip`,
carrying working aarch64 builds of all three. So arm64 is supported by the
project and unreachable through the two channels a Dockerfile would use, which
reads as "arm64 unsupported" and is not.

**Meanwhile.** `docker/ten/Dockerfile` has two builder stages selected by
`TARGETARCH`; the arm64 one unpacks the release assets. Both legs build, and
this repository's images run on both.

**Proposed fix.** Publish the aarch64 packages to the registry, and the build
image as a manifest list.

---

## 3. The arm64 `tman` needs a newer glibc than the base image the project uses

**Project** TEN framework · **Version** 0.11.71 · **Status** worked around

**Observed.** The arm64 `tman` from the release will not start on
`ubuntu:22.04`:

```
tman: /lib/aarch64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
tman: /lib/aarch64-linux-gnu/libc.so.6: version `GLIBC_2.39' not found
```

**Expected.** The project's own build image is 22.04-based (glibc 2.35), so a
release binary that cannot run there is inconsistent with the toolchain the
project ships.

**Meanwhile.** The arm64 builder and the runtime image are `ubuntu:24.04`
(glibc 2.39). The amd64 leg keeps TEN's own image, so the path upstream tests
is unchanged.

**Proposed fix.** Build the arm64 release binaries against the same glibc as
the published build image, or publish the minimum required version.


---

## 4. The Python addon loader looks for `libpython3.10` by name

**Project** TEN framework · **Version** 0.11.71 · **Status** worked around

**Observed.** On a 24.04 image (Python 3.12) every worker exits 250:

```
Failed to dlopen libpython3.10.so: cannot open shared object file
[Python addon loader] Failed to load Python libraries. Cannot continue.
```

**Expected.** The loader to find the interpreter it is running under. It does
name the escape hatch — `TEN_PYTHON_LIB_PATH` — which is good; what is not
documented is that the value is a **single file path**, not a search path. A
colon-separated list is `dlopen`ed verbatim and fails reporting the whole
string as a filename.

**Meanwhile.** The image symlinks the real library to one fixed path and points
the variable at it, so one value is right on both architectures.

**Proposed fix.** Derive the library name from the running interpreter, and say
in the error that the variable takes a file.

---

## 5. `ten_ai_base` imports `aiofiles` without declaring it

**Project** TEN framework · **Version** 0.11.71 · **Status** worked around

**Observed.** `whisper_stt_python` fails at instance creation:

```
ModuleNotFoundError: No module named 'aiofiles'
  File ".../whisper_stt_python/addon.py", line 12, in on_create_instance
```

Its `requirements.txt` lists `faster-whisper`, `numpy`, `pydantic`, `pytest` —
no `aiofiles`. Across the whole catalogue only `soniox_asr_python` declares it,
so every other ASR extension works or fails depending on what else happened to
be installed alongside it.

**Expected.** A dependency of the base class to be declared by the base class.

**Meanwhile.** The image installs `aiofiles` explicitly and asserts the import
at build time. The failure is otherwise invisible until a session starts, which
is after `/start` has answered 200.

**Proposed fix.** Declare it in `ten_ai_base`.


---

## 6. `ten_vad` has no Linux aarch64 build

**Project** TEN VAD (via `ten_vad_python`) · **Version** as pinned at 0.11.71 ·
**Status** routed around

**Observed.** The extension registers, then dies in `on_start`:

```
NotImplementedError: Unsupported platform: Linux aarch64
  ten_vad/__init__.py, line 72
```

The whole graph fails with it, so a single unsupported node makes the entire
line unstartable on arm64 — everything else in this repository runs there
natively.

**Expected.** Either an aarch64 build, or a node that degrades rather than
raising. The library is a small signal-processing routine, not something with
an architectural reason to be x86-only.

**Meanwhile.** The node is gone from both graphs. `whisper_stt_python` already
runs `vad_filter=True` with its own silence parameters
(`whisper_client.py:136`), so voice activity detection still happens — it
happens inside the recogniser instead of in front of it. What is lost is a
separately tunable VAD, which switch #1's "fixed" mode did not use anyway.

**Proposed fix.** Publish an aarch64 wheel.


---

## 7. `main_python` sends `temperature`, and the Claude extension only strips it on the thinking path

**Project** TEN framework · **Version** 0.11.71 · **Status** patched in the fork

**Observed.** Every turn fails:

```
RuntimeError: CreateMessage failed, err:
AsyncMessages.stream() got an unexpected keyword argument 'temperature'
```

**Why the two halves miss each other.** `main_python/agent/llm_exec.py:162`
sends `parameters={"temperature": 0.7}` on every turn.
`anthropic_llm2_python/anthropic_llm.py:431` drops sampling parameters — but
only `if thinking_enabled`, and adaptive thinking is added only for
4.6-generation models and later. So the combination that fails is
**`main_python` + `anthropic_llm2_python` + any 4.5-generation model**, which
is exactly what a latency-conscious voice agent would choose for its host: the
extension's own comment names `main_python` as the source of the value, so
both halves knew about each other and neither covers this case.

**Meanwhile.** The fork sends no sampling parameters. The host speaks one or
two short sentences to a fixed policy and wants no temperature.

**Proposed fix.** Strip sampling parameters whenever the SDK rejects them, not
only when thinking is on — or stop sending them from `main_python`.
