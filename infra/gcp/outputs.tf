# Sensitive: fetch with `terraform output -raw places_api_key_test` and store into
# AWS Secrets Manager fmaj/{stage}/places-key (do not commit).
output "places_api_keys" {
  value     = { for s, k in google_apikeys_key.places : s => k.key_string }
  sensitive = true
}
