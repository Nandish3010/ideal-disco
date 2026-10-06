# Runtime identity of corridor-api and the traffic logger job.
resource "google_service_account" "api" {
  account_id   = "corridor-api"
  display_name = "corridor-api runtime"
}

# What GitHub Actions deploys as (through Workload Identity Federation, see wif.tf).
resource "google_service_account" "ci" {
  account_id   = "corridor-ci"
  display_name = "GitHub Actions deployer"
}

locals {
  api_roles = [
    "roles/aiplatform.user",
    "roles/bigquery.dataEditor",
    "roles/cloudtranslate.user",
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/run.invoker", # the scheduler runs the logger job as this account
    "roles/secretmanager.secretAccessor",
    # added with the tracing and push work; the hand-built project does not have them yet
    "roles/cloudtrace.agent",             # spans to Cloud Trace
    "roles/firebasecloudmessaging.admin", # FCM send to the cop on duty
  ]
  ci_roles = [
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/firebasehosting.admin",
    "roles/logging.viewer",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/storage.admin",
  ]
}

resource "google_project_iam_member" "api" {
  for_each = toset(local.api_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "ci" {
  for_each = toset(local.ci_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.ci.email}"
}

# `gcloud run deploy --service-account corridor-api` runs as corridor-ci, which must be allowed to act as it.
resource "google_service_account_iam_member" "ci_acts_as_api" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci.email}"
}
