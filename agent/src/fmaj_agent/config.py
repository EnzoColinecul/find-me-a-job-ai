"""Runtime config for the agent — stage-aware secret names, region, budgets."""
import os

STAGE = os.environ.get("FMAJ_STAGE", "test")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")


def _limit(name: str, default: int) -> int:
    """A budget knob. **0 means unlimited** — that's how production turns a PoC
    guard rail off without a code change."""
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return max(value, 0)

PLACES_KEY_SECRET = f"fmaj/{STAGE}/places-key"
ADZUNA_SECRET = f"fmaj/{STAGE}/adzuna"
WEB_SEARCH_SECRET = f"fmaj/{STAGE}/web-search-key"  # SerpAPI

# ── LLM provider ──────────────────────────────────────────
# "gemini" (Google, via Vertex AI) or "bedrock" (Anthropic Claude).
# Default is gemini: Bedrock access is pending the Anthropic use-case form, and GCP
# credits are funding the PoC. Switch with FMAJ_LLM_PROVIDER=bedrock when approved.
LLM_PROVIDER = os.environ.get("FMAJ_LLM_PROVIDER", "gemini")

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

# ── Per-search budgets ────────────────────────────────────
# These exist because SerpAPI's free tier is ~250 searches/MONTH, and that is the
# binding constraint on how often we can run at all.
#
# Companies are investigated in PARALLEL Lambdas (Step Functions Map), so there is
# no shared live counter to spend against. The ceiling is therefore arithmetic and
# deliberately pessimistic:
#
#     worst case SerpAPI calls per search = MAX_COMPANIES x MAX_WEB_SEARCHES
#
# PoC defaults: 5 x 2 = 10 calls per search -> ~25 searches/month. The agent is
# also told to try the company's own site and Adzuna first (prompts/system.md),
# so the real number is usually well under the ceiling — but never above it.
#
# **Set any of these to 0 for unlimited.** That is how production lifts the PoC
# guard rails without touching code. Raising MAX_COMPANIES also raises the
# Places Details spend (Enterprise SKU, 1K/month) — see the cost notes in
# CLAUDE.md before you do.
MAX_COMPANIES = _limit("FMAJ_MAX_COMPANIES", 5)
MAX_WEB_SEARCHES = _limit("FMAJ_MAX_WEB_SEARCHES", 2)
MAX_TOOL_CALLS = _limit("FMAJ_MAX_TOOL_CALLS", 8)
MAX_SECONDS = _limit("FMAJ_MAX_SECONDS", 60)


def budget_summary() -> dict:
    """What the caps currently allow — logged per run so a surprising bill is
    traceable to the settings that produced it."""
    ceiling = (
        MAX_COMPANIES * MAX_WEB_SEARCHES
        if MAX_COMPANIES and MAX_WEB_SEARCHES
        else 0
    )
    return {
        "max_companies": MAX_COMPANIES or "unlimited",
        "max_web_searches_per_company": MAX_WEB_SEARCHES or "unlimited",
        "max_tool_calls": MAX_TOOL_CALLS or "unlimited",
        "max_seconds": MAX_SECONDS or "unlimited",
        "worst_case_web_searches_per_search": ceiling or "unlimited",
    }
