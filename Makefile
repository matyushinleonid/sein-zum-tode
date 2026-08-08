PYTHON ?= python3.14
VERBOSE ?= 0
USE_WORKERS ?= 1
PYTEST_WORKERS ?= auto

ifeq ($(VERBOSE),1)
PYTEST_FLAGS := -v
else
PYTEST_FLAGS :=
endif

ifeq ($(USE_WORKERS),1)
PYTEST_FLAGS += -n $(PYTEST_WORKERS) --dist loadscope --maxprocesses 4
endif

.PHONY: install run test replay lint typecheck format check

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	docker compose up --build telegram-ingress telegram-worker

test:
	$(PYTHON) -m pytest $(PYTEST_FLAGS)

replay:
	@test -n "$(SINCE)" || { echo "SINCE is required, for example: make replay SINCE=2026-08-01"; exit 1; }
	REPLAY_SINCE="$(SINCE)" $(PYTHON) -m pytest tests/replay -m replay --no-cov -s

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

check: lint typecheck test