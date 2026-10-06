# Scripts

## eval_run.py
Posts audio clips (`.m4a`, `.wav`, `.mp3`) to `/triage` (intervention notes to `/log`), compares extracted fields to expected labels, computes field and tier accuracy and per-clip latency. A clip that fails extraction counts as wrong; there are no retries. Calls are paced under the per-IP rate limit (6.5 s apart), so 12 clips take about two minutes.

**Usage:** `python3 scripts/eval_run.py [--dry-run] [--clips DIR] [--labels FILE] [--rescore] [--agreement] [--vertex-eval]`
- `--clips DIR`, `--labels FILE`: default `data/eval` and `data/eval/labels.json`; `results.json` and `results.md` are written into DIR
- `--dry-run`: Show plan without calling API (always works, no credentials needed)
- `--rescore`: re-score the raw responses already in `DIR/results.json`; no API calls
- `--agreement`: reads Firestore `runs` over the public REST API and prints suggested vs confirmed tier agreement (free)
- `--vertex-eval`: Flag for future Vertex AI submission (not yet implemented)

Binds plate `KA01AB4321` (override with `EVAL_PLATE`) so a run does not supersede a demo run on `KA01AB1234`. `API_BASE` overrides the API URL.

**Credentials:** None. Live run needs network access to the API endpoint.

**Paid calls:** one Gemini extraction per clip via `/triage` or `/log`; `POST /incidents`, `POST /runs` and `POST /vehicles/bind` are Firestore only.

## make_eval_clips.py
Synthesizes the evaluation clips into `data/eval/synthetic/` with Cloud Text-to-Speech (rotating en-IN voices at 0.95 to 1.1 speaking rate, plus Kannada-English mixed versions of clip01 and clip05) and writes `synthetic/labels.json`. Existing clips are skipped, so a rerun costs nothing.

**Usage:** `GOOGLE_APPLICATION_CREDENTIALS=<key.json> python3 scripts/make_eval_clips.py`

**Paid calls:** Cloud Text-to-Speech, one per clip written (12 on a clean run), one retry on error.

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
