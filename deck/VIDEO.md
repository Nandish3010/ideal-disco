# Submission video plan (2:40, seventeen scenes)

Required deliverable for the Google Cloud AI Builder Cup 2026. Judged 40% gen AI and technical, 25% impact, 25% innovation, 10% UX. This file describes the video as recorded. The narration is in [VOICEOVER.txt](VOICEOVER.txt), one paragraph per scene, labelled with the scene id used below. Runtime 2:40, inside the 3:00 limit.

## 1. Premise and arc

**Premise:** an ambulance loses minutes at red lights because nobody at the junction knows it is coming; we tell the right officer early enough, with the real queue and turn, and it runs today without waiting for the signal controller.

The video opens on the result (a replay with a running minutes-saved counter), states the problem on two cards, then walks the same run through the product: vehicle triage, the routing agent, the cop alert and acknowledgement, the cop voice note, junction sequencing, the hospital handover, the control room, the story timeline. It closes on the evaluation, sustainability and honest-limits slides and the links.

Rules decide, Gemini explains: the narration says so where it matters (the triage tier is a lookup table, the cop note is turned into a fixed form and plain rules act on it, the sequencing sentence is only worded by Gemini and validated by the server).

## 2. Scene table (as recorded)

URLs are `https://green-corridor-2026.web.app`. "Card" = a title card from `deck/video-cards/`; "Slide" = a page of `deck/Green-Corridor-Deck.pdf`. The ids match the paragraph labels in VOICEOVER.txt. English only in the demo.

| Scene | Time | On screen | Narration gist |
|---|---|---|---|
| L00 | 0:00-0:11 | `/sim?mode=replay&scenario=blr-two-vehicles`: Replay mode, the Minutes saved counter running. | Can an ambulance cross Bengaluru without stopping at every red? Same ambulance, same traffic, with a green corridor: almost eight minutes saved, in this simulation. |
| L01 | 0:11-0:17 | Card: opener (`00-opener.png`). | We are Green Corridor; the entry warns the constable at the next junction before the siren arrives. |
| L02 | 0:17-0:27 | Card: problem (`01-problem.png`), with the audit statistic. | More than sixty percent of serious emergency calls in Karnataka missed the ten-minute target, per a state audit; the officer at the junction is never told. |
| L03 | 0:27-0:39 | `/sim` replay walk-through: left pane "Today stops at every red", right pane the corridor with the cop warned early, sized to the queue. | Explains the two panes. The traffic is a scripted scenario and the signals are simulated. |
| L04 | 0:39-0:50 | `/vehicle`: the crew's spoken patient description, extracted fields, suggested tier, one-tap confirm. | Gemini on Vertex AI pulls out the fields; a lookup table, not the model, sets the tier; one tap confirms. |
| L05 | 0:50-1:00 | `/vehicle` TraceCard: the routing agent's tool calls and the chosen hospital. | A routing agent built on the Agent Development Kit picks the hospital, calls four tools, a guardrail in code checks the choice, and the whole trace is on screen. |
| L06 | 1:00-1:18 | `/cop`: the PREPARE alert card (about 4 min out, 400 m queue); the phone speaks the alert. | The cop is told to prepare; the phone speaks the alert aloud. |
| L06b | 1:18-1:21 | `/cop`: the ACK tap. | One tap to acknowledge. |
| L07 | 1:21-1:28 | `/cop` voice note: the officer's spoken report becomes a fixed form, and the resulting action. | Gemini fills a fixed form; plain rules decide what happens to the green. |
| L08 | 1:28-1:40 | `/sim` Live, All vehicles: the J3 Junction sequencing card with its sentence. | With three vehicles at one junction, rules set the order: both ambulances first, then the fire engine twelve seconds later. Gemini only words the sentence and the server validates it. |
| L09 | 1:40-1:48 | `/hospital`: the ATMIST brief, "A clinician confirms these values", synthetic-patient banner. | The handover lands before the ambulance does; a clinician confirms every value; the patients are synthetic. |
| L10 | 1:48-1:56 | `/control`: every junction and every acknowledgement. | The control room sees all of it; if nobody answers in twenty seconds, it escalates. |
| L11 | 1:56-2:03 | `/story`: the run as a timeline. | The whole run, as a timeline. |
| L12 | 2:03-2:15 | Slide 13 (validation). | Evaluated on twelve synthetic voice clips: ninety percent field accuracy, a hundred percent tier accuracy; not field results; hundreds of automated tests back it up. |
| L12b | 2:15-2:23 | Slide 15 (sustainability). | Sizing the green to the queue limits idling; the fuel and carbon figures are a sourced illustration, not a measurement. |
| L13 | 2:23-2:32 | Slide 14 (honest limits and what comes next). | Signals are simulated behind an adapter and patients are synthetic; cop alerts are deployable today; real signal controllers plug in next. |
| L14 | 2:32-2:40 | Card: closing (`06-closing.png`) with the app and repo links and QR codes. | Try it at green-corridor-2026 dot web dot app; the code is public on GitHub; thank you. |

Total 2:40 (160 s).

## 3. Notes on specific scenes

- **Sequencing (L08).** The scene shows both critical ambulances getting their green first and the fire engine getting its green 12 s later. That is the rule outcome, not an error: that fire call had no trapped persons, so it ranks below the two critical ambulances. The sentence on the card is template-first (rules build it, Gemini may reword it, the server validates it), so the card may show either wording.
- **Spoken alert (L06).** The constable alert you hear is the real stored MP3 (the same file the cop's phone plays from the media bucket), mixed into the soundtrack under the narration. It is the alert audio the system itself generated and stored, not a line voiced for the video.
- **Honesty lines kept in the narration.** The replay is a scripted scenario (L00, L03: "in this simulation", "a scripted scenario, and signals are simulated"); signals are simulated behind an adapter (L13); patients are synthetic (L09, L13); the eval numbers are on synthetic clips and not field results (L12); the fuel and carbon figures are a sourced illustration (L12b). Do not claim a live-signal integration or a measured field result.

## 4. Setup to reproduce the demo

Before the screen runs (once, then again before each take):

1. Warm the API: open `https://corridor-api-919512130399.asia-south1.run.app/health` until it answers fast (a cold Cloud Run instance adds seconds to every Gemini step), and load `/sim` once so the Google map tiles show.
2. In the repo root with `GOOGLE_APPLICATION_CREDENTIALS` set: `python3 scripts/demo_reset.py --apply` (run without `--apply` first to read the counts). It ends open runs, deletes alerts, audit, reports, briefs and **duty**, closes incidents, clears junction phases and unbinds devices. So after the reset: re-bind phone A (`/vehicle` Bind) and put phone B back on duty (see Devices).
3. Run one full scenario with the cop ACKing: phone B on duty, feeder started from `/sim` Live, tap **ACK** on every alert. This leaves a finished run with alerts, ACKs, a brief and an after-action report for `/story`, `/control` and `/hospital` to show.
4. `python3 scripts/pin_showcase.py --apply` (the script is being added; it pins that finished run so the pages you record show it). Read its dry run first.
5. Then record. Confirm `/health` returns ok and the media bucket MP3s exist.

Devices:

- **Laptop:** 1920x1080, browser at 125%, dark mode, browser language English (India or US) so Maps labels render in English, no bookmarks bar, no extension icons, notifications off (Do Not Disturb). Not signed in anywhere that shows a personal name.
- **Phone A (vehicle):** open `/vehicle`, mic permission granted, built-in screen recorder with mic on, Do Not Disturb.
- **Phone B (cop):** open `/cop`, junction **BTM Udupi Garden Junction** (j3), tap **GO ON DUTY at BTM Udupi Garden Junction** (this unlocks audio), ringer unmuted, media volume high, the **Sound on** toggle showing, screen recorder on. Keep the screen awake. Do the on-duty tap after the reset.
- **Cops on duty at j3 and j4:** besides phone B at j3, put a second device (a laptop tab on `/cop` is enough) on duty at **Gurappanapalya Cross** (j4), so both junctions the ambulance reaches with a real queue are staffed. j1, j2 and j5 stay unstaffed on purpose: their alerts are never acknowledged, so they **escalate by design** after 20 s (`/control` shows the ESCALATED badges). This is expected, not a fault; the after-action report mentions those escalations, so say so in the voiceover or caption if the report is on screen.
- **External mic** for the voiceover and for the EMT line (record the EMT line close to the mic if phone A's mic sounds thin).

Take A, the hero ambulance (L04 to L07 and L09 to L11): the brief is only generated when the run has at least one log entry, so the EMT must speak into the same run the feeder drives.

1. Phone A: bind `KA01AB1234`. Laptop `/dispatch`: **Issue incident ID**. Phone A: paste, **Start run**.
2. Phone A: **Hold to speak** (triage line), **Confirm CRITICAL**; then, in "Log note" mode, "Aspirin three hundred milligrams given, chewed."
3. Laptop `/sim` Live, **One vehicle**, vehicle KA01AB1234, untick "Create runs", paste phone A's run ID into **Run ID**, speed **1x**, **Start**. Cop alerts arrive on phone B in real time: tap **ACK** by hand, then **Hold to report** with "Stalled bus, two more minutes." Capture the TraceCard on `/vehicle`, `/hospital` once the brief has landed, `/control` and `/story`.

Take B, the sequencing scene (L08): all vehicles, one continuous take.

1. Reset again, phone B back on duty.
2. Laptop `/sim` Live: under the feeder card choose **All vehicles**, "Create runs" ticked (default), speed **1x**, **Start**. The live feed is about 8 min long (485 s). Frame the J3 **Junction sequencing** card: both critical ambulances get their green first and the fire engine 12 s later, because that fire call had no trapped persons.

Replay and slides (L00, L03, L01, L02, L12 to L14): the replay needs no reset (`/sim?mode=replay&scenario=blr-two-vehicles`); `/story` needs the pinned finished run from the checklist above; the title cards come from `deck/video_cards.py` and the slides from the submission deck (`deck/build_deck.py`).

Publishing: export H.264 MP4, 1080p, under 3:00 (this cut is 2:40). Upload to YouTube as unlisted; put the link on the submission deck's Links slide (edit the Links entry in `DATA` in `deck/build_deck.py`, rebuild the PDF) and in the submission form.

## 5. Fallback if a live step fails

- **Anything visual:** use Replay mode (`/sim`). It runs entirely from the scenario file in the browser, needs no Gemini or Firestore, and shows the same split, queues, sequencing order and minutes saved. L08's sentence needs the live Junction sequencing card, so do not substitute the Replay template line.
- **Spoken alert (L06):** if phone B stays silent or the alert is late, open the latest alert's `audio_url` MP3 from the media bucket (`green-corridor-2026-media`) and play it next to the alert card; it is the same file the cop's phone plays.
- **EMT extraction (L04):** if the audio extraction is slow, use the **Type instead** box with the same sentence (same path), or record again. Do not leave a spinner.
- **Brief (L09):** if the brief does not land, press **Regenerate brief** once; if it still fails, use a brief from an earlier good run.
- Keep the honest line in every version: signals in this demo are simulated; cop alerts are deployable today. Do not claim a live-signal integration, and do not claim a measured field result for the minutes-saved number.

## 6. Do-not-show list

| Do not show | How to avoid it |
|---|---|
| Kannada or Telugu text (judges may not read it) | Alerts default to English (`ALERT_LANG=en`). Set the laptop browser language to English so Maps labels are English; keep the app in English. Zoom the map past areas with local-script labels, or crop. Check every frame before export. |
| Stale test data | Run `scripts/demo_reset.py --apply` before each take. It keeps old incident documents, so the `/dispatch` "Last 10 incidents" list still has history: record only the form and the new ID card, crop the list. Reset also clears `/control` of old report cards. |
| The Maps SVG fallback ("Map preview (SVG fallback)" under the `/sim` legend) | It appears when the Maps key is missing in the build. Load `/sim` once before recording and confirm the Google map tiles show and the legend line is absent. Never record from a local preview without the key. |
| Long spinners ("Thinking...", "Loading...", brief generation of 5 to 10 s) | Warm `/health` first, rehearse until Gemini is warm, reload the page before the take, trim the wait in the edit and say what happened in a caption. Where a wait is real, jump-cut. |
| Placeholders and dev leftovers | Crop the "Call junction (placeholder)" button in the escalation banner, close the "debug" details on `/cop`, hide the console, keep the address bar out of the frame, and avoid 501 or "not implemented" cards. |
| Personal or real data | Synthetic patients only; keep the "Demo: synthetic patients only" banner. No personal names in the browser profile, no notifications on the phones, no real plate numbers other than the registry's. |
