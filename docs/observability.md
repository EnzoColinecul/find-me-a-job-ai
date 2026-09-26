# Observability runbook — Langfuse Cloud

Every search is one Langfuse trace. You can use it to inspect model quality, tool
behaviour, latency, failures, token usage and cost. Code:
`agent/src/fmaj_agent/observability.py`.

## Where a search's trace is

The trace id comes from the search id, so any process can compute it:

```bash
cd agent && uv run python -m fmaj_agent.observability <search_id>
# <search_id>  <trace_id>  https://cloud.langfuse.com/project/…/traces/<trace_id>
```

It is also stored on the DynamoDB item `SEARCH#<id> / META` as
`observability_trace_id`. The API never returns it to the browser. In the
Langfuse UI you can also filter Traces by metadata `search_id = <id>`.

A local single-company run (`python -m fmaj_agent.run …`) makes its own trace,
named `company.local`. Role interpretation (`POST /roles/interpret`) is a short
trace named `roles.interpret`.

### What a trace contains

```
search                                  trace   (name "search")
├── api.create_search                   span    API Lambda: roles, radius, pipeline started?
├── discovery                           span    companies found, per-country counts
├── company            ×N               agent   one per company (Investigate Lambda)
│   ├── triage                          generation
│   ├── agent.turn     ×k               generation   one per model turn
│   ├── tool.<name>    ×k               tool         ok / reason / result shape
│   │   └── role_match                  generation   when a gate judges vacancy titles
│   ├── budget.denied                   event   a metered tool was refused (WARNING)
│   ├── budget.breach                   event   tool-call/time budget hit (WARNING)
│   ├── forced_report                   generation   the forced report_findings call
│   └── report.downgraded               event   the report gate rejected a claim
└── aggregate | search.failed           span    final counts, or the Step Functions error type
```

On a `company` observation, the output shows `opportunity_type`, `confidence`,
link and email *counts*, `forced_report` and `error`. The metadata shows tool
calls, web searches, tokens and seconds. Levels are `ERROR` (agent error),
`WARNING` (forced report, failed tool, empty model reply) and `DEFAULT`.

Each generation records the model, the provider (`gemini` / `bedrock`), the
parameters, `usage_details` (input/output/total tokens) and latency. Cost is
explained below.

## Filtering

| To find… | In Langfuse |
|---|---|
| one search | Traces → metadata `search_id` = … (or open the URL above) |
| one company | Observations → name `company`, metadata `place_id` = … |
| a role | Traces → tags `role:chef`, or metadata `role` |
| a country | tags `country:au`, metadata `country_code` |
| a provider | tags `provider:gemini` / `provider:bedrock`; generations have metadata `provider` |
| a model | Observations → type Generation → Model |
| a stage | the environment picker (`test`, `prod`, or `local` if you set it) |
| failures | Observations → Level = ERROR (agent errors, failed searches) |
| budget trouble | Observations → name `budget.breach` / `budget.denied` |

## What is never sent

Tracing sends ids, counts, tool and model names, token usage and timings.
**It never sends:**

- **Prompts, completions or scraped page text.** They hold Places data and raw
  page bodies. Tool inputs are recorded as argument names and sizes only
  (`{"url": "<str:38>"}`). Tool outputs are recorded as `ok`, `reason` and the
  *shape* of the data (`text_chars`, `emails_count`, `job_count`).
- **Company name, address or website.** Places terms don't allow keeping place
  data beyond the search. `place_id` is exempt, and it is how you get from a
  trace to the `STEP#` rows, which have a 7-day TTL. While a company is being
  investigated, its name, address and website host are scrubbed out of every
  string (`observability.sensitive`).
- **Anything about the applicant.** That covers the Cognito sub, coordinates,
  the location label and the free-text role description (only its length is
  sent).
- **Credentials.** A second line of defence, `observability.redact`, runs as the
  client's `mask` and on every status message. It removes emails, bearer tokens,
  JWTs, API keys, and URLs (only their host is kept). It drops values under keys
  such as `secret`, `token`, `api_key`, `text`, `content` and `messages`, and it
  truncates long strings.

`agent/tests/test_observability.py` and `api/tests/test_searches.py` enforce
this. They plant a company name, address, website, email, page text and an API
key in a run, then assert that none of them appears in any exported span.

## Fail-safe behaviour

Tracing can never fail a search.

- If there are no keys, or `FMAJ_LANGFUSE_ENABLED=0`, or the secret can't be
  read, or the SDK can't start, the client resolves to "off" and every call
  becomes a no-op.
- Errors raised by Langfuse itself are logged and swallowed.
- Each Lambda handler ends with `observability.flush()`, which waits at most
  **3 s** (1 s in the API). If Langfuse is down, the export gives up in the
  background and the search carries on.

## Configuration

| Where | How |
|---|---|
| Local dev | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` in the **repo-root `.env`**. Only those three names are read from that file: it also holds AWS keys, which must not override the `fmaj-deploy` profile. Process env beats the file. Optionally set `LANGFUSE_TRACING_ENVIRONMENT=local` so local runs don't mix with `test`. |
| Test / Prod | Secrets Manager `fmaj/{stage}/langfuse` (JSON: `public_key`, `secret_key`, `base_url`). CDK sets `FMAJ_LANGFUSE_SECRET` on the API and all four pipeline Lambdas and grants them read access. |
| Tests | Always off (`conftest.py`). Tests that check tracing use an in-memory exporter. |

The variable names are the Langfuse Python SDK's own (checked against
`langfuse` 4.15, which is pinned `>=4.15,<5`). `LANGFUSE_HOST` still works as a
fallback for `LANGFUSE_BASE_URL`. **Never** put any of these in `web/` or in a
`NEXT_PUBLIC_*` variable: only the backend traces.

### Cost

Langfuse prices a generation by matching its model name against its model
table. Open one generation from a real run and check that it shows a cost. If it
doesn't (likely for `gemini-3.6-flash`, and possibly for Bedrock's `au.`-prefixed
inference-profile ids), add the model once under **Langfuse → Settings → Models**
with a match pattern and the input/output prices from the provider's pricing
page. Langfuse then prices those generations from that point on. If you need to
override it in code, set
`FMAJ_LLM_PRICES='{"<model>": [usd_per_1M_in, usd_per_1M_out]}'`, which sends
`cost_details` with every generation.

## First-time setup / deploy

```bash
# 1. Register the keys for a stage. Leave the other prompts blank to keep them.
AWS_PROFILE=fmaj-deploy ./scripts/store-external-secrets.sh test

# 2. Deploy. The agent package changed, so the Pipeline stack must be redeployed.
cd infra && cdk deploy 'Fmaj-Test/Pipeline' 'Fmaj-Test/Api' --profile fmaj-deploy
```

## Rotating the Cloud keys

1. In Langfuse, go to **Settings → API Keys → Create new API keys**. Keep the
   old pair for now.
2. Local: replace the two values in the repo-root `.env`.
3. Each deployed stage: run
   `AWS_PROFILE=fmaj-deploy ./scripts/store-external-secrets.sh <stage>`, enter
   only the three Langfuse values, and leave everything else blank.
4. Lambdas cache the key for the life of a warm container. To pick up the new
   key straight away, redeploy or update any env var. Otherwise it takes effect
   as containers recycle, and the old key must stay valid until then.
5. Run a search. Check that its trace arrives (`python -m fmaj_agent.observability
   <search_id>`).
6. **Delete** the old key pair in Langfuse.

If a key has leaked, do step 6 first. Tracing drops to "off" until the new key
is in place, and searches are unaffected.
