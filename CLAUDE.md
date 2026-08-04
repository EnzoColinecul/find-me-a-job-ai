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
  JS + Places Autocomplete Data API — see below) in `web/.env.local`
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
- **Trace (`trace.py`) feeds the "nothing hidden" panel, so it must not lie.**
  `TOOL_LABELS` is the one place internal names become display names, and every
  label must name a call we really make (the mockup's `places.details` row is
  labelled `triage` because that's what runs — a test enforces this). Empty tool
  results are `Checking`, never `Found`. `investigate(on_step=…)` emits steps; a
  throwing sink is swallowed — the panel must never fail a search.

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

Tests: api 24, agent 44 (pytest; agent uses PYTHONPATH=src or uv). Web: `npx tsc
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

## Design (mockups landed 2026-08-04)

Source of truth: **`design/DESIGN-SPEC.md`** (tokens, per-screen specs, gaps) with
`design/mockups-extracted.html` (decoded markup — open for exact values) and the
original bundle `design/Find Me A Job AI - Mockups.html`. Logo: `design/Logo-Idea.png`
(2.1 MB — must be optimised into `web/public/` before use).

Direction: warm **paper-like editorial** UI — cream `#f6f5f2`, surface `#fffdf7`,
navy ink `#14213d`, accent `#3d6fb5`, pin `#ff5a45`, Inter. A stylised street map is
the hero; the agent's work is shown openly. **This reverses the current dark-by-default
styling** — the design is light-native.

Five screens: login (map hero + "Continue with Google") · conversational home
("Hello Alex — what role do you want next?") · **three-pane workspace** (recent
searches + profile | map | roles/radius/start) · results ("3 places worth contacting",
source-labelled links) · **live agent trace** ("What I'm doing — nothing hidden").
Full mobile set included.

The trace panel's tools map 1:1 onto real ones (`places.nearby`→discovery,
`fetch_page`→`fetch_url`, `extract_jobs`→careers/Adzuna, `web_search`→SerpAPI,
`extract_contact`→`extract_emails`). Steps **are** now persisted mid-flight as
`STEP#` items, `GET /searches/{id}` returns `steps` + `progress`, and
`POST /searches/{id}/stop` cancels the execution — so no backend gaps remain
behind the redesign, only the deploys listed under Phases.

Notion cards live in their own **Phase 5 — UI redesign** (design system → login → home
→ workspace → trace → results → mobile); hardening/beta is now **Phase 6**.

### Frontend styling (decided 2026-08-04 — design-system card, Phase 5)

**Tailwind CSS v4.** Tokens live in one `@theme` block in `web/src/app/globals.css`
and generate the utilities (`bg-paper`, `bg-surface`, `text-ink`, `text-slate-muted`,
`border-line`, `rounded-panel`, `shadow-sheet`, the `bg-map-*` fills…). **Never
hardcode hex outside `globals.css`** — the only sanctioned exceptions are the Google
brand mark, `viewport.themeColor`, and the Maps `Circle` fallback, each commented
in place.

**Light-only.** `html { color-scheme: light }` opts out of dark mode; the paper
direction has no designed dark counterpart. Revisit post-beta.

**Inter** is self-hosted via `next/font/local` from a vendored variable woff2 at
`web/src/fonts/`. Do not switch to `next/font/google` — it fetches from
fonts.googleapis.com at build time and makes CI builds network-dependent.

Primitives to reuse rather than re-roll: `web/src/components/ui/` (`Card`, `Pill`,
`Button`, `TagChip`), `web/src/components/StreetMapBackdrop.tsx`, and
`web/src/components/map/MapPieces.tsx` (`AddressInput`, `RadiusCircle` — extracted
when `SearchForm.tsx` was deleted).

Screen flow lives in `web/src/app/page.tsx`: signed out → `LoginScreen`, signed in
with no interpreted roles → `HomeScreen`, roles interpreted → `Workspace`.

**`WorkspaceShell` is the shell for both `/` and `/search/{id}`** (rail | map |
optional right column). Mockup 4 is mockup 3 with a third pane — results are *not*
a separate page, the map stays on screen. The right column renders only when there
are findings; in-flight/empty/failed searches show the status pill over the map
instead of an empty gutter.

**Google Maps chrome is off** (`disableDefaultUI` + explicit `cameraControl`,
`streetViewControl`, `zoomControl`, … `false`). Two things not to "fix":
`keyboardShortcuts` stays **true** — with the buttons gone it's the only non-mouse
way to pan/zoom; and the **Google wordmark + "Terms"/"Report a map error" links are
required by the Maps ToS** to stay visible and unobscured, so they cannot be
removed. The Places autocomplete is a web component with its own Roboto/white
styling — `globals.css` restyles it via `gmp-place-autocomplete` + `::part(input)`.

`web/src/lib/links.ts` classifies result links by URL pattern into badge types.
**Keep it conservative** — an unrecognised path gets a generic badge, never an
overclaimed "Live listing". The badge is only useful if it's trustworthy without
clicking. Revisit only if the agent starts returning `{url, kind, label}` from
`report_findings` (needs a schema change + eval re-run).

**Contrast:** `ink-muted` (~3.4:1) and `slate-faint` (~2.8:1) are below WCAG AA for
body text — decorative use only. Body copy uses `slate-muted` or `ink`.

## Data model (DynamoDB single table `fmaj-{stage}-main`, PK/SK)

- `USER#<cognito-sub> / PROFILE`: email, name, `free_search_used` (quota = atomic
  conditional flip False→True; 402 on second search — no payments in V1).
- `SEARCH#<id> / META`: params, status pending→running→completed|failed, user_sub.
- `SEARCH#<id> / RESULT#<place_id>`: written incrementally by the pipeline; frontend
  polls `GET /searches/{id}` every 3s and renders grouped by opportunity_type.
- `SEARCH#<id> / STEP#<iso>#<place_id>`: live agent trace, written as each tool
  returns. **TTL'd (7d) via `expires_at`** — progress, not a record, and it keeps
  Places-derived names from living forever. Nothing else sets that attribute.
- `USER#<sub> / SEARCH#<created_at>#<id>`: owner index for `GET /searches` (the
  workspace rail). Adjacency list, **not a GSI** — no extra provisioned capacity and
  no infra change. Descriptive fields only, deliberately **no status**: status lives
  on META and a denormalised copy would go stale.

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
  (Gemini run verified) · eval set ✅ (14/14 accuracy, 20/20 links) · Step Functions
  pipeline ✅ deployed, real searches returning real leads · Phase 5: design system ✅
  login ✅ home ✅ workspace ✅ results-in-right-panel ✅ + link labels ✅ ·
  live agent trace 🚧 code-complete, **blocked on `cdk deploy 'Fmaj-Test/Data'`
  (new TTL attr) + `'Fmaj-Test/Pipeline'` (agent changed)** (branch
  `feat/design-system-and-login`, **not yet browser-verified**). Deferred: numbered
  map pins (own card — needs lat/lng persisted → Pipeline redeploy + a Places ToS
  call) and Refine prefilling the previous params.
  **Next: mobile layouts (last Phase 5 card), then Phase 4 (PDF report) and
  Phase 6 (hardening + private beta).**

## Known state / gotchas

- **⚠️ The `agent` package is shared by the API and the Lambdas.** Changing anything in
  it (models, discovery, tools, prompts) means **redeploying `Fmaj-Test/Pipeline`** —
  restarting the local API is not enough. Symptom of forgetting: every search fails.
- `pydantic-settings` does NOT export `.env` to `os.environ`; `api/app/settings.py`
  calls `load_dotenv()` so google.auth / `fmaj_agent.config` can see their vars.
- Gemini 3 spends part of `max_output_tokens` on thinking — a tight budget returns
  EMPTY text. Use generous limits + `json_mode` for structured calls.
- A `failed` search must never render like an empty one (it hides breakage) — the
  results page has a separate error state.

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
