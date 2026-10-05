# Contracts

Firestore **(default)** database in project `green-corridor-2026`. Timestamps are Firestore Timestamps, shown here as ISO 8601.
Clients read; only the Cloud Run service account writes. Every server log line carries `run_id` and `junction_id`.

## Firestore collections

### `vehicles/{plate}`
```json
{ "type": "ambulance", "agency": "108 Karnataka", "active": true, "bound_device_id": "dev-1" }
```
`bound_device_id` is set by `/vehicles/bind`. `type`: `ambulance | fire | police`.

### `incidents/{id}`
```json
{ "type": "cardiac", "severity_note": "Synthetic demo incident", "created_at": "2026-10-05T09:00:00Z", "state": "open" }
```

### `runs/{id}`
```json
{
  "vehicle_plate": "KA01AB1234", "vehicle_type": "ambulance", "incident_id": "INC-0001",
  "state": "en_route", "patient_on_board": false,
  "acuity_tier": "critical", "confirmed_tier": "critical",
  "destination": {"name": "Jayadeva Institute of Cardiovascular Sciences", "lat": 12.9185, "lng": 77.599},
  "source": "gps", "last_tick_at": "2026-10-05T09:03:10Z", "eta_hospital_s": 412,
  "brief_fired": false, "corridor": "blr"
}
```
`routing` (written by the hospital routing agent, below) is optional until the tier is confirmed.
`state`: `en_route | arrived | ended | stale | off_route` (`ended_reason: "superseded"` when a newer run for the same plate replaced it). `/location` sets `arrived` (and writes the report card) when a tick is within 100 m of the destination; `/runs` end sets `ended`. `source`: `gps | sim`. `acuity_tier` is the lookup result written by `/triage`, `confirmed_tier` the crew's tap written by `/runs/{id}/confirm` (which also sets `patient_on_board: true`); only `confirmed_tier` enters priority.

Written by `/location` on every tick:
```json
{
  "ticks": [{"t": "2026-10-05T09:03:10Z", "lat": 12.9197, "lng": 77.6204, "speed_mps": 13.2}],
  "last_tick_at": "2026-10-05T09:03:10Z", "heading": 231, "source": "sim", "state": "en_route",
  "eta_hospital_s": 412, "brief_due": false,
  "next_junction_id": "blr_j3", "next_approach": "NE", "next_eta_s": 143,
  "ahead_ids": ["blr_j3", "blr_j4"], "ahead": {"blr_j3": {"eta_s": 143, "approach": "NE"}, "blr_j4": {"eta_s": 215, "approach": "E"}},
  "last_eval": {"next_junction": "blr_j3", "approach": "NE", "jam_m": 520, "eta_s": 143, "stage": "PREPARE", "exit_move": "left", "traffic": "live"},
  "alert_state": {"blr_j3": {"prepare": true, "stop": false, "jam_m": 520}}, "alert_count": 1, "distance_m": 2310,
  "first_tick_at": "2026-10-05T09:00:05Z", "passed_junctions": ["blr_j1", "blr_j2"]
}
```
`distance_m` is the running sum of distance between ticks. `first_tick_at` is the client time (`t`) of the run's first `/location` tick, set once; the report card measures the drive from it, not from `started_at`. `passed_junctions` lists the corridor junctions the vehicle has driven through, in corridor order (always a prefix of the corridor's junction list: passing one passes every earlier one); a junction counts as passed once a tick-to-tick step crossed its stop-line circle (`radius_m`) and the vehicle is outside it again. Passed junctions are never evaluated, alerted or reported as `next_junction` again, so `next_junction` only moves forward. `ticks` keeps the last 12 (at most one per 5 s, so they span about a minute; `t` is the client's tick time). `last_tick_at` is server time and drives the stale check. `ahead` / `ahead_ids` list every junction still ahead (nearest first in `next_*`); other runs read them to find contenders. `last_eval.traffic`: `live | stale | scenario`; `stale` means Routes failed and no spans under 60 s old were left, so the queue was treated as NORMAL (control room shows "traffic data stale"). `brief_due` is set for ambulance runs only (fire and police never get a brief), once `eta_hospital_s <= 300`, `brief_fired` is false, the run has at least one log entry and it is under way: at least one junction passed or `distance_m >= 500` (a scenario run's first tick never qualifies; with no log yet the check repeats on later ticks). The same tick then generates the brief inline (about 5-10 s) exactly once, writes `briefs/{run_id}`, sets `brief_fired: true` and clears `brief_due`. If Gemini fails the tick logs `brief_error` and leaves `brief_due: true` with `brief_fired: false`, so the hospital's Regenerate button (`POST /brief`) is the retry; nothing else retries. Optional `scenario: "<name>"` (set by the scenario runner, not by `/runs`) makes `/location` read `recorded_spans` from `data/scenarios/<name>.json` instead of calling Routes, and follow the corridor config instead of the Routes polyline (no off-route check). A scenario run keeps its destination: `eta_hospital_s` and arrival use the run's own `destination` (else the corridor hospital) whatever the routing agent picks.

`routing` (written by `/runs/{id}/confirm` and `/route`; ambulance runs only):
```json
{
  "destination": "Jayadeva Institute of Cardiovascular Sciences", "hospital_id": "blr_jayadeva", "eta_s": 438,
  "reasons": ["The hospital provides the required cath_lab capability and has 4 beds available.", "It is the closest eligible facility with an ETA of 438 seconds."],
  "trace": [
    {"tool": "required_capabilities", "args": {"confirmed_tier": "critical", "fields": {"complaint": "chest pain"}}, "result": "cath_lab", "text": "called required_capabilities(critical) -> cath_lab"},
    {"tool": "list_hospitals", "args": {"corridor": "blr"}, "result": "3 hospitals: blr_jayadeva, blr_apollo_bg, blr_fortis_bg", "text": "called list_hospitals(blr) -> 3 hospitals: ..."},
    {"tool": "eta_to", "args": {"lat": 12.9172, "lng": 77.6229, "dest_lat": 12.9185, "dest_lng": 77.599}, "result": "438 s", "text": "called eta_to(Jayadeva Institute of Cardiovascular Sciences) -> 438 s"}
  ],
  "decided_at": "2026-10-05T09:02:40Z", "applied": true
}
```
The routing agent (`api/agent.py`, Google ADK `LlmAgent` `hospital_router` on Vertex AI, tools `list_hospitals`, `eta_to`, `required_capabilities`) picks the hospital that has every required capability and a free bed with the lowest traffic-aware ETA, from the mock roster in `api/hospitals.py`. `trace` is built from the ADK event stream, one entry per tool call (`text` is ready to show in the UI). It never changes `acuity_tier` / `confirmed_tier` and never touches signal priority. The agent's choice is checked server-side (known hospital, every required capability, beds > 0, and `eta_s` taken from the `eta_to` result); on any failure, invalid choice or a 20 s timeout the nearest eligible hospital is used and `trace` is `[{"fallback": "<error type>"}]`. `destination` is set from it when it was empty (or was itself set by an earlier routing); `/location` uses the routed hospital for `eta_hospital_s`. `applied` is `true` for live runs. A scenario run still gets `routing` written but `applied` is `false` with `reason: "scenario run keeps corridor hospital"`, and neither its `destination` nor its ETA hospital changes.

### `runs/{id}/log/{n}`
```json
{
  "t": "2026-10-05T09:02:00Z", "kind": "voice", "transcript_en": "Patient has chest pain, BP 85 over 50",
  "fields": {"age": 58, "sex": "male", "complaint": "chest pain", "vitals": {"sbp": 85, "dbp": 50}},
  "interventions": [{"kind": "drug", "name": "aspirin", "dose": "300 mg", "route": null, "time_note": null}],
  "confirmed": true
}
```
A photo entry also carries `"photo_url": "https://storage.googleapis.com/green-corridor-2026-media/photos/run-1a2b3c4d/0.jpg"` (public, `photos/{run_id}/{n}.jpg` in the media bucket, whatever the image type; `null` if the upload failed, the entry is still saved) and its `transcript_en` describes the monitor, e.g. `"Monitor: HR 112, SpO2 89%, NIBP 86/54"`. `kind`: `voice | photo | form`. `interventions` is written by `/log` only (always present, `[]` when none): each is `{kind: drug | procedure | observation, name, dose, route, time_note}` exactly as the crew said it, `null` for any part not said. `/triage` entries carry `interventions: []`.

### `runs/{id}/alerts/{n}`
```json
{
  "junction_id": "blr_j3", "approach": "NE", "stage": "PREPARE", "jam_m": 520, "eta_s": 240,
  "exit_move": "left",
  "text": "AMBULANCE CRITICAL · 520 m queue on your north-east approach · turning LEFT · arrives in 4 min",
  "text_local": "ಆಂಬ್ಯುಲೆನ್ಸ್ ...",
  "audio_url": "https://storage.googleapis.com/green-corridor-2026-media/alerts/run-1a2b3c4d/blr_j3/PREPARE-0.mp3",
  "acked_at": null, "ack_latency_s": null, "escalated": false, "created_at": "2026-10-05T09:03:10Z"
}
```
`n` counts up from 0 per run (`alert_count`). `stage`: `PREPARE | STOP | UPDATE`; per run and junction PREPARE fires once and only when `jam_m >= 50` (a shorter queue needs no warning), UPDATE when `jam_m` grew more than 100 m since the last alert, STOP once at eta <= 30 s (or inside the stop-line geofence) whatever the queue. `text` prefix: `STOP CROSS TRAFFIC · ` or `UPDATE · `; the tier word is `confirmed_tier`, else `acuity_tier`, else `UNCONFIRMED` (ambulance). `created_at` is a server timestamp. `text_local` is `text` rewritten as a spoken line by Gemini (template fallback), in the language set by env `ALERT_LANG`: conversational Indian English by default (`en`), or colloquial Kannada / Telugu with English loanwords (`kn` / `te`; `corridor` = the corridor's language: `kn` blr, `te` hyd); `text` itself stays the terse structured line; `audio_url` is its MP3 (public, in the media bucket, cached per text and language so an unchanged UPDATE reuses the file). If speech synthesis fails both are `null` and the alert is text only. `exit_move`: `left | straight | right`. `acked_at` and `ack_latency_s` (seconds from `created_at`, 0.1 s) are set by `/ack`, with `acked_by` when a `device_id` was sent. `escalated` flips true, with `escalated_at`, once the alert is more than 20 s old with no ACK; checked on every `/location` tick for that run's alerts and those of the other `en_route` runs it shared a preemption sequence with (`runs/{id}.contenders`), and written to `audit/` as `action: "escalation"`.

### `junctions/{corridor}_{id}`
```json
{ "phase": {"approach": "E", "until": "2026-10-05T09:04:30Z", "run_ids": ["run-fire-1", "run-amb-1"],
            "sequence": [{"run_id": "run-fire-1", "offset_s": 0, "approach": "E"}, {"run_id": "run-amb-1", "offset_s": 12, "approach": "NE"}]},
  "lang": "kn" }
```
`phase` may also carry `rationale` (English) and `rationale_local` (corridor language): Gemini's one-line explanation of the order, written when the sequence has two or more vehicles and removed otherwise; omitted if Gemini or translation failed. `phase` is `null` when no preemption is active. Written by `SimAdapter.request_green`. `sequence` is the `priority.sequence` order: each vehicle gets its approach's green `offset_s` seconds after the phase starts; `approach` at the top is the first vehicle's. Vehicles on the same approach whose ETAs are within 45 s of the slot leader's share the leader's `offset_s` (one slot, no extra 12 s gap); otherwise each slot is 12 s after the previous. `until` = now + clear time + 30 s + the last offset + the ETA spread inside the last slot. A phase is a request, not a hold: past `until` it is stale and ignored.

### `duty/{corridor}_{junction_id}`
```json
{ "device_id": "dev-cop-1", "name": "Constable Rao", "on": true, "since": "2026-10-05T09:00:00Z" }
```
Written by `/duty` when a cop goes on or off duty at a junction (doc id like `blr_j3`). `name` may be `null`.

### `briefs/{run_id}`
```json
{
  "atmist": {"age": "58", "time": "08:55", "mechanism": "n/a", "injuries": "chest pain",
             "signs": "SBP 85, SpO2 91", "treatment": "oxygen 4 L"},
  "checklist": ["Activate cath lab", "Page cardiology", "Prepare heparin"],
  "summary": "A 58-year-old male with chest pain since about 08:55 ...",
  "disclaimer": "Synthetic patient. Clinician confirms.", "generated_at": "2026-10-05T09:03:00Z", "model": "gemini-3-flash-preview"
}
```
Written by `POST /brief` (and the `/location` trigger). `atmist` keys are lowercase; every value is a string, and anything the log does not say reads `unknown` or `unconfirmed`. `checklist` has 3 to 8 short imperative items. One doc per run, overwritten on regenerate.

### `after_action/{run_id}`
```json
{
  "summary": "The ambulance reached the hospital after clearing 5 junctions ...",
  "timeline": [{"t": "2026-10-05T09:00:00Z", "event": "Run created (ambulance KA01AB1234)"}],
  "issues": ["PREPARE alert at blr_j3 escalated with no acknowledgement"],
  "recommendations": ["Confirm the on-duty constable at blr_j3 before the next run"],
  "disclaimer": "Drafted from the recorded run data. A person reviews it before it is filed.",
  "generated_at": "2026-10-05T09:12:00Z", "model": "gemini-3-flash-preview"
}
```
Written by `POST /runs/{id}/after-action`. `timeline` is built in code, not by Gemini, from the run's `started_at` and `first_tick_at`, its log entries, each alert's `created_at` / `acked_at` / `escalated_at` and the run end (report `ended_at`, else the last tick), sorted by time, `t` as an ISO 8601 string. Gemini writes only `summary`, `issues` and `recommendations`, from the run, report, routing (without `trace`), alert summary and timeline. One doc per run, overwritten on regenerate.

### `audit/{n}`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "preempt_requested", "stage": "PREPARE", "approach": "NE",
  "sequence": [{"run_id": "run-amb-1", "offset_s": 0}], "at": "2026-10-05T09:03:20Z" }
```
Escalations: `{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "escalation", "alert_n": 0, "stage": "PREPARE", "at": "..." }`.

### `reports/{run_id}`
```json
{
  "corridor": "blr", "run_id": "run-amb-1", "vehicle_type": "ambulance", "confirmed_tier": "critical",
  "started_at": "2026-10-05T09:00:00Z", "ended_at": "2026-10-05T09:09:00Z",
  "actual_s": 540, "baseline_s": 840, "minutes_saved": 5.0, "junctions_cleared": 5,
  "alerts": 7, "ack_latency_s": [6.2, 4.8, 9.1], "avg_ack_latency_s": 6.7, "escalations": 1,
  "distance_m": 5200, "method": "simulated-baseline"
}
```
Written once per run when it ends (`POST /runs` end) or arrives (`/location` within 100 m of the destination, which first sets `state: arrived`); a later end returns the stored report. `started_at` is the run's `first_tick_at` (run creation if it never ticked) and `ended_at` the last GPS tick, else the time of the call; `actual_s = ended_at - started_at`. `junctions_cleared` counts the distinct junctions with a `preempt_requested` audit entry for this run (so a run that never qualified for preemption has 0). `alerts` counts the run's alert docs, `ack_latency_s` lists the acked ones (`avg_ack_latency_s` is `null` when none), `escalations` counts the run's `escalation` audit entries.
The baseline is a simulation, not a measurement (`method: "simulated-baseline"`): at each cleared junction a vehicle without preemption would stop for the remaining red, assumed to be `cycle_s / 4` (arrival at mid-red), plus the queue drain time `jam_m / 2.0` with `jam_m` from that junction's PREPARE alert (STOP-only alert: that alert's; none: 0). `baseline_s = actual_s + sum(stops)`, `minutes_saved = sum(stops) / 60`.
The same row is inserted into BigQuery `corridor.run_reports` (created on first use; `ack_latency_s` is REPEATED FLOAT, timestamps are TIMESTAMP). A BigQuery failure logs `report_bq_error` and never fails the request.

## API

All bodies JSON. Errors: `{"error": "<code>", "detail": "..."}` with 4xx/5xx. Unwritten endpoints currently return 501 `{"todo": "<name>"}`. Request bodies that fail validation return 422 `{"error": "validation_error", "detail": "<field>: <message>; ..."}`; `detail` is always text, and some errors add keys (`state`, `fallback`). Firestore failures return 503 `{"error": "store_unavailable"}`, anything unexpected 500 `{"error": "internal_error"}`. Every response carries an `X-Request-Id` header (the caller's, else a new uuid4) that is also on every server log line. CORS allows only the two Firebase Hosting origins, `localhost:5173` / `127.0.0.1:5173` and the comma-separated env `EXTRA_ORIGINS`.

### `GET /health`
Response `{"ok": true, "model": "gemini-3.1-flash-lite"}`

### `POST /vehicles/bind` (mock registry)
```json
{ "plate": "KA01AB1234", "device_id": "dev-1" }
```
200 `{ "plate": "KA01AB1234", "type": "ambulance", "agency": "108 Karnataka", "active": true, "bound_device_id": "dev-1" }`
404 `{ "error": "unregistered_vehicle" }` (also when the vehicle is inactive) (the UI shows a visible rejection)

### `POST /incidents` (mock dispatch console)
```json
{ "type": "cardiac", "severity_note": "chest pain, adult" }
```
200 `{ "incident_id": "INC-4BC6E7" }` (state `open`)

### `POST /runs`
Start:
```json
{ "action": "start", "plate": "KA01AB1234", "incident_id": "INC-0001", "corridor": "blr", "destination": {"name": "...", "lat": 0, "lng": 0}, "source": "gps" }
```
`destination` and `scenario` (a `data/scenarios/<name>` replay: recorded spans, no Routes calls) are optional. 200 `{ "run_id": "run-1a2b3c4d" }` (state `en_route`, `patient_on_board` false). 403 `{ "error": "unregistered_vehicle" }` or `{ "error": "no_active_incident" }` (incident missing or not `open`).
A vehicle has one active run: starting a run for a plate that already has one in `en_route`, `stale` or `off_route` first ends the earlier run (`state: "ended"`, `ended_reason: "superseded"`, `ahead` / `ahead_ids` cleared, no report card) and then creates the new one.
End:
```json
{ "action": "end", "run_id": "run-amb-1" }
```
200 `{ "run_id": "run-amb-1", "state": "ended", "report": { "...": "the `reports/{run_id}` doc, timestamps as ISO strings" } }` (`report` is `null` for a run whose corridor is unknown). 404 `{ "error": "unknown_run" }`.

### `POST /triage`
Request (audio, image or text). Audio and images are base64 in JSON; multipart is not supported. `lang_hint` is optional. An image is a photo of a patient monitor or ECG strip: `image_b64` with `mime` `image/jpeg | image/png | image/webp` (no `audio_b64` alongside, else 400 `bad_request`).
```json
{ "run_id": "run-amb-1", "vehicle_type": "ambulance", "audio_b64": "...", "mime": "audio/webm" }
```
```json
{ "run_id": "run-amb-1", "vehicle_type": "ambulance", "text": "chest pain, BP 85 over 50" }
```
```json
{ "run_id": "run-amb-1", "vehicle_type": "ambulance", "image_b64": "...", "mime": "image/png" }
```
200 (`suggested_tier` is the deterministic lookup, stored as `runs/{id}.acuity_tier`; the crew must confirm):
```json
{ "fields": { "...": "Gemini response schema below" }, "transcript_en": "...", "suggested_tier": "critical", "photo_url": "https://storage.googleapis.com/green-corridor-2026-media/photos/run-amb-1/0.jpg" }
```
`photo_url` is present for image input only, so the UI can show the extracted values beside the photo.
Each call appends `runs/{id}/log/{n}` with `confirmed: false`.
422 `{ "error": "extraction_failed", "fallback": "form" }` (after one retry on the first model, then one try on the other; the UI shows the form).

Gemini response schema:
```json
{
  "age": 58,
  "sex": "male",
  "complaint": "chest pain",
  "conscious": true,
  "breathing": true,
  "vitals": { "sbp": 85, "dbp": 50, "hr": 110, "spo2": 91, "rr": 22, "temp": 36.8 },
  "trapped_persons": 0,
  "incident_type": "medical",
  "transcript_en": "Patient has chest pain, blood pressure 85 over 50"
}
```
Unknown values are `null` (`age` is an integer, `sex` free text as said). Gemini never returns a score.
For an image Gemini reads only values visible on the screen, returns `null` for anything not legible, never infers a diagnosis, and sets `transcript_en` to a one-line description of the monitor (`"Monitor: HR 112, SpO2 89%, NIBP 86/54"`); the vitals feed the same acuity lookup (SpO2 < 90 or SBP < 90 is `critical`).
Models: all extraction (text, audio, image) uses `GEMINI_MODEL` (`gemini-3.1-flash-lite`, about 3x faster than `gemini-3-flash-preview` on the same clip with the same fields). Attempts per call: `GEMINI_MODEL` twice, then `GEMINI_FALLBACK_MODEL` (`gemini-3-flash-preview`) once. Per-attempt timeout is 15 s for audio and images, 8 s for text.

### `POST /runs/{run_id}/confirm`
The crew's one tap.
```json
{ "tier": "critical" }
```
200 `{ "run_id": "run-amb-1", "confirmed_tier": "critical", "patient_on_board": true, "routing": { "...": "runs.routing" } }` (`routing` is always `null` here: the routing agent runs after the response as a background task, up to 20 s, and writes `runs/{id}.routing`, which the UI reads live from Firestore; it stays absent for fire and police runs). 400 `{ "error": "bad_tier" }`, 404 `{ "error": "unknown_run" }`.

### `POST /route`
Re-runs the hospital routing agent for a confirmed ambulance run (for example after the patient's condition or position changed).
```json
{ "run_id": "run-amb-1" }
```
200 the `runs.routing` object, also written to the run. 404 `{ "error": "unknown_run" }`, 409 `{ "error": "not_routable" }` (not an ambulance run, no confirmed tier, or corridor without a roster).

### `POST /log`
Same request and 422 as `/triage` (optional `kind`: `voice | photo | form`; defaults to `photo` for an image); appends a log entry only, no tier change.
```json
{ "run_id": "run-amb-1", "kind": "voice", "audio_b64": "...", "mime": "audio/webm" }
```
200 `{ "n": 3, "transcript_en": "Oxygen 4 litres started", "fields": {"...": "same schema as /triage"}, "interventions": [{"kind": "drug", "name": "oxygen", "dose": "4 litres", "route": null, "time_note": null}], "confirmed": false }`
The `/log` response schema is the `/triage` one (including `photo_url` for an image) plus `interventions: [{kind: "drug" | "procedure" | "observation", name, dose, route, time_note}]`. Gemini lists only what was said, never infers. `interventions` is returned and stored beside `fields`, not inside it.

### `POST /brief`
```json
{ "run_id": "run-amb-1" }
```
Generates from the run's log entries (Gemini on `GEMINI_TEXT_MODEL`, default `gemini-3-flash-preview`, then `GEMINI_MODEL`; 15 s per attempt), writes `briefs/{run_id}` and sets `runs/{id}.brief_fired: true` (`brief_due: false`). Also what the hospital's Regenerate button calls.
200 the stored doc: `{ "atmist": { "...": "..." }, "checklist": ["..."], "summary": "...", "disclaimer": "Synthetic patient. Clinician confirms.", "generated_at": "2026-10-05T09:03:00Z", "model": "gemini-3-flash-preview" }`. 404 `{ "error": "unknown_run" }`, 422 `{ "error": "no_log_entries" }`, 502 `{ "error": "brief_failed" }` (hospital page offers "regenerate brief").

### `POST /runs/{run_id}/after-action`
No body. Generates the after-action report for a finished run (Gemini on `GEMINI_TEXT_MODEL`, default `gemini-3-flash-preview`, then `GEMINI_MODEL`; 15 s per attempt), writes `after_action/{run_id}` and returns it. A second call returns the stored doc without calling Gemini; `?regenerate=1` generates and overwrites it.
200 the stored doc (see `after_action/{run_id}`). 404 `{ "error": "unknown_run" }`, 409 `{ "error": "run_not_finished" }` (state is not `ended` or `arrived`), 502 `{ "error": "after_action_failed" }`.

### `POST /location`
```json
{ "run_id": "run-amb-1", "lat": 12.9197, "lng": 77.6204, "speed_mps": 13.2, "heading": 231, "t": "2026-10-05T09:02:30Z", "source": "sim" }
```
`heading` (degrees) and `t` are optional (derived from the previous tick / server time); `source`: `gps | sim`.
200:
```json
{
  "state": "en_route", "next_junction": "blr_j3", "approach": "NE", "jam_m": 520, "eta_s": 143, "stage": "PREPARE",
  "exit_move": "left", "eta_hospital_s": 412,
  "alerts_fired": [{"junction": "blr_j3", "stage": "PREPARE"}], "brief_due": false, "observed_speed_60s": 13.2, "traffic": "live"
}
```
`next_junction`, `approach`, `jam_m`, `eta_s`, `stage`, `exit_move`, `traffic` describe the nearest junction ahead and are `null` when none is left or the run is `off_route`. Every junction ahead is evaluated each tick (alerts and preemption can fire for a far junction while a nearer one is still to come); `alerts_fired` lists what fired this tick. `stage` is `PREPARE | STOP | null`. `exit_move`: `left | straight | right` (Routes manoeuvre at that junction; `straight` when none). `state`: `en_route`, `off_route` (vehicle more than 80 m from the Routes polyline: no junction logic, no preemption; ticks revive `stale` and `off_route` runs) or `arrived` (tick within 100 m of the destination; the report card is written and later ticks get 403). `traffic`: `live | stale | scenario`.
Preemption: when an alert fires and the run qualifies (ambulance with `confirmed_tier` and `patient_on_board`; fire or police with an incident), the contenders for that junction are the other `en_route` runs with it in `ahead_ids`; `priority.sequence` orders them and `junctions/{id}.phase` plus an `audit/` entry are written.
Side effect: any `/location` call marks other `en_route` runs with no tick for 30 s as `stale`.
403 `{ "error": "run_not_active", "state": "ended" }` (only `en_route`, `off_route`, `stale` runs take ticks), 404 `{ "error": "unknown_run" }`, 400 `{ "error": "unknown_corridor" }`.

### `POST /ack`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "alert_n": 0, "device_id": "dev-cop-1" }
```
`device_id` is optional. Sets `acked_at` (server time) and `ack_latency_s` on `runs/{run_id}/alerts/{alert_n}`; a repeat ACK changes nothing and returns the first values.
200 `{ "ok": true, "acked_at": "2026-10-05T09:03:26Z", "ack_latency_s": 6.2, "latency_s": 6.2 }` (`latency_s` duplicates `ack_latency_s` for the cop page). 404 `{ "error": "unknown_alert" }` (no such alert, or its `junction_id` differs).

### `POST /duty`
```json
{ "corridor": "blr", "junction_id": "blr_j3", "device_id": "dev-cop-1", "on": true, "name": "Constable Rao" }
```
`junction_id` may be `blr_j3` or `j3`; `name` is optional. Writes `duty/blr_j3`.
200 the doc: `{ "device_id": "dev-cop-1", "name": "Constable Rao", "on": true, "since": "2026-10-05T09:00:00Z" }`. 400 `{ "error": "unknown_corridor" }`, 404 `{ "error": "unknown_junction" }`.

## Dev-only: `OFFLINE_AI=1`

Local testing without any paid Google call (never set in a deploy workflow; the API logs `{"event": "offline_ai"}` once at startup when it is on). Firestore is still used. With it set: `tts.localize_alert` returns the English text, `tts.speak` returns `(None, text)` so alerts are text only (no Translation, TTS or Storage), `brief.generate` returns a fixed stub (`model: "offline"`), `aar.generate` a fixed summary, issues and recommendations (`model: "offline"`, the timeline is still built from the record), the routing agent returns its rule-based fallback at once (`trace: [{"fallback": "offline_ai"}]`, straight-line ETAs, no Routes call), the preemption `rationale` is skipped, and `/triage` and `/log` answer 422 `extraction_failed` (set tiers through `/runs/{id}/confirm`). `api/offline_replay.py` replays a scenario against a local API in this mode.
