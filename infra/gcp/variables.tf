variable "project_id" {
  type        = string
  description = "GCP project id (project-7187e8cf-43d5-451b-be4)"
}

variable "region" {
  type    = string
  default = "australia-southeast1"
}

variable "stages" {
  type    = set(string)
  default = ["test", "prod"]
}
