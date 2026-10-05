---
marp: true
theme: default
paginate: true
style: |
  section { font-size: 26px; }
  section h1 { color: #0b6b3a; }
  section h2 { color: #0b6b3a; }
  pre { font-size: 14px; line-height: 1.25; }
  table { font-size: 20px; }
  .ph { color: #b45309; }
---

<!-- Draft. Items in [brackets] are placeholders to fill before export. -->

# Emergency Green Corridor

## Every red light costs a life.

Google Cloud AI Builder Cup 2026 · Sustainability & Social Impact

Team: Nandish · [second team member, or delete this line]

<!--
Emergency Green Corridor tells the cop at the next junction, early enough and with real numbers, that an ambulance, fire engine or police vehicle is coming. Gemini does the language work, deterministic rules do the safety-critical decisions. Everything in this deck is running at green-corridor-2026.web.app.
-->

---

## The problem, seen daily on Hosur Road

- Ambulances and fire engines sit at red signals in a queue they cannot clear.
- The officer at the junction has no idea they are coming.
- Nobody is told, nothing adapts, and the delay is paid in lives or property.
- In cardiac arrest, survival falls by [X% per minute without defibrillation, cite source].
- Bengaluru emergency response times: [median / 90th percentile, cite source].
- Full signal preemption needs city controller integration: years away.

<!--
Every Bengaluru commuter has seen this on Hosur Road. The missing piece is not a siren, it is information reaching the one person who can clear the queue. Fill the bracketed numbers from cited sources (resuscitation literature, city or 108 response-time data) before export.
-->

---

## The 20-second demo

**Today** (stops at every red) vs **With corridor** (cop warned early, queue cleared), side by side on the Silk Board → Jayadeva Hospital corridor.

- 3 vehicles: critical ambulance, fire engine with trapped persons, urgent ambulance.
- Counter on screen: **11.8 minutes saved** across the three.
- Same recorded GPS trace and the same recorded traffic in both lanes.
- State plainly: a **simulated baseline on recorded traffic, not a field measurement**.

<!--
The /sim screen replays the same trace twice. On the left the vehicle stops at each junction for the remaining red of a fixed signal cycle, on the right the corridor is cleared and only sequencing gaps remain. The number is an estimate from a simulation, and the slide says so.
-->

---

## What it does: six screens

- **/vehicle** crew binds a plate, speaks in any Indian language, confirms the tier with one tap, sees the routed hospital.
- **/dispatch** issues incident IDs (mock dispatch console).
- **/cop** on-duty toggle for a junction, spoken alerts, one giant ACK.
- **/hospital** live transit log, English ATMIST brief and prep checklist, countdown.
- **/control** all runs, junction ACK states, escalation flags.
- **/sim** corridor digital twin, with-vs-without replay, minutes-saved counter.

<!--
Six React PWA routes, one Firestore event bus, every screen subscribes live. Unknown plates are rejected visibly, and preemption needs a registered plate plus an open incident. Corridor is chosen by ?corridor=blr or ?corridor=hyd.
-->

---

## How a cop gets warned: the lead-time engine

Live Routes traffic spans → queue metres → clearance time → two-stage alert

```
jam_m   = Σ TRAFFIC_JAM metres + 0.5 × Σ SLOW metres      (walk back from stop line to first NORMAL)
clear_s = reaction_s (20) + jam_m / clearance_rate_mps (2.0)
eta_s   = 0.5 × routes_eta + 0.5 × distance / observed_speed_60s   (floor 3 m/s)
PREPARE            when eta_s <= clear_s + 15
STOP CROSS TRAFFIC when eta_s <= 30
```

- Spoken in conversational English; Kannada / Telugu switchable (Gemini rewrite, Cloud Translation, Text-to-Speech).
- Cop taps ACK; no ACK in 20 s raises an escalation flag in the control room and an audit entry.

<!--
A 500 m queue alerts earlier than a 100 m queue, because the cop needs the time to clear exactly what is there. The constants (2.0 m/s clearance, 50/50 ETA blend) are deliberately simple and tunable. Each stage fires once per junction per run.
-->

---

## Rules decide, Gemini explains

- Gemini extracts fields from speech. It never returns a score.
- `acuity.py`: a deterministic lookup (SBP < 90, SpO2 < 90, unconscious, chest pain, trapped persons ...) → critical / urgent / stable. The crew confirms with one tap; only the confirmed tier enters priority.
- `priority.py`: sort by (tier rank, ETA). Output is a **sequence, not a hold**: "Fire engine first, ambulance 12 s later." Everyone passes.
- Gemini only writes the one-line rationale of the order, in the cop's language.
- Why it matters: a language model must not decide who lives; rules are auditable, testable and have self-checks.

<!--
Hallucination risk is removed from the safety path by construction. The model sits before the rules (extraction) and after them (explanation), never inside them. acuity.py, priority.py and leadtime.py each ship with assert-based self-checks.
-->

---

## Where Gemini is load-bearing

| Job | Mode | Example |
|---|---|---|
| Voice extraction | audio in, fixed JSON schema, no tool calling | "chest pain, BP 85 over 50" → `{complaint, vitals.sbp: 85}` → lookup says critical [sample] |
| Transit log | voice note → interventions | "Oxygen 4 litres started" → `{drug, oxygen, 4 litres}`, shown beside transcript |
| Hospital brief | ATMIST + prep checklist | "Activate cath lab · Page cardiology · Prepare heparin" |
| Sequence rationale | one line, cop's language | "Fire engine first, ambulance 12 s later" |
| Alert wording | spoken line per language | "Ambulance coming, critical case. 520 metre queue..." |
| Monitor photo → vitals | vision, same schema | [sample; include only if shipped before export] |

Synthetic patients only. Clinician confirms every extracted value.

<!--
Each use changes what a human sees or hears next, and each has a form or template fallback if the model fails. Examples are the contract examples in SCHEMA.md and are marked [sample] where not captured from a live run. Remove the photo row if that feature is not on main at export time.
-->

---

## The agent: hospital routing on Agent Development Kit

An ADK agent on Vertex AI picks the destination after the crew confirms the tier. Three tools:

- `required_capabilities(tier, fields)` → e.g. cath_lab
- `list_hospitals(corridor)` → mock capability and bed roster
- `eta_to(...)` → traffic-aware Routes ETA

```
called required_capabilities(critical) -> cath_lab
called list_hospitals(blr) -> 3 hospitals
called eta_to(Jayadeva Institute of Cardiovascular Sciences) -> 438 s
```

- Trace is shown in the UI. The server re-checks the choice (capability, beds, ETA from the tool).
- Any failure or 20 s timeout → nearest eligible hospital, trace marked fallback.

<!--
The trace above is the contract example from SCHEMA.md; replace with a captured run if you have one. The agent never changes acuity or signal priority. The roster is invented demo data and the slide says so.
-->

---

## Architecture

```
 vehicle PWA ──GPS/voice──▶ Cloud Run corridor-api ──▶ Vertex AI Gemini (global) · ADK agent
 sim feeder  ──GPS───────▶   │ /location: Routes (throttled) → leadtime → priority
                             │        └─▶ >>> SignalAdapter.request_green <<<
                             │                 └─▶ SimAdapter → Firestore junctions/
                             ▼
                        Firestore (event bus) ──▶ cop (TTS audio) · hospital · control · sim
 Cloud Scheduler ─▶ Cloud Run Job ──Routes spans──▶ BigQuery corridor.traffic_spans
```

Routes API · Maps JavaScript API (map) · Cloud Storage (alert audio) · Secret Manager (keys) · Cloud Translation + Text-to-Speech (alerts) · Firebase Hosting (PWA) · Cloud Build + Artifact Registry (deploy) · Cloud Logging (run_id on every line).
**Day 9, not yet on main:** BigQuery ML, Gen AI Evaluation. [update at freeze]

<!--
The SignalAdapter seam is the point: today SimAdapter writes the junction phase to Firestore, tomorrow a real controller adapter implements the same one method. Firestore is the single event bus and the accepted single point of failure for the demo. Only products wired on main are shown.
-->

---

## Real data: the traffic logger

**Built**
- Cloud Scheduler triggers a Cloud Run Job every 10 minutes.
- Records live Bengaluru jam and slow spans per junction approach into BigQuery `corridor.traffic_spans`, for two corridors (Bengaluru, Hyderabad).
- The same `jam_metres` function the live engine uses, so logged and live data agree.

**Roadmap (day 9, not built yet)**
- BigQuery ML forecast of queue length by junction and hour.
- First step toward a learning controller; clearance rate stays a constant until observed clearance times exist.

<!--
Be explicit that the forecast is not built yet at the time of writing. What exists is the data collection that makes it possible. Update this slide if BQML lands before export.
-->

---

## Sustainability

Every cleared queue is fuel not burned at idle.

```
fuel_saved_L = queue_vehicles × idle_burn_L_per_s × seconds_saved
CO₂_kg       = fuel_saved_L × [emission factor kg CO₂/L]
```

- Per cleared queue: [N] litres of fuel, [N] kg CO₂ avoided (illustrative, from the demo corridor).
- Idle burn rate: [L/h per vehicle, cite fuel-economy / idling study]. Emission factor: [cite, e.g. national grid or IPCC factor].
- **SDG 3.6** halve road traffic deaths and injuries. **SDG 11.2** sustainable transport systems.

<!--
The queue length comes from the same Routes spans the engine already reads, so the estimate costs nothing extra. All numbers are placeholders until sourced; cite the idle burn rate and emission factor on the slide.
-->

---

## Deployment path, and honesty

- **Today:** cop alerts, no hardware. Deployable on a phone.
- **Phase 2:** a real signal controller behind `SignalAdapter`.
- **Phase 3:** a learning controller trained on the junction data layer.

What is simulated or limited, stated plainly:
- Signals are simulated. Patients are synthetic. Hospital roster is mock.
- No auth in the demo: endpoints are publicly writable, identity is a mock plate registry.
- Minutes saved is a simulated estimate, not a field measurement.

<!--
We would rather be believed on a smaller claim. Cop alerts are the part that needs no city integration. The auth gap is a documented demo decision, so judges can open every screen.
-->

---

## Global by configuration

- A corridor is one JSON file: junctions, approaches, signal cycle, language.
- Bengaluru (`blr`, Silk Board → Jayadeva) and Hyderabad (`hyd`) are shipped. Switch with one click.
- Any city with adaptive signals, or none: cop alerts work anywhere Routes reports traffic.
- Alert language is a setting: English, Kannada, Telugu today.

<!--
Adding a city is a config change plus a hospital roster, no code. The Hyderabad corridor proves the schema is not Bengaluru-shaped.
-->

---

## Try it

- Live app: https://green-corridor-2026.web.app
- API: https://corridor-api-919512130399.asia-south1.run.app/health
- Repo: https://github.com/Nandish3010/ideal-disco
- Demo video: [link, 3 minutes]

**Ask:** feedback from traffic police and 108 operators, and a pilot junction.

<!--
Close on the one-line pitch: every red light costs a life, and the first fix does not need to wait for the signal controller. Fill in the video link before export.
-->
