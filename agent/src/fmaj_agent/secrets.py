"""Read external API keys.

Order of resolution for each key:
  1. Local env var (FMAJ_PLACES_KEY, FMAJ_ADZUNA_APP_ID/KEY, FMAJ_SERPAPI_KEY)
     — convenient for local iteration without AWS calls.
  2. AWS Secrets Manager (fmaj/{stage}/...) — how Lambdas get them in the cloud.

Values are cached per process.
"""
import json
import os
from functools import lru_cache

import boto3

from fmaj_agent import config


@lru_cache(maxsize=1)
def _client():
    return boto3.client("secretsmanager", region_name=config.AWS_REGION)


@lru_cache(maxsize=8)
def _secret_string(name: str) -> str:
    return _client().get_secret_value(SecretId=name)["SecretString"]


def places_api_key() -> str:
    return os.environ.get("FMAJ_PLACES_KEY") or _secret_string(config.PLACES_KEY_SECRET)


def adzuna_credentials() -> tuple[str, str]:
    env_id = os.environ.get("FMAJ_ADZUNA_APP_ID")
    env_key = os.environ.get("FMAJ_ADZUNA_APP_KEY")
    if env_id and env_key:
        return env_id, env_key
    data = json.loads(_secret_string(config.ADZUNA_SECRET))
    return data["app_id"], data["app_key"]


def serpapi_key() -> str:
    return os.environ.get("FMAJ_SERPAPI_KEY") or _secret_string(config.WEB_SEARCH_SECRET)
