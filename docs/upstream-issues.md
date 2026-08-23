# Upstream issues

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
