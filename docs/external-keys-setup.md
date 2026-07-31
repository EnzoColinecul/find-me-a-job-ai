# External API keys

Three external services, one Secrets Manager entry each, per stage:

| Secret name | Contents | Used by |
|---|---|---|
| `fmaj/{stage}/places-key` | Google Places API key (string) | Discovery Lambda |
| `fmaj/{stage}/adzuna` | `{"app_id": "...", "app_key": "..."}` | `search_jobs_adzuna` tool |
| `fmaj/{stage}/web-search-key` | SerpAPI key (string) | `web_search` tool |

## Register (run once per stage)

```bash
cd ~/Documents/Dev/find-me-a-job-ai
chmod +x scripts/store-external-secrets.sh
AWS_PROFILE=fmaj-deploy ./scripts/store-external-secrets.sh test
```

The script prompts for each value (input hidden, not stored in shell history) and
writes via a temp file so secrets never appear in the process list. Re-running
updates existing secrets.

Verify:

```bash
aws secretsmanager list-secrets --profile fmaj-deploy --region ap-southeast-2 \
  --query "SecretList[?starts_with(Name, 'fmaj/test/')].Name"
```

## How the code reads them

`fmaj_agent.secrets` resolves each key as: **env var first, then Secrets Manager.**

- Local iteration (no AWS calls): export `FMAJ_PLACES_KEY`, `FMAJ_ADZUNA_APP_ID`,
  `FMAJ_ADZUNA_APP_KEY`, `FMAJ_SERPAPI_KEY`.
- In Lambda: no env vars set → boto3 fetches from `fmaj/{stage}/...`. The Lambda
  execution role needs `secretsmanager:GetSecretValue` on those secret ARNs
  (granted in `PipelineStack` when the discovery/agent Lambdas are built).

## Rotation

Re-run the script (or `put-secret-value`) with the new value — the code fetches at
cold start, so rotation takes effect on the next Lambda cold start / process restart.
