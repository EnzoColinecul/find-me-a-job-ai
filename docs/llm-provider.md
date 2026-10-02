# LLM provider — Bedrock or Gemini

The agent's model backend is pluggable (see `agent/src/fmaj_agent/providers.py`).
Switch with `FMAJ_LLM_PROVIDER`.

| Provider | Value | Model env | Auth | Cost source |
|---|---|---|---|---|
| Anthropic Claude (Bedrock) | `bedrock` | `FMAJ_AGENT_MODEL`, `FMAJ_TRIAGE_MODEL` | AWS creds | AWS credits |
| Google Gemini (Vertex AI) | `gemini` (default) | `FMAJ_GEMINI_MODEL` (default `gemini-3.6-flash`) | `GOOGLE_APPLICATION_CREDENTIALS` | GCP credits |

## Request deadlines and partial coverage

`FMAJ_MODEL_CALL_SECONDS` defaults to **30 seconds per attempt**, clipped to the
remaining company or API deadline. Zero, negative, nonfinite, and invalid values
fall back to 30 seconds. The company budget remains 60 seconds, including a
3-second persistence tail; the 40-company breadth and shared tool-spend caps are
independent of this request timeout.

Transient requests have at most **two attempts total**, with at least one second
of jittered backoff and enough remaining time for another request. Vertex status
408/429/499/500/502/503/504 can be retried; authentication and validation errors
cannot. Gemini SDK retries are explicitly disabled so they cannot multiply the
application's attempts. Cooperative stop checks still prevent further tools and
result commits after cancellation.

If a model request or final report fails, previously verified vacancy titles,
explicit careers links, or hiring emails can survive as **partial findings**.
Recovery makes no extra model calls and uses the existing source and hiring gates.
The investigation still records an error, and aggregation reports incomplete
coverage; a timeout must never become a verified “nothing found” result.

## Using Gemini (Vertex AI)

Draws on your GCP credits, using the IaC service-account key you already have.

### One-time prerequisites
```bash
PROJECT=project-7187e8cf-43d5-451b-be4
SA=iac-find-me-a-job-ai@project-7187e8cf-43d5-451b-be4.iam.gserviceaccount.com

# 1. Enable Vertex AI
gcloud services enable aiplatform.googleapis.com --project "$PROJECT"

# 2. Let the service account call Vertex
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user"
```

### Run the agent on one company with Gemini
The tools still read the Adzuna/SerpAPI/Places keys from Secrets Manager, so you need
AWS creds too (or set the `FMAJ_*` fallback env vars). Both credential sets coexist:

```bash
cd ~/Documents/Dev/find-me-a-job-ai/agent
uv sync   # pulls in google-genai

AWS_PROFILE=fmaj-deploy \
GOOGLE_APPLICATION_CREDENTIALS=../project-7187e8cf-43d5-451b-be4-84a9aac3c5df.json \
FMAJ_LLM_PROVIDER=gemini \
uv run python -m fmaj_agent.run \
  --name "Single O Surry Hills" --website https://singleo.com.au/ \
  --types cafe,coffee_shop --role barista
```

The STATS block shows `"provider": "gemini"` so you can confirm which backend ran.

### Region / data residency
`FMAJ_VERTEX_LOCATION` defaults to `global`. For AU data residency try
`FMAJ_VERTEX_LOCATION=australia-southeast1` (confirm the model is offered there;
`global` is the most broadly available for newest Gemini models).

## Switching back to Bedrock
Set `FMAJ_LLM_PROVIDER=bedrock` once the Anthropic use-case form is
approved. No code change — same tools, loop, and budgets.
