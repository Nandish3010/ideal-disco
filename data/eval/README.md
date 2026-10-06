# Evaluation Clips

Record 10 audio clips (≤ 20 seconds each) as realistic Bengaluru EMT voice memos. Use conversational English or Kannada-English mix as naturally spoken. Audio format: `.m4a` or `.wav`, named `clip01.m4a` through `clip10.m4a`.

Each clip corresponds to a scenario in `labels.json`. Read the script (or describe the case in your own words) at the pace of a radio call or quick patient summary.

## Scenarios

1. **Chest pain with vitals** — Adult with chest pain, mention BP and SpO2.
2. **Unconscious patient** — Unresponsive, mention age and sex.
3. **Stroke signs** — Patient with facial droop, arm weakness, or speech difficulty.
4. **Fracture in a child** — Pediatric fracture (leg, arm), describe mechanism.
5. **Breathing difficulty** — Respiratory distress, mention SpO2 or breathing quality.
6. **Burns** — Thermal injury, note extent and depth.
7. **Moderate bleeding** — Controlled but significant bleeding, mention site.
8. **Stable case** — Minor injury or complaint, normal vitals, low risk.
9. **Fire dispatch note** — Fire call with trapped persons, give location and count.
10. **Intervention log note** — Medical procedure or drug administered (e.g., oxygen, aspirin), include dose.

A synthetic set (Cloud Text-to-Speech voices) lives in [synthetic/](synthetic/) until real recordings replace it; evaluate a directory with `python3 scripts/eval_run.py --clips <dir> --labels <dir>/labels.json`.

Each clip will be posted to `/triage` with base64 encoding and compared to the expected fields in `labels.json`.
