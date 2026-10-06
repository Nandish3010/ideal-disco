resource "google_cloud_scheduler_job" "logger_peak" {
  name             = "corridor-traffic-logger-10m"
  region           = var.region
  schedule         = "*/10 8-10,17-20 * * *" # Bengaluru peak hours
  time_zone        = "Asia/Kolkata"
  attempt_deadline = "180s"

  retry_config {
    min_backoff_duration = "5s"
    max_backoff_duration = "3600s"
    max_doublings        = 5
    max_retry_duration   = "0s"
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.logger.name}:run"
    oauth_token {
      service_account_email = google_service_account.api.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}

# Stale and escalation sweeps without waiting for a vehicle tick; spaced to let Cloud Run scale to zero.
resource "google_cloud_scheduler_job" "housekeeping" {
  name             = "corridor-housekeeping"
  region           = var.region
  schedule         = "*/30 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "30s"

  retry_config {
    min_backoff_duration = "5s"
    max_backoff_duration = "3600s"
    max_doublings        = 5
    max_retry_duration   = "0s"
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.api.uri}/housekeeping"
    headers = {
      "Content-Type"         = "application/json"
      "X-Housekeeping-Token" = var.housekeeping_token
    }
  }
}
