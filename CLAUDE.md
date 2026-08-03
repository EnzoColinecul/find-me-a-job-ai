# CLAUDE.md — Find-Me-A-Job AI

Job search by geolocation: a user picks a location + radius + role(s); Google Places
finds nearby businesses; an LLM agent investigates each one (careers page → job boards
→ contact email) and returns a ranked list of opportunities. V1 market: **Australia**
(hospitality/retail/trades focus — Places is weak for office roles). Full plan:
`docs/PLAN.md`. Diagram: `docs/architecture.mermaid`.

## Repo layout

```
web/     Next.js 15 + TS (npm, NOT pnpm). Map form, results page, PKCE login.
api/     FastAPI on Lambda (Mangum). uv. Auth (JWT verify), /me, /searches.
agent/   Python (uv, src layout: src/fmaj_agent). Discovery + per-company LLM agent.
infra/   AWS CDK (Python, uv). Stages Fmaj-Test / Fmaj-Prod. infra/gcp = Terraform.
docs/    PLAN.md, architecture.mermaid, google-login-setup.md, external-keys-setup.md,
         llm-provider.md
scripts/ store-external-secrets.sh (Secrets Manager registration)
```

## Environments & identities

- AWS account **418862088910**, region **ap-southeast-2**. Two isolated CDK stages:
  `Fmaj-Test-*` and `Fmaj-Prod-*` (stacks: Data, Auth, Api, Pipeline — Api/Pipeline
  still empty shells; **don't `cdk deploy` empty stacks, deploy named ones**).
- Local deploys/dev AWS calls: profile **`fmaj-deploy`** (user assumes admin role
  `find-me-a-job-ai_role`).
- CI: GitHub Actions OIDC assumes `find-me-a-job-ai_oidc-policy` (trust scoped to
  `repo:EnzoColinecul/find-me-a-job-ai:ref:refs/heads/main`). Merge to main →
  deploy test (`deploy.yml`); prod = manual `workflow_dispatch` (`deploy-prod.yml`,
  free GitHub plan → no environment protection rules).
- GCP project **project-7187e8cf-43d5-451b-be4**; IaC service account
  `iac-find-me-a-job-ai@...` (OAuth Client Admin + Service Usage Admin + API Keys
  Admin). Key JSON sits in repo root but is **git-ignored** — never commit it.
- Cognito test pool: `ap-southeast-2_7asBOlMUh`, client `19mi48bjem0sberbq0b4bas81n`,
  domain `https://fmaj-test.auth.ap-southeast-2.amazoncognito.com`.

## Secrets — rules learned the hard way

- `.gitignore` blocks `.env*`, `client_secret*.json`, `project-*.json`,
  `*gserviceaccount*.json`, `*-outputs.json`, tfstate/tfvars, `*_results.csv`.
  CI has a `secret-scan` job. **Always check `git diff --cached` for secrets before
  committing.**
- Secrets Manager per stage: `fmaj/{stage}/google-client-secret`, `places-key`,
  `adzuna` (JSON app_id/app_key), `web-search-key` (SerpAPI). SSM param:
  `/fmaj/{stage}/google-client-id`. Register via `scripts/store-external-secrets.sh`.
- **Two Google Maps keys, never mix:** a browser key (HTTP-referrer restricted, Maps
  JS + legacy-free autocomplete via `PlaceAutocompleteElement`) in `web/.env.local`
  as `NEXT_PUBLIC_GOOGLE_MAPS_KEY`; a server key (no app restriction, Places API
  (New) only) in Secrets Manager. A referrer-restricted key from a server returns
  403 `API_KEY_HTTP_REFERRER_BLOCKED`.
- `fmaj_agent.secrets` resolves keys env-var-first (`FMAJ_PLACES_KEY`,
  `FMAJ_ADZUNA_APP_ID/KEY`, `FMAJ_SERPAPI_KEY`), Secrets Manager second.

## LLM provider (agent)

Pluggable via `FMAJ_LLM_PROVIDER` = `bedrock` | `gemini` (`agent/src/fmaj_agent/providers.py`).
- **Currently using `gemini`** (`gemini-3.6-flash` on Vertex, GCP credits). Needs
  `GOOGLE_APPLICATION_CREDENTIALS` pointing at the SA key. Gemini 3 requires echoing
  `thought_signature` on function-call parts — handled in GeminiProvider.
- Bedrock (Claude Haiku/Sonnet 4.5 via `au.` inference profiles) is blocked until
  the Anthropic use-case form is approved in the Bedrock console; then it's a drop-in.
- Orchestrator (`orchestrator.py`): triage → tool loop → `report_findings` (strict
  JSON), hard budgets in code (8 tool calls / 60s), forced structured report on
  budget breach, token/cost accounting per run. Tools never raise (ToolResult).
- Conduct: robots.txt respected, honest UA, **never scrape Seek/LinkedIn** (links
  only via SerpAPI `site:` queries) — ToS requirement, don't "fix" this.

## Commands

```bash
make install / dev / test / lint          # dev-api sets AWS_PROFILE=fmaj-deploy
cd infra && cdk deploy 'Fmaj-Test/Data' --profile fmaj-deploy   # cdk is a Node CLI —
                                                                # NEVER `uv run cdk`
cd agent && AWS_PROFILE=fmaj-deploy uv run python scripts/discovery_harness.py \
    --suburb "Surry Hills:-33.8845:151.2119" --role chef        # discovery QA → CSV
cd agent && AWS_PROFILE=fmaj-deploy GOOGLE_APPLICATION_CREDENTIALS=../project-*.json \
    FMAJ_LLM_PROVIDER=gemini uv run python -m fmaj_agent.run \
    --name "X" --website https://x.com --role chef              # one-company agent run
# Reset the free-search quota after testing:
aws dynamodb update-item --table-name fmaj-test-main \
  --key '{"PK":{"S":"USER#<sub>"},"SK":{"S":"PROFILE"}}' \
  --update-expression "SET free_search_used = :f" \
  --expression-attribute-values '{":f":{"BOOL":false}}' \
  --profile fmaj-deploy --region ap-southeast-2
```

Tests: api 10, agent 20 (pytest; agent uses PYTHONPATH=src or uv). Web: `npx tsc
--noEmit` + `npm run lint`. Python target is 3.12+ but avoid 3.11+-only stdlib
(e.g. use `str, Enum` not `StrEnum`) for tooling compatibility.

## Role input (free text → LLM → confirm)

Users describe what they want in their own words; `POST /roles/interpret` (auth, **no
quota consumed**) returns ordered `RoleSuggestion`s they edit/confirm before the search
runs. Each suggestion carries `curated_key` — the `role_mapping.yaml` role whose Places
types to borrow — so a label we've never seen ("dishwasher") still searches the right
venues instead of Text-Searching appliance stores. Falls back to the raw text as one
role if the LLM output is unusable.

**`max_roles` is one knob** (`api/app/settings.py`, PoC = 1). The API validates against
it and the frontend *fetches* it from `GET /config` — raising it for subscriptions needs
no code change. Never hardcode role/radius limits in the frontend.

## Data model (DynamoDB single table `fmaj-{stage}-main`, PK/SK)

- `USER#<cognito-sub> / PROFILE`: email, name, `free_search_used` (quota = atomic
  conditional flip False→True; 402 on second search — no payments in V1).
- `SEARCH#<id> / META`: params, status pending→running→completed|failed, user_sub.
- `SEARCH#<id> / RESULT#<place_id>`: written incrementally by the pipeline; frontend
  polls `GET /searches/{id}` every 3s and renders grouped by opportunity_type.

## Cost discipline (why the code looks the way it does)

- Places (New): search calls use **Pro-only field masks** (5K free/mo); `websiteUri`
  needs **Enterprise** Place Details (1K free/mo → the real monthly ceiling, ~25-33
  searches) so Details is called ONLY for the ≤40 shortlisted companies.
  `rankPreference: DISTANCE` on Nearby (user wants local results).
- Places ToS: don't persist place data beyond the search (place_id is exempt).
- Budgets/caps exist in code, not prompts. Keep per-search cost logged.

## Workflow conventions

- **Notion board tracks everything**: "Find-Me-A-Job AI — V1 Board" under the user's
  Projects page (data source `c378ff64-2263-4147-bd74-3d296332d62e`). When work
  starts/finishes, update the card Status and prepend a dated ✅/🚧 note with
  verification evidence. Cards carry acceptance criteria — meet them before Done.
- Git: small commits with descriptive messages after each working increment; run
  tests before committing; verify no secrets staged. Linters may rewrite files
  (e.g. workflows) — don't revert user edits.
- Verify in the browser (Chrome MCP) when a change is user-facing; server errors that
  surface as CORS "Failed to fetch" are usually unhandled 500s — the api has a global
  exception handler for this; check uvicorn logs.
- Phases from PLAN.md: 0 foundations ✅ · 1 search UX ✅ (browser-verified) ·
  2 discovery ✅ (harness: ~85% relevance, 100% website coverage) · 3 agent core ✅
  (Gemini run verified) — **next: eval set (20 golden companies, precision gate),
  then Step Functions pipeline (Discover → Map conc. 5-10 → Aggregate), then
  Phase 4 results/PDF, Phase 5 hardening/beta.**

## Known state / gotchas

- Deployed so far: `Fmaj-Test/Data` + `Fmaj-Test/Auth` only. Api/Pipeline Lambdas not
  deployed — local uvicorn + npm dev is the working setup; searches stay `pending`
  (no pipeline yet) and the results page correctly shows incremental progress UI.
- `api/.env` and `web/.env.local` hold the working local config (git-ignored).
- AWS free plan: $100 + $100 credits, expires ~late Aug 2026 or when spent — Budgets
  alarms exist; check before enabling anything costly.
- Adzuna ~1K calls/mo free; SerpAPI ~100-250/mo free — the agent uses several
  web_search calls per company, watch this during eval runs.
- The user (Enzo) runs commands locally when credentials/console access is needed;
  give exact copy-pasteable commands and expect pasted output/errors back.
