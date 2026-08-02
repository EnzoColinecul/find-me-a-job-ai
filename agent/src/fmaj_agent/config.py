"""Runtime config for the agent — stage-aware secret names + region."""
import os

STAGE = os.environ.get("FMAJ_STAGE", "test")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")

PLACES_KEY_SECRET = f"fmaj/{STAGE}/places-key"
ADZUNA_SECRET = f"fmaj/{STAGE}/adzuna"
WEB_SEARCH_SECRET = f"fmaj/{STAGE}/web-search-key"  # SerpAPI

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
