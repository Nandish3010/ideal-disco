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

The replay on the current scenario (`blr-two-vehicles`: a critical ambulance, a platoon ambulance behind it, and a fire engine) saves ≈ 16.5 min <!-- update from replay test --> across the three vehicles. The scenario is a scripted demo scenario: GPS ticks generated along the real corridor roads, with hand-authored traffic spans (a 500 m queue at junction 3, 100 m at junction 4). The saving is one simulated baseline, not a field measurement: per junction passed, the "Today" lane waits `cycle_s / 4 + queue_m / 2` seconds (the expected remaining red, a quarter of the cycle, plus the queue draining at 2 m/s). The replay and the run report cards use the same formula.

## How a cop gets warned

Live runs use live Routes traffic spans for the queue at each junction approach; scenario runs use the scripted spans from `data/scenarios/`. The lead-time engine (`api/leadtime.py`, mirrored in `web/src/replay.js`) turns it into a time budget:

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
4. **Explanation.** The rules build a template sentence ("Fire engine first, ambulance 12 s later"); Gemini may reword it in the cop's language, the result is validated, and the template is used if it fails. The sentence is stored on the junction phase and never reorders anything.

`acuity.py`, `priority.py`, `leadtime.py` and `report.py` carry assert-based self-checks and are exercised in CI.

## Where Gemini is used

All calls go through Vertex AI (`google-genai`, global endpoint). Each has a template or rule-based fallback, and values extracted from speech or photos are transcription support that a clinician confirms. Extraction runs on `gemini-3.1-flash-lite` with `gemini-3-flash-preview` as the fallback; the brief, the report, the sequencing sentence and the agent text use `gemini-3-flash-preview`.

- **Voice and photo extraction:** speech, typed text or a monitor photo into a fixed schema, with no tools.
- **ATMIST handover:** the hospital brief and prep checklist, generated at ETA minus 5 minutes.
- **Alert phrasing:** the short spoken line each junction cop hears.
- **Sequencing sentence:** Gemini rewords a rule-built template into one line; the result is validated and the template is used if it fails.
- **Cop voice notes to rule actions:** a spoken report from the junction fills a fixed schema, and plain rules act on it.
- **After-action report:** a plain summary of each finished run, with the timeline built in code.
- **Hospital routing agent:** built on Agent Development Kit, with four tools and a code guard that checks its choice before it is applied.

The routing agent picks the destination hospital with four tools: `list_hospitals` (a mock capability and bed roster), `eta_to` (traffic-aware Routes ETA), `check_diversion` (a mock diversion feed), and `required_capabilities`, which is a keyword-table baseline used for validation, not an answer. It returns the chosen hospital with up to two rejected alternatives and a confidence. A code guard re-checks the choice (known hospital, no diversion, a bed, every required capability, no critical baseline capability dropped) and falls back to the nearest eligible hospital on any failure or 20 s timeout. The tool trace, including any guard that tripped, is shown on `/vehicle`; the alternatives and confidence come back in the `/route` response. The agent never changes acuity or signal priority.

## Architecture

![Architecture](deck/img/architecture.svg)

Google products actually wired:

- **Vertex AI, Gemini:** extraction, ATMIST brief, alert and sequencing wording, cop voice notes, after-action report.
- **Agent Development Kit:** hospital routing agent.
- **Cloud Run:** `corridor-api` (FastAPI) and the traffic logger job.
- **Firestore:** event bus and store; every screen subscribes.
- **Firebase Hosting:** the React PWA.
- **Routes API and Maps JavaScript:** traffic spans, ETAs, map.
- **Cloud Text-to-Speech, Cloud Translation, Cloud Storage:** spoken alerts and their MP3s.
- **Secret Manager:** Maps server key.
- **Cloud Scheduler, Cloud Build, Artifact Registry:** traffic logger schedule and image.
- **BigQuery:** traffic spans and run reports. **BigQuery ML:** a jam-forecast pipeline is in place and is retrained before submission; it is a pipeline proof, not a deployed forecast (see Real data).
- **Workload Identity Federation:** keyless CI deploys.

Signal preemption sits behind a one-method `SignalAdapter` (`api/signal_adapter.py`). Today `SimAdapter` writes the junction phase to Firestore; a real controller implements the same method.

## Real data

A Cloud Run Job (`jobs/traffic_logger.py`), triggered by Cloud Scheduler during peak hours, logs Routes traffic spans per junction approach into BigQuery `corridor.traffic_spans`, using the same `jam_metres` as the live engine. [jobs/bqml](jobs/bqml) builds a feature view and a BigQuery ML boosted-tree model, `corridor.jam_forecast`, for the next reading's jam length. Every run also writes its report card to `corridor.run_reports`.

Be clear about what that is today: the logger has run on Cloud Scheduler for Bengaluru peak hours since 6 Oct, with N rows so far [fill at freeze]. The first 216 rows were logged at midnight with zero queues, so the label had no variance and the model learned nothing useful. The BigQuery ML model is a pipeline proof until peak-hour rows accumulate; it is retrained before submission and is not a deployed forecast. It will only say something after the logger has seen weeks of real congestion. See [jobs/bqml/README.md](jobs/bqml/README.md) for the numbers and limits.

## Honest limits

Traffic signals are simulated behind an adapter; the demo scenario uses hand-authored traffic spans; patients are synthetic; no user accounts; device-scoped tokens protect vehicle, cop and run actions; demo endpoints are rate-limited but reachable.

- Cop alerts are deployable today; real signal data is phase 2.
- The hospital roster is invented demo data, and a clinician confirms every extracted value. Identity is a mock plate registry that visibly rejects unknown plates.
- Minutes saved is a simulation, not a field measurement. Corridor coordinates are approximate.
- **Scenario mode.** `/sim` replay and the feeder play the scripted scenario from `data/scenarios/` (generated GPS ticks, hand-authored spans); the feeder drives the real API with that trace, not real vehicles. Live runs use live Routes traffic.

## Security posture for the demo

Firestore is public read, and every write goes through the API's service account. There are no user accounts. A device that binds a vehicle or goes on duty at a junction receives a random token, and calls that change a run or a junction (start and end run, triage, log, location, confirm, ACK, go off duty, cop notes) must send it in `X-Device-Token`; only its hash is stored (see SCHEMA.md, Device tokens). This is a demo-grade control, not authentication: binding a registered plate or going on duty stands in for an agency registry and a roster, and both are open. Everything else stays reachable so judges can open every screen, protected by per-IP rate limits (10 Gemini, Routes or agent calls a minute, 60 general) and a per-run cap of 20 triage and log calls.

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
- **Web:** vitest unit tests, including the replay maths and the scenario minutes-saved total; ESLint and Prettier checks.
- **Gate:** CI runs lint, format, tests and the production build, and enforces a minimum coverage threshold on the API. Run the same commands locally before opening a PR.

## Deploy

Every push to main runs the checks workflow; the deploy workflows run only after checks succeed and only for the paths that changed (`api/` to Cloud Run, `web/` to Firebase Hosting, and `jobs/`: build image, update the Cloud Run Job, run it once to verify). Branch protection also requires checks before merge. All authenticate to Google Cloud with Workload Identity Federation, so no keys are stored in GitHub. Firestore rules are deployed manually with `firebase deploy --only firestore:rules`.

Runtime configuration (set by the workflows): project `green-corridor-2026`, service `corridor-api` in `asia-south1`, Gemini on the `global` location, and these variables.

| Env var | Purpose |
|---|---|
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | extraction from text, audio and photos (`gemini-3.1-flash-lite`), and its fallback (`gemini-3-flash-preview`) |
| `GEMINI_TEXT_MODEL` | hospital brief, sequencing sentence, after-action report and agent text (`gemini-3-flash-preview`) |
| `GEMINI_LOCATION`, `GCP_PROJECT` | Vertex AI location and project |
| `MAPS_SERVER_KEY` | from Secret Manager `corridor-maps-server-key` |
| `MEDIA_BUCKET` | spoken-alert MP3s |
| `ALERT_LANG` | `en` (default), `kn`, `te`, or `corridor` for the corridor's own language |

## Evaluation

`scripts/eval_run.py` posts voice clips to `/triage` (intervention notes to `/log`) and scores each against `data/eval/labels.json`: exact match per field (strings case-insensitive, vitals within ±5, trapped persons not stated counts as none) and the suggested tier against the expected one. A clip that fails extraction (422) counts as wrong. Preview with `python3 scripts/eval_run.py --dry-run`.

**These numbers are from synthetic voices (Cloud Text-to-Speech), 12 clips, 6 Oct 2026, one pass against the deployed API. They are not field recordings.** Field accuracy is 87% (67 of 77 field checks over the 11 triage clips), tier accuracy 73% (8 of 11), and the intervention note logged both drugs correctly. Mean latency was 2.9 s per clip (max 3.2 s), including the two Kannada-English mixed clips, which scored the same as their English twins on tier.

| Clip | Description | Endpoint | Expected Tier | Suggested Tier | Tier Match | Field Accuracy | Latency |
|------|-------------|----------|---------------|----------------|------------|----------------|---------|
| clip01 | Chest pain with hypotensive vitals | /triage | critical | critical | ✓ | 100% | 2.9 s |
| clip01-kn | Chest pain with hypotensive vitals (Kannada-English mixed) | /triage | critical | critical | ✓ | 100% | 3.2 s |
| clip02 | Unconscious patient | /triage | critical | critical | ✓ | 86% | 2.8 s |
| clip03 | Stroke with classic signs | /triage | critical | stable | ✗ | 86% | 2.8 s |
| clip04 | Pediatric fracture | /triage | urgent | urgent | ✓ | 86% | 2.9 s |
| clip05 | Respiratory distress with low SpO2 | /triage | critical | critical | ✓ | 100% | 2.8 s |
| clip05-kn | Respiratory distress with low SpO2 (Kannada-English mixed) | /triage | critical | critical | ✓ | 86% | 2.8 s |
| clip06 | Significant burn injury | /triage | critical | stable | ✗ | 86% | 2.8 s |
| clip07 | Controlled moderate bleeding | /triage | urgent | stable | ✗ | 86% | 2.8 s |
| clip08 | Minor injury with normal vitals | /triage | stable | stable | ✓ | 57% | 2.9 s |
| clip09 | Fire dispatch with trapped person | /triage | fire_with_trapped | fire_with_trapped | ✓ | 86% | 2.8 s |
| clip10 | Intervention log entry (for /log endpoint, not /triage) | /log | - | - | - | interventions ✓ | 2.8 s |

| Field | Accuracy |
|-------|----------|
| age | 100% |
| sex | 100% |
| complaint | 36% |
| conscious | 91% |
| breathing | 82% |
| vitals | 100% |
| trapped_persons | 100% |

The tier misses (clip03 stroke, clip06 burns, clip07 bleeding) are extraction wording, not transcription: Gemini returns the complaint as spoken ("facial drooping on left, right arm weakness"), the lookup in `api/acuity.py` matches fixed complaint phrases, so those cases fall through to `stable`. Complaint is a free-text field, so exact match (36%) is the harshest line in the table.

To replace these with real clips, record 10 clips as described in [data/eval/README.md](data/eval/README.md), save them next to a `labels.json`, and run `python3 scripts/eval_run.py --clips <dir> --labels <dir>/labels.json`. The synthetic set is regenerated with `scripts/make_eval_clips.py` (12 Text-to-Speech calls) and lives in [data/eval/synthetic](data/eval/synthetic/) with its per-clip voices and rates; raw responses are in `results.json` there, and `--rescore` re-scores them without calling the API.

**Crew agreement.** `python3 scripts/eval_run.py --agreement` reads Firestore `runs` (public REST, free) and reports the suggested tier against the crew's confirmed tier over runs that have both. On 6 Oct 2026 it was 19 of 19 (100%); those are demo and rehearsal runs, so it shows the crew confirmed the suggestion in every rehearsal run, not clinical agreement.

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
3. **Agency identity and rosters.** Replace the open bind and duty calls (which hand out device tokens), the mock plate registry and the hospital roster with real agency identity and bed data.
