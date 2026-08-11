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
# HISTORY, because the shape of this matters. Companies are investigated in
# PARALLEL Lambdas (Step Functions Map), so there was no shared counter to spend
# against and the ceiling had to be arithmetic:
#
#     worst case SerpAPI calls per search = MAX_COMPANIES x MAX_WEB_SEARCHES
#
# That product coupled two unrelated things. Keeping SerpAPI inside its free tier
# meant dropping MAX_COMPANIES from 40 to 5 — which cut the number of places the
# user is shown by 8x, to buy headroom on a tool most companies never reach. The
# knob that was supposed to control cost was silently controlling the product.
#
# `budget.DynamoSearchBudget` gives those Lambdas the shared counter they lacked,
# so the two are now separate:
#
#   MAX_COMPANIES              how many places the user gets     -> Places Details
#   MAX_WEB_SEARCHES_PER_SEARCH  how much SerpAPI a search may use -> SerpAPI
#
# Defaults: 40 companies (Details is the Enterprise SKU, 1K/month free -> ~25
# searches/month) and 10 shared SerpAPI calls (~25 searches/month). Both land on
# the same number, which is the point — neither knob is now the other's hostage.
#
# MAX_WEB_SEARCHES stays as a per-company backstop for when the shared counter
# can't be reached; see the fail-open note in budget.py.
#
# **Set any of these to 0 for unlimited.** That is how production lifts the PoC
# guard rails without touching code.
MAX_COMPANIES = _limit("FMAJ_MAX_COMPANIES", 40)
MAX_WEB_SEARCHES = _limit("FMAJ_MAX_WEB_SEARCHES", 2)
MAX_WEB_SEARCHES_PER_SEARCH = _limit("FMAJ_MAX_WEB_SEARCHES_PER_SEARCH", 10)
MAX_TOOL_CALLS = _limit("FMAJ_MAX_TOOL_CALLS", 8)
MAX_SECONDS = _limit("FMAJ_MAX_SECONDS", 60)

#: Per-search ceilings for metered tools, keyed by tool name. Read at call time
#: rather than captured, so tests and env overrides both work.
_SHARED_CAPS = {"web_search": lambda: MAX_WEB_SEARCHES_PER_SEARCH}


def shared_cap(tool: str) -> int:
    """The per-search ceiling for a metered tool. 0 = no shared ceiling."""
    getter = _SHARED_CAPS.get(tool)
    return getter() if getter else 0


def budget_summary() -> dict:
    """What the caps currently allow — logged per run so a surprising bill is
    traceable to the settings that produced it."""
    arithmetic = (
        MAX_COMPANIES * MAX_WEB_SEARCHES
        if MAX_COMPANIES and MAX_WEB_SEARCHES
        else 0
    )
    # The shared cap is the real ceiling when it is set; the arithmetic product
    # only bites if the counter is unreachable.
    if MAX_WEB_SEARCHES_PER_SEARCH:
        effective = (
            min(MAX_WEB_SEARCHES_PER_SEARCH, arithmetic)
            if arithmetic
            else MAX_WEB_SEARCHES_PER_SEARCH
        )
    else:
        effective = arithmetic
    return {
        "max_companies": MAX_COMPANIES or "unlimited",
        "max_web_searches_per_company": MAX_WEB_SEARCHES or "unlimited",
        "max_web_searches_per_search": MAX_WEB_SEARCHES_PER_SEARCH or "unlimited",
        "max_tool_calls": MAX_TOOL_CALLS or "unlimited",
        "max_seconds": MAX_SECONDS or "unlimited",
        "web_searches_per_search": effective or "unlimited",
    }
