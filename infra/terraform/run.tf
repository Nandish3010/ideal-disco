resource "google_cloud_run_v2_service" "api" {
  name     = "corridor-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.api.email
    timeout                          = "300s"
    max_instance_request_concurrency = 80
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    containers {
      image = var.api_image
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = false # --no-cpu-throttling: background tasks keep running after the response
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = merge(
          {
            GCP_PROJECT           = var.project_id
            GEMINI_MODEL          = "gemini-3.1-flash-lite"
            GEMINI_FALLBACK_MODEL = "gemini-3-flash-preview"
            GEMINI_TEXT_MODEL     = "gemini-3-flash-preview"
            GEMINI_LOCATION       = "global"
            OTEL_ENABLED          = "1"
          },
          var.extra_env,
        )
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "MAPS_SERVER_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.maps_server_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "HOUSEKEEPING_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.housekeeping_token.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  # deploy-api.yml ships the image and env with `gcloud run deploy --source`; Terraform only owns the shape.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, template[0].revision, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

# The demo API is public: judges open every screen without signing in.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Traffic logger: Routes traffic spans per junction approach into BigQuery, run by Cloud Scheduler at peak hours.
resource "google_cloud_run_v2_job" "logger" {
  name     = "corridor-traffic-logger"
  location = var.region

  template {
    task_count = 1
    template {
      service_account = google_service_account.api.email
      max_retries     = 1
      timeout         = "300s"
      containers {
        image = var.logger_image
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name = "MAPS_SERVER_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.maps_server_key.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}
