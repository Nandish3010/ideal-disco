output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "hosting_url" {
  value = "https://${google_firebase_hosting_site.web.site_id}.web.app"
}

output "ci_service_account" {
  value = google_service_account.ci.email
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}
