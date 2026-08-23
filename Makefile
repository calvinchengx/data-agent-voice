# data-agent-voice -- thin wrappers over docker compose, same verbs as the
# family. The compose file is the source of truth.
#
#   make doctor                  # toolchain, docker, and the upstream stack
#   make up                      # ten + local tts   (PROFILE=semantic adds GPU turn detection)
#   make status                  # is the line usable? (non-zero if not)
#   make call                    # open the browser client against the running line
#   make test                    # the witnesses (docs/00-plan.md §11)
#   make down                    # stop; make clean also drops the model caches
#
# ENV=prod swaps .env for .env.prod (cloud speech, Agora transport, real
# Azure upstream) and nothing else -- discipline rule 2, one level up.
ENV     ?= local
ENVFILE := $(if $(filter prod,$(ENV)),.env.prod,.env)
# PROFILE=semantic | panel | "semantic panel"
PROFILE ?=
COMPOSE  = ENVFILE=$(ENVFILE) docker compose --env-file $(ENVFILE) $(foreach p,$(PROFILE),--profile $(p))
TOOLS    = $(COMPOSE) --profile tools run --rm -e ANTHROPIC_API_KEY tools

# Where the upstream checkout is, for `make doctor` to ask it whether its
# stack is up. Consumed over the network at run time; never built from here.
DAS_DIR ?= ../data-agent-service

ifeq ($(OS),Windows_NT)
  SHELL := sh.exe
  .SHELLFLAGS := -c
endif

PY ?= $(shell for c in python3.13 python3.12 python3 python py; do if "$$c" -c 'import sys; assert sys.version_info >= (3,12)' >/dev/null 2>&1; then echo "$$c"; break; fi; done)

.PHONY: help doctor up down clean restart status ps logs pull build call test witnesses lint format docs docs-build vendor vendor-check lock

help: ## Show the available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

doctor: ## Check the toolchain, docker, and that the upstream stack is reachable
	@ok=1; \
	for c in docker "$(PY)"; do command -v "$$c" >/dev/null 2>&1 && printf "  \033[32mok\033[0m    %s\n" "$$c" || { printf "  \033[31mFAIL\033[0m  %s not found\n" "$$c"; ok=0; }; done; \
	docker compose version >/dev/null 2>&1 && printf "  \033[32mok\033[0m    docker compose\n" || { printf "  \033[31mFAIL\033[0m  docker compose\n"; ok=0; }; \
	test -f $(ENVFILE) && printf "  \033[32mok\033[0m    $(ENVFILE) present\n" || printf "  \033[33mwarn\033[0m  $(ENVFILE) absent; make up copies .env.example\n"; \
	net=$$(grep -E '^DAS_STACK_NETWORK=' $(ENVFILE) .env.example 2>/dev/null | head -1 | cut -d= -f2); \
	docker network inspect "$$net" >/dev/null 2>&1 && printf "  \033[32mok\033[0m    upstream network %s\n" "$$net" || { printf "  \033[31mFAIL\033[0m  upstream network %s absent -- run \`make up\` in $(DAS_DIR) first\n" "$$net"; ok=0; }; \
	if [ -d $(DAS_DIR) ]; then $(MAKE) -s -C $(DAS_DIR) status >/dev/null 2>&1 && printf "  \033[32mok\033[0m    upstream stack reports OK\n" || { printf "  \033[31mFAIL\033[0m  upstream stack not OK (make -C $(DAS_DIR) status)\n"; ok=0; }; fi; \
	docker compose -f $(DAS_DIR)/docker-compose.yml ps --format '{{.Name}} {{.Status}}' 2>/dev/null | grep -q 'ask-1.*healthy' && printf "  \033[32mok\033[0m    upstream ask service healthy\n" || { printf "  \033[31mFAIL\033[0m  upstream ask service not up -- \`make ask-serve\` in $(DAS_DIR)\n"; ok=0; }; \
	arch=$$(uname -m); case "$$arch" in x86_64|arm64|aarch64) printf "  \033[32mok\033[0m    %s: the image has a native leg for this architecture\n" "$$arch";; *) printf "  \033[33mwarn\033[0m  %s has no native leg; the image will run under emulation\n" "$$arch";; esac; \
	docker info 2>/dev/null | grep -qi nvidia && printf "  \033[32mok\033[0m    nvidia runtime (PROFILE=semantic possible)\n" || printf "  \033[33mwarn\033[0m  no nvidia runtime: PROFILE=semantic will not start; DAV_EOU_MODE=fixed\n"; \
	free=$$(df -k . | awk 'NR==2{print int($$4/1048576)}'); [ "$$free" -ge 10 ] && printf "  \033[32mok\033[0m    %s GB free (models: whisper ~150MB-3GB, kokoro ~400MB, turn detection ~15GB)\n" "$$free" || { printf "  \033[31mFAIL\033[0m  %s GB free; need 10\n" "$$free"; ok=0; }; \
	[ $$ok = 1 ] && echo "doctor: ready" || { echo "doctor: fix the FAIL rows"; exit 1; }

pull: ## Pull the pinned dependency images
	$(COMPOSE) pull

build: ## Build the TEN image with this repo's tenapp overlaid on the pinned tag
	$(COMPOSE) build ten

up: ## Start the line in the background (PROFILE=semantic|panel to add services)
	@test -f $(ENVFILE) || cp .env.example $(ENVFILE)
	$(COMPOSE) up -d --build --wait

down: ## Stop and remove containers
	$(COMPOSE) --profile semantic --profile panel down

clean: ## Stop and remove containers AND the model caches (full reset)
	$(COMPOSE) --profile semantic --profile panel down -v

restart: clean up ## Full reset, then start again

status: ## Report whether the line is usable (non-zero exit if not)
	@ok=1; \
	curl -fsS "http://localhost:$${TEN_API_PORT:-8080}/health" >/dev/null 2>&1 && printf "  \033[32mok\033[0m    ten api\n" || { printf "  \033[31mFAIL\033[0m  ten api\n"; ok=0; }; \
	curl -fsS "http://localhost:$${TEN_API_PORT:-8080}/graphs" 2>/dev/null | grep -q analyst_line && printf "  \033[32mok\033[0m    graph analyst_line registered\n" || { printf "  \033[31mFAIL\033[0m  graph analyst_line not registered\n"; ok=0; }; \
	curl -fsS "http://localhost:$${TTS_PORT:-8880}/health" >/dev/null 2>&1 && printf "  \033[32mok\033[0m    tts\n" || { printf "  \033[31mFAIL\033[0m  tts\n"; ok=0; }; \
	[ $$ok = 1 ] && echo "line OK" || { echo "line NOT OK"; exit 1; }

ps: ## Container states
	$(COMPOSE) ps

logs: ## Follow logs (SERVICE=name to filter)
	$(COMPOSE) logs -f $(SERVICE)

call: ## Open the browser client against the running line
	@$(PY) -m webbrowser "http://localhost:$${TEN_API_PORT:-8080}/" >/dev/null 2>&1 || echo "open http://localhost:$${TEN_API_PORT:-8080}/"

test: ## The checks that hold this repo's configuration to itself
	uv run --with pytest --with pytest-cov --with pydantic --with httpx python -m pytest -q $(ARGS)

witnesses: ## Record what the suite witnessed, for the badges (--check to verify)
	uv run --with pytest --with pytest-cov --with pydantic --with httpx python scripts/witnesses.py $(ARGS)

docs: ## Serve the documentation site locally
	pnpm install && pnpm run docs:dev

docs-build: ## Build the site exactly as the workflow does, into _site/
	pnpm install --frozen-lockfile
	python3 scripts/check_docs_nav.py
	pnpm --filter data-agent-voice-docs typecheck
	pnpm run docs:build
	rm -rf _site && mkdir -p _site
	cp site/index.html _site/index.html
	cp -R website/dist _site/docs
	python3 scripts/badges.py --out _site --landing site/index.html
	python3 scripts/check_links.py --site _site

load: ## N concurrent conversations against the line (ARGS="--conversations 5")
	$(TOOLS) python -m load.run $(ARGS)

lint: ## Ruff over the extensions and harnesses
	uv run --with ruff ruff check .

format: ## Ruff format
	uv run --with ruff ruff format .

vendor: ## Copy the extensions this repo uses from the pinned TEN tag into extensions/vendor/
	$(PY) scripts/vendor.py --tag $$(grep -E '^TEN_VERSION=' .env.example | cut -d= -f2)

vendor-check: ## Fail if a vendored extension differs from its tag without a VENDORED entry naming the PR
	$(PY) scripts/vendor.py --check

lock: ## Refresh manifest-lock.json inside the TEN image (the registry packages' pins)
	$(COMPOSE) run --rm ten sh -c 'cd /app/agents/analyst_line/tenapp && tman install && cat manifest-lock.json' > tenapp/manifest-lock.json
