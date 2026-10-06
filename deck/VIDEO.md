# Submission video plan (3:00)

Required deliverable for the Google Cloud AI Builder Cup 2026. Judged 40% gen AI and technical, 25% impact, 25% innovation, 10% UX. The voiceover is in [VOICEOVER.txt](VOICEOVER.txt); words and timings there match the shot rows below.

## 1. Premise and arc

**Premise:** an ambulance loses minutes at red lights because nobody at the junction knows it is coming; we tell the right officer early enough, with the real queue and turn, and the whole thing runs today without waiting for the signal controller.

| Beat | Time | What the viewer feels | Shots |
|---|---|---|---|
| Problem and the 20-second proof | 0:00-0:20 | "That is a lot of minutes." Same ambulance, same traffic, two lanes, a counter running. | 1 |
| How | 0:20-2:04 | Gemini hears the crew, rules set the tier, the cop's phone speaks, queues size the alert, a fire engine and an ambulance are ordered. | 2-9 |
| Trust | 2:04-2:38 | Clinician confirms, hospital is ready, nothing is hidden, nobody is left unacknowledged. | 10-11 |
| Scale | 2:38-3:00 | One click to another city, then the honest path from cop alerts today to a learning controller. | 12-14 |

Judge map: gen AI and technical (shots 4, 5, 9, 10: audio extraction, ADK routing trace, Gemini rationale, ATMIST brief; rules decide, Gemini explains), impact (1, 6, 7, 11), innovation (6, 7, 8, 12), UX (the single-tap and giant-button moments in 4, 6).

## 2. Shot list

URLs are `https://green-corridor-2026.web.app`. "Laptop" = screen recording of the browser at 1920x1080. "Phone A" = vehicle phone, built-in screen recorder. "Phone B" = cop phone, built-in screen recorder with the speaker audible. Voiceover (VO) text is the same as in VOICEOVER.txt.

| # | Time | On screen (route and state) | Device | VO | Caption |
|---|---|---|---|---|---|
| 1 | 0:00-0:20 | `/sim?mode=replay&scenario=blr-two-vehicles`. Replay mode, scenario `blr-two-vehicles`, speed `50x`, press **Play** at 0:00 (the ~7.5 min scenario then finishes in about 9 s; if the build lacks 50x, drag the Replay time slider to 60 % first, keep `20x`, press **Play** and let it run to the end). Left pane "Today stops at every red", right pane "With corridor green ahead, no stops". The **Minutes saved** counter runs from 0.0 and is still ticking at 0:18. Hold the final value for 2 s. Keep the line "simulated estimate" in frame. | Laptop | "On the left, an ambulance across Bengaluru today, stopping at every red. On the right, the same ambulance in the same traffic with a green corridor, and the minutes saved are counting up." | "Same ambulance. Same traffic. N min saved." (N = the number on screen, rounded; add "simulated estimate, scripted scenario") |
| 2 | 0:20-0:30 | `/vehicle` section "1. Bind this device". Type `KA01XX9999`, tap **Bind**: red card "Unregistered vehicle ... No run can start." Then clear, type `KA01AB1234`, tap **Bind**: green card "KA01AB1234 bound, Type: ambulance". | Phone A | "Only registered vehicles can start. An unknown plate is turned away." | "Unregistered plate: refused" then "Registered ambulance: bound" |
| 3 | 0:30-0:38 | Laptop `/dispatch`: type `medical`, note `chest pain, adult`, **Issue incident ID**, ID appears (cut here). Phone A `/vehicle` "2. Start run": paste the ID, tap **Start run**, state shows `en_route` and the tier pill "Tier not confirmed". | Laptop, then Phone A | "Dispatch opens an incident, and the crew starts a run against it." | "Registered plate + open incident + audit trail" |
| 4 | 0:38-0:58 | Phone A `/vehicle` "3. Patient". Hold **Hold to speak** and say, in English, conversationally (about 10 s): "Male, around fifty-five, chest pain for forty minutes, BP ninety over sixty, pulse one-ten, saturation ninety-four." Show "Listening", then "Thinking...", then Transcript (English), extracted fields tagged "in transcript", **Suggested tier CRITICAL**, then one tap on **Confirm CRITICAL** until it reads "Confirmed CRITICAL". Cut the Thinking wait to under 1.5 s. | Phone A (mic on, the spoken line must be audible) | (silent while the EMT speaks) then "We turn the speech into fields, a lookup table sets the tier, and one tap from the crew confirms it." | "Gemini on Vertex AI hears it. A lookup table sets the tier. The crew confirms." |
| 5 | 0:58-1:08 | Terminal, dark theme, large font (about 20 pt), one prepared command already typed: `curl -s -X POST $API/route -H 'content-type: application/json' -d '{"run_id":"<run>"}' \| jq -r '.destination, .trace[].text'`. Run it. Output lists the tool calls ending in `called eta_to(Jayadeva Institute of Cardiovascular Sciences) -> 394 s` (use the number that actually prints, and make the caption match). | Laptop (terminal) | "A routing agent then picks the hospital, and you can see exactly which tools it called." | "Google ADK agent: called eta_to(Jayadeva) -> 394 s" |
| 6 | 1:08-1:28 | Phone B `/cop`, on duty at BTM Udupi Garden Junction. The PREPARE alert card fills the screen (queue in metres, "turning LEFT", "arrives in about 4 min"). The phone speaks the alert aloud, full line, audio at normal level. Then a thumb taps the giant **ACK** button; the card changes to ACK with latency. Optional 3 s cutaway: a second phone or webcam filming Phone B so the speaker is visible. | Phone B (screen recording with audio); optional phone-filming-phone | (silent while the alert plays) then "The officer hears it, not just reads it, and taps ACK." | "Cop alert, spoken, in the junction's language" |
| 7 | 1:28-1:42 | Laptop `/sim` Live mode. Split in the edit: left, the J3 approach with a long red tail and the first alert line in the feed ("PREPARE", ~400 m queue, about 4 min out); right, the J4 approach with a short tail and its later alert ("1 min out"). Both pulled from the same run (one take, two moments). | Laptop | "A long queue means an early alert. A short queue means a late one, so nobody is called out sooner than they need to be." | "J3: long queue, alert 4 min out. J4: short queue, alert 1 min out" |
| 8 | 1:42-1:54 | `/sim` Live, All vehicles at `1x`. The fire engine (F) appears from the cross street (south approach) toward J3 while the ambulance (A) closes on the east approach; J3 turns green for the fire approach first; both markers clear J3 one after the other. Optionally show a second ambulance behind the first sharing the green. | Laptop | "A fire engine joins from the cross street. Rules set the order, so the fire engine goes first and the ambulance gets its green twelve seconds later." | "Fire first, ambulance 12 s later. Both pass." |
| 9 | 1:54-2:04 | During the Session 2 live take, `/sim` Live: the "Junction sequencing" card for J3 showing the one-line rationale sentence (or the J3 card on `/control`). The rationale is validated server-side and falls back to a template if the model's sentence fails the check, so the card may show the template wording; say so in the voiceover. The Replay-mode "fire engine first, ambulance 12 s later" line is a client-side template, so do not use it for this shot. Then a 4 s insert: Firebase console, Firestore `junctions/blr_j3`, field `phase.rationale` (Gemini's one-line reason). | Laptop | "The rules choose the order; the model writes the sentence, and the system checks it." | "Rules decide. Gemini explains. The system checks." |
| 10 | 2:04-2:24 | `/hospital` for Jayadeva Institute of Cardiovascular Sciences. First the Transit log: the crew's second note shows an **aspirin 300 mg** chip beside the vitals. Then the Brief card goes from "Brief arrives when the ambulance is 5 minutes out" to the ATMIST rows, summary, prep checklist, and the line "A clinician confirms these values." Keep the "Demo: synthetic patients only" banner in frame. | Laptop | "The hospital sees the live log, and the brief lands before the ambulance does, for a clinician to confirm." | "Brief ready 5 min before arrival. Synthetic patient." |
| 11 | 2:24-2:38 | `/control`, corridor `blr`. The **Junction board** with J3 showing "GREEN for ..." and ACKed latency, then the red "ESCALATED, no ACK in 20 s" banner for J4 (no cop is on duty there). Frame so the "Call junction (placeholder)" button is cropped out. | Laptop | "The control room sees every junction. If nobody acknowledges within twenty seconds, it is flagged." | "No ACK in 20 s: flagged to the control room" |
| 12 | 2:38-2:44 | `/control`, open the **Corridor** select and choose `hyd · Gachibowli -> Continental Hospitals`. Map and junction board switch to Hyderabad in one click. | Laptop | "A corridor is just configuration, so this is Hyderabad, one click later." | "Corridor = config. Bengaluru and Hyderabad." |
| 13 | 2:44-2:56 | Deck slide "Deployment path", three steps, one highlighted at a time: **Today: cop alerts** / **Next: real signal data through the SignalAdapter** / **Then: a controller that learns from logged junction data**. A small tag on the first step: "Signals in this demo are simulated." | Deck (slide export) | "Signals here are simulated. Cop alerts can be deployed today; real signal data plugs into an adapter next, then a controller that learns from our junction data." | "Today: cop alerts. Next: signal adapter. Then: learning controller." |
| 14 | 2:56-3:00 | End card, plain background: project name, `green-corridor-2026.web.app`, repo link, "Google Cloud AI Builder Cup 2026". | Deck (still) | "Try it at green-corridor-2026 dot web dot app." | "green-corridor-2026.web.app" |

Rules of the cut: no cut longer than 1.5 s hides a wait; where a wait is real (Gemini, brief), jump-cut and keep a caption that says what happened. Native audio (EMT in 4, spoken alert in 6) plays at full level and the voiceover ducks, it never talks over them.

## 3. Recording checklist

Before anything (once, then again before each take):

1. In the repo root with `GOOGLE_APPLICATION_CREDENTIALS` set: `python3 scripts/demo_reset.py --apply` (run without `--apply` first to read the counts). It ends open runs, deletes alerts, audit, reports, briefs and **duty**, closes incidents, clears junction phases and unbinds devices. So after every reset: re-bind phone A (`/vehicle` Bind) and put phone B back on duty.
2. Confirm the deployed build is the `submission` tag (`/health` returns ok) and the media bucket MP3s exist.

Devices:

- **Laptop:** 1920x1080, browser at 125%, dark mode, browser language set to English (India or US) so Maps labels render in English, no bookmarks bar, no extensions icons, notifications off (Do Not Disturb). Browser signed in nowhere that shows a personal name.
- **Phone A (vehicle):** open `/vehicle`, mic permission granted, built-in screen recorder with mic on, Do Not Disturb.
- **Phone B (cop):** open `/cop`, junction **BTM Udupi Garden Junction**, tap **GO ON DUTY at BTM Udupi Garden Junction** (this unlocks audio), ringer unmuted, media volume high, the **Sound on** toggle showing, screen recorder on. Keep the screen awake. Do the on-duty tap after the reset.
- **External mic** for the voiceover and for the EMT line (record the EMT line close to the mic if phone A's mic sounds thin; either is fine as long as it is clear).

Session 1, the hero ambulance (shots 2 to 6, 10): the brief is only generated when the run has at least one log entry, so the EMT must speak into the same run the feeder drives.

1. Reset (step 1 above). Phone B on duty.
2. Phone A: bind `KA01XX9999` (rejected, shot 2), then `KA01AB1234`. Laptop `/dispatch`: **Issue incident ID**. Phone A: paste, **Start run**.
3. Phone A, screen recording on: **Hold to speak** (triage line, shot 4), **Confirm CRITICAL**. Then, in "Log note" mode, hold to speak a second line: "Aspirin three hundred milligrams given, chewed." (the chip in shot 10).
4. Laptop `/sim` Live, **One vehicle**, vehicle KA01AB1234, untick the "Create runs" checkbox, paste phone A's run ID into the **Run ID** box, speed **1x**, **Start**. Cop alerts arrive on phone B in real time (first PREPARE about 1:45 into the run, scenario clock). Record phone B, the `/hospital` page and, once the brief has landed, the terminal for shot 5.

Session 2, the junction and sequencing beats (shots 7, 8, 9, 11): all vehicles, one continuous take.

1. Reset again. Phone B back on duty.
2. Laptop `/sim` Live: under the feeder card choose **All vehicles**, make sure "Create runs" is ticked (it is by default; it starts each run and confirms the ambulance tier for you), speed **1x**, **Start**. The scenario is about 7.5 min long: the fire engine enters at +311 s and the second ambulance (KA01AB4321, urgent) at +40 s. If you triage that one by voice, the line is a stroke case, so the agent and the scenario agree on Jayadeva (it has a stroke unit): "68 year old female, sudden left-side weakness and slurred speech 20 minutes ago, BP 170 over 100, conscious." Record `/sim` full time; record `/control` in a second window or run a second pass.
3. Leave J4 without a cop (nobody goes on duty there) so its alert goes unacknowledged and escalates after 20 s.

Replay and Hyderabad (shots 1, 12): need no reset. `/sim?mode=replay&scenario=blr-two-vehicles`, pick **50x** for shot 1; shot 9 is recorded from the live `/sim` or `/control` card during Session 2; shot 12 is a click on the Corridor select in `/control`.

Recorder settings: macOS QuickTime or OBS, 1920x1080, 60 fps for the laptop; phones' built-in recorder (mic on for phone A and for any spoken-alert pickup, check that the alert audio is captured on phone B before the real take). Captions are burned in during the edit. No music. One take per beat, assemble in iMovie or DaVinci Resolve, export H.264 MP4, 1080p, 3:00 or under (target 2:55 to leave margin). Upload to YouTube as unlisted; put the link in the last slide of the deck (`deck/slides.md`, placeholder "[link, 3 minutes]") and in the submission form.

## 4. Fallback plan

If a live beat fails on the day (Gemini slow, alert late, mic blocked):

- **Anything visual:** use Replay mode for every on-screen beat. It runs entirely from the scenario file in the browser, needs no Gemini or Firestore, and shows the same split, queues, sequencing order and minutes saved (shots 1, 7, 8 work from `/sim` Replay; shot 9 needs the live rationale text, so do not substitute the Replay template line).
- **Spoken alert (shot 6):** if phone B stays silent or the alert is late, open the latest alert's `audio_url` MP3 from the media bucket (`green-corridor-2026-media`), play it on the laptop or phone B next to the alert card, and record that. Say it is the same file the cop's phone plays.
- **EMT extraction (shot 4):** if the audio extraction is slow, use the **Type instead** box with the same sentence (it goes through the same path); or record the take again after a second attempt. Do not leave a spinner.
- **Brief (shot 10):** if the brief does not land, press **Regenerate brief** once; if it still fails, use a brief from an earlier good run and say so in the editing notes.
- Keep the honest line in every version: "Signals in this demo are simulated; cop alerts are deployable today." Do not claim a live-signal integration, and do not claim a measured field result for the minutes-saved number.

## 5. What Nandish does by hand, and what is pre-recorded

By hand, in order:

1. Run the reset script (dry run, then `--apply`) and check `/health`.
2. Set up the three devices as listed in section 3 (laptop settings, phone A, phone B on duty).
3. Record shot 1: Replay at 50x on `/sim`, read the final minutes-saved value and write it into the caption.
4. Record shots 2 and 3: bind the unknown plate, then the registered one, issue the incident, start the run.
5. Record shot 4: speak the triage line into phone A, tap **Confirm CRITICAL**; then speak the aspirin log line.
6. Start the Session 1 feeder with phone A's run ID at 1x; record phone B (shot 6, tap **ACK** by hand), `/hospital` (shot 10) and the terminal (shot 5).
7. Reset, put phone B back on duty, run Session 2 with **All vehicles** at 1x; record shots 7, 8, 9, 11.
8. Record the Firebase console insert for shot 9 and shot 12 (one click to Hyderabad).
9. Record the voiceover from VOICEOVER.txt with the external mic, one paragraph per shot.
10. Assemble, add burned-in captions, export, upload unlisted to YouTube, paste the link into the deck and the submission.

Pre-recorded or prepared: the scripted scenario file (generated GPS ticks, hand-authored traffic spans: `data/scenarios/blr-two-vehicles.json`), the deck slides for shots 13 and 14, the end card, the MP3 alert audio in the media bucket as the fallback, and the minutes-saved figure (computed, not measured).

## 6. Do-not-show list

| Do not show | How to avoid it |
|---|---|
| Kannada or Telugu text (judges may not read it) | Alerts default to English (`ALERT_LANG=en`; do not set `kn`). Set the laptop browser language to English so Maps labels are English; do not use the Kannada UI strings. Zoom the map past areas with local-script labels, or crop. Check every frame before export. |
| Stale test data | Run `scripts/demo_reset.py --apply` before each take. It keeps old incident documents, so the `/dispatch` "Last 10 incidents" list still has history: record only the form and the new ID card, crop the list. Clear `/control` of old report cards by resetting (it deletes them). |
| The Maps SVG fallback ("Map preview (SVG fallback)" under the `/sim` legend) | It appears when the Maps key is missing in the build. Load `/sim` once before recording and confirm the Google map tiles show and the legend line is absent. Never record from a local preview without the key. |
| Long spinners ("Thinking...", "Loading...", brief generation of 5 to 10 s) | Rehearse until Gemini is warm; trim the wait in the edit and say what happened in a caption; reload the page before the take so it is not cold. Where a wait is real, jump-cut. |
| Placeholders and dev leftovers | Crop the "Call junction (placeholder)" button in the escalation banner, close the "debug" details on `/cop`, hide the console, keep the address bar out of the frame for terminal and phone shots, and avoid 501 or "not implemented" cards. |
| Personal or real data | Synthetic patients only; keep the "Demo: synthetic patients only" banner. No personal names in the browser profile, no notifications on the phones, no real plate numbers other than the registry's. |
