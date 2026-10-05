# Emergency Green Corridor

**Every red light costs a life. Tell the cop at the next junction, early enough and with the real queue, that an ambulance or fire engine is coming.** Built by Nandish for the Google Cloud AI Builder Cup 2026 (Sustainability & Social Impact).

[![checks](https://github.com/Nandish3010/ideal-disco/actions/workflows/checks.yml/badge.svg)](https://github.com/Nandish3010/ideal-disco/actions/workflows/checks.yml)
[![deploy-api](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-api.yml/badge.svg)](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-api.yml)
[![deploy-web](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-web.yml/badge.svg)](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-web.yml)
[![deploy-job](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-job.yml/badge.svg)](https://github.com/Nandish3010/ideal-disco/actions/workflows/deploy-job.yml)

- Live app: https://green-corridor-2026.web.app (try `/sim?mode=replay&scenario=blr-two-vehicles` first, no sign-in)
- API health: https://corridor-api-919512130399.asia-south1.run.app/health
- Deck: [deck/slides.pdf](deck/slides.pdf) · Video plan: [deck/VIDEO.md](deck/VIDEO.md) · Contracts: [SCHEMA.md](SCHEMA.md)

## The problem

Ambulances, fire engines and police vehicles sit at red signals while the officer at the junction has no idea they are coming. Full signal preemption needs integration with city controllers, which is years away. What can ship today is the missing link: warn the right cop early enough, sized to the queue that is actually there and the way the vehicle turns, and sequence several vehicles fairly.

## What it does in 60 seconds

A crew binds a registered vehicle, starts a run against a dispatched incident, speaks the patient's condition, and taps once to confirm the tier. From then on the vehicle's GPS drives everything else. Six React PWA screens, all live from one Firestore event bus:

| Screen | For | Shows |
|---|---|---|
| `/vehicle` | ambulance or fire crew | voice or monitor-photo triage, tier confirm, transit log, routed hospital and agent trace |
| `/cop` | officer at a junction | on-duty toggle, spoken two-stage alert, giant ACK button |
| `/hospital` | receiving hospital | live transit log, ATMIST brief, prep checklist, arrival countdown |
| `/control` | control room | all runs, junction board with ACK states, escalations, report cards |
| `/sim` | everyone | corridor digital twin; live feeder, or a with-vs-without replay that counts minutes saved |
| `/dispatch` | dispatcher | issues incident IDs |

Pick a corridor with `?corridor=blr` or `?corridor=hyd`; a corridor is one JSON file in `data/corridors/`.

The replay on the current scenario (`blr-two-vehicles`: a critical ambulance, a platoon ambulance behind it, and a fire engine) saves 738.8 s, about 12.3 minutes across the three vehicles. That is a simulated baseline on recorded traffic, not a field measurement.

## How a cop gets warned

Live Routes traffic spans give the queue at each junction approach. The lead-time engine (`api/leadtime.py`, mirrored in `web/src/replay.js`) turns it into a time budget:

```
jam_m   = Σ JAM m + 0.5 × Σ SLOW m          (walking back from the stop line to the first NORMAL span)
clear_s = 20 + jam_m / 2.0                  (reaction time + queue drain at 2 m/s)
eta_s   = 0.5 × routes_eta + 0.5 × distance / speed_60s    (speed floored at 3 m/s)
PREPARE            when eta_s <= clear_s + 15
STOP CROSS TRAFFIC when eta_s <= 30
```

A 500 m queue alerts earlier than a 100 m queue, so nobody is called out sooner than they need to be. Each stage fires once per junction per run. The alert is a short conversational line (English by default, colloquial Kannada or Telugu by configuration), spoken on the cop's phone with Text-to-Speech so the officer hears it, not just reads it. The cop taps ACK; if nobody acknowledges within 20 s the alert is flagged as an escalation on the control room board and written to the audit log.

## Rules decide, Gemini explains

Nothing a language model says sets a tier or a signal.

1. **Acuity.** Gemini extracts fields (complaint, vitals) into a fixed schema. `api/acuity.py` maps them to critical, urgent or stable with a deterministic lookup, and the crew confirms with one tap. Preemption needs a confirmed tier.
2. **Sequencing.** `api/priority.py` orders vehicles by (tier, ETA). It is a sequence, not a hold: fire first, ambulance a fixed 12 s later, and everyone passes.
3. **Platoon.** Vehicles on the same approach arriving within 45 s of a leader share the leader's green slot instead of queuing for their own.
4. **Explanation.** Gemini then writes one line in the cop's language ("Fire engine first, ambulance 12 s later") and stores it on the junction phase. It never reorders anything.

`acuity.py`, `priority.py`, `leadtime.py` and `report.py` carry assert-based self-checks and are exercised in CI.

## Where Gemini is used

All calls go through Vertex AI (`google-genai`, global endpoint). Each has a template or rule-based fallback, and values extracted from speech or photos are transcription support that a clinician confirms.

- **Extraction.** Speech (any Indian language) or typed text to a fixed JSON schema, with no tools and no free-form output. The same path serves triage and transit-log notes.
- **Photo to vitals.** A photo of a monitor or ECG is read with the same schema; unreadable values stay null.
- **ATMIST brief.** A hospital handover brief with prep checklist, generated at ETA minus 5 minutes.
- **Rationale.** The one-line sequencing explanation above, and the wording of the spoken alert.
- **Routing agent.** An agent built on Agent Development Kit picks the destination hospital with three tools: `required_capabilities`, `list_hospitals` (a mock capability and bed roster) and `eta_to` (traffic-aware Routes ETA). The tool trace is shown on `/vehicle`. The server re-checks the choice and falls back to the nearest eligible hospital on any failure or 20 s timeout. The agent never changes acuity or signal priority.

## Architecture

![Architecture](deck/img/architecture.svg)

Google products actually wired:

- **Vertex AI, Gemini:** extraction, photo vitals, briefs, rationale.
- **Agent Development Kit:** hospital routing agent.
- **Cloud Run:** `corridor-api` (FastAPI) and the traffic logger job.
- **Firestore:** event bus and store; every screen subscribes.
- **Firebase Hosting:** the React PWA.
- **Routes API and Maps JavaScript:** traffic spans, ETAs, map.
- **Cloud Text-to-Speech, Cloud Translation, Cloud Storage:** spoken alerts and their MP3s.
- **Secret Manager:** Maps server key.
- **Cloud Scheduler, Cloud Build, Artifact Registry:** traffic logger schedule and image.
- **BigQuery and BigQuery ML:** traffic spans, run reports, jam forecast.
- **Workload Identity Federation:** keyless CI deploys.

Signal preemption sits behind a one-method `SignalAdapter` (`api/signal_adapter.py`). Today `SimAdapter` writes the junction phase to Firestore; a real controller implements the same method.

## Real data

A Cloud Run Job (`jobs/traffic_logger.py`), triggered by Cloud Scheduler during peak hours, logs Routes traffic spans per junction approach into BigQuery `corridor.traffic_spans`, using the same `jam_metres` as the live engine. [jobs/bqml](jobs/bqml) builds a feature view and a BigQuery ML boosted-tree model, `corridor.jam_forecast`, for the next reading's jam length. Every run also writes its report card to `corridor.run_reports`.

Be clear about what that is today: the sample so far is short (about 50 minutes) and was free-flowing, so the label has no variance and the model has learned nothing useful. It is a proof that the collection, features and training run end to end, and it will only say something after the logger has seen weeks of real congestion. See [jobs/bqml/README.md](jobs/bqml/README.md) for the numbers and limits.

## Honest limits

- **Signals are simulated** behind `SignalAdapter`. Cop alerts are deployable today; real signal data is phase 2.
- **Patients are synthetic** and the hospital roster is invented demo data. A clinician confirms every extracted value.
- **Demo-only auth.** Identity is a mock plate registry that visibly rejects unknown plates. Demo endpoints are publicly writable so judges can open every screen.
- **Minutes saved is a simulation** on recorded traffic, not a field measurement. Corridor coordinates are approximate.
- **Scenario mode.** `/sim` replay and the feeder play recorded GPS and traffic from `data/scenarios/`; the live feeder drives the real API with that recorded trace, not real vehicles.

## Run locally

Prerequisites: Python 3.12, Node 20+ (22 in CI), and a Google Cloud project with Firestore. Keep any service-account key outside this repo.

```
# API, with no paid Gemini, Translation or TTS calls (Firestore is still used; see SCHEMA.md)
cd api && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=<path to a key outside this repo>
OFFLINE_AI=1 uvicorn main:app --reload --port 8080

# Web dev server
cd web && cp .env.example .env.local   # set VITE_FIREBASE_CONFIG; VITE_API_BASE=http://127.0.0.1:8080 for your local API
npm install && npm run dev

# Scenario replay against the local offline API (asserts sequencing, alerts, escalation)
cd api && python3 offline_replay.py http://127.0.0.1:8080
# Or open /sim?mode=replay&scenario=blr-two-vehicles in the web app: client-side only, no backend needed.

# Seed or reset demo data (reset is a dry run without --apply)
python3 scripts/demo_seed.py
python3 scripts/demo_reset.py --apply
```

For repository workflow and contribution conventions, see CONTRIBUTING.md.

## Testing

- **API:** pytest against a fake Firestore, so tests need no credentials and make no cloud calls; the engines also self-check with `python3 api/acuity.py` and friends.
- **Web:** vitest unit tests, including the replay maths and the recorded minutes-saved total on the current scenario; ESLint and Prettier checks.
- **Gate:** CI runs lint, format, tests and the production build, and enforces a minimum coverage threshold on the API. Run the same commands locally before opening a PR.

## Deploy

Pushing to `main` runs `checks`, then the path-filtered workflows deploy: `api/` to Cloud Run, `web/` to Firebase Hosting, and `jobs/` (build image, update the Cloud Run Job, run it once to verify). All authenticate to Google Cloud with Workload Identity Federation, so no keys are stored in GitHub. `main` is branch-protected: changes land through pull requests with `checks` passing. Firestore rules are deployed manually with `firebase deploy --only firestore:rules`.

Runtime configuration (set by the workflows): project `green-corridor-2026`, service `corridor-api` in `asia-south1`, Gemini on the `global` location, and these variables.

| Env var | Purpose |
|---|---|
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | extraction from text, audio and photos, and its fallback |
| `GEMINI_TEXT_MODEL` | hospital brief and sequence rationale |
| `GEMINI_LOCATION`, `GCP_PROJECT` | Vertex AI location and project |
| `MAPS_SERVER_KEY` | from Secret Manager `corridor-maps-server-key` |
| `MEDIA_BUCKET` | spoken-alert MP3s |
| `ALERT_LANG` | `en` (default), `kn`, `te`, or `corridor` for the corridor's own language |

## Evaluation

`scripts/eval_run.py` posts recorded EMT clips to `/triage` and scores per-field and tier accuracy against `data/eval/labels.json`. Preview with `python3 scripts/eval_run.py --dry-run`. The scripted scenarios and filenames (`clip01.m4a` to `clip10.m4a`) are in [data/eval/README.md](data/eval/README.md); results are written to `data/eval/results.json`.

## Repository layout

```
api/        FastAPI app; acuity.py, priority.py, leadtime.py, signal_adapter.py; agent.py + hospitals.py (routing agent)
web/        Vite React PWA, six routes, replay maths, vitest tests
jobs/       traffic_logger.py (Cloud Run Job) and bqml/ (BigQuery ML jam forecast)
data/       corridors/{blr,hyd}.json, scenarios/*.json, eval/ clips and labels
scripts/    demo_seed.py, demo_reset.py, eval_run.py, make_scenario.py
deck/       Marp slides, video plan and voiceover, architecture diagram
.github/    checks and deploy workflows
```

## Roadmap

1. **Real signal adapter.** A controller implementation of `SignalAdapter`, starting with one pilot junction.
2. **Learning controller.** Replace the constant 2 m/s clearance rate with a model trained on logged junction data and run report cards.
3. **Agency rosters.** Replace the mock plate registry and hospital roster with real agency and bed data, with real authentication.
