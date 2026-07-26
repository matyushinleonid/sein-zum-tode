PYTHON ?= python3.14

.PHONY: install run test lint typecheck format check

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	docker compose up --build telegram-ingress

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

check: lint typecheck test
