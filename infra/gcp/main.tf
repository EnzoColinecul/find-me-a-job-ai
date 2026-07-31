# What IS automatable on the GCP side:
#   - enable the Places API (New)
#   - one restricted Places API key per stage
#
# What is NOT automatable (see README + docs/google-login-setup.md):
#   - the OAuth 2.0 web client (client id + secret). Terraform's google provider has
#     no resource for generic web OAuth clients; it must be created in the console.
#     Its output is stored in AWS SSM + Secrets Manager and consumed by the CDK
#     AuthStack.

resource "google_project_service" "places" {
  project            = var.project_id
  service            = "places.googleapis.com"
  disable_on_destroy = false
}

resource "google_apikeys_key" "places" {
  for_each     = var.stages
  project      = var.project_id
  name         = "fmaj-${each.key}-places"
  display_name = "fmaj-${each.key}-places"

  restrictions {
    api_targets {
      service = "places.googleapis.com"
    }
  }

  depends_on = [google_project_service.places]
}
