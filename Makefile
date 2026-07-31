PYTHON ?= python3.14
VERBOSE ?= 0

ifeq ($(VERBOSE),1)
PYTEST_FLAGS := -v
else
PYTEST_FLAGS :=
endif

.PHONY: install run test lint typecheck format check

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	docker compose up --build telegram-ingress telegram-worker

test:
	$(PYTHON) -m pytest $(PYTEST_FLAGS)

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

check: lint typecheck test