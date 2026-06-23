DEV_DOCKER_COMPOSE ?= docker compose -f docker-compose.dev.yml
DEV_EMBEDDING_PROVIDER ?= openai
DEV_INDEX_BATCH_SIZE ?= 100

.PHONY: install format lint type test check migrate docker-up docker-down start-dev-docker migrate-dev-docker stop-dev-docker index-dev run-api run-worker web-install web-dev web-api-types web-check web-e2e

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

start-dev-docker:
	$(DEV_DOCKER_COMPOSE) up --build

migrate-dev-docker:
	$(DEV_DOCKER_COMPOSE) run --rm migrate

stop-dev-docker:
	$(DEV_DOCKER_COMPOSE) down

index-dev:
	$(DEV_DOCKER_COMPOSE) run --rm migrate
	$(DEV_DOCKER_COMPOSE) run --rm api company-lens ingest-company-facts --all
	$(DEV_DOCKER_COMPOSE) run --rm api company-lens ingest-sec --all
	$(DEV_DOCKER_COMPOSE) run --rm api company-lens process-documents
	$(DEV_DOCKER_COMPOSE) run --rm api company-lens index-embeddings --embedding-provider $(DEV_EMBEDDING_PROVIDER) --batch-size $(DEV_INDEX_BATCH_SIZE)

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
