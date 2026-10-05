# Emergency Green Corridor

Built for the Google Cloud AI Builder Cup 2026 (Sustainability & Social Impact).

## Problem

In Bengaluru, and in every congested city, ambulances, fire engines and police vehicles sit at red
signals while the officer at the junction has no idea they are coming. Nobody is told early enough
to clear the queue, and nothing adapts. Every minute costs lives or property.

Signal preemption exists on paper, but it needs real-time integration with city controllers, which
is years away. What can ship today is the missing link: telling the right cop, early enough, with
the actual queue length and which way the vehicle turns, and sequencing several vehicles fairly.

## The product

- **Early cop alert.** Two stages (PREPARE, then STOP CROSS TRAFFIC) sized to the queue that is actually there, spoken in the junction's language.
- **Signal preemption behind `SignalAdapter`.** Today a simulated digital twin of a real corridor; a real controller drops in later.
- **Multi-vehicle sequencing.** Deterministic acuity tiers decide the order ("fire engine first, ambulance 12 s later"); Gemini only explains it.
- **Voice and photo triage.** The crew speaks in any Indian language, or photographs the monitor; Gemini extracts fields, a lookup table sets the tier, the crew confirms with one tap.
- **Hospital routing agent.** A Google ADK agent on Vertex AI picks the destination from a mock capability and bed roster plus traffic-aware ETAs, and shows its tool-call trace; it never changes acuity or signal priority.
- **Hospital handover.** A live transit log and an English ATMIST brief with a prep checklist, ready before arrival.
- **Control room and replay.** All runs, junction ACK states, escalations, and a with-vs-without replay that counts minutes saved. Every run ends with a report card (Firestore and BigQuery).

## Architecture

```
 vehicle PWA ──GPS/voice──▶ Cloud Run corridor-api ──▶ Gemini 3.x Flash (global)
 sim feeder  ──GPS───────▶   │ /location: Routes (throttled) → leadtime → priority
   (source field)            │        └─▶ SignalAdapter.request_green(J, approach, T)
                             │                 └─▶ SimAdapter → Firestore junctions/
                             ▼
                        Firestore (default) (event bus; every screen subscribes)
                             │
   cop ◀─listener+TTS────────┼────────▶ hospital ◀─brief at ETA−5 (inside /location)
   control room ◀────────────┘          sim + with-vs-without replay
 Cloud Run Job (10 min) ──Routes spans──▶ BigQuery corridor.* ──▶ BQML clearance model
 run end ──report card──▶ BigQuery ──▶ Looker Studio
```

## Screens (React PWA)

`/vehicle` voice triage, acuity confirm, log, route · `/cop` junction listener, on-duty toggle, ACK ·
`/hospital` live log, brief, countdown · `/control` all runs, ACK states, escalations ·
`/sim` corridor twin with with-vs-without split · `/dispatch` issues incident IDs.
Pick a corridor with `?corridor=blr` or `?corridor=hyd`.

## API (FastAPI, Cloud Run)

`POST /vehicles/bind` · `POST /incidents` · `POST /runs` (start/end) · `POST /triage` · `POST /log` ·
`POST /brief` · `POST /route` · `POST /location` · `POST /ack` · `POST /duty` · `GET /health`. Contracts are in [SCHEMA.md](SCHEMA.md).

## Traffic data and forecast

A scheduled Cloud Run Job logs Routes traffic spans per junction approach into BigQuery `corridor.traffic_spans`. [jobs/bqml](jobs/bqml) turns them into a feature view and a BigQuery ML boosted-tree model, `corridor.jam_forecast`, that predicts the next reading's jam length. It is a proof of the pipeline on one evening of data, not a forecast to deploy; see its README for the numbers and limits.

## Honest notes

- **Signals are simulated behind `SignalAdapter`.** Cop alerts are deployable today; the signal API is phase 2.
- **No auth: demo only, endpoints publicly writable.** Identity is a mock plate registry plus a visible rejection of unknown plates.
- **Synthetic patients only.** Extracted values are transcription support; a clinician confirms.
- Minutes saved is a simulated estimate on recorded traffic, not a field measurement.
- Corridor coordinates in `data/corridors/*.json` are approximate.

## Run

Prerequisites: Python 3.12, Node 20+, a Google Cloud project with the (default) Firestore database.

```
# api/  (placeholder, fill in as the API lands)
cd api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=<path to a key kept OUTSIDE this repo>
uvicorn main:app --reload --port 8080

# web/  (placeholder)
cd web
cp .env.example .env.local   # fill in VITE_FIREBASE_CONFIG
npm install && npm run dev

# engine self-checks (pure python, no dependencies)
python3 api/acuity.py && python3 api/priority.py && python3 api/leadtime.py

# seed demo data
python3 scripts/demo_seed.py
```

## Reset demo data

Before a demo take, clear old runs, alerts, audit, reports, briefs, duty and junction phases (dry run without `--apply` first; needs `GOOGLE_APPLICATION_CREDENTIALS`):

```
python3 scripts/demo_reset.py --apply
```

## Configuration

Project `green-corridor-2026`, Firestore `(default)` database, hosting https://green-corridor-2026.web.app, Cloud Run service `corridor-api` in asia-south1.

Traffic logger: Cloud Run Job `corridor-traffic-logger` (`jobs/traffic_logger.py`, `Dockerfile.job`) writes Routes traffic spans to BigQuery `corridor.traffic_spans` every 10 minutes via Cloud Scheduler `corridor-traffic-logger-10m`.

| Env var | Value |
|---|---|
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` (field extraction from text, audio and photos) |
| `GEMINI_FALLBACK_MODEL` | `gemini-3-flash-preview` (extraction fallback) |
| `GEMINI_TEXT_MODEL` | `gemini-3-flash-preview` (default in code; hospital brief and sequence rationale, with `GEMINI_MODEL` as fallback) |
| `GCP_PROJECT` | `green-corridor-2026` |
| `GEMINI_LOCATION` | `global` |
| `MAPS_SERVER_KEY` | from Secret Manager `corridor-maps-server-key` |
| `MEDIA_BUCKET` | `green-corridor-2026-media` |
| `ALERT_LANG` | `en` (default): conversational English alerts and voice; `kn` / `te`: colloquial Kannada / Telugu with English loanwords; `corridor`: the corridor's own language |

## Evaluation

Run `python3 scripts/eval_run.py --dry-run` to preview the plan; record 10 audio clips into `data/eval/clip01.m4a` … `clip10.m4a`, then run without `--dry-run` to compute per-field and tier accuracy against `data/eval/labels.json`. Results written to `data/eval/results.json`.

## Layout

```
api/        FastAPI, acuity.py, priority.py, leadtime.py, signal_adapter.py, agent.py + hospitals.py (routing agent, mock roster)
web/        Vite React PWA, 6 routes
jobs/       traffic_logger.py (Cloud Run Job -> BigQuery)
data/       corridors/{blr,hyd}.json, scenarios/*.json
scripts/    demo_seed.py
```

## Deploy

Pushes to `main` deploy `api/` to Cloud Run and `web/` to Firebase Hosting via GitHub Actions, authenticated with Workload Identity Federation (no stored keys). Checks run on every push.

The `jobs/` traffic logger deploys separately: `deploy-job` builds the image, updates the `corridor-traffic-logger` Cloud Run Job and runs it once to verify. Run it with `workflow_dispatch` after changing job-related files outside the paths it watches.
