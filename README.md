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
- **Voice triage.** The crew speaks in any Indian language; Gemini extracts fields, a lookup table sets the tier, the crew confirms with one tap.
- **Hospital handover.** A live transit log and an English ATMIST brief with a prep checklist, ready before arrival.
- **Control room and replay.** All runs, junction ACK states, escalations, and a with-vs-without replay that counts minutes saved.

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
`POST /brief` · `POST /location` · `POST /ack` · `GET /health`. Contracts are in [SCHEMA.md](SCHEMA.md).

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

## Configuration

Project `green-corridor-2026`, Firestore `(default)` database, hosting https://green-corridor-2026.web.app, Cloud Run service `corridor-api` in asia-south1.

| Env var | Value |
|---|---|
| `GEMINI_MODEL` | `gemini-3-flash-preview` |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.1-flash-lite` |
| `GCP_PROJECT` | `green-corridor-2026` |
| `GEMINI_LOCATION` | `global` |
| `MAPS_SERVER_KEY` | from Secret Manager `corridor-maps-server-key` |
| `MEDIA_BUCKET` | `green-corridor-2026-media` |

## Layout

```
api/        FastAPI, acuity.py, priority.py, leadtime.py, signal_adapter.py
web/        Vite React PWA, 6 routes
jobs/       traffic_logger.py (Cloud Run Job -> BigQuery)
data/       corridors/{blr,hyd}.json, scenarios/*.json
scripts/    demo_seed.py
```

## Deploy

Pushes to `main` deploy `api/` to Cloud Run and `web/` to Firebase Hosting via GitHub Actions, authenticated with Workload Identity Federation (no stored keys). Checks run on every push.
