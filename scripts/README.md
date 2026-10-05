# Scripts

## eval_run.py
Posts audio clips to `/triage` endpoint, compares extracted fields to expected labels, computes accuracy metrics.

**Usage:** `python3 scripts/eval_run.py [--dry-run] [--vertex-eval]`
- `--dry-run`: Show plan without calling API (always works, no credentials needed)
- `--vertex-eval`: Flag for future Vertex AI submission (not yet implemented)

**Credentials:** None required for `--dry-run`. For live run: network access to API endpoint.

**Paid calls:** `POST /incidents`, `POST /runs`, `POST /vehicles/bind`, `POST /triage` (Gemini extraction per clip).

## demo_seed.py
Seeds Firestore database with initial data: vehicles (ambulance, fire, police), junctions for both corridors, and one open incident.

**Usage:** `python3 scripts/demo_seed.py`

**Credentials:** Requires `GOOGLE_APPLICATION_CREDENTIALS` set to service account JSON.

**Paid calls:** Firestore writes only (no external API calls).

## demo_reset.py
Resets demo Firestore to a clean state: ends active runs, deletes alerts/audit/reports/briefs/duty docs, closes incidents, clears junction phases, removes vehicle bindings.

**Usage:** `python3 scripts/demo_reset.py [--apply]`
- Dry run by default (prints counts); pass `--apply` to execute changes

**Credentials:** Requires `GOOGLE_APPLICATION_CREDENTIALS` set to service account JSON.

**Paid calls:** Firestore batch updates only (no external API calls).

## make_scenario.py
Generates `data/scenarios/blr-two-vehicles.json` from corridor topology and traffic data. Rerun this after updating the corridor config.

**Usage:** `python3 scripts/make_scenario.py`

**Credentials:** None (reads local JSON files only).

**Paid calls:** None.
