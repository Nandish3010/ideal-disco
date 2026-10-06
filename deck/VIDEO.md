# Submission video plan (3:00, nine beats)

Required deliverable for the Google Cloud AI Builder Cup 2026. Judged 40% gen AI and technical, 25% impact, 25% innovation, 10% UX. The voiceover is in [VOICEOVER.txt](VOICEOVER.txt); words and timings there match the beat rows below. Target runtime 2:55 so there is margin under the 3:00 limit.

## 1. Premise and arc

**Premise:** an ambulance loses minutes at red lights because nobody at the junction knows it is coming; we tell the right officer early enough, with the real queue and turn, and it runs today without waiting for the signal controller.

| Beat | Time | What the viewer feels | Judge map |
|---|---|---|---|
| 1 Statistic card | 0:00-0:03 | The stakes, in one line. | impact |
| 2 With vs without replay | 0:03-0:23 | "That is a lot of minutes." Same ambulance, same traffic, a counter running. | impact, innovation |
| 3 Plate check, EMT voice, tier | 0:23-0:50 | Only a registered vehicle starts; Gemini hears the crew, a lookup table sets the tier, one tap confirms. | gen AI and technical, UX |
| 4 Monitor photo | 0:50-0:54 | The crew can photograph the monitor instead of reading it out. | gen AI and technical |
| 5 Cop phone speaks, ACK | 0:54-1:14 | The officer hears the alert and taps one giant button. | impact, UX |
| 6 Cop voice note, green extends | 1:14-1:34 | A spoken report from the junction changes the green, by rule. | gen AI and technical, innovation |
| 7 Fire engine sequencing | 1:34-1:58 | Rules order two vehicles; Gemini only words the sentence. | innovation, gen AI and technical |
| 8 Hospital brief | 1:58-2:20 | The routing agent shows its tools, the brief lands before the ambulance. | gen AI and technical |
| 9 Story and closing card | 2:20-2:55 | The whole run as a timeline, then "From constable to controller" and a QR code. | impact, innovation |

Rules decide, Gemini explains: the voiceover says so once (beat 7) and the shots show it (tier lookup in 3, rule actions in 6, template-first sentence in 7).

## 2. Shot list

URLs are `https://green-corridor-2026.web.app`. "Laptop" = screen recording of the browser at 1920x1080. "Phone A" = vehicle phone, built-in screen recorder with mic. "Phone B" = cop phone, built-in screen recorder with the speaker audible. Voiceover (VO) text is the same as in VOICEOVER.txt. **English only in the demo** (project rule): the language toggle appears only in the optional shot 5b.

| # | Time | On screen (route and state) | Device | VO | Caption |
|---|---|---|---|---|---|
| 1 | 0:00-0:03 | Plain statistic card, one line on how much time emergency vehicles lose at red lights, with its public source on the card. Use a figure you can cite; if none can be sourced, use the replay's own number instead ("N min saved, simulated estimate") so nothing is invented. | Deck (still) | (none, or the VO's first half-sentence over the end of the card) | the statistic and its source |
| 2 | 0:03-0:23 | `/sim?mode=replay&scenario=blr-two-vehicles`. Replay mode, speed `50x`, press **Play** at 0:03 (the 16:10 replay timeline finishes in about 19 s; if the build lacks 50x, drag the Replay time slider to 60 % first, keep `20x`, press **Play** and let it run to the end). Left pane "Today stops at every red", right pane "With corridor green ahead, no stops". The **Minutes saved** counter runs from 0.0 and is still ticking at 0:20. Hold the final value for 1 s. Keep the line "simulated estimate" in frame. | Laptop | "On the left, an ambulance across Bengaluru today, stopping at every red. On the right, the same ambulance in the same traffic with a green corridor, and the minutes saved are counting up." | "Same ambulance. Same traffic. N min saved." (N = the number on screen, rounded; add "simulated estimate, scripted scenario") |
| 3 | 0:23-0:50 | Phone A `/vehicle`. Bind `KA01XX9999`: red card "Unregistered vehicle ... No run can start." Cut. Then (run already started on a dispatched incident, off camera) hold **Hold to speak** and say in English, about 10 s: "Male, around fifty-five, chest pain for forty minutes, BP ninety over sixty, pulse one-ten, saturation ninety-four." Show "Listening", "Thinking...", the Transcript, extracted fields tagged "in transcript", **Suggested tier CRITICAL**, then one tap on **Confirm CRITICAL** until it reads "Confirmed CRITICAL". Cut the Thinking wait to under 1.5 s. | Phone A (mic on, the spoken line must be audible) | "An unknown plate is turned away." (silent while the EMT speaks) "Gemini turns the speech into fields, a lookup table sets the tier, and one tap from the crew confirms it." | "Unregistered plate: refused" then "Gemini on Vertex AI hears it. A lookup table sets the tier. The crew confirms." |
| 4 | 0:50-0:54 | Phone A `/vehicle`, the **Monitor photo** option: a photo of a vitals monitor goes in, the fields come back tagged "from photo". Four seconds, jump-cut the wait. | Phone A | (silent) | "Or photograph the monitor." |
| 5 | 0:54-1:14 | Phone B `/cop`, on duty at BTM Udupi Garden Junction. The PREPARE alert card fills the screen (queue in metres, "going STRAIGHT", "arrives in about 4 min"). The phone speaks the alert aloud, full line, audio at normal level. A thumb taps the giant **ACK** button; the card changes to ACK with latency. Optional 3 s cutaway: a second phone or webcam filming Phone B so the speaker is visible. | Phone B (screen recording with audio) | (silent while the alert plays) "The officer hears it, not just reads it, and taps ACK." | "Cop alert, spoken. One tap to acknowledge." |
| 5b | optional, 3 s after 5 | Phone B `/cop`, tap the language toggle to Kannada, the alert card re-renders in Kannada, English subtitle burned in ("Prepare: ambulance in about 4 minutes, queue 400 m"). **Optional**: include only if the cut is under 2:55 without it; drop it first if runtime is tight. The rest of the demo stays English. | Phone B | (silent) | English subtitle of the Kannada alert |
| 6 | 1:14-1:34 | Phone B `/cop`, **Hold to report**: the officer says "Stalled bus, two more minutes." The card shows the extracted action (extra seconds) and J3 on `/sim` or `/control` shows the green extended. Frame the rule outcome, not the model. | Phone B, then Laptop | "A spoken report from the junction fills a fixed form, and plain rules extend the green." | "Cop voice note. Rules act on it." |
| 7 | 1:34-1:58 | `/sim` Live, All vehicles at `1x`. The fire engine (F) joins from the cross street toward J3 while the ambulance (A) closes on the east approach; J3 turns green for the fire approach first; both clear J3 one after the other. Then hold on the **Junction sequencing** card for J3 and read its sentence aloud, word for word (it is template-first: the rules build it, Gemini may reword it, the server validates it, so the card may show either wording). Do not use the Replay-mode template line for this shot. | Laptop | "A fire engine joins from the cross street. Rules set the order, so it goes first and the ambulance gets its green twelve seconds later." then read the sentence on the card. "Rules decide. Gemini explains." | "Fire first, ambulance 12 s later. Both pass." then "Rules decide. Gemini explains. The system checks." |
| 8 | 1:58-2:20 | First 4 s: `/vehicle` **TraceCard** (the in-app routing trace): the agent's tool calls ending in the chosen hospital and its ETA (use the number that actually shows, make the caption match). Then `/hospital` for Jayadeva Institute of Cardiovascular Sciences: the Transit log with the aspirin chip (optional), then the Brief card goes from "Brief arrives when the ambulance is 5 minutes out" to the ATMIST rows, summary, prep checklist and "A clinician confirms these values." Keep the "Demo: synthetic patients only" banner in frame. | Laptop | "A routing agent picks the hospital, and the trace shows every tool it called. The brief lands before the ambulance does, for a clinician to confirm." | "Google ADK agent trace. Brief ready 5 min before arrival. Synthetic patient." |
| 9 | 2:20-2:55 | `/story`: the run as a timeline, scroll slowly through it (about 15 s). Then the closing card "From constable to controller" with the QR code to `green-corridor-2026.web.app` and the repo link, "Google Cloud AI Builder Cup 2026" (about 15 s, hold the last 3 s). Keep a small tag "Signals in this demo are simulated." on the card. | Laptop, then card (still) | "Here is the whole run as a timeline. Signals here are simulated; cop alerts can be deployed today, and real signal data plugs into an adapter next. From constable to controller. Try it at green-corridor-2026 dot web dot app." | "From constable to controller" and the URL |

Rules of the cut: no cut longer than 1.5 s hides a wait; where a wait is real (Gemini, brief), jump-cut and keep a caption that says what happened. Native audio (EMT in 3, spoken alert in 5) plays at full level and the voiceover ducks, it never talks over them. The terminal `curl` and Firebase console shots are gone: the routing trace comes from the in-app TraceCard and the sequencing sentence from the live Junction sequencing card.

## 3. Recording checklist

Before anything (once, then again before each take):

1. Warm the API: open `https://corridor-api-919512130399.asia-south1.run.app/health` until it answers fast (a cold Cloud Run instance adds seconds to every Gemini beat), and load `/sim` once so the Google map tiles show.
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

Take A, the hero ambulance (beats 3 to 6 and 8): the brief is only generated when the run has at least one log entry, so the EMT must speak into the same run the feeder drives.

1. Phone A: bind `KA01XX9999` (rejected), then `KA01AB1234`. Laptop `/dispatch`: **Issue incident ID**. Phone A: paste, **Start run**.
2. Phone A, screen recording on: **Hold to speak** (triage line), **Confirm CRITICAL**; then the **Monitor photo** shot; then, in "Log note" mode, "Aspirin three hundred milligrams given, chewed."
3. Laptop `/sim` Live, **One vehicle**, vehicle KA01AB1234, untick "Create runs", paste phone A's run ID into **Run ID**, speed **1x**, **Start**. Cop alerts arrive on phone B in real time (first PREPARE about 1:45 into the run, scenario clock). Record phone B (tap **ACK** by hand), then **Hold to report** with "Stalled bus, two more minutes." and the J3 green on `/sim` or `/control`. Record the TraceCard on `/vehicle` and, once the brief has landed, `/hospital`.

Take B, the sequencing beat (beat 7): all vehicles, one continuous take.

1. Reset again, phone B back on duty.
2. Laptop `/sim` Live: under the feeder card choose **All vehicles**, "Create runs" ticked (default), speed **1x**, **Start**. The live feed is about 8 min long (485 s): the fire engine enters at +311 s and the second ambulance (KA01AB4321, a critical stroke case) at +40 s. Record `/sim` full time and the J3 **Junction sequencing** card.

Replay, story and closing card (beats 1, 2, 9): need no reset. `/sim?mode=replay&scenario=blr-two-vehicles` at **50x** for beat 2; `/story` for beat 9 (it needs the pinned finished run from the checklist above); the statistic card and the closing card come from the submission deck (`deck/build_deck.py`).

Recorder settings: macOS QuickTime or OBS, 1920x1080, 60 fps for the laptop; phones' built-in recorder (mic on for phone A and for any spoken-alert pickup, check that the alert audio is captured on phone B before the real take). Captions are burned in during the edit. No music. One take per beat, assemble in iMovie or DaVinci Resolve, export H.264 MP4, 1080p, 3:00 or under (target 2:55). Upload to YouTube as unlisted; put the link on the submission deck's Links slide (edit the Links entry in `DATA` in `deck/build_deck.py`, rebuild the PDF) and in the submission form.

## 4. Fallback plan

If a live beat fails on the day (Gemini slow, alert late, mic blocked):

- **Anything visual:** use Replay mode (`/sim`). It runs entirely from the scenario file in the browser, needs no Gemini or Firestore, and shows the same split, queues, sequencing order and minutes saved (beats 2 and 7). Beat 7's sentence needs the live Junction sequencing card, so do not substitute the Replay template line.
- **Spoken alert (beat 5):** if phone B stays silent or the alert is late, open the latest alert's `audio_url` MP3 from the media bucket (`green-corridor-2026-media`), play it next to the alert card, and say it is the same file the cop's phone plays.
- **EMT extraction (beat 3):** if the audio extraction is slow, use the **Type instead** box with the same sentence (same path), or record again after a second attempt. Do not leave a spinner.
- **Brief (beat 8):** if the brief does not land, press **Regenerate brief** once; if it still fails, use a brief from an earlier good run and say so in the editing notes.
- Keep the honest line in every version: "Signals in this demo are simulated; cop alerts are deployable today." Do not claim a live-signal integration, and do not claim a measured field result for the minutes-saved number.

## 5. What Nandish does by hand, and what is pre-recorded

By hand, in order:

1. Warm `/health`, run `demo_reset.py` (dry run, then `--apply`), run one scenario with the cop ACKing, then `pin_showcase.py --apply`.
2. Set up the three devices as listed in section 3 (laptop settings, phone A, phone B on duty).
3. Record beat 2: Replay at 50x on `/sim`, read the final minutes-saved value and write it into the caption.
4. Record take A: beats 3 to 6 and the trace and brief of beat 8.
5. Record take B: beat 7.
6. Record `/story` for beat 9, and optionally the Kannada toggle (5b).
7. Record the voiceover from VOICEOVER.txt with the external mic, one paragraph per beat.
8. Assemble, add burned-in captions, export, upload unlisted to YouTube, add the link to the submission deck via `build_deck.py` and to the submission form.

Pre-recorded or prepared: the scripted scenario file (`data/scenarios/blr-two-vehicles.json`: generated GPS ticks, hand-authored traffic spans), the statistic card and closing card (with QR), the MP3 alert audio in the media bucket as the fallback, and the minutes-saved figure (computed, not measured).

## 6. Do-not-show list

| Do not show | How to avoid it |
|---|---|
| Kannada or Telugu text outside the optional beat 5b (judges may not read it) | Alerts default to English (`ALERT_LANG=en`). Set the laptop browser language to English so Maps labels are English; keep the app in English except in 5b, where the English subtitle is burned in. Zoom the map past areas with local-script labels, or crop. Check every frame before export. |
| Stale test data | Run `scripts/demo_reset.py --apply` before each take. It keeps old incident documents, so the `/dispatch` "Last 10 incidents" list still has history: record only the form and the new ID card, crop the list. Reset also clears `/control` of old report cards. |
| The Maps SVG fallback ("Map preview (SVG fallback)" under the `/sim` legend) | It appears when the Maps key is missing in the build. Load `/sim` once before recording and confirm the Google map tiles show and the legend line is absent. Never record from a local preview without the key. |
| Long spinners ("Thinking...", "Loading...", brief generation of 5 to 10 s) | Warm `/health` first, rehearse until Gemini is warm, reload the page before the take, trim the wait in the edit and say what happened in a caption. Where a wait is real, jump-cut. |
| Placeholders and dev leftovers | Crop the "Call junction (placeholder)" button in the escalation banner, close the "debug" details on `/cop`, hide the console, keep the address bar out of the frame, and avoid 501 or "not implemented" cards. |
| Personal or real data | Synthetic patients only; keep the "Demo: synthetic patients only" banner. No personal names in the browser profile, no notifications on the phones, no real plate numbers other than the registry's. |
