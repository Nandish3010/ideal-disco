#!/usr/bin/env bash
# Build the view, train, evaluate, predict. Needs bq authenticated against the corridor project.
# Training takes about 15 minutes even on this tiny table.
set -euo pipefail
cd "$(dirname "$0")"
for f in features train evaluate predict; do bq query --use_legacy_sql=false --format=pretty < "$f.sql"; done
