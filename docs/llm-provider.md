# LLM provider — Bedrock or Gemini

The agent's model backend is pluggable (see `agent/src/fmaj_agent/providers.py`).
Switch with `FMAJ_LLM_PROVIDER`.

| Provider | Value | Model env | Auth | Cost source |
|---|---|---|---|---|
| Anthropic Claude (Bedrock) | `bedrock` (default) | `FMAJ_AGENT_MODEL`, `FMAJ_TRIAGE_MODEL` | AWS creds | AWS credits |
| Google Gemini (Vertex AI) | `gemini` | `FMAJ_GEMINI_MODEL` (default `gemini-3.6-flash`) | `GOOGLE_APPLICATION_CREDENTIALS` | GCP credits |

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
Unset `FMAJ_LLM_PROVIDER` (or set `=bedrock`) once the Anthropic use-case form is
approved. No code change — same tools, loop, and budgets.
