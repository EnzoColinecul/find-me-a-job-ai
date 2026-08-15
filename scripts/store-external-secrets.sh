#!/usr/bin/env bash
# Register external API keys into AWS Secrets Manager for a stage.
# Usage:  ./scripts/store-external-secrets.sh [test|prod]
# Reads values interactively (never echoed, never in shell history).
#
# LEAVE A PROMPT BLANK TO KEEP THE EXISTING SECRET. Rotating one key should
# never require retyping the others — an earlier version of this script wrote
# every value on every run, so rotating the SerpAPI key meant re-entering the
# Places key too, and pasting the browser key there silently broke the pipeline
# with 403 API_KEY_HTTP_REFERRER_BLOCKED.
set -euo pipefail

STAGE="${1:-test}"
PROFILE="${AWS_PROFILE:-fmaj-deploy}"
REGION="ap-southeast-2"

put_secret () {
  local name="$1" value="$2"
  if [ -z "$value" ]; then
    echo "skipped  $name (left blank — existing value kept)"
    return
  fi
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
echo "Press Enter to leave any value unchanged."
echo
echo "!! The Places key here is the SERVER key: NO application restriction,"
echo "!! restricted to Places API (New). It is NOT the browser key from"
echo "!! web/.env.local — that one is HTTP-referrer restricted and a server"
echo "!! using it gets 403 API_KEY_HTTP_REFERRER_BLOCKED."
echo
read -rs -p "Google Places SERVER key: " PLACES; echo
read -rs -p "Adzuna app_id: "           ADZ_ID; echo
read -rs -p "Adzuna app_key: "          ADZ_KEY; echo
read -rs -p "SerpAPI key: "             SERP;   echo

put_secret "fmaj/$STAGE/places-key"     "$PLACES"
# Adzuna is one JSON secret, so both halves are needed to rewrite it.
if [ -n "$ADZ_ID" ] && [ -n "$ADZ_KEY" ]; then
  put_secret "fmaj/$STAGE/adzuna" \
    "$(printf '{"app_id":"%s","app_key":"%s"}' "$ADZ_ID" "$ADZ_KEY")"
elif [ -n "$ADZ_ID" ] || [ -n "$ADZ_KEY" ]; then
  echo "skipped  fmaj/$STAGE/adzuna (needs BOTH app_id and app_key — one was blank)"
else
  echo "skipped  fmaj/$STAGE/adzuna (left blank — existing value kept)"
fi
put_secret "fmaj/$STAGE/web-search-key" "$SERP"

echo
echo "Done. Verify:  aws secretsmanager list-secrets --profile $PROFILE --region $REGION \\
  --query \"SecretList[?starts_with(Name, 'fmaj/$STAGE/')].Name\""
