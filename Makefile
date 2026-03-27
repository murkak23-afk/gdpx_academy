PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: venv install test lint fmt check run-local migrate-local docker-up docker-down logs-bot

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

migrate-local:
	ENV_FILE=.env.local $(BIN)/alembic upgrade head

run-local:
	ENV_FILE=.env.local $(BIN)/python -m src

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

logs-bot:
	docker compose logs -f bot
