# Deploying the frontend (Amplify Hosting) + the API

This is the runbook for **Phase 4 — Frontend deploy** and its dependency, the
**API stack**. Deploying the frontend alone isn't enough: the live app calls a
public API for `/me`, `/searches`, `/roles/interpret`, so the API Gateway + Lambda
stack (`Fmaj-Test/Api`) has to be deployed too, and the login redirect + CORS have
to name the Amplify domain.

There's a small chicken-and-egg to it — the Amplify URL only exists after the
first build, but Cognito's callback list and the API's CORS list need to contain
it. So the order below deploys the API first, builds Amplify to *learn* its URL,
then wires that URL back and redeploys the two stacks that care.

Everything under `cdk deploy` / `aws` you run locally with `--profile fmaj-deploy`
(Enzo). Docker must be running — the API Lambda bundles compiled wheels for
linux/amd64.

---

## What was already done in the repo

- `infra/fmaj/stacks/api_stack.py` — HTTP API (API Gateway v2) proxying a Mangum
  Lambda that bundles `api/` + the shared `agent/` package. Env + grants wired:
  DynamoDB RW, reports-bucket RW (the PDF), Step Functions Start **and** Stop,
  the Gemini SA secret for `/roles/interpret`, and `FMAJ_CORS_ORIGINS` /
  `FMAJ_GLOBAL_MONTHLY_SEARCHES` from per-stage config.
- `api/requirements-lambda.txt` — pinned runtime deps for the bundle.
- `amplify.yml` (repo root) — the monorepo build spec (`appRoot: web`, SSR).
- `infra/fmaj/config.py` — a single `hosting_urls` list per stage that feeds
  Cognito callback URLs, Cognito logout URLs, and the API CORS allow-list at once.

The API does its own JWT verification and CORS (FastAPI), so the HTTP API is a
thin proxy with **no gateway authorizer** — that would otherwise block `/health`,
`/config`, and the CORS preflight.

---

## Step 1 — Deploy the API stack

```bash
cd infra
cdk deploy 'Fmaj-Test/Api' --profile fmaj-deploy
```

Depends on `Data`, `Auth`, and `Pipeline` (already deployed). If `Pipeline` isn't
deployed yet, deploy it first (`cdk deploy 'Fmaj-Test/Pipeline' 'Fmaj-Test/Api'`).

Copy the stack output **`ApiUrl`** (looks like
`https://abc123.execute-api.ap-southeast-2.amazonaws.com`). Smoke-test it:

```bash
curl "$API_URL/health"     # -> {"status":"ok","stage":"test"}
curl "$API_URL/config"     # -> {"max_roles":1,...}
```

## Step 2 — Create the Amplify app (connect the repo)

Amplify Console → **New app → Host web app** → GitHub →
`EnzoColinecul/find-me-a-job-ai`, branch `main`.

- Amplify detects the monorepo `amplify.yml`; confirm **app root = `web`** and the
  **Next.js SSR** platform.
- **Environment variables** (App settings → Environment variables):

  | Name | Value |
  |---|---|
  | `NEXT_PUBLIC_API_URL` | the `ApiUrl` from Step 1 |
  | `NEXT_PUBLIC_COGNITO_CLIENT_ID` | Auth stack `UserPoolClientId` (`19mi48bjem0sberbq0b4bas81n` for test) |
  | `NEXT_PUBLIC_COGNITO_DOMAIN` | `https://fmaj-test.auth.ap-southeast-2.amazoncognito.com` |
  | `NEXT_PUBLIC_GOOGLE_MAPS_KEY` | the browser Maps key (referrer-restricted) |

- Save and run the first build. Copy the branch URL, e.g.
  `https://main.d1abc2xyz.amplifyapp.com` — call it **`AMPLIFY_URL`**.

At this point the site loads but login/search still fail: Cognito won't redirect
back to an unregistered URL, the API rejects the origin (CORS), and the map key
blocks the new referrer. Step 3 fixes all three.

## Step 3 — Wire the Amplify URL back

**a) Cognito callback/logout URLs + API CORS** — one edit in `infra/fmaj/config.py`,
add `AMPLIFY_URL` (scheme+host, **no trailing slash**) to the `TEST` stage:

```python
TEST = StageConfig(
    stage="test",
    monthly_search_cap=10,
    log_retention_days=7,
    app_base_url="http://localhost:3000",
    hosting_urls=["https://main.d1abc2xyz.amplifyapp.com"],  # <- AMPLIFY_URL
)
```

That one list flows to the Cognito app client's callback + logout URLs **and** the
API's `FMAJ_CORS_ORIGINS`. Local dev (`http://localhost:3000`) stays allowed.

**b) Google Maps browser key** — in Google Cloud Console → Credentials → the
browser Maps key → **Website restrictions**, add:
`https://main.d1abc2xyz.amplifyapp.com/*`. Without it the map 403s
(`RefererNotAllowedMapError`) on the deployed URL.

> No Google **OAuth** client change is needed: the sign-in redirect goes to the
> Cognito hosted UI (`.../oauth2/idpresponse`), which is unchanged. Only Cognito's
> own callback list (step 3a) has to learn the Amplify URL.

## Step 4 — Redeploy the two stacks that changed

```bash
cd infra
cdk deploy 'Fmaj-Test/Auth' 'Fmaj-Test/Api' --profile fmaj-deploy
```

`Auth` picks up the new callback/logout URLs; `Api` picks up the widened CORS.

## Step 5 — Verify on the live URL

On `AMPLIFY_URL`:
1. **Continue with Google** → returns signed in (Cognito callback resolves).
2. Type a role → `/roles/interpret` returns suggestions (no CORS error in devtools).
3. Run a search in an AU suburb → results stream in; the map renders (Maps key OK).
4. Open a completed search → **Download PDF** returns a file.

Push a trivial change to `main` → Amplify rebuilds and redeploys in a few minutes
(acceptance criterion #1).

---

## Notes

- **Preview branches** (optional): enable in Amplify to get per-PR URLs. Each
  preview origin would also need adding to `hosting_urls` + the Maps key to be
  fully functional — fine to skip for the PoC.
- **Custom domain**: later; the default `*.amplifyapp.com` is fine for the PoC.
- **Prod**: repeat with `Fmaj-Prod/*` and the `PROD` config once `app_base_url`
  has a real domain.
- **Cost**: watch the AWS credits (expiring ~late Aug 2026). Amplify SSR + the API
  Lambda are cheap at PoC traffic, but the Budgets alarms still apply.
