PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: venv install test lint fmt check

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(BIN)/python -m pip install -U pip
	$(BIN)/pip install -r requirements.txt

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check .

fmt:
	$(BIN)/ruff format .

check: lint test
