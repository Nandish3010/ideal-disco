# Contracts

Firestore **(default)** database in project `green-corridor-2026`. Timestamps are Firestore Timestamps, shown here as ISO 8601.
Clients read; only the Cloud Run service account writes. Every server log line carries `run_id` and `junction_id`.

## Firestore collections

### `vehicles/{plate}`
```json
{ "type": "ambulance", "agency": "108 Karnataka", "active": true, "bound_device_id": "dev-1", "device_token_hash": "9f86d0..." }
```
`bound_device_id` and `device_token_hash` (sha256 of the device token, hex) are set by `/vehicles/bind`; the token itself is never stored. `type`: `ambulance | fire | police`.

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
  "first_tick_at": "2026-10-05T09:00:05Z", "route_index": 2, "passed_junctions": ["blr_j1", "blr_j2"]
}
```
Counters written by the other endpoints: `log_count` (last number given to a log entry, see `runs/{id}/log/{n}`) and `extract_calls` (`/triage` and `/log` calls so far, capped at 20).
`distance_m` is the running sum of distance between ticks. `first_tick_at` is the client time (`t`) of the run's first `/location` tick, set once; the report card measures the drive from it, not from `started_at`. `route_index` is the corridor index of the next junction to reach (0 at the start); it only ever increases, and `passed_junctions` is always the first `route_index` junctions of the corridor, in corridor order (passing one passes every earlier one). A junction counts as passed when a tick-to-tick step went through its stop-line circle (`radius_m`) and the vehicle is outside it again, or, because a 5 s tick can jump the circle, when the vehicle's position projected onto the route polyline is more than 15 m past the junction's own projection on it (only for a junction within 100 m of the route, and only while `en_route`). Junctions below `route_index` are never evaluated, alerted or reported as `next_junction` again, whatever the GPS or a fresh route does, so `next_junction` only moves forward. `ticks` keeps the last 12 (at most one per 5 s, so they span about a minute; `t` is the client's tick time). `last_tick_at` is server time and drives the stale check. `ahead` / `ahead_ids` list every junction still ahead (nearest first in `next_*`); other runs read them to find contenders. `last_eval.traffic`: `live | stale | scenario`; `stale` means Routes failed and no spans under 60 s old were left, so the queue was treated as NORMAL (control room shows "traffic data stale"). Queue and ETA of every junction come from the run's one route call (see Routes call budget). `brief_due` is set for ambulance runs only (fire and police never get a brief), once `eta_hospital_s <= 300`, `brief_fired` is false, the run has at least one log entry and it is under way: at least one junction passed or `distance_m >= 500` (a scenario run's first tick never qualifies; with no log yet the check repeats on later ticks). The brief is then generated exactly once, after that tick's response has been sent (about 5-10 s, a background task: `brief_due` is `true` in that response), writes `briefs/{run_id}`, sets `brief_fired: true` and clears `brief_due`. If Gemini fails the tick logs `brief_error` and leaves `brief_due: true` with `brief_fired: false`, so the hospital's Regenerate button (`POST /brief`) is the retry; nothing else retries. Optional `scenario: "<name>"` (set by the scenario runner, not by `/runs`) makes `/location` read `recorded_spans` from `data/scenarios/<name>.json` instead of calling Routes, and follow the corridor config instead of the Routes polyline (no off-route check). Slow side effects of a tick (alert speech, the phase rationale, the brief) are background tasks that run after the response; the tick itself returns once its Firestore writes are done. A scenario run keeps its destination: `eta_hospital_s` and arrival use the run's own `destination` (else the corridor hospital) whatever the routing agent picks.

`routing` (written by `/runs/{id}/confirm` and `/route`; ambulance runs only):
```json
{
  "destination": "Jayadeva Institute of Cardiovascular Sciences", "hospital_id": "blr_jayadeva", "eta_s": 438,
  "reasons": ["Jayadeva has a cath lab, 4 beds and a 38 min door-to-balloon time.", "Apollo is on diversion and Fortis has no cath lab, so Jayadeva wins on ETA as well."],
  "capabilities": [{"capability": "cath_lab", "reason": "Chest pain with sweating: STEMI pathway"}, {"capability": "icu", "reason": "Hypotensive, may need ventilation"}],
  "alternatives": [{"hospital_id": "blr_apollo_bg", "eta_s": 512, "why_not": "On diversion"}, {"hospital_id": "blr_fortis_bg", "eta_s": 530, "why_not": "No cath lab"}],
  "confidence": 0.85,
  "trace": [
    {"tool": "required_capabilities", "args": {"confirmed_tier": "critical", "fields": {"complaint": "chest pain"}}, "result": "cath_lab", "text": "called required_capabilities(critical) -> cath_lab"},
    {"tool": "list_hospitals", "args": {"corridor": "blr"}, "result": "3 hospitals: blr_jayadeva, blr_apollo_bg, blr_fortis_bg", "text": "called list_hospitals(blr) -> 3 hospitals: ..."},
    {"tool": "check_diversion", "args": {"hospital_id": "blr_apollo_bg"}, "result": "on diversion", "text": "called check_diversion(Apollo Hospital Bannerghatta Road) -> on diversion"},
    {"tool": "eta_to", "args": {"lat": 12.9172, "lng": 77.6229, "dest_lat": 12.9185, "dest_lng": 77.599}, "result": "438 s, 2.7 km", "text": "called eta_to(Jayadeva Institute of Cardiovascular Sciences) -> 438 s, 2.7 km"},
    {"step": "capabilities", "text": "capabilities: cath_lab (Chest pain ...); icu (Hypotensive ...). Added to baseline: icu"}
  ],
  "decided_at": "2026-10-05T09:02:40Z", "applied": true
}
```
The routing agent (`api/agent.py`, Google ADK `LlmAgent` `hospital_router` on Vertex AI, tools `list_hospitals`, `eta_to`, `check_diversion`, `required_capabilities`) makes the decision; the code only guards it. The model reads the free-text transcript and fields and decides the required capabilities itself (`cath_lab`, `stroke_unit`, `trauma`, `burns`, `paediatrics`, `icu`, `dialysis`, `obstetrics`) with a one-line reason each, then weighs ETA against beds, diversion and specialty fit (`trauma_level`, `cath_lab_door_to_balloon_min`, `distance_km` from `eta_to`) over the mock roster in `api/hospitals.py` (`beds_available`, `diversion`, `trauma_level`, `cath_lab_door_to_balloon_min`). It may choose a farther hospital than the nearest eligible one. `required_capabilities` is a validation tool: it returns the keyword-table baseline (`required`) and the time-critical part of it (`critical`: `cath_lab`, `stroke_unit`, `burns`), so the model can see whether it adds or drops something. `check_diversion(hospital_id)` is the mock live feed: Apollo Bannerghatta Road is on diversion for about 30 % of run ids (CRC32 of the run id, so the same run always gets the same answer), and the roster `diversion` flag is also honoured; a diverted first choice makes the model re-plan, which shows as a branch in `trace`.

`capabilities` is the model's decision, `[{capability, reason}]`. `alternatives` are the top two hospitals it rejected, `[{hospital_id, eta_s, why_not}]` (`eta_s` from the `eta_to` result when it asked, else the model's number or `null`). `confidence` is 0 to 1, or `null` when no model judgment is behind the pick (fallback). `trace` is built from the ADK event stream, one entry per tool call (`text` is ready to show in the UI), plus a final `{"step": "capabilities", "text": ...}` entry that lists what the model added to or dropped from the baseline. It never changes `acuity_tier` / `confirmed_tier` and never touches signal priority.

Server-side guards (the model's answer is used only if all hold): it may add capabilities (each with a reason) and drop a non-critical baseline item (with a reason in `dropped`), but never a `critical` baseline item; every capability is in the vocabulary above; the hospital is in the corridor's roster, not on diversion, has `beds_available > 0` and every required capability; `eta_s` is taken from the `eta_to` result. A tripped guard appends `{"guard": "<name>", "text": ...}` to `trace` (names: `dropped_baseline_capability`, `unjustified_deviation`, `unknown_capability`, `ineligible_choice`) and the rule-based fallback is used. Any other failure, an unparsable answer or a 20 s timeout also falls back, with `trace` `[{"fallback": "<error type>"}]`. The fallback is the nearest hospital that has the baseline capabilities, a bed and no diversion (else the nearest free one); it still fills `alternatives` (the two nearest others with the reason, from straight-line ETAs) and `capabilities` (the baseline, reason `keyword baseline`), with `confidence: null`. `destination` is set from it when it was empty (or was itself set by an earlier routing); `/location` uses the routed hospital for `eta_hospital_s`. `applied` is `true` for live runs. A scenario run still gets `routing` written but `applied` is `false` with `reason: "scenario run keeps corridor hospital"`, and neither its `destination` nor its ETA hospital changes.

### `runs/{id}/log/{n}`
```json
{
  "t": "2026-10-05T09:02:00Z", "kind": "voice", "transcript_en": "Patient has chest pain, BP 85 over 50",
  "fields": {"age": 58, "sex": "male", "complaint": "chest pain", "vitals": {"sbp": 85, "dbp": 50}},
  "interventions": [{"kind": "drug", "name": "aspirin", "dose": "300 mg", "route": null, "time_note": null}],
  "confirmed": true
}
```
`n` is 1-based and comes from `runs/{id}.log_count`, bumped with `Increment(1)` in a Firestore transaction, so concurrent writers never share a number (a run that has entries but no counter yet starts after them). `/triage` and `/log` share it. A photo entry also carries `"photo_url": "https://storage.googleapis.com/green-corridor-2026-media/photos/run-1a2b3c4d/0.jpg"` (public, `photos/{run_id}/{n}.jpg` in the media bucket, whatever the image type; `null` if the upload failed, the entry is still saved) and its `transcript_en` describes the monitor, e.g. `"Monitor: HR 112, SpO2 89%, NIBP 86/54"`. `kind`: `voice | photo | form`. `interventions` is written by `/log` only (always present, `[]` when none): each is `{kind: drug | procedure | observation, name, dose, route, time_note}` exactly as the crew said it, `null` for any part not said. `/triage` entries carry `interventions: []`.

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
`n` counts up from 0 per run (`alert_count`). `stage`: `PREPARE | STOP | UPDATE`; per run and junction PREPARE fires once (the check and the write of `alert_state` / `alert_count` for a run, junction and stage are one Firestore transaction, so two concurrent ticks never fire the same alert twice) and only when `jam_m >= 50` (a shorter queue needs no warning), UPDATE when `jam_m` grew more than 100 m since the last alert, STOP once at eta <= 30 s (or inside the stop-line geofence) whatever the queue. `text` prefix: `STOP CROSS TRAFFIC · ` or `UPDATE · `; the tier word is `confirmed_tier`, else `acuity_tier`, else `UNCONFIRMED` (ambulance). `created_at` is a server timestamp. An alert is written first with `text_local: null` and `audio_url: null`; a background task patches both in a few seconds, so a client that listens live sees the text at once and the voice follow. `text_local` is `text` rewritten as a spoken line by Gemini (template fallback), in the language set by env `ALERT_LANG`: conversational Indian English by default (`en`), or colloquial Kannada / Telugu with English loanwords (`kn` / `te`; `corridor` = the corridor's language: `kn` blr, `te` hyd); `text` itself stays the terse structured line; `audio_url` is its MP3 (public, in the media bucket, cached per text and language so an unchanged UPDATE reuses the file). If speech synthesis fails both stay `null` and the alert is text only. `cop_note` (the note below, with `junction_id`, `n` and `at`) and `cop_delay_s` (seconds of delay the cop has reported, cumulative; `eta_s` itself is not changed) are added by `POST /cop-note` to the alerts at that junction of runs still heading for it, and the vehicle page shows them ("Cop at J3: bus stalled, +2 min"); `escalation_reason` (`cop_reported_delay | cop_cannot_clear`) is set when a note escalates the alert; a `cleared` note acks the newest unacked alert with `acked_by: "cop-note"`. `exit_move`: `left | straight | right`. `acked_at` and `ack_latency_s` (seconds from `created_at`, 0.1 s) are set by `/ack`, with `acked_by` when a `device_id` was sent. `escalated` flips true, with `escalated_at`, once the alert is more than 20 s old with no ACK; checked on every `/location` tick for that run's alerts (and, for all live runs, by `POST /housekeeping`) and those of the other `en_route` runs it shared a preemption sequence with (`runs/{id}.contenders`), and written to `audit/` as `action: "escalation"`.

### `junctions/{corridor}_{id}`
```json
{ "phase": {"approach": "E", "until": "2026-10-05T09:04:30Z", "run_ids": ["run-fire-1", "run-amb-1"],
            "sequence": [{"run_id": "run-fire-1", "offset_s": 0, "approach": "E"}, {"run_id": "run-amb-1", "offset_s": 12, "approach": "NE"}]},
  "lang": "kn" }
```
`phase` may also carry `rationale` (English) and `rationale_local` (corridor language): the one-line explanation of the order (template first: see below), written when the sequence has two or more vehicles and removed otherwise, a few seconds after the phase itself (background task); `rationale_local` is omitted if translation failed. The stored text is the deterministic sentence from `priority.template_rationale`, e.g. "Fire engine with trapped persons goes first: higher priority tier. Ambulance follows 12 s later."; Gemini only rewrites it. It gets that sentence plus one fact entry per slot (so it never sees raw offsets as arrival order), `{vehicle_type, tier, approach, eta_s, offset_s, reason_code, offset_s_is_gap_assigned_by_rules: true}`, where `reason_code` is why the slot sits where it does against its neighbour (the first slot: why it beats the next; later slots: why they follow the one before): `higher_tier` (tier beats ETA), `earlier_eta_same_tier` (equal tier, earlier ETA first) or `platoon_shared_approach` (same approach, one shared green). It is told to rewrite the sentence for a traffic constable in one plain sentence, keep the same vehicles in the same order and add no reasons or numbers. Its rewrite replaces the template only if it is under 200 characters, contains no underscore or code token (`higher_tier`, braces, backticks), names the same vehicle types (fire, ambulance, police) in the same order as the template, uses only digits that appear in the template, and does not talk about arrival timing unless the template does (equal-tier ordering); otherwise the template stays (`rationale_template` is logged). A Gemini failure or timeout also leaves the template (`rationale_error` is logged). `phase.blocked` is `true` when a cop reported the junction cannot clear while this phase was requested (its clear time was doubled); `cop_block_until` (top level, set by a `cannot_clear` note, now + 5 min) is what `/location` checks: while it is in the future the junction's clear time is doubled, so alerts fire earlier and the green is requested longer. `phase` is `null` when no preemption is active. Written by `SimAdapter.request_green`. `sequence` is the `priority.sequence` order: each vehicle gets its approach's green `offset_s` seconds after the phase starts; `approach` at the top is the first vehicle's. Vehicles on the same approach whose ETAs are within 45 s of the slot leader's share the leader's `offset_s` (one slot, no extra 12 s gap); otherwise each slot is 12 s after the previous. `until` = now + clear time + 30 s + the last offset + the ETA spread inside the last slot. A phase is a request, not a hold: past `until` it is stale and ignored.

### `duty/{corridor}_{junction_id}`
```json
{ "device_id": "dev-cop-1", "name": "Constable Rao", "on": true, "since": "2026-10-05T09:00:00Z", "device_token_hash": "5e8848..." }
```
Written by `/duty` when a cop goes on or off duty at a junction (doc id like `blr_j3`). `name` may be `null`. `device_token_hash` is the sha256 of the token handed to the cop who went on duty; it is removed when that cop goes off duty. `fcm_token` (optional) is the web push token of the cop's browser, sent with `POST /duty`; the API pushes each new alert for this junction to it (`api/push.py`) while `on` is true. It is removed when the cop goes off duty, and when the next cop goes on duty without sending one. Like the rest of `duty/`, it is readable in the demo rules. `note_count` is the number of cop notes so far (below); going on duty again keeps it.

### `duty/{corridor}_{junction_id}/notes/{n}`
```json
{ "kind": "delay", "extra_seconds": 120, "reason": "bus stalled", "transcript_en": "A bus has stalled in the junction",
  "t": "2026-10-05T09:03:40Z", "device_id": "dev-cop-1",
  "effects": { "phase_extended_s": 120, "acked": 0, "escalated": 1, "blocked_s": 0 } }
```
Written by `POST /cop-note`, `n` counting up from 0 per junction. `kind`: `delay | cleared | cannot_clear | other`; `extra_seconds` only for a `delay` (after the cap); `reason` at most 80 characters, `transcript_en` at most 500. `effects` is what the rules did (see `POST /cop-note`).

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
  "timeline": [{"t": "2026-10-05T09:00:00Z", "offset": "t+0:00", "event": "Run created (ambulance KA01AB1234)"}],
  "issues": ["PREPARE alert at blr_j3 escalated with no acknowledgement"],
  "recommendations": ["Confirm the on-duty constable at blr_j3 before the next run"],
  "disclaimer": "Drafted from the recorded run data. A person reviews it before it is filed.",
  "generated_at": "2026-10-05T09:12:00Z", "model": "gemini-3-flash-preview"
}
```
Written by `POST /runs/{id}/after-action`. `timeline` is built in code, not by Gemini, from the run's `started_at` and `first_tick_at`, its log entries, each alert's `created_at` / `acked_at` / `escalated_at` and the run end, in time order. All events sit on one run clock: `offset` is the label `t+M:SS` seconds after `started_at`, and `t` is `started_at` plus that offset (ISO 8601), so the order never depends on the device clock. Log entries and alerts are server-stamped, so their offsets are exact. `first_tick_at` and the last tick carry the client's tick time (simulated in a replay), so they are moved onto the server clock by the difference between the run's `last_tick_at` (server arrival of the last tick) and that tick's own `t`; the run end is `last_tick_at` (else the report's `ended_at`); offsets below zero are clamped to `t+0:00`. Gemini writes only `summary`, `issues` and `recommendations`, from the run, report, routing (without `trace`), alert summary and a timeline of `{offset, event}` only (no wall-clock). The prompt lists the facts it may use and asks for process-action recommendations without speculation about causes; afterwards an issue or recommendation that names `connectivity`, `network`, `hardware` or `gps fault` is dropped unless a timeline event contains that word. One doc per run, overwritten on regenerate.

### `audit/{n}`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "preempt_requested", "stage": "PREPARE", "approach": "NE",
  "sequence": [{"run_id": "run-amb-1", "offset_s": 0}], "at": "2026-10-05T09:03:20Z" }
```
Escalations: `{ "run_id": "run-amb-1", "junction_id": "blr_j3", "action": "escalation", "alert_n": 0, "stage": "PREPARE", "at": "..." }`; one raised by a cop note also carries `"reason": "cop_reported_delay" | "cop_cannot_clear"` and counts in the report like a timed one.
Cop notes (one per note, no `run_id`): `{ "junction_id": "blr_j3", "action": "cop_delay", "note_n": 0, "extra_seconds": 120, "reason": "bus stalled", "run_ids": ["run-amb-1"], "device_id": "dev-cop-1", "at": "..." }`; `action` is `cop_delay | cop_cleared | cop_cannot_clear | cop_note` (kind `other`).

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
Written once per run when it ends (`POST /runs` end) or arrives (`/location` within 100 m of the destination, which first sets `state: arrived`); a later end returns the stored report. `started_at` is the run's `first_tick_at` (run creation if it never ticked) and `ended_at` the last GPS tick, else the time of the call; `actual_s = ended_at - started_at`. `junctions_cleared` counts the distinct junctions that are in the run's `passed_junctions` and also have a `preempt_requested` audit entry for this run: preemption is requested for every junction ahead minutes early, but only a junction the vehicle actually drove through is credited (a run that never qualified for preemption, or ended before reaching a junction, gets 0 for it). `alerts` counts the run's alert docs, `ack_latency_s` lists the acked ones (`avg_ack_latency_s` is `null` when none), `escalations` counts the run's `escalation` audit entries.
The baseline is a simulation, not a measurement (`method: "simulated-baseline"`): at each cleared (passed and preempted) junction a vehicle without preemption would stop for the remaining red, assumed to be `cycle_s / 4` (arrival at mid-red), plus the queue drain time `jam_m / 2.0` with `jam_m` from that junction's PREPARE alert (STOP-only alert: that alert's; none: 0). `baseline_s = actual_s + sum(stops)`, `minutes_saved = sum(stops) / 60`.
The same row is inserted into BigQuery `corridor.run_reports` (created on first use; `ack_latency_s` is REPEATED FLOAT, timestamps are TIMESTAMP). A BigQuery failure logs `report_bq_error` and never fails the request.

### `ratelimits/{bucket}:{ip}:{window}`
```json
{ "count": 7, "expires_at": "2026-10-06T09:03:00Z" }
```
The shared per-IP counters behind Rate limits and caps. `bucket` is `heavy | location | general`, `ip` the client address (at most 64 characters, `/` replaced by `_`), `window` the Unix minute (`floor(time / 60)`). One Firestore transaction per limited request reads the count, refuses at the limit and otherwise writes `Increment(1)`. `expires_at` is two windows after the window started.

### `route_cache/{run_id}`
```json
{ "result": { "duration_s": 412, "intervals": [{ "from_m": 0, "to_m": 900, "speed": "NORMAL" }], "steps": [], "polyline_points": [12.91, 77.62, 12.92, 77.63] },
  "fetched_at": "2026-10-06T09:02:30Z", "expires_at": "2026-10-07T09:02:30Z" }
```
The run's one Routes result (see Routes call budget), shared by every API instance. `polyline_points` is stored flat (`[lat, lng, lat, lng, ...]`) because Firestore has no nested arrays. A document is reused for 20 s after `fetched_at` (the off-route route stays pinned and is reused for as long as the run lives). `expires_at` is a day after the fetch.

### `idempotency/{run_id}/keys/{key}`
```json
{ "response": { "state": "en_route", "next_junction": "blr_j3", "stage": "PREPARE" }, "expires_at": "2026-10-06T09:12:30Z" }
```
The first successful `POST /location` response for an `Idempotency-Key` (or `tick_id`), kept 10 minutes. Refused ticks (403, 404) are not stored.

TTL: `ratelimits`, `route_cache` and the `keys` collection group of `idempotency` expire by their `expires_at` field. Create the policies once per project, they are not part of any deploy: `gcloud firestore fields ttls update expires_at --collection-group=ratelimits --enable-ttl` (and likewise `route_cache` and `keys`). Nothing depends on the deletion: every reader checks the time itself.

## API

All bodies JSON. Errors: `{"error": "<code>", "detail": "..."}` with 4xx/5xx. Request bodies that fail validation return 422 `{"error": "validation_error", "detail": "<field>: <message>; ..."}`; `detail` is always text, and some errors add keys (`state`, `fallback`). Firestore failures return 503 `{"error": "store_unavailable"}`, anything unexpected 500 `{"error": "internal_error"}`. Every response carries an `X-Request-Id` header (the caller's, else a new uuid4) that is also on every server log line; with `OTEL_ENABLED=1` each line also has `trace_id` and `logging.googleapis.com/trace`, which links it to its Cloud Trace span. CORS allows only the two Firebase Hosting origins, `localhost:5173` / `127.0.0.1:5173` and the comma-separated env `EXTRA_ORIGINS`.

### Device tokens
There are no accounts. Instead a device holds a random token (32 bytes, urlsafe) and the calls that change a run or a junction must send it in the header `X-Device-Token`. Only its sha256 is stored (`vehicles/{plate}.device_token_hash`, `duty/{junction}.device_token_hash`), so a read of Firestore gives nobody a usable token.

| Token | Handed out by | Rotated by |
|---|---|---|
| vehicle token | `POST /vehicles/bind` (`device_token` in the response) | the next bind of that plate, from any device: the previous device's calls then get 403 |
| junction token | `POST /duty` with `on: true` (`device_token` in the response) | the next go-on-duty at that junction; removed by go-off-duty |
| hospital desk token | `POST /hospital/duty` `{hospital_id}` (`hospital_token` in the response; 404 `unknown_hospital` for an id outside the roster) | the next sign-in of that hospital desk; stored hashed on `hospital_duty/{hospital_id}` |

Which token each protected call needs:

| Call | Token that must match |
|---|---|
| `POST /runs` (start and end), `POST /triage`, `POST /log`, `POST /location`, `POST /runs/{id}/confirm` | the vehicle token of the run's plate (for a start, of the `plate` in the body) |
| `POST /route`, `POST /runs/{id}/after-action?regenerate=1` | the vehicle token of the run's plate; the after-action regenerate also accepts any hospital desk token (`/route` does not) |
| `POST /brief` with `"regenerate": true` | the vehicle token of the run's plate, or any hospital desk token |
| `POST /ack` | the token of the cop on duty at the alert's junction, or the vehicle token of the run's plate |
| `POST /duty` with `on: false` | the junction token of that junction (going on duty needs none) |

Errors: 401 `{ "error": "device_token_required" }` (no header), 403 `{ "error": "device_token_mismatch" }` (not a token that call accepts, including a vehicle that was never bound, or a cop who is off duty). A missing run or alert is still 404 first. Left open on purpose in demo mode (production mode, below, closes the ones marked there): `/health`, every read, `POST /incidents` (the dispatch console; per-IP rate limited), the first `POST /brief` of a run, a `POST /runs/{id}/after-action` without `regenerate` (returns the stored report, or writes the first one), `POST /hospital/duty` (stands in for a hospital roster, like `/duty`), and `POST /housekeeping` (its own `X-Housekeeping-Token`).
This is a demo-grade control, not authentication: `/vehicles/bind` stands in for the agency registry and `/duty` for a roster, and both are open, so anyone who knows a registered plate or a junction can take its token over (which also locks the previous holder out). Real binding would sit behind agency sign-in. The web sim feeder binds each scenario vehicle itself (`device_id: "sim-<plate>"`) and uses that token, which rotates the token of a real phone bound to the same plate: the phone must bind again.
Env `DEVICE_TOKENS_DISABLED=1` turns the check off (for `api/offline_replay.py` only); unset, the default, it is enforced.

### `hospital_duty/{hospital_id}`
```json
{ "device_token_hash": "5e8848...", "since": "2026-10-06T09:00:00Z" }
```
Written by `POST /hospital/duty` (doc id from the roster, like `blr_jayadeva`). Only the sha256 of the desk token is kept. The web hospital page keeps the token in `localStorage` as `hospital_token_<hospital_id>`.

### Rate limits and caps
The endpoints are unauthenticated apart from the device tokens above, so they are limited per client. Per client IP (the last `X-Forwarded-For` entry, else the socket address), in fixed one-minute windows counted in Firestore (`ratelimits/{bucket}:{ip}:{window}`), so every Cloud Run instance spends one shared budget. If Firestore errors, that instance logs `{"event": "ratelimit_fallback"}` and counts in memory (a token bucket per instance, refilled continuously) for 30 s before trying Firestore again, so a store outage never blocks requests and never lifts the limits.

| Bucket | Paths | Limit |
|---|---|---|
| heavy | `/triage`, `/log`, `/brief`, `/route`, `/cop-note`, `/runs/{id}/after-action` | 10 per minute |
| location | `/location` | 900 per minute (three simulated vehicles at 20x send 720) |
| general | everything else except `/health` (never limited) | 60 per minute |

Over the limit: 429 `{"error": "rate_limited", "detail": "rate limited"}` with a `Retry-After` header (seconds; to the next window). Env `RATE_LIMIT_DISABLED=1` switches the limits off (tests and `api/offline_replay.py`, which sends a few hundred ticks without sleeping).
Per-run caps, whatever the IP: at most 20 `/triage` plus `/log` calls per run (`runs/{id}.extract_calls`; the 21st is 429 `{"error": "run_cap_reached"}`), and at most one `/brief` per run per 10 minutes unless the body has `"regenerate": true` (otherwise 429 `{"error": "brief_cooldown", "retry_after_s": 412}`).

### Documentation
`GET /docs` (Swagger UI) and `GET /openapi.json` describe every endpoint: tags, request and response examples, and one shared `Error` response (the envelope above, with `X-Request-Id`) for 429, 500 and 503. The version is the first seven characters of env `GIT_SHA` (`dev` when unset). `api/openapi.json` is the committed copy: `make openapi` regenerates it and CI runs `python -m api.export_openapi --check`, failing if it is stale. `make contract` runs schemathesis (every check, 20 examples per operation) against the API on an in-memory Firestore.

### `GET /health`
Response `{"ok": true, "model": "gemini-3.1-flash-lite"}`

### `POST /vehicles/bind` (mock registry)
```json
{ "plate": "KA01AB1234", "device_id": "dev-1" }
```
200 `{ "plate": "KA01AB1234", "type": "ambulance", "agency": "108 Karnataka", "active": true, "bound_device_id": "dev-1", "device_token": "<43 characters>" }` (a new token on every bind; see Device tokens)
404 `{ "error": "unregistered_vehicle" }` (also when the vehicle is inactive) (the UI shows a visible rejection)

### `POST /incidents` (mock dispatch console)
```json
{ "type": "cardiac", "severity_note": "chest pain, adult" }
```
200 `{ "incident_id": "INC-4BC6E7" }` (state `open`)

### `GET /runs/{run_id}/log` and `GET /briefs/{run_id}`
The transit log and the stored ATMIST brief over the API, for browsers that may not read them from Firestore (production mode, below). Header `X-Device-Token`: the run's vehicle token or any hospital desk token (401 `device_token_required`, 403 `device_token_mismatch`; 404 `unknown_run` first). The log is `[{ "n": 1, "t": "<ISO>", "kind": "voice", "transcript_en": "...", "fields": {}, "interventions": [], "confirmed": false }]`, oldest first, timestamps as ISO strings; the brief is the `briefs/{run_id}` doc with `generated_at` as an ISO string, or 404 `no_brief`. Both work in demo mode too, where the browser reads Firestore directly instead.

### Production mode (`PRODUCTION_MODE=1`)
The demo leaves the calls a judge needs open. With `PRODUCTION_MODE=1` (middleware in `api/production.py`, registered inside the request context, so a refusal still has an `X-Request-Id`):

| Call | Needs |
|---|---|
| `POST /incidents` | header `X-Dispatch-Token` equal to env `DISPATCH_TOKEN`: 401 `dispatch_token_required` without it, 403 `forbidden` when wrong |
| `POST /vehicles/bind`, `POST /hospital/duty` | header `X-Agency-Key` equal to env `AGENCY_KEY`: 401 `agency_key_required`, 403 `forbidden` |
| `POST /brief` | a hospital desk token in `X-Device-Token` (the first brief of a run is no longer open) |
| `POST /runs/{id}/after-action` | the run's vehicle token or a hospital desk token, `regenerate` or not |

A credential env that is unset refuses every call (403 `forbidden`): production never falls open. `DEVICE_TOKENS_DISABLED` is ignored. `web/firestore.rules.production` denies browser reads of `runs/*/log`, `briefs`, `after_action`, `vehicles` and `hospital_duty`; the two GET endpoints above serve the first two, `POST /runs/{id}/after-action` the third. Cop go-on-duty (`POST /duty`) stays open: an agency roster is the roadmap item.

### `POST /runs`
Start:
```json
{ "action": "start", "plate": "KA01AB1234", "incident_id": "INC-0001", "corridor": "blr", "destination": {"name": "...", "lat": 0, "lng": 0}, "source": "gps" }
```
`destination` and `scenario` (a `data/scenarios/<name>` replay: recorded spans, no Routes calls) are optional; a run with a `scenario` and no `destination` is stored with the corridor hospital (`{name, lat, lng}`) as its `destination`, so a replay never reads "to —". 200 `{ "run_id": "run-1a2b3c4d" }` (state `en_route`, `patient_on_board` false). 403 `{ "error": "unregistered_vehicle" }` or `{ "error": "no_active_incident" }` (incident missing or not `open`).
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
422 `{ "error": "extraction_failed", "fallback": "form" }` (after one retry on the first model, then one try on the other; the UI shows the form). 429 `{ "error": "run_cap_reached" }` once the run has made 20 `/triage` and `/log` calls.

Gemini response schema:
```json
{
  "age": 58,
  "sex": "male",
  "complaint": "chest pain",
  "complaint_category": "chest_pain",
  "burn_percent": null,
  "bleeding_severity": null,
  "conscious": true,
  "breathing": true,
  "vitals": { "sbp": 85, "dbp": 50, "hr": 110, "spo2": 91, "rr": 22, "temp": 36.8 },
  "trapped_persons": 0,
  "incident_type": "medical",
  "transcript_en": "Patient has chest pain, blood pressure 85 over 50"
}
```
Unknown values are `null` (`age` is an integer, `sex` free text as said). Gemini never returns a score.
`complaint` stays free text as spoken. `complaint_category` is the clinically closest match for what was said, one of `chest_pain | stroke_signs | major_bleeding | moderate_bleeding | burns | breathing_difficulty | fracture | unconscious | seizure | allergic_reaction | abdominal_pain | minor_injury | other` (`other` when unsure; `null` is treated like `other`). `burn_percent` (integer, body surface area) and `bleeding_severity` (`minor | moderate | major`) are filled only when stated or plainly described, else `null`. Gemini never infers vitals and never returns a score.

Tier lookup (`api/acuity.py`, deterministic; ambulance runs). Any vitals or consciousness rule below sets the tier on its own, whatever the category:

| Tier | Rule |
|------|------|
| `critical` | `conscious` or `breathing` is `false`; SBP < 90; SpO2 < 90; trapped persons > 0; category `chest_pain`, `stroke_signs`, `major_bleeding`, `unconscious` or `seizure`; `bleeding_severity: major`; `allergic_reaction` with `breathing: false` or an airway word in `complaint` (breath, wheeze, throat, airway, swelling); `burns` with `burn_percent` >= 20 or face / airway / inhalation in `complaint` |
| `urgent` | any vital outside its range (SBP 90-180, DBP 50-110, HR 50-110, SpO2 94-100, RR 10-24, temp 36.0-38.5); category `moderate_bleeding`, `breathing_difficulty` or `fracture`; `bleeding_severity: moderate`; `burns` below 20 % (or no percentage given); `abdominal_pain` with any abnormal vital |
| `stable` | everything else (`minor_injury`, `abdominal_pain` with normal vitals, `allergic_reaction` without an airway sign, `other`) |

When `complaint_category` is missing or `other`, the lookup falls back to matching fixed phrases in `complaint` (chest pain, stroke signs, major bleeding, burns > 20 % are `critical`; fracture, moderate bleeding, breathing difficulty are `urgent`). Fire runs are `fire_with_trapped` (trapped persons > 0) or `fire`; police runs `police_with_incident` (an incident is set) or `police`.
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
{ "run_id": "run-amb-1", "regenerate": false }
```
`regenerate` is optional (default `false`): a brief written less than 10 minutes ago is not replaced unless it is `true`. Generates from the run's log entries (Gemini on `GEMINI_TEXT_MODEL`, default `gemini-3-flash-preview`, then `GEMINI_MODEL`; 15 s per attempt), writes `briefs/{run_id}` and sets `runs/{id}.brief_fired: true` (`brief_due: false`). Also what the hospital's Regenerate button calls.
200 the stored doc: `{ "atmist": { "...": "..." }, "checklist": ["..."], "summary": "...", "disclaimer": "Synthetic patient. Clinician confirms.", "generated_at": "2026-10-05T09:03:00Z", "model": "gemini-3-flash-preview" }`. 404 `{ "error": "unknown_run" }`, 422 `{ "error": "no_log_entries" }`, 429 `{ "error": "brief_cooldown", "retry_after_s": 412 }`, 502 `{ "error": "brief_failed" }` (hospital page offers "regenerate brief").

### `POST /runs/{run_id}/after-action`
No body. Generates the after-action report for a finished run (Gemini on `GEMINI_TEXT_MODEL`, default `gemini-3-flash-preview`, then `GEMINI_MODEL`; 15 s per attempt), writes `after_action/{run_id}` and returns it. A second call returns the stored doc without calling Gemini; `?regenerate=1` generates and overwrites it.
200 the stored doc (see `after_action/{run_id}`). 404 `{ "error": "unknown_run" }`, 409 `{ "error": "run_not_finished" }` (state is not `ended` or `arrived`), 502 `{ "error": "after_action_failed" }`.

### `POST /location`
```json
{ "run_id": "run-amb-1", "lat": 12.9197, "lng": 77.6204, "speed_mps": 13.2, "heading": 231, "t": "2026-10-05T09:02:30Z", "source": "sim" }
```
`heading` (degrees) and `t` are optional (derived from the previous tick / server time); `source`: `gps | sim`. Optional `tick_id` (`[A-Za-z0-9_.:-]`, 1 to 128 characters), or the same value in an `Idempotency-Key` header (the header wins): a repeat with a key seen for this run in the last 10 minutes returns the first response again with `Idempotent-Replayed: true` and changes nothing (`idempotency/{run_id}/keys/{key}`); the device token is still checked first. A malformed key is 422.
200:
```json
{
  "state": "en_route", "next_junction": "blr_j3", "approach": "NE", "jam_m": 520, "eta_s": 143, "stage": "PREPARE",
  "exit_move": "left", "eta_hospital_s": 412,
  "alerts_fired": [{"junction": "blr_j3", "stage": "PREPARE"}], "brief_due": false, "observed_speed_60s": 13.2, "traffic": "live"
}
```
`next_junction`, `approach`, `jam_m`, `eta_s`, `stage`, `exit_move`, `traffic` describe the nearest junction ahead and are `null` when none is left or the run is `off_route`. Every junction ahead is evaluated each tick (alerts and preemption can fire for a far junction while a nearer one is still to come); `alerts_fired` lists what fired this tick; those alerts are written without voice, which a background task adds after the response (see `runs/{id}/alerts/{n}`). `stage` is `PREPARE | STOP | null`. `exit_move`: `left | straight | right` (Routes manoeuvre at that junction; `straight` when none). `state`: `en_route`, `off_route` (vehicle more than 80 m from the Routes polyline: no junction logic, no preemption; ticks revive `stale` and `off_route` runs) or `arrived` (tick within 100 m of the destination; the report card is written and later ticks get 403). `traffic`: `live | stale | scenario`.
Preemption: when an alert fires and the run qualifies (ambulance with `confirmed_tier` and `patient_on_board`; fire or police with an incident), the contenders for that junction are the other `en_route` runs with it in `ahead_ids`; `priority.sequence` orders them and `junctions/{id}.phase` plus an `audit/` entry are written.
`brief_due` is `true` in the response when this tick found the brief due: it is written right after the response. Queue and ETA per junction are read from the run's one traffic-aware route (Routes call budget below): the route's speed spans are sliced to the 600 m before the junction's stop line (the end of its approach polyline, projected onto the route, and not behind the vehicle) and walked back from the stop line; the ETA is the distance to the junction at the route's average traffic-aware pace, blended with the observed speed.
Side effect: any `/location` call marks other `en_route` runs with no tick for 30 s as `stale` and escalates unacknowledged alerts (the same sweep as `POST /housekeeping`, which also runs without a tick).
403 `{ "error": "run_not_active", "state": "ended" }` (only `en_route`, `off_route`, `stale` runs take ticks), 404 `{ "error": "unknown_run" }`, 400 `{ "error": "unknown_corridor" }`.

### `POST /ack`
```json
{ "run_id": "run-amb-1", "junction_id": "blr_j3", "alert_n": 0, "device_id": "dev-cop-1" }
```
`device_id` is optional. Needs `X-Device-Token`: the on-duty cop's junction token or the run's vehicle token (401 / 403, see Device tokens). Sets `acked_at` (server time) and `ack_latency_s` on `runs/{run_id}/alerts/{alert_n}`; a repeat ACK changes nothing and returns the first values.
200 `{ "ok": true, "acked_at": "2026-10-05T09:03:26Z", "ack_latency_s": 6.2, "latency_s": 6.2 }` (`latency_s` duplicates `ack_latency_s` for the cop page). 404 `{ "error": "unknown_alert" }` (no such alert, or its `junction_id` differs).

### `POST /housekeeping`
No body. The sweep that otherwise piggybacks on `/location`, runnable without any tick: marks `en_route` runs with no tick for 30 s as `stale` (newest 20), and flags every unacknowledged alert older than 20 s as `escalated` (with its `audit/` entry) across the first 200 runs in `en_route`, `off_route` or `stale`. Header `X-Housekeeping-Token` must equal env `HOUSEKEEPING_TOKEN`: 403 `{ "error": "forbidden" }` otherwise; when the env is unset the endpoint is disabled and answers 404 `{ "error": "not_found" }`.
200 `{ "stale": 1, "escalated": 2, "runs_checked": 5 }`.
The token lives in Secret Manager as `corridor-housekeeping-token` and reaches the service through `--set-secrets HOUSEKEEPING_TOKEN=corridor-housekeeping-token:latest` in `deploy-api.yml`. Cloud Scheduler calls it every 30 minutes:
```
gcloud scheduler jobs create http corridor-housekeeping --location asia-south1 --schedule "*/30 * * * *" \
  --uri <API>/housekeeping --http-method POST --headers X-Housekeeping-Token=<secret>
```
Ticks run the same sweeps, so the scheduler only covers idle periods and is spaced to let Cloud Run scale to zero.

### `POST /duty`
```json
{ "corridor": "blr", "junction_id": "blr_j3", "device_id": "dev-cop-1", "on": true, "name": "Constable Rao" }
```
`junction_id` may be `blr_j3` or `j3`; `name` is optional; `fcm_token` (optional, at most 4096 characters) is the browser's FCM registration token: stored on `duty/blr_j3` when `on` is true, never echoed back. Writes `duty/blr_j3`.

**Push.** When an alert is written for a junction whose `duty` doc is `on` and has an `fcm_token`, `finish_alert` (after the voice is attached) sends one FCM message with a `notification` (title `<stage> · emergency vehicle`, body the spoken-language text, else the English text) and a `data` payload of strings: `run_id`, `alert_n`, `junction_id`, `stage`, `text`, `audio_url` (empty when synthesis failed). Web push headers: `Urgency: high`, `TTL: 120`. A failure is logged (`push_error`) and never raised; a token FCM reports as unregistered is removed from the doc. `push_sent` is logged on success. The service account needs `roles/firebasecloudmessaging.admin`.
200 the doc: `{ "device_id": "dev-cop-1", "name": "Constable Rao", "on": true, "since": "2026-10-05T09:00:00Z", "device_token": "<43 characters>" }`; `device_token` is present only when `on` is true and is new every time (see Device tokens). `on: false` needs the header `X-Device-Token` with that junction's token (401 / 403) and answers without a token. 400 `{ "error": "unknown_corridor" }`, 404 `{ "error": "unknown_junction" }`.

### `POST /cop-note`
The on-duty cop's voice back-channel: one spoken or typed report to control. Needs `X-Device-Token` of the cop on duty at that junction (401 / 403, see Device tokens).
```json
{ "corridor": "blr", "junction_id": "blr_j3", "audio_b64": "...", "mime": "audio/webm" }
```
or `"text": "bus stalled, need two more minutes"` instead of audio. `junction_id` may be `blr_j3` or `j3`. Gemini (no tools) only fills a fixed schema: `{ "kind": "delay" | "cleared" | "cannot_clear" | "other", "extra_seconds": int | null, "reason": "<at most 6 words>", "transcript_en": "..." }`, told to treat the report as data. Plain rules then act on it, so a misheard report can at worst extend a green by 3 minutes:

| kind | Effect |
|---|---|
| `delay` | `extra_seconds` (none, zero or negative: 60; capped at 180) is added to the junction's running `phase.until` (a missing or already ended phase is left alone); every alert at that junction of a run still heading there gets `cop_delay_s` and `cop_note`; written to `audit/` as `cop_delay`. If the delay is over 90 s the active alert (the newest unacked one, else the newest) is escalated: `escalated: true`, `escalation_reason: "cop_reported_delay"`, plus an `escalation` audit entry. |
| `cleared` | the newest unacked alert at the junction gets `acked_at`, `ack_latency_s`, `acked_by: "cop-note"` (the same as an ACK); audit `cop_cleared`. |
| `cannot_clear` | the active alert is escalated at once (`cop_cannot_clear`); `cop_block_until` is set to now + 5 min and `phase.blocked: true` when a phase exists; from then on `/location` doubles the junction's clear time (earlier PREPARE, longer green); audit `cop_cannot_clear`. |
| `other` | only the `cop_note` on the alerts and audit `cop_note`. |

An alert the 20 s timer already escalated is not flagged twice. The note is stored at `duty/{junction}/notes/{n}`. Rate limit: the heavy bucket.
200 `{ "n": 0, "kind": "delay", "extra_seconds": 120, "reason": "bus stalled", "transcript_en": "...", "effects": { "phase_extended_s": 120, "acked": 0, "escalated": 1, "blocked_s": 0 }, "action_text": "Green extended by 2 min, escalated" }`. `action_text` is English text for the cop page ("Alert acknowledged", "Escalated: junction cannot clear, earlier warnings for the next 5 min", "Noted", ...). 400 `{ "error": "bad_request" }` (no audio or text, or `audio_b64` not base64) or `unknown_corridor`, 404 `{ "error": "unknown_junction" }`, 422 `{ "error": "extraction_failed", "fallback": "text" }` (nothing is changed).

## Routes call budget

A live run makes **one** Routes `computeRoutes` call (vehicle to hospital, `TRAFFIC_AWARE`, `TRAFFIC_ON_POLYLINE`, with steps) at most every 20 s, cached per run in `route_cache/{run_id}` (shared by every instance, with a short in-memory copy in front; a Firestore error just means a fetch); `/location` ticks in between reuse it (`ROUTE_TTL_S`). That one response carries the hospital ETA, the polyline used for junction and off-route detection, the exit manoeuvres and the `speedReadingIntervals` of the whole route, and every junction ahead reads its own queue out of it (the intervals sliced to the 600 m before its stop line). While `off_route` the route stays pinned and no new call is made. When a call fails, the cached route and spans are reused for 60 s, then the queue reads as NORMAL (`traffic: "stale"`).

| | calls per vehicle-minute |
|---|---|
| before: one hospital call per 30 s plus one call per junction ahead per 20 s (5 junctions on `blr`) | about 17 |
| now: one call per 20 s | about 3 |

Scenario runs make no Routes calls (recorded spans). The routing agent's `eta_to` calls are separate (cached 30 s per origin and destination) and happen only when a tier is confirmed or `/route` is called.

## Dev-only: `OFFLINE_AI=1` and `DEVICE_TOKENS_DISABLED=1`

Local testing without any paid Google call (never set in a deploy workflow; the API logs `{"event": "offline_ai"}` once at startup when it is on). Firestore is still used. With it set: `tts.localize_alert` returns the English text, `tts.speak` returns `(None, text)` so alerts are text only (no Translation, TTS or Storage), `brief.generate` returns a fixed stub (`model: "offline"`), `aar.generate` a fixed summary, issues and recommendations (`model: "offline"`, the timeline is still built from the record), the routing agent returns its rule-based fallback at once (`trace: [{"fallback": "offline_ai"}]`, straight-line ETAs, no Routes call), the preemption `rationale` is skipped, `/cop-note` answers from a stub (text containing "bus": `delay`, 120 s, "bus stalled"; anything else, or audio alone: `cleared`), and `/triage` and `/log` answer 422 `extraction_failed` (set tiers through `/runs/{id}/confirm`). `api/offline_replay.py` replays a scenario against a local API in this mode; start that API with `RATE_LIMIT_DISABLED=1` too (see Rate limits and caps) so the replay is never throttled, and with `DEVICE_TOKENS_DISABLED=1` because the replay sends no device tokens (see Device tokens).

## Operations environment

| Env | Effect |
|---|---|
| `OTEL_ENABLED=1` | Cloud Trace spans via OpenTelemetry (set by `deploy-api.yml`): one per request (not `/health`), one per outgoing httpx call (Gemini, Routes), and manual spans `leadtime`, `priority`, `brief`, `agent.route`, `tts`, `push.send`. Unset, nothing is imported or exported. The service account needs `roles/cloudtrace.agent`. |
| `OTEL_SAMPLE_RATIO` | Share of traces kept, default `1`. |
| `PRODUCTION_MODE=1`, `DISPATCH_TOKEN`, `AGENCY_KEY` | See Production mode above. |
