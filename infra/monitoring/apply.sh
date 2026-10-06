#!/usr/bin/env bash
# Monitoring as code for corridor-api. Idempotent: a dashboard, uptime check or metric that already exists is skipped.
#   ./apply.sh              dashboard + uptime check (both free)
#   ./apply.sh metrics      also the four log-based metrics the dashboard's last row reads
#   NOTIFICATION_CHANNEL=projects/P/notificationChannels/ID ./apply.sh alert    also the alert policy
# Create a channel first (email is free): gcloud beta monitoring channels create --display-name=oncall --type=email \
#   --channel-labels=email_address=you@example.com
set -euo pipefail
cd "$(dirname "$0")"
PROJECT="${PROJECT:-green-corridor-2026}"
val() { awk -F': ' -v k="$1" '$1==k {gsub(/^'"'"'|'"'"'$/, "", $2); print $2}' uptime.yaml; }

DASH="Green Corridor - corridor-api"
if [ -z "$(gcloud monitoring dashboards list --project "$PROJECT" --filter="displayName=\"$DASH\"" --format='value(name)')" ]; then
  gcloud monitoring dashboards create --project "$PROJECT" --config-from-file=dashboard.json
fi

UPTIME="$(val display_name)"
check() { gcloud monitoring uptime list-configs --project "$PROJECT" --filter="displayName=\"$UPTIME\"" --format='value(name)'; }
if [ -z "$(check)" ]; then
  gcloud monitoring uptime create "$UPTIME" --project "$PROJECT" \
    --resource-type=uptime-url --resource-labels="host=$(val host),project_id=$PROJECT" \
    --protocol="$(val protocol)" --port="$(val port)" --path="$(val path)" \
    --period="$(val period_minutes)" --timeout="$(val timeout_seconds)" \
    --matcher-type=contains-string --matcher-content="$(val content_match)"
fi
CHECK_ID="$(check | awk -F/ '{print $NF}')"
echo "uptime check: $CHECK_ID"

for step in "$@"; do
  case "$step" in
    metrics) # event names are the `event` field of the API's JSON log lines
      for pair in alert_fired:alert escalation:escalation rationale_template:rationale_template brief_error:brief_error; do
        name="${pair%%:*}"; event="${pair##*:}"
        gcloud logging metrics describe "$name" --project "$PROJECT" >/dev/null 2>&1 ||
          gcloud logging metrics create "$name" --project "$PROJECT" \
            --description="corridor-api log lines with event=$event" \
            --log-filter="resource.type=\"cloud_run_revision\" resource.labels.service_name=\"corridor-api\" jsonPayload.event=\"$event\""
      done ;;
    alert)
      : "${NOTIFICATION_CHANNEL:?set NOTIFICATION_CHANNEL to a notification channel name}"
      tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
      sed "s/\${UPTIME_CHECK_ID}/$CHECK_ID/" alert.yaml > "$tmp"
      printf 'notificationChannels:\n  - %s\n' "$NOTIFICATION_CHANNEL" >> "$tmp"
      gcloud alpha monitoring policies create --project "$PROJECT" --policy-from-file="$tmp" ;;
    *) echo "unknown step: $step" >&2; exit 2 ;;
  esac
done
