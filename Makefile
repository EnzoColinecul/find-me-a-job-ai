.PHONY: install dev dev-api dev-web test lint fmt synth

install:
	cd web && npm install
	cd api && uv sync
	cd agent && uv sync
	cd infra && uv sync

dev-api:
	cd api && AWS_PROFILE=$${AWS_PROFILE:-fmaj-deploy} uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

dev:
	$(MAKE) -j2 dev-api dev-web

test:
	cd api && uv run pytest
	cd agent && uv run pytest
	cd infra && uv run pytest

lint:
	cd api && uv run ruff check . && uv run mypy app
	cd agent && uv run ruff check .
	cd infra && uv run ruff check .
	cd web && npm run lint

fmt:
	cd api && uv run ruff format .
	cd agent && uv run ruff format .
	cd infra && uv run ruff format .

synth:
	cd infra && cdk synth
