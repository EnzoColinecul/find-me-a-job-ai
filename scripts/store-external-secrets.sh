#!/usr/bin/env bash
# Register external API keys into AWS Secrets Manager for a stage.
# Usage:  ./scripts/store-external-secrets.sh [test|prod]
# Reads values interactively (never echoed, never in shell history).
set -euo pipefail

STAGE="${1:-test}"
PROFILE="${AWS_PROFILE:-fmaj-deploy}"
REGION="ap-southeast-2"

put_secret () {
  local name="$1" value="$2"
  # write via a temp file so the secret is not visible in the process list
  local tmp; tmp="$(mktemp)"; printf '%s' "$value" > "$tmp"
  if aws secretsmanager create-secret --profile "$PROFILE" --region "$REGION" \
        --name "$name" --secret-string "file://$tmp" >/dev/null 2>&1; then
    echo "created  $name"
  else
    aws secretsmanager put-secret-value --profile "$PROFILE" --region "$REGION" \
        --secret-id "$name" --secret-string "file://$tmp" >/dev/null
    echo "updated  $name"
  fi
  rm -f "$tmp"
}

echo "Storing secrets for stage: $STAGE (profile: $PROFILE)"
read -rs -p "Google Places API key: " PLACES; echo
read -rs -p "Adzuna app_id: "        ADZ_ID; echo
read -rs -p "Adzuna app_key: "       ADZ_KEY; echo
read -rs -p "SerpAPI key: "          SERP;   echo

put_secret "fmaj/$STAGE/places-key"     "$PLACES"
put_secret "fmaj/$STAGE/adzuna"         "$(printf '{"app_id":"%s","app_key":"%s"}' "$ADZ_ID" "$ADZ_KEY")"
put_secret "fmaj/$STAGE/web-search-key" "$SERP"

echo "Done. Verify:  aws secretsmanager list-secrets --profile $PROFILE --region $REGION \\
  --query \"SecretList[?starts_with(Name, 'fmaj/$STAGE/')].Name\""
