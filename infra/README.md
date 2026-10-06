# Infrastructure

Two directories, both code for what already runs in project `green-corridor-2026`.

| Path | What |
|---|---|
| `terraform/` | A Terraform module that **mirrors the hand-built setup**: enabled APIs, Cloud Run service `corridor-api` and job `corridor-traffic-logger`, the two Scheduler jobs, Firestore `(default)`, the media bucket, the BigQuery dataset, the Secret Manager secrets (no values), the two service accounts and their IAM roles, the Workload Identity pool and provider for GitHub, the Firebase Hosting site, and the Maps API keys. |
| `monitoring/` | Cloud Monitoring as code: dashboard, `/health` uptime check, alert policy, and `apply.sh`. |

## The Terraform module is a mirror, not the owner

The project was built by hand with `gcloud`, and the deploy workflows keep shipping images and env vars with `gcloud run deploy --source` and `gcloud run jobs update`. So the module:

- takes the image as a variable and ignores later image changes on the service and the job, so a plan never rolls back a deploy;
- has been checked with `terraform init -backend=false && terraform validate` only. It has **not been planned or applied** against the live project;
- leaves out what other tools own: the Firebase-created web API key, the owner-level `corridor-deploy` key account, Artifact Registry repositories, BigQuery tables (created by the job and `report.py`), Firestore rules and indexes (Firebase CLI), and every secret value.

Two IAM roles in `iam.tf` do not exist in the live project yet: `roles/cloudtrace.agent` (tracing) and `roles/firebasecloudmessaging.admin` (push). Grant them by hand or by applying the module:

```
for r in cloudtrace.agent firebasecloudmessaging.admin; do
  gcloud projects add-iam-policy-binding green-corridor-2026 \
    --member=serviceAccount:corridor-api@green-corridor-2026.iam.gserviceaccount.com --role=roles/$r
done
```

## Importing the existing resources

Terraform would otherwise try to create them. From `infra/terraform`, with `terraform.tfvars` (or `TF_VAR_*`) holding `api_image`, `logger_image` and `housekeeping_token`:

```
terraform init
P=green-corridor-2026; R=asia-south1
terraform import google_service_account.api projects/$P/serviceAccounts/corridor-api@$P.iam.gserviceaccount.com
terraform import google_service_account.ci  projects/$P/serviceAccounts/corridor-ci@$P.iam.gserviceaccount.com
terraform import google_iam_workload_identity_pool.github projects/$P/locations/global/workloadIdentityPools/github
terraform import google_iam_workload_identity_pool_provider.github projects/$P/locations/global/workloadIdentityPools/github/providers/gh-oidc
terraform import google_firestore_database.default projects/$P/databases/'(default)'
terraform import google_storage_bucket.media $P-media
terraform import google_bigquery_dataset.corridor projects/$P/datasets/corridor
terraform import google_secret_manager_secret.maps_server_key projects/$P/secrets/corridor-maps-server-key
terraform import google_secret_manager_secret.housekeeping_token projects/$P/secrets/corridor-housekeeping-token
terraform import google_cloud_run_v2_service.api projects/$P/locations/$R/services/corridor-api
terraform import google_cloud_run_v2_job.logger projects/$P/locations/$R/jobs/corridor-traffic-logger
terraform import google_cloud_scheduler_job.logger_peak projects/$P/locations/$R/jobs/corridor-traffic-logger-10m
terraform import google_cloud_scheduler_job.housekeeping projects/$P/locations/$R/jobs/corridor-housekeeping
terraform import google_firebase_hosting_site.web projects/$P/sites/$P
terraform import google_apikeys_key.maps_browser projects/$P/locations/global/keys/19fa6f8a-8c5c-4ebf-8479-abeebe26bddc
terraform import google_apikeys_key.maps_server  projects/$P/locations/global/keys/e9a95e44-df05-4c3d-a73d-2db07a509294
terraform plan
```

IAM members, bucket IAM and the Cloud Run invoker binding are additive: `plan` shows them as creates, and applying an already-present binding is harmless. Read the plan before any apply: expect differences in the Cloud Run env (the module sets `OTEL_ENABLED`) and the two new roles above.

## Monitoring

```
infra/monitoring/apply.sh            # dashboard and uptime check (free); skips what exists
infra/monitoring/apply.sh metrics    # also the four log-based metrics the dashboard's last row reads
NOTIFICATION_CHANNEL=projects/green-corridor-2026/notificationChannels/<id> infra/monitoring/apply.sh alert
```

The alert policy needs a notification channel, so it is not created by default; `alert.yaml` has two conditions (the uptime check failing, and 5xx above 2% of requests over 5 minutes).
