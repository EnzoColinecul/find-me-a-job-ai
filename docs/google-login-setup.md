# Google login — end-to-end setup

How the pieces fit:

```
Google OAuth client (manual, console)
        │  client_id ─────────► SSM  /fmaj/{stage}/google-client-id
        │  client_secret ─────► Secrets Manager  fmaj/{stage}/google-client-secret
        ▼
CDK AuthStack  → Cognito user pool + Google IdP + hosted UI + app client
        │  outputs: UserPoolId, UserPoolClientId, CognitoDomain
        ▼
Next.js (PKCE hosted-UI redirect)  ──id_token──►  FastAPI /me  ──►  DynamoDB USER#
```

## 1. Create the Google OAuth client (one-time, manual)

Terraform can't create generic web OAuth clients, so do this in the console once
(the consent screen is already configured):

1. GCP Console → APIs & Services → **Credentials** → **Create credentials** →
   **OAuth client ID** → Application type **Web application**, name `fmaj-test`.
2. **Authorized JavaScript origins:** `http://localhost:3000`
3. **Authorized redirect URIs:** the Cognito IdP response URL —
   `https://fmaj-test.auth.ap-southeast-2.amazoncognito.com/oauth2/idpresponse`
   (the domain prefix `fmaj-test` matches the CDK `HostedDomain`).
4. Create → copy the **Client ID** and **Client secret**.
5. Repeat for `fmaj-prod` with the prod origin + `fmaj-prod...` redirect URL.

## 2. Store the client credentials (consumed by CDK)

```bash
STAGE=test
CLIENT_ID=xxxxx.apps.googleusercontent.com
CLIENT_SECRET=yyyyy

aws ssm put-parameter --profile fmaj-deploy --region ap-southeast-2 \
  --name "/fmaj/$STAGE/google-client-id" --type String --value "$CLIENT_ID" --overwrite

aws secretsmanager create-secret --profile fmaj-deploy --region ap-southeast-2 \
  --name "fmaj/$STAGE/google-client-secret" --secret-string "$CLIENT_SECRET" \
  || aws secretsmanager put-secret-value --profile fmaj-deploy --region ap-southeast-2 \
     --secret-id "fmaj/$STAGE/google-client-secret" --secret-string "$CLIENT_SECRET"
```

## 3. Deploy the Auth stack

```bash
cd infra
cdk deploy 'Fmaj-Test/Auth' --profile fmaj-deploy
```

Note the outputs `UserPoolClientId` and `CognitoDomain`.

## 4. Point the frontend at the pool

```bash
cd web
cp .env.example .env.local
# set NEXT_PUBLIC_COGNITO_CLIENT_ID and NEXT_PUBLIC_COGNITO_DOMAIN from the outputs
```

## 5. Run the backend with the pool ids

```bash
cd api
FMAJ_COGNITO_USER_POOL_ID=<UserPoolId> \
FMAJ_COGNITO_CLIENT_ID=<UserPoolClientId> \
FMAJ_TABLE_NAME=fmaj-test-main \
uv run uvicorn app.main:app --reload --port 8000
```

## 6. Test the round trip

`make dev` → open http://localhost:3000 → **Sign in with Google** → consent →
redirected back → the page shows your name/email and "1 free search available",
proving `/me` verified the token and created the `USER#` record.

## Places API keys (Terraform, separate from login)

```bash
cd infra/gcp
cp terraform.tfvars.example terraform.tfvars
export GOOGLE_APPLICATION_CREDENTIALS=../../project-7187e8cf-43d5-451b-be4-84a9aac3c5df.json
terraform init && terraform apply
# store the keys into Secrets Manager (used later by the discovery Lambda):
terraform output -raw places_api_keys
```
