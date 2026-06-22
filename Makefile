.PHONY: install format lint type test check migrate docker-up docker-down run-api run-worker web-install web-dev web-api-types web-check web-e2e

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

run-worker:
	company-lens research-worker

web-install:
	pnpm --dir web install

web-dev:
	pnpm --dir web dev

web-api-types:
	pnpm --dir web api:generate

web-check:
	pnpm --dir web lint
	pnpm --dir web typecheck
	pnpm --dir web test
	pnpm --dir web build

web-e2e:
	pnpm --dir web test:e2e
