# syntax=docker/dockerfile:1.7
#
# The Analyst Line's TEN image, multi-arch.
#
#   docker buildx build --platform linux/amd64,linux/arm64 -f docker/ten/Dockerfile .
#
# TEN publishes its build image for amd64 only, and its package registry
# serves the runtime as `linux/x64` alone -- so `tman install` cannot resolve
# a runtime on arm64 at all (docs/05-ten.md §8). But the release assets at the
# same tag DO include `ten_packages-linux-arm64-gcc-release.zip` and
# `tman-linux-release-arm64.zip`, carrying ten_runtime, ten_runtime_python and
# ten_runtime_go built for aarch64. So the two legs differ only in where the
# runtime comes from:
#
#   amd64  -- TEN's published build image, then `tman install`. The path
#             upstream tests, and the one to trust when the two disagree.
#   arm64  -- ubuntu:22.04 plus the release assets unpacked into place, with
#             `tman install --standalone` for the pure-Python packages only.
#
# Everything after that is identical, so a bug that reproduces on one leg and
# not the other is a runtime-build difference and belongs in
# docs/upstream-issues.md rather than being worked around here.

ARG TEN_VERSION=0.11.71
ARG TEN_BUILD_IMAGE_VERSION=0.7.14

# --------------------------------------------------------------- sources --
# The framework at the pin, for the stock extensions and the Go API server.
# Cloned rather than vendored into this repo: the tag IS the pin, a clone is
# reviewable by diffing against it, and only PATCHED extensions need to live
# in this repo (extensions/vendor/, docs/05-ten.md §7).
FROM alpine/git:2.45.2 AS ten-src
ARG TEN_VERSION
WORKDIR /src
RUN git clone --depth 1 --branch ${TEN_VERSION} \
      https://github.com/TEN-framework/ten-framework.git ten \
 && rm -rf ten/.git

# ------------------------------------------------------- builder (amd64) --
FROM ghcr.io/ten-framework/ten_agent_build:${TEN_BUILD_IMAGE_VERSION} AS builder-amd64
ARG TEN_VERSION
ENV TEN_ARCH_SOURCE=registry
# TEN's build image is 22.04, whose pip predates PEP 668 and rejects the flag
# the 24.04 leg needs. One variable rather than two install steps.
ENV PIP_FLAGS=""

# ------------------------------------------------------- builder (arm64) --
# The same toolchain the published image has, assembled for aarch64, plus the
# runtime unpacked from the release. Versions match
# tools/docker_for_building/ubuntu/22.04/Dockerfile at the tag.
# 24.04, not 22.04: the arm64 `tman` in the release is linked against glibc
# 2.38/2.39 and 22.04 ships 2.35, so it will not start at all. The amd64 leg
# keeps TEN's own 22.04-based image, which is what upstream tests.
FROM ubuntu:24.04 AS builder-arm64
ARG TEN_VERSION
ENV TEN_ARCH_SOURCE=release
ENV PIP_FLAGS="--break-system-packages"
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential clang cmake curl unzip zip git jq ca-certificates \
      libasound2-dev libgstreamer1.0-dev libunwind-dev libssl-dev libc++1 \
      python3 python3-dev python3-pip python3-venv \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSLO https://go.dev/dl/go1.22.3.linux-arm64.tar.gz \
 && tar -C /usr/local -xzf go1.22.3.linux-arm64.tar.gz \
 && rm go1.22.3.linux-arm64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
# tman and the aarch64 runtime, from the release assets at the same tag.
RUN set -eux; \
    base="https://github.com/TEN-framework/ten-framework/releases/download/${TEN_VERSION}"; \
    curl -fsSLo /tmp/tman.zip "$base/tman-linux-release-arm64.zip"; \
    unzip -q /tmp/tman.zip -d /tmp/tman; \
    install -m 0755 /tmp/tman/ten_manager/bin/tman /usr/local/bin/tman; \
    curl -fsSLo /tmp/pkgs.zip "$base/ten_packages-linux-arm64-gcc-release.zip"; \
    mkdir -p /opt/ten_arm64; \
    unzip -q /tmp/pkgs.zip -d /opt/ten_arm64; \
    rm -rf /tmp/tman.zip /tmp/tman /tmp/pkgs.zip; \
    test -f /opt/ten_arm64/ten_packages/system/ten_runtime_python/lib/libten_runtime_python.so

# ---------------------------------------------------------------- build --
# TARGETARCH picks the leg; everything below is arch-neutral.
FROM builder-${TARGETARCH} AS build
ARG TEN_VERSION
ARG TARGETARCH
WORKDIR /app

COPY --from=ten-src /src/ten/ai_agents/server/            server/
COPY --from=ten-src /src/ten/ai_agents/agents/scripts/    agents/scripts/
COPY --from=ten-src /src/ten/ai_agents/agents/ten_packages/ agents/ten_packages/

# This repo's own extensions, then any patched stock ones on top. A vendored
# extension always shadows its upstream namesake, and `make vendor-check`
# fails if it differs from the tag without a VENDORED file naming the PR.
COPY extensions/            agents/ten_packages/extension/
COPY tenapp/                agents/analyst_line/tenapp/

WORKDIR /app/agents/analyst_line/tenapp
RUN set -eux; \
    if [ "$TEN_ARCH_SOURCE" = "release" ]; then \
      # The registry has no aarch64 runtime; place it, then let tman resolve
      # only what is left (ten_ai_base is pure Python and arch-neutral --
      # its `supports` list at the tag is empty).
      mkdir -p ten_packages; \
      cp -a /opt/ten_arm64/ten_packages/. ten_packages/; \
      tman install --standalone || tman install; \
    else \
      tman install; \
    fi; \
    test -d ten_packages/system/ten_runtime_python

# Python dependencies for every extension the graph loads.
#
# `find -L`, and the count is asserted. `tman install` links each extension
# into ten_packages/ rather than copying it, so a plain `find` matches nothing
# -- which it did, silently, behind a `||` fallback: the image built, and
# `ctranslate2` was simply absent, so the ASR node would have failed to load
# at the first call rather than at build time. An install step that can find
# nothing and still succeed is not an install step.
RUN set -eux; \
    reqs=$(find -L ten_packages/extension -maxdepth 2 -name requirements.txt); \
    test -n "$reqs"; \
    echo "$reqs" | wc -l; \
    for r in $reqs; do pip3 install --no-cache-dir $PIP_FLAGS -r "$r"; done; \
    # Not every extension declares its dependencies in requirements.txt --
    # ten_turn_detection uses pyproject.toml and needs `openai`, which a
    # requirements-only sweep misses entirely.
    for t in $(find -L ten_packages/extension -maxdepth 2 -name pyproject.toml); do \
      pip3 install --no-cache-dir $PIP_FLAGS "$(dirname "$t")" || true; \
    done; \
    python3 -c "import ctranslate2, faster_whisper, httpx, anthropic"

# Undeclared and unreachable dependencies. `ten_ai_base` imports aiofiles and
# only one ASR extension in the catalogue happens to list it, so an extension
# whose own requirements do not is fine at build time and fails at instance
# creation -- after /start has answered 200. `ten_turn_detection` needs openai
# and declares it in pyproject.toml, which a requirements.txt sweep never sees.
# docs/upstream-issues.md 5.
RUN pip3 install --no-cache-dir $PIP_FLAGS aiofiles openai \
 && python3 -c "import aiofiles, openai"

# The Go API server: /start spawns one worker per session.
WORKDIR /app/server
RUN go build -o bin/api ./cmd/api 2>/dev/null || go build -o bin/api .

# Package what the runtime image needs.
# The app binary. `tman install` fetches the runtime and the extensions, and
# the API server is a separate program -- neither produces this. The worker the
# server spawns is `tenapp/bin/main`, built from the tenapp's own main.go, and
# without it every session dies with "bin/main not found" AFTER /start has
# already answered 200. Asserted here so a missing binary fails the build.
WORKDIR /app/agents/analyst_line/tenapp
# cgo has to be told where the runtime is. `tman install` puts
# libten_runtime_go.a and libten_runtime.so under ten_packages/system/, and
# nothing sets CGO_LDFLAGS for them -- so a bare `go build` fails at link with
# a page of undefined references to ten_go_*, which reads as a broken module
# rather than a missing -L.
ENV LIBS=/app/agents/analyst_line/tenapp/ten_packages/system
RUN CGO_LDFLAGS="-L$LIBS/ten_runtime_go/lib -L$LIBS/ten_runtime/lib -lten_runtime_go -lten_runtime -lten_utils -Wl,-rpath,\$ORIGIN/../ten_packages/system/ten_runtime/lib" \
    go build -o bin/main . \
 && test -x bin/main
RUN tman package --output-path /tmp/app.tar 2>/dev/null || true

# --------------------------------------------------------------- runtime --
# Also 24.04, for the same reason on the arm64 leg -- the runtime libraries in
# the release need it. amd64 binaries built on 22.04 run here unchanged, glibc
# being backward compatible; the reverse is what fails.
FROM ubuntu:24.04
ARG TEN_VERSION
LABEL org.opencontainers.image.title="data-agent-voice / analyst-line" \
      org.opencontainers.image.description="TEN graph for the Analyst Line: WebSocket in, local ASR/TTS, Claude host, the ask service behind it" \
      org.opencontainers.image.source="https://github.com/calvinchengx/data-agent-voice" \
      org.opencontainers.image.licenses="Apache-2.0" \
      com.calvinchengx.ten.version="${TEN_VERSION}"

ENV DEBIAN_FRONTEND=noninteractive
# libasound2 became libasound2t64 in 24.04 (the time_t transition). Naming the
# old one here fails the build with "no installation candidate", which reads as
# a missing package rather than a renamed one.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libasound2t64 libgstreamer1.0-dev libunwind-dev libc++1 libssl-dev \
      python3 python3-pip python3-venv ca-certificates curl jq \
      libpython3.12 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app/agents/    agents/
COPY --from=build /app/server/bin/api server/bin/api
COPY --from=build /usr/local/lib  /usr/local/lib
COPY --from=build /usr/local/bin/tman /usr/local/bin/tman
RUN ldconfig

# faster-whisper's weights are pulled on first use into this cache, which
# compose keeps in a volume: a cold start downloads, a restart does not.
# LOG_PATH is required, not optional: the server exits at start-up with
# "mkdir : no such file or directory" when it is unset, which names the
# symptom and not the cause. Set here so the image runs on its own rather
# than only under this repository's compose file.
# TEN_PYTHON_LIB_PATH because the Python addon loader looks for
# `libpython3.10.so` by name and this image is 24.04, which ships 3.12. The
# loader says so itself and names the variable; without it every worker exits
# 250 with "Cannot continue" and the session dies AFTER /start answered 200.
#
# The value is a FILE, not a search path -- a colon-separated list is dlopened
# verbatim and fails naming itself. The symlink below gives one path that is
# right on both architectures. docs/upstream-issues.md 4.
#
# AGORA_APP_ID is validated at start-up whether or not a graph contains an
# `agora_rtc` node, and this one does not -- the transport is
# `websocket_server` (docs/05-ten.md §1). The check is `len() != 32` and
# nothing else, so the placeholder is exactly 32 characters and says what it
# is. Nothing reads it. Written up in docs/upstream-issues.md.
# One fixed path to the real library, whatever the architecture calls its
# multiarch directory.
RUN set -eux; \
    lib=$(find /usr/lib -name "libpython3.12.so.1.0" | head -1); \
    test -n "$lib"; \
    ln -sf "$lib" /usr/lib/libpython-for-ten.so
RUN mkdir -p /app/log
ENV HF_HOME=/root/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    LOG_PATH=/app/log \
    LOG_STDOUT=true \
    WORKERS_MAX=10 \
    WORKER_QUIT_TIMEOUT_SECONDS=120 \
    SERVER_PORT=8080 \
    AGORA_APP_ID=noagorartcnodeinthisgraph0000000 \
    TEN_PYTHON_LIB_PATH=/usr/lib/libpython-for-ten.so

EXPOSE 8080 8765
HEALTHCHECK --interval=10s --timeout=5s --retries=18 --start-period=30s \
  CMD curl -fsS http://localhost:${SERVER_PORT}/health || exit 1

# Never `bin/worker` directly, and never the binary without the tenapp dir --
# the server needs it to find the graph (docs/ai/L1/07_gotchas.md).
CMD ["/app/server/bin/api", "-tenapp_dir=/app/agents/analyst_line/tenapp"]
