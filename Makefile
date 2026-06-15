.PHONY: install format lint type test check migrate docker-up docker-down run-api

install:
	python -m pip install -e ".[dev]"

format:
	ruff format .
	ruff check --fix .

lint:
	ruff check .
	ruff format --check .

type:
	mypy

test:
	pytest

check: lint type test

migrate:
	alembic upgrade head

docker-up:
	docker compose up --build

docker-down:
	docker compose down

run-api:
	uvicorn company_lens.main:app --reload --host 0.0.0.0 --port 8000

