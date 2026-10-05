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
`state`: `en_route | arrived | ended | stale | off_route`. `source`: `gps | sim`. `acuity_tier` is the lookup result written by `/triage`, `confirmed_tier` the crew's tap written by `/runs/{id}/confirm` (which also sets `patient_on_board: true`); only `confirmed_tier` enters priority.

Written by `/location` on every tick:
```json
{
  "ticks": [{"t": "2026-10-05T09:03:10Z", "lat": 12.9197, "lng": 77.6204, "speed_mps": 13.2}],
  "last_tick_at": "2026-10-05T09:03:10Z", "heading": 231, "source": "sim", "state": "en_route",
  "eta_hospital_s": 412, "brief_due": false,
  "next_junction_id": "blr_j3", "next_approach": "NE", "next_eta_s": 143,
  "ahead_ids": ["blr_j3", "blr_j4"], "ahead": {"blr_j3": {"eta_s": 143, "approach": "NE"}, "blr_j4": {"eta_s": 215, "approach": "E"}},
  "last_eval": {"next_junction": "blr_j3", "approach": "NE", "jam_m": 520, "eta_s": 143, "stage": "PREPARE", "exit_move": "left", "traffic": "live"},
  "alert_state": {"blr_j3": {"prepare": true, "stop": false, "jam_m": 520}}, "alert_count": 1
}
```
`ticks` keeps the last 12 (at most one per 5 s, so they span about a minute; `t` is the client's tick time). `last_tick_at` is server time and drives the stale check. `ahead` / `ahead_ids` list every junction still ahead (nearest first in `next_*`); other runs read them to find contenders. `last_eval.traffic`: `live | stale | scenario`; `stale` means Routes failed and no spans under 60 s old were left, so the queue was treated as NORMAL (control room shows "traffic data stale"). `brief_due` is set once `eta_hospital_s <= 300`, `brief_fired` is false and the run has at least one log entry (a run that is already inside 300 s on its first tick qualifies; with no log yet the check repeats on later ticks). The same tick then generates the brief inline (about 5-10 s) exactly once, writes `briefs/{run_id}`, sets `brief_fired: true` and clears `brief_due`. If Gemini fails the tick logs `brief_error` and leaves `brief_due: true` with `brief_fired: false`, so the hospital's Regenerate button (`POST /brief`) is the retry; nothing else retries. Optional `scenario: "<name>"` (set by the scenario runner, not by `/runs`) makes `/location` read `recorded_spans` from `data/scenarios/<name>.json` instead of calling Routes, and follow the corridor config instead of the Routes polyline (no off-route check).

### `runs/{id}/log/{n}`
```json
{
  "t": "2026-10-05T09:02:00Z", "kind": "voice", "transcript_en": "Patient has chest pain, BP 85 over 50",
  "fields": {"age": 58, "sex": "male", "complaint": "chest pain", "vitals": {"sbp": 85, "dbp": 50}},
  "interventions": [{"kind": "drug", "name": "aspirin", "dose": "300 mg", "route": null, "time_note": null}],
  "confirmed": true
}
```
`kind`: `voice | photo | form`. `interventions` is written by `/log` only (always present, `[]` when none): each is `{kind: drug | procedure | observation, name, dose, route, time_note}` exactly as the crew said it, `null` for any part not said. `/triage` entries carry `interventions: []`.

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
`n` counts up from 0 per run (`alert_count`). `stage`: `PREPARE | STOP | UPDATE`; per run and junction PREPARE fires once, UPDATE when `jam_m` grew more than 100 m since the last alert, STOP once at eta <= 30 s (or inside the stop-line geofence). `text` prefix: `STOP CROSS TRAFFIC · ` or `UPDATE · `; the tier word is `confirmed_tier`, else `acuity_tier`, else `UNCONFIRMED` (ambulance). `created_at` is a server timestamp. `text_local` is `text` rewritten as a spoken line by Gemini (template fallback), in the language set by env `ALERT_LANG`: conversational Indian English by default (`en`), or colloquial Kannada / Telugu with English loanwords (`kn` / `te`; `corridor` = the corridor's language: `kn` blr, `te` hyd); `text` itself stays the terse structured line; `audio_url` is its MP3 (public, in the media bucket, cached per text and language so an unchanged UPDATE reuses the file). If speech synthesis fails both are `null` and the alert is text only. `exit_move`: `left | straight | right`. `acked_at` and `ack_latency_s` (seconds from `created_at`, 0.1 s) are set by `/ack`, with `acked_by` when a `device_id` was sent. `escalated` flips true, with `escalated_at`, once the alert is more than 20 s old with no ACK; checked on every `/location` tick for that run's alerts and those of the other `en_route` runs it shared a preemption sequence with (`runs/{id}.contenders`), and written to `audit/` as `action: "escalation"`.

### `junctions/{corridor}_{id}`
```json
{ "phase": {"approach": "E", "until": "2026-10-05T09:04:30Z", "run_ids": ["run-fire-1", "run-amb-1"],
            "sequence": [{"run_id": "run-fire-1", "offset_s": 0, "approach": "E"}, {"run_id": "run-amb-1", "offset_s": 12, "approach": "NE"}]},
  "lang": "kn" }
```
`phase` may also carry `rationale` (English) and `rationale_local` (corridor language): Gemini's one-line explanation of the order, written when the sequence has two or more vehicles and removed otherwise; omitted if Gemini or translation failed. `phase` is `null` when no preemption is active. Written by `SimAdapter.request_green`. `sequence` is the `priority.sequence` order: each vehicle gets its approach's green `offset_s` seconds after the phase starts; `approach` at the top is the first vehicle's. `until` = now + clear time + 30 s + the last offset. A phase is a request, not a hold: past `until` it is stale and ignored.

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

### `audit/{n}`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "preempt_requested", "stage": "PREPARE", "approach": "NE",
  "sequence": [{"run_id": "run-amb-1", "offset_s": 0}], "at": "2026-10-05T09:03:20Z" }
```
Escalations: `{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "escalation", "alert_n": 0, "stage": "PREPARE", "at": "..." }`.

### `reports/{run_id}`
```json
{ "baseline_s": 840, "actual_s": 540, "minutes_saved": 5.0, "junctions_cleared": 5, "ack_latency_s": [6.2, 4.8, 9.1] }
```

## API

All bodies JSON. Errors: `{"error": "<code>", "detail": "..."}` with 4xx/5xx. Unwritten endpoints currently return 501 `{"todo": "<name>"}`. Request bodies that fail validation return FastAPI's 422 `{"detail": [...]}`. Firestore failures return 503 `{"error": "store_unavailable"}`.

### `GET /health`
Response `{"ok": true, "model": "gemini-3-flash-preview"}`

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
`destination` is optional. 200 `{ "run_id": "run-1a2b3c4d" }` (state `en_route`, `patient_on_board` false). 403 `{ "error": "unregistered_vehicle" }` or `{ "error": "no_active_incident" }` (incident missing or not `open`).
End:
```json
{ "action": "end", "run_id": "run-amb-1" }
```
200 `{ "run_id": "run-amb-1", "state": "ended" }` (the `report` field comes with the report card later). 404 `{ "error": "unknown_run" }`.

### `POST /triage`
Request (audio or text; image later). Audio is base64 in JSON; multipart is not supported. `lang_hint` is optional.
```json
{ "run_id": "run-amb-1", "vehicle_type": "ambulance", "audio_b64": "...", "mime": "audio/webm" }
```
```json
{ "run_id": "run-amb-1", "vehicle_type": "ambulance", "text": "chest pain, BP 85 over 50" }
```
200 (`suggested_tier` is the deterministic lookup, stored as `runs/{id}.acuity_tier`; the crew must confirm):
```json
{ "fields": { "...": "Gemini response schema below" }, "transcript_en": "...", "suggested_tier": "critical" }
```
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
Models: text input uses `GEMINI_MODEL`; audio input uses `GEMINI_AUDIO_MODEL` (default `gemini-3.1-flash-lite`, about 3x faster on the same clip with the same fields). Attempts per call: the first model twice, then once on the other (`GEMINI_FALLBACK_MODEL`, or `GEMINI_MODEL` when audio already runs on the fallback model). Per-attempt timeout is 15 s for audio, 8 s for text.

### `POST /runs/{run_id}/confirm`
The crew's one tap.
```json
{ "tier": "critical" }
```
200 `{ "run_id": "run-amb-1", "confirmed_tier": "critical", "patient_on_board": true }`. 400 `{ "error": "bad_tier" }`, 404 `{ "error": "unknown_run" }`.

### `POST /log`
Same request and 422 as `/triage` (optional `kind`: `voice | photo | form`); appends a log entry only, no tier change.
```json
{ "run_id": "run-amb-1", "kind": "voice", "audio_b64": "...", "mime": "audio/webm" }
```
200 `{ "n": 3, "transcript_en": "Oxygen 4 litres started", "fields": {"...": "same schema as /triage"}, "interventions": [{"kind": "drug", "name": "oxygen", "dose": "4 litres", "route": null, "time_note": null}], "confirmed": false }`
The `/log` response schema is the `/triage` one plus `interventions: [{kind: "drug" | "procedure" | "observation", name, dose, route, time_note}]`. Gemini lists only what was said, never infers. `interventions` is returned and stored beside `fields`, not inside it.

### `POST /brief`
```json
{ "run_id": "run-amb-1" }
```
Generates from the run's log entries (Gemini on `GEMINI_MODEL`, then the fallback; 15 s per attempt), writes `briefs/{run_id}` and sets `runs/{id}.brief_fired: true` (`brief_due: false`). Also what the hospital's Regenerate button calls.
200 the stored doc: `{ "atmist": { "...": "..." }, "checklist": ["..."], "summary": "...", "disclaimer": "Synthetic patient. Clinician confirms.", "generated_at": "2026-10-05T09:03:00Z", "model": "gemini-3-flash-preview" }`. 404 `{ "error": "unknown_run" }`, 422 `{ "error": "no_log_entries" }`, 502 `{ "error": "brief_failed" }` (hospital page offers "regenerate brief").

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
`next_junction`, `approach`, `jam_m`, `eta_s`, `stage`, `exit_move`, `traffic` describe the nearest junction ahead and are `null` when none is left or the run is `off_route`. Every junction ahead is evaluated each tick (alerts and preemption can fire for a far junction while a nearer one is still to come); `alerts_fired` lists what fired this tick. `stage` is `PREPARE | STOP | null`. `exit_move`: `left | straight | right` (Routes manoeuvre at that junction; `straight` when none). `state`: `en_route` or `off_route` (vehicle more than 80 m from the Routes polyline: no junction logic, no preemption; ticks revive `stale` and `off_route` runs). `traffic`: `live | stale | scenario`.
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
