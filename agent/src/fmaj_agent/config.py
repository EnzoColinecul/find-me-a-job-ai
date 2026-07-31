"""Runtime config for the agent — stage-aware secret names + region."""
import os

STAGE = os.environ.get("FMAJ_STAGE", "test")
AWS_REGION = os.environ.get("FMAJ_AWS_REGION", "ap-southeast-2")

PLACES_KEY_SECRET = f"fmaj/{STAGE}/places-key"
ADZUNA_SECRET = f"fmaj/{STAGE}/adzuna"
WEB_SEARCH_SECRET = f"fmaj/{STAGE}/web-search-key"  # SerpAPI
