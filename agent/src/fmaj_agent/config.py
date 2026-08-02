"""Runtime config for the agent — stage-aware secret names + region."""
import os

STAGE = os.environ.get("FMAJ_STAGE", "test")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")

PLACES_KEY_SECRET = f"fmaj/{STAGE}/places-key"
ADZUNA_SECRET = f"fmaj/{STAGE}/adzuna"
WEB_SEARCH_SECRET = f"fmaj/{STAGE}/web-search-key"  # SerpAPI

# ── LLM provider ──────────────────────────────────────────
# "bedrock" (Anthropic Claude) or "gemini" (Google, via Vertex AI).
LLM_PROVIDER = os.environ.get("FMAJ_LLM_PROVIDER", "bedrock")

# Bedrock model IDs (AU cross-region inference profiles). Override via env if the
# version suffix differs in your account (Bedrock console → Cross-region inference).
AGENT_MODEL = os.environ.get(
    "FMAJ_AGENT_MODEL", "au.anthropic.claude-haiku-4-5-20251001-v1:0"
)
TRIAGE_MODEL = os.environ.get(
    "FMAJ_TRIAGE_MODEL", "au.anthropic.claude-haiku-4-5-20251001-v1:0"
)
# Sonnet available for escalation / higher-quality orchestration:
#   FMAJ_AGENT_MODEL=au.anthropic.claude-sonnet-4-5-20250929-v1:0

# Gemini (Vertex AI — draws on GCP credits, uses GOOGLE_APPLICATION_CREDENTIALS).
GEMINI_MODEL = os.environ.get("FMAJ_GEMINI_MODEL", "gemini-3.6-flash")
VERTEX_PROJECT = os.environ.get("FMAJ_VERTEX_PROJECT", "project-7187e8cf-43d5-451b-be4")
VERTEX_LOCATION = os.environ.get("FMAJ_VERTEX_LOCATION", "global")
