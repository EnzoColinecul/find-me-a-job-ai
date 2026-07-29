# GCP IaC — OAuth clients + Places API keys

Provisioned with service account
`iac-find-me-a-job-ai@project-7187e8cf-43d5-451b-be4.iam.gserviceaccount.com`
(roles: IAM OAuth Client Admin, Service Usage Admin, API Keys Admin — all granted;
OAuth consent screen already configured manually).

Auth: `export GOOGLE_APPLICATION_CREDENTIALS=<path to SA key JSON>` — the key file
is git-ignored and must never be committed.

Resources per environment (test, prod) — see Notion card "GCP IaC":

- OAuth client `fmaj-{stage}` with redirect
  `https://fmaj-{stage}.auth.ap-southeast-2.amazoncognito.com/oauth2/idpresponse`
- Places API (New) key restricted per stage
- Outputs stored into AWS Secrets Manager `fmaj/{stage}/google-oauth` and
  `fmaj/{stage}/places-key`

TODO: Terraform configuration.
