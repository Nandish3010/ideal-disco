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
`ticks` keeps the last 12 (at most one per 5 s, so they span about a minute; `t` is the client's tick time). `last_tick_at` is server time and drives the stale check. `ahead` / `ahead_ids` list every junction still ahead (nearest first in `next_*`); other runs read them to find contenders. `last_eval.traffic`: `live | stale | scenario`; `stale` means Routes failed and no spans under 60 s old were left, so the queue was treated as NORMAL (control room shows "traffic data stale"). `brief_due` is set once `eta_hospital_s <= 300` and `brief_fired` is false; `/brief` consumes it. Optional `scenario: "<name>"` (set by the scenario runner, not by `/runs`) makes `/location` read `recorded_spans` from `data/scenarios/<name>.json` instead of calling Routes, and follow the corridor config instead of the Routes polyline (no off-route check).

### `runs/{id}/log/{n}`
```json
{
  "t": "2026-10-05T09:02:00Z", "kind": "voice", "transcript_en": "Patient has chest pain, BP 85 over 50",
  "fields": {"complaint": "chest pain", "vitals": {"sbp": 85, "dbp": 50}}, "confirmed": true
}
```
`kind`: `voice | photo | form`.

### `runs/{id}/alerts/{n}`
```json
{
  "junction_id": "blr_j3", "approach": "NE", "stage": "PREPARE", "jam_m": 520, "eta_s": 240,
  "exit_move": "left",
  "text": "AMBULANCE CRITICAL · 520 m queue on your north-east approach · turning LEFT · arrives in 4 min",
  "audio_url": "gs://green-corridor-2026-media/alerts/blr_j3_run1_prepare.mp3",
  "acked_at": null, "escalated": false, "created_at": "2026-10-05T09:03:10Z"
}
```
`n` counts up from 0 per run (`alert_count`). `stage`: `PREPARE | STOP | UPDATE`; per run and junction PREPARE fires once, UPDATE when `jam_m` grew more than 100 m since the last alert, STOP once at eta <= 30 s (or inside the stop-line geofence). `text` prefix: `STOP CROSS TRAFFIC · ` or `UPDATE · `; the tier word is `confirmed_tier`, else `acuity_tier`, else `UNCONFIRMED` (ambulance). `audio_url` arrives with TTS (not written yet). `exit_move`: `left | straight | right`. `escalated` flips true after 20 s without ACK.

### `junctions/{corridor}_{id}`
```json
{ "phase": {"approach": "E", "until": "2026-10-05T09:04:30Z", "run_ids": ["run-fire-1", "run-amb-1"],
            "sequence": [{"run_id": "run-fire-1", "offset_s": 0, "approach": "E"}, {"run_id": "run-amb-1", "offset_s": 12, "approach": "NE"}]},
  "lang": "kn" }
```
`phase` is `null` when no preemption is active. Written by `SimAdapter.request_green`. `sequence` is the `priority.sequence` order: each vehicle gets its approach's green `offset_s` seconds after the phase starts; `approach` at the top is the first vehicle's. `until` = now + clear time + 30 s + the last offset. A phase is a request, not a hold: past `until` it is stale and ignored.

### `briefs/{run_id}`
```json
{
  "atmist": {"age": "58", "time": "08:55", "mechanism": "n/a", "injuries": "chest pain",
             "signs": "SBP 85, SpO2 91", "treatment": "oxygen 4 L"},
  "checklist": ["Cath lab on standby", "12-lead ECG on arrival"], "generated_at": "2026-10-05T09:03:00Z"
}
```

### `audit/{n}`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "preempt_requested", "stage": "PREPARE", "approach": "NE",
  "sequence": [{"run_id": "run-amb-1", "offset_s": 0}], "at": "2026-10-05T09:03:20Z" }
```

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
422 `{ "error": "extraction_failed", "fallback": "form" }` (after one retry on the primary model, then one try on the fallback model; the UI shows the form).

Gemini response schema:
```json
{
  "complaint": "chest pain",
  "conscious": true,
  "breathing": true,
  "vitals": { "sbp": 85, "dbp": 50, "hr": 110, "spo2": 91, "rr": 22, "temp": 36.8 },
  "trapped_persons": 0,
  "incident_type": "medical",
  "transcript_en": "Patient has chest pain, blood pressure 85 over 50"
}
```
Unknown values are `null`. Gemini never returns a score.

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
200 `{ "n": 3, "transcript_en": "Oxygen started", "fields": {"treatment": "oxygen 4 L"}, "confirmed": false }`

### `POST /brief`
```json
{ "run_id": "run-amb-1" }
```
200 `{ "atmist": { "...": "..." }, "checklist": ["..."], "generated_at": "2026-10-05T09:03:00Z" }`. 502 `{ "error": "brief_failed" }` (hospital page offers "regenerate brief").

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
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "alert_n": 0 }
```
200 `{ "acked_at": "2026-10-05T09:03:26Z", "latency_s": 6.2 }`
