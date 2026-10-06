variable "project_id" {
  type    = string
  default = "green-corridor-2026"
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "api_image" {
  type        = string
  description = "corridor-api image, e.g. asia-south1-docker.pkg.dev/green-corridor-2026/cloud-run-source-deploy/corridor-api@sha256:... CI deploys it with gcloud run deploy --source, so changes to it are ignored after creation."
}

variable "logger_image" {
  type        = string
  description = "corridor-traffic-logger job image, e.g. asia-south1-docker.pkg.dev/green-corridor-2026/corridor/traffic-logger:latest. Updated by the deploy-job workflow."
}

variable "github_repo" {
  type    = string
  default = "Nandish3010/ideal-disco"
}

variable "housekeeping_token" {
  type        = string
  sensitive   = true
  description = "Value of the corridor-housekeeping-token secret, sent by the scheduler as X-Housekeeping-Token. Pass with TF_VAR_housekeeping_token; it lands in state."
}

variable "extra_env" {
  type        = map(string)
  default     = {}
  description = "More plain environment variables for corridor-api (EXTRA_ORIGINS, ALERT_LANG, PRODUCTION_MODE...)."
}
