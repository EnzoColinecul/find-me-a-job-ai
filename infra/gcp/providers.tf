terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Auth via the IaC service account:
#   export GOOGLE_APPLICATION_CREDENTIALS=<path to SA key JSON>   (git-ignored)
provider "google" {
  project = var.project_id
  region  = var.region
}
