# Deck screenshots

The PNGs in this folder are grey placeholders. Replace each one with a real capture from https://green-corridor-2026.web.app (same filename, same aspect ratio), then re-export the deck. Use synthetic data only; no real names, plates or keys in frame.

| File | Route | Viewport | State to capture | Used on slide |
|---|---|---|---|---|
| `sim-split.png` | `/sim?corridor=blr` | 1440x810 | Mid-replay of the 3-vehicle scenario, both lanes visible, minutes-saved counter showing a non-zero value | Title, The 20-second demo |
| `vehicle.png` | `/vehicle` | 390x844 (phone) | After voice triage: extracted fields, confirmed tier chip, routed hospital shown | Six screens |
| `cop.png` | `/cop?corridor=blr` | 390x844 (phone) | Cop on duty at Silk Board Junction, PREPARE alert showing, ACK button visible | Six screens |
| `hospital.png` | `/hospital?corridor=blr` | 1280x720 | Live transit log, ATMIST brief and prep checklist, countdown running | Six screens |
| `cop-alert.png` | `/cop?corridor=blr` | 390x844 (phone) | STOP CROSS TRAFFIC stage: queue length in metres and the spoken-text line visible | Lead-time engine |
| `triage-gemini.png` | `/vehicle` | 390x844 (phone) | Voice or monitor-photo input beside the extracted JSON fields and the lookup-derived tier awaiting the one-tap confirm | Where Gemini is load-bearing |
| `agent-trace.png` | `/vehicle` (route panel) | 1280x720 | Agent tool-call trace (required_capabilities, list_hospitals, eta_to) and the chosen hospital | The agent |
| `control.png` | `/control?corridor=hyd` | 1280x720 | Hyderabad corridor selected, run list, junction ACK states, one escalation flag if available | Global by configuration |

`architecture.svg` is source-controlled, not a screenshot; edit it directly.
