# Firestore: the event bus and store. Rules and indexes are deployed by the Firebase CLI from web/.
resource "google_firestore_database" "default" {
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  concurrency_mode        = "PESSIMISTIC"
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
  depends_on              = [google_project_service.enabled]
}

# Spoken-alert MP3s. Public read: the cop's browser plays them from storage.googleapis.com.
resource "google_storage_bucket" "media" {
  name                        = "${var.project_id}-media"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  soft_delete_policy {
    retention_duration_seconds = 604800
  }
}

resource "google_storage_bucket_iam_member" "media_public_read" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_storage_bucket_iam_member" "media_api_writes" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

# traffic_spans and run_reports are created by the logger job and by report.py on first write, not here.
resource "google_bigquery_dataset" "corridor" {
  dataset_id = "corridor"
  location   = var.region
}

# Secret containers only; the values are added with `gcloud secrets versions add` and never live in this repo.
resource "google_secret_manager_secret" "maps_server_key" {
  secret_id = "corridor-maps-server-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "housekeeping_token" {
  secret_id = "corridor-housekeeping-token"
  replication {
    auto {}
  }
}
