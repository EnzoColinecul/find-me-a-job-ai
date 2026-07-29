# Find-Me-A-Job AI

Job search by geolocation: pick a location + radius + role, and an LLM agent investigates nearby companies (careers pages → job boards → contact emails). See [docs/PLAN.md](docs/PLAN.md).

## Structure

```
web/     Next.js 15 frontend (map, search form, results)
api/     FastAPI backend (Lambda + Mangum)
agent/   Per-company LLM agent: tools, prompts, evals
infra/   AWS CDK (Python) — test & prod stages
docs/    Plan, architecture diagram, ADRs
```

## Prerequisites

- Node 20+ and pnpm (`corepack enable`)
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- AWS CDK CLI (`npm i -g aws-cdk`)
- AWS CLI profile `fmaj-deploy` assuming `arn:aws:iam::418862088910:role/find-me-a-job-ai_role` (region ap-southeast-2)

## Setup

```bash
cp .env.example .env          # fill in keys — .env is git-ignored
make install                  # installs web + python deps
make dev                      # runs api (:8000) + web (:3000)
make test                     # all tests
make lint                     # ruff + mypy + eslint
```

## Deploy

```bash
cd infra
uv run cdk deploy 'Fmaj-Test/*' --profile fmaj-deploy   # test env
uv run cdk deploy 'Fmaj-Prod/*' --profile fmaj-deploy   # prod env (via CI approval normally)
```

## Secrets policy

`.env*` files and GCP service-account JSON keys are git-ignored. Never commit credentials; runtime secrets live in AWS Secrets Manager per stage (`fmaj/test/*`, `fmaj/prod/*`).
