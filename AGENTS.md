# CLAUDE.md — Find-Me-A-Job AI

Job search by geolocation: a user picks a location + radius + role(s); Google Places
finds nearby businesses; an LLM agent investigates each one (careers page → job boards
→ contact email) and returns a ranked list of opportunities. Focus is
hospitality/retail/trades — Places is weak for office roles. Full plan:
`docs/PLAN.md`. Diagram: `docs/architecture.mermaid`.

**Searchable worldwide since 2026-08-15.** V1 was Australia-only, enforced by a
bounding box in `SearchRequest` and `includedRegionCodes: ["au"]` on the address
autocomplete; both are gone so the private beta can be tested from any country.
Nothing gates on geography any more — gate on plan/quota instead. What remains
country-specific is _job-board coverage_, and it is now data, not an assumption:
discovery reads the ISO country off the Places address components onto
`Company.country_code`, the orchestrator binds that into the tool dispatch, and
each board tool decides for itself (Adzuna picks its national index, Seek refuses
outside AU). Australia is still the best-covered market; elsewhere the agent leans
harder on the company's own site. See "LLM provider (agent)" below.

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
  403 `API_KEY_HTTP_REFERRER_BLOCKED` — **this has already happened once**
  (2026-08-04, pasted the browser key while rotating the SerpAPI key). `places.py`
  now translates that 403 into a message naming the fix, and
  `store-external-secrets.sh` **keeps a secret unchanged if you leave the prompt
  blank**, so rotating one key can't clobber another.
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
  JSON), hard budgets in code (see "Cost discipline" — read off `config` at call
  time, not copied into module constants), forced structured report on budget
  breach, token/cost accounting per run. Tools never raise (ToolResult).
- **Country-aware job boards (2026-08-15).** `Company.country_code` (ISO-3166
  alpha-2, lowercase) comes from the Places `addressComponents` — Pro tier, so it
  costs nothing extra; `discovery._country_code` reads it, and a place missing the
  component inherits the shortlist's majority country. `orchestrator._dispatch_for`
  binds it into the tool callables, so **the model never passes a country** — a
  hallucinated `"au"` would put a Berlin bakery back in the Australian index, which
  is the bug this replaced. `search_jobs_adzuna` routes to
  `/v1/api/jobs/{country}/search/1` for the ~19 markets in `ADZUNA_COUNTRIES`;
  `find_seek_company_page` is AU-only (`SEEK_COUNTRIES`). Unknown or uncovered
  country → `ok=False` with a readable reason the model can route around, shown in
  the trace as `Skipping` — **never a silent fallback to Australia**. Adding
  `nz.seek.co.nz` needs its own robots.txt check first; don't assume it mirrors AU.
- **Role matching (2026-09-03) — "is hiring" is not "is hiring for this role".**
  A Melbourne *software developer* search returned Virtual IT Group with a Seek
  link whose three vacancies were a Service Desk Analyst, a BDM and an Account
  Manager. Nothing was broken: `find_seek_company_page` only ever counted
  vacancies, so there was never a title to check. `role_match.py` is the fix — an
  LLM judge (triage model, one batched call per company, cached) scoring each
  vacancy title against the roles sought, with a verbatim-substring fast path in
  front of it and `FMAJ_ROLE_MATCH_THRESHOLD` (default **0.8**) as the bar. Two
  enforcement points, **both in code, not the prompt**: `role_match.GATES` filters
  `find_seek_company_page` and `search_jobs_adzuna` before the model sees them (a
  refusal names the rejected titles, so the agent keeps looking instead of
  reporting), and `orchestrator._verify_listing` re-checks the `matched_title` the
  model must now supply with any `job_listing` — one it never saw, or one that
  isn't the role, is downgraded. `web_search` is deliberately **not** gated: its
  result titles are page titles, not vacancy titles, so filtering on them would
  reject good links; those listings are caught by the report gate instead.
  **Fails closed** — an unreachable judge, unparseable output or unreadable titles
  all mean "no match", like the markup check next to it. Downgrade ladder (the
  product decision): a careers page or a contact email still earns the company a
  place in the results, nothing at all drops it, and links to a *board*
  (`_BOARD_HOSTS`) are dropped on downgrade while the company's own site survives
  — a Seek link with no matching vacancy says nothing. `FMAJ_ROLE_MATCH_THRESHOLD`
  is a **confidence** threshold, not a measured accuracy; `evals/golden.yaml` is
  what measures the latter, and it has not been re-run against this gate yet.
- **Contact emails are gated too (2026-09-03) — an address is not a lead.**
  `sales@trendzit.com.au` was reported as a way into a company whose site was
  down, scraped out of a directory, with no vacancy anywhere. Three tiers, all
  deterministic, no LLM call: `impl.NEVER_EMAIL` (`sales@`, `support@`,
  `billing@`, `noreply@` …) is dropped inside `extract_emails` so the model never
  sees it; `impl.RECRUITMENT_EMAIL` (`careers@`, `hr@`, `recruit*@` …) stands on
  its own; everything else (`info@`, `contact@` — often the ONLY address a cafe
  publishes, and hospitality is the core market) counts only when a page we
  fetched carried an actual invitation, `impl.HIRING_INVITATION` ("please send us
  your resume", "we're hiring" — phrase-level on purpose, a "Careers" nav item is
  not an invitation). `orchestrator._verify_email` also demands provenance: the
  address must have come back from `extract_emails`, not out of a `web_search`
  snippet. Nothing survives → `none` and the company drops, links included — a
  `contact_email` finding only ever links to the contact page it read.
  `_verify()` is the one door both this and the listing gate run behind, so no
  report path can skip either.
- Conduct: robots.txt respected, honest UA, **never scrape Seek/LinkedIn for listing
  content** (links only via SerpAPI `site:` queries) — ToS requirement, don't "fix"
  this. **One deliberate exception** (2026-08-11, widened 2026-09-03):
  `find_seek_company_page` GETs `au.seek.com/{slug}-jobs/at-this-company` to count
  job markers and, since the role-match gate, to read the vacancy **titles** — the
  minimum needed to answer "is this the job the user asked for?", which counting
  alone could not. Titles only: no descriptions, salaries or dates, nothing beyond
  that one page, no `/job/` page ever fetched, and nothing persisted — the titles
  live in the tool result for the run and are gone with it. That path carries no
  `/job/` segment and no query string, so Seek's robots.txt allows it for our UA
  (`*/job/`, `*?`, `/graphql`, `/api/jobsearch/` are the disallowed ones). Reading
  a listing's body, or fetching one, would still breach the rule.
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
# One-company agent run. NOTE the credentials path is written out in full: a
# glob in a `VAR=value` prefix is NOT expanded by the shell, so
# `GOOGLE_APPLICATION_CREDENTIALS=../project-*.json` reaches google.auth as a
# literal string and dies with "File ../project-*.json was not found."
cd agent && AWS_PROFILE=fmaj-deploy \
    GOOGLE_APPLICATION_CREDENTIALS=../project-7187e8cf-43d5-451b-be4-84a9aac3c5df.json \
    FMAJ_LLM_PROVIDER=gemini uv run python -m fmaj_agent.run \
    --name "X" --website https://x.com --role chef --country au
# Reset the free-search quota after testing:
aws dynamodb update-item --table-name fmaj-test-main \
  --key '{"PK":{"S":"USER#<sub>"},"SK":{"S":"PROFILE"}}' \
  --update-expression "SET free_search_used = :f" \
  --expression-attribute-values '{":f":{"BOOL":false}}' \
  --profile fmaj-deploy --region ap-southeast-2
```

Tests: api 24, agent 124 (pytest; agent uses PYTHONPATH=src or uv). Web: `npx tsc
--noEmit` + `npm run lint`. Python target is 3.12+ but avoid 3.11+-only stdlib
(e.g. use `str, Enum` not `StrEnum`) for tooling compatibility.

**Office roles are described, not typed (2026-09-03).** Google has a venue type
for a cafe and none for a software company, so hospitality/retail/trades get
precise Nearby results while office roles fall back to Text Search — where the
candidate pool is only as good as the phrase. `it support`'s lone "IT services
company" is why a Melbourne *software developer* search returned nothing but
managed service providers: the query asked for MSPs and Google obliged, and no
amount of pagination or match-gate tuning helps when the right companies were
never in the pool. `role_mapping.yaml` now takes `text_queries` (a list) as well
as `text_query`, and several phrasings share the page budget — three queries one
page deep beat one query three pages deep, because deeper pages are the same
query's long tail.

**A broad Nearby type next to text queries is worse than no type at all**
(graded, Melbourne CBD, 2026-09-03). `software developer` was tried with
`types: [corporate_office, consultant]`: those two took **39 of the 40**
shortlist places — migration agents, naturopaths, accountants, virtual-office
registrations sharing one Bourke St address — leaving exactly one text-search
result (Whispir) standing. The mechanism is ranking, not relevance: Nearby
returns the 20 NEAREST of each type, all within metres of a CBD pin, so
`ranked[:max_companies]` cut every genuine software company. Office roles
therefore carry `types: []` and live on their phrasings. Re-graded text-only:
**~85-90% plausible employers** (Whispir, Milanote, ELMO, ClickSend, Buildxact,
Endava, TCS, SSW, TatvaSoft…), on par with the hospitality benchmark and up from
roughly 5-10% with the types in. The three queries are complementary rather than
redundant — "software company" surfaces product companies, "software development
company" consultancies, "web development agency" small studios — which is the
argument for `text_queries` being a list. The same crowding-out
is latent for any role mixing both (`construction labourer`, `cleaner`) — check
`stats["by_source"]` before assuming a role's text queries contribute anything.
`Company.discovery_source` and the harness's `source` column exist for exactly
that; `it support` (text-only) came back clean by comparison, all real IT firms.

## Role input (free text → LLM → confirm)

Users describe what they want in their own words; `POST /roles/interpret` (auth, **no
quota consumed**) returns ordered `RoleSuggestion`s they edit/confirm before the search
runs. Each suggestion carries `curated_key` — the `role_mapping.yaml` role whose Places
types to borrow — so a label we've never seen ("dishwasher") still searches the right
venues instead of Text-Searching appliance stores. Falls back to the raw text as one
role if the LLM output is unusable.

**`max_roles` is one knob** (`api/app/settings.py`, PoC = 1). The API validates against
it and the frontend _fetches_ it from `GET /config` — raising it for subscriptions needs
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
optional right column). Mockup 4 is mockup 3 with a third pane — results are _not_
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

**The base map is cloud-styled (2026-09-03).** `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` is
a real map ID from Map Management, associated with a style that hides Google's own
POI icons (restaurants, museums, supermarkets…) — they competed with our numbered
result pins. It replaced the literal `mapId="fmaj-search"`, which was never
registered with Google, so the map ran on the default look and `AdvancedMarker` had
no valid ID. Consequence: **a hardcoded `styles` prop is ignored on a cloud-styled
map** — all base-map appearance lives in the console (edits apply with no deploy),
and the map ID must be set in every environment (`web/.env.local`, Amplify env vars)
or `AdvancedMarker` breaks. `clickableIcons={false}` only stopped POIs being
*clicked*; it never hid them.

`web/src/lib/links.ts` classifies result links by URL pattern into badge types.
A "Live listing" badge is only as honest as `opportunity_type`, which is why the
role-match gate lives in the agent and not here — the frontend cannot tell a Seek
employer page with a matching vacancy from one without.
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
  Places-derived names from living forever.
- `SEARCH#<id> / BUDGET`: metered-API spend for this search, one attribute per
  tool, incremented by conditional `ADD` from the parallel company Lambdas
  (`agent/src/fmaj_agent/budget.py`). **Also TTL'd (7d) via `expires_at`** — a
  spend counter is progress, not a record, same as `STEP#`. These two are the
  only items that set that attribute.
- `USER#<sub> / SEARCH#<created_at>#<id>`: owner index for `GET /searches` (the
  workspace rail). Adjacency list, **not a GSI** — no extra provisioned capacity and
  no infra change. Descriptive fields only, deliberately **no status**: status lives
  on META and a denormalised copy would go stale.

## Cost discipline (why the code looks the way it does)

- **Nearby Search (New) returns max 20 places and has NO pagination.** Discovery
  therefore calls it **once per mapped type**, not once with every type bundled —
  a bundled call caps the entire search at 20 candidates regardless of radius or
  `MAX_COMPANIES` (this is exactly what limited a 5km Melbourne CBD search to 20).
  3-5 calls/search on the Pro SKU is ~1000 searches/mo, so it's effectively free;
  a test asserts the call count. Don't "optimise" it back into one call.
- **Text Search paginates; Nearby does not (2026-09-03).** `maxResultCount` is
  documented as "between 1 and 20 (default)" and Nearby has no page token, so 20
  per request is Google's ceiling, not ours — raising the number does nothing.
  Breadth comes from more requests. Nearby gets one call per type (above); Text
  Search now follows `nextPageToken` up to `discovery.MAX_TEXT_PAGES` (3), but
  **only for roles with no Places types**, since those reach the API through Text
  Search alone. That was a silent 20-candidate ceiling on `MAX_COMPANIES` for
  `it support` and for every uncurated label — i.e. every office role, "software
  developer" included. Roles that have types stay on one text page; they already
  have 20 per type and each page is a billed call.
- Places (New): search calls use **Pro-only field masks** (5K free/mo); `websiteUri`
  needs **Enterprise** Place Details (1K free/mo → the real monthly ceiling, ~25-33
  searches) so Details is called ONLY for the ≤40 shortlisted companies.
  `rankPreference: DISTANCE` on Nearby (user wants local results).
- Places ToS: don't persist place data beyond the search (place_id is exempt).
- Budgets/caps exist in code, not prompts. Keep per-search cost logged.
- **Per-search budgets live in `fmaj_agent/config.py`, env-driven, `0 = unlimited`**
  (`FMAJ_MAX_COMPANIES` 40, `FMAJ_MAX_WEB_SEARCHES` 2 per company,
  `FMAJ_MAX_WEB_SEARCHES_PER_SEARCH` 10 shared, `FMAJ_MAX_TOOL_CALLS` 8,
  `FMAJ_MAX_SECONDS` 60).
- **Breadth and SerpAPI spend are separate knobs — keep them that way.** They
  weren't: companies run in parallel Lambdas, so the only enforceable ceiling was
  arithmetic (`MAX_COMPANIES × MAX_WEB_SEARCHES`), and staying inside SerpAPI's
  ~250/month meant cutting `MAX_COMPANIES` 40→5. That silently cut results per
  search by 8× — the knob meant to control cost was controlling the product.
  `budget.DynamoSearchBudget` gives those Lambdas the shared counter they lacked
  (`SEARCH#<id> / BUDGET`, conditional `ADD`), so `MAX_COMPANIES` now costs only
  Places Details and `MAX_WEB_SEARCHES_PER_SEARCH` is the real SerpAPI ceiling.
  Defaults: 40 companies → ~25 searches/mo on Details (Enterprise, 1K free);
  10 shared web searches → ~25 searches/mo on SerpAPI. **Don't re-couple them by
  lowering `MAX_COMPANIES` to save SerpAPI quota** — a test asserts they're
  independent.
- The per-company `MAX_WEB_SEARCHES` stays as a backstop: `DynamoSearchBudget`
  **fails open** if DynamoDB errors, which is only safe because the local cap
  still bounds the damage at the old arithmetic worst case.
- `web_search` is the only metered tool; over budget it returns `ok=False` with a
  reason, which the model can react to and the trace shows as `Skipping` — never a
  silent drop. `FMAJ_MAX_COMPANIES=0` still caps at `discovery.HARD_MAX_COMPANIES`
  (40) because Place Details is the Enterprise SKU. The prompt orders tools by cost
  (own site → Adzuna → `web_search` last); that's guidance, the cap is the guarantee.

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
  live agent trace ✅ deployed (`Fmaj-Test/Data` + `Fmaj-Test/Pipeline` both
  redeployed), browser-verified — animated newest-first timeline, Stop wired up ·
  mobile layouts (login, search, results) 🚧 code-complete: touch targets ≥44px
  throughout, trace panel collapses to a one-line summary below `lg` with a
  "Show all steps" toggle, trace⇄results switch no longer `lg`-only. **Not yet
  verified on a real phone** — this sandbox can't run `next build`/`next dev`
  (arm64/registry limits) or a browser, so the 375px no-scroll check and
  pin-drag-with-touch still need a manual pass. Deferred: numbered map pins
  (own card — needs lat/lng persisted → Pipeline redeploy + a Places ToS call)
  and Refine prefilling the previous params.
  **Next: eyeball mobile on a phone, then Phase 4 (PDF report) and Phase 6
  (hardening + private beta).**

## Known state / gotchas

- **⚠️ The role-match gate (2026-09-03) changed the `agent` package**, so
  `Fmaj-Test/Pipeline` must be redeployed before a search picks it up. The Seek
  title selector IS verified against the real page (`scripts/check_seek_titles.py
  "Virtual IT Group"` on a normal network — the sandbox egress proxy blocks
  `au.seek.com` — returned `job_count=1, "Product Manager"`, which is also the
  reported bug in miniature: a live vacancy that is not the role). A live agent run
  against that company then returned `contact_email` + `careers@vitg.com.au` with
  **no Seek link** — the reported bug, fixed end to end. Still outstanding: the
  eval set has not been re-run against the gate. Re-run
  `scripts/check_seek_titles.py` first if AU listings ever go quiet: an empty title
  list with a non-zero `job_count` means Seek's markup moved, and the gate fails
  closed (safe, but the source goes dark).
- That run finished via `_force_report` — 8 tool calls, the whole `MAX_TOOL_CALLS`
  budget, and both per-company `web_search` calls. Not the gate's doing (it costs
  an LLM call, not a tool call): `virtualitgroup.com.au` redirects to `vitg.com.au`,
  so the agent spent its first `find_careers_link` on the old domain and needed a
  `web_search` to find the real one. Worth remembering before reading a forced
  report as a budget problem.

- **⚠️ Going worldwide touched the `agent` package** (models, discovery, places,
  tools, orchestrator, prompt), so `Fmaj-Test/Pipeline` **must be redeployed** before
  a non-AU search will work — see the next bullet. Verified in tests only: agent 76
  passing, api 66 passing, `tsc --noEmit` + `next lint` clean. **No real overseas
  search has been run yet** — the first one is worth watching, because Places venue
  coverage and `role_mapping.yaml`'s types were both tuned against AU suburbs.
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
