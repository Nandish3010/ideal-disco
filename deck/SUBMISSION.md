# Submission deck

**`Green-Corridor-Deck.pdf` is the submission deck**: our own design (white content slides, near-black `#0B0D10` cover and closing, amber `#F59E0B` accent, Arial), 17 slides, covering every section of the organiser's template in the template's order, each section name as the slide title: Team details, Brief about the idea, Opportunities (how it differs / how it solves / USP), List of features, Process flow, Wireframes, Architecture, Technologies, Estimated implementation cost, Snapshots of the prototype (two slides), Performance report / benchmarking, Additional details / future development, Sustainability (an extra slide, not a template section), Links. Slides 1 and 17 are the dark cover and closing. No organiser header or footer artwork. PDF is about 2 MB (limit 5 MB). It is hosted at https://green-corridor-2026.web.app/deck.pdf (and `/deck.pptx`): `deploy-web` copies both files from `deck/` into `web/public/` at build time, so rebuilding the deck and pushing to main redeploys them.

`Green-Corridor-Submission.pptx` / `.pdf` (below) is the fallback: the organiser's own 16-slide template filled in.

Regenerate (copy and numbers come from `DATA` in `build_submission.py`; eval numbers from `data/eval/synthetic/results.md`). Needs `pip install python-pptx pillow qrcode pymupdf`; the PDF step needs Microsoft PowerPoint on macOS:

```
python3 deck/build_deck.py          # Green-Corridor-Deck.pptx
python3 deck/build_deck.py --pdf    # also the PDF via PowerPoint (AppleScript), recompressed with PyMuPDF
python3 deck/video_cards.py         # 1920x1080 title cards into deck/video-cards/ (same palette)
```

The build prints the body-word count per slide (target 35; slides 9 and 10 run a few over). The deck uses `img/architecture-deck.svg` (merged clients, grouped Google services, larger type); `img/architecture.svg` stays for the fallback deck. Slide 15's per-queue litres tile (20 vehicles x 60 s x 0.76 L/h) is an illustration, not a measurement. Slide 10's city-month tile is an illustration (100 runs x about 50 rupees), not a measured volume. No /story capture exists yet, so the snapshots slide has three images.

## Fill before submitting

- Slide 16: demo video link (the dashed "[link]" tile; add a QR for it with `qr_png` in `build_deck.py`).
- Slide 13: re-check the load-test tile (17 / 37 ms), test counts (412 Python, 161 web, 98 % coverage, from the CI run on main) and the eval numbers (12 synthetic clips, 11 scored for tier, 1 intervention note) at freeze; slide 3 and 13: 16.5 min, 4 min vs 1 min.
- Slide 10: rupee figures are list-price estimates; re-check against current price lists.

## Template-based fallback

`Green-Corridor-Submission.pptx` is the organiser's 16-slide template (`template/Submission-Template-AI-Builder-Cup.pptx`) filled with the Green Corridor content: slides 1 and 3-14 are filled, slides 2 (template note), 15 and 16 are untouched. `Green-Corridor-Submission.pdf` is its export.

Design pass (October 2026): slide order, section headings (restyled as small spaced-caps eyebrows, text unchanged), the template header and footer artwork, slide 2 and slides 15-16 are as the organiser supplied them; the body areas are redrawn with stat tiles, cards, device frames, a two-lane flow, a grouped product grid, a three-step roadmap and QR codes. Palette: white page, near-black tiles, amber `#F59E0B` for numbers, rules and highlighted boxes. Type scale: headline 22 pt, body 14 pt, captions 10-11 pt, tile numbers 32-40 pt. Screenshots are cropped, downscaled to 1600 px and stored as JPEG q80, so the .pptx is about 2 MB and the PDF about 2.4 MB (limit 5 MB).

Regenerate (all copy and numbers sit in the `DATA` dict at the top of the script; eval numbers are read from `data/eval/synthetic/results.md`, so rerun after the eval changes). Needs `pip install python-pptx pillow qrcode pymupdf`; the PDF step needs Microsoft PowerPoint on macOS:

```
python3 deck/build_submission.py          # .pptx; renders deck/img/architecture.svg via npx sharp-cli
python3 deck/build_submission.py --pdf    # also exports the PDF through PowerPoint (AppleScript), then recompresses images with PyMuPDF
python3 deck/video_cards.py               # 1920x1080 title cards into deck/video-cards/
```

The build prints the body-word count per slide (target 35); slide 5 (six screens with captions) runs to about 46 on purpose.

## Video title cards

`deck/video-cards/`: `00-opener.png`, `01-problem.png`, `02-how-a-cop-gets-warned.png`, `03-rules-decide.png`, `04-the-hospital-knows.png`, `05-from-constable-to-controller.png`, `06-closing.png` (QR codes and URLs for the repo and the live app). Suggested placement against the VIDEO.md shot list: opener before shot 1; Problem = shot 1; How a cop gets warned = shots 2-6; Rules decide = shots 7-9; The hospital knows = shots 10-11; From constable to controller = shots 12-14; closing = shot 14.

## Fill in the fallback deck

- Slide 14: demo video link (the "[link]" tile; add a QR for it with `qr_png` in the script).
- Slide 12: re-check the load-test tile (`DATA["load"]`, from `api/loadtest/RESULTS.md`: 17 / 37 ms), the test counts (`DATA["tests"]`: 412 Python, 161 web, 98% API coverage, from the CI run on main) and the rehearsal numbers (16.5 min saved, J3 4 min, J4 1 min) at freeze.
- Slide 10: the rupee figures are list-price estimates, labelled as such; re-check against current price lists.

## Export (fallback deck)

Keep the file as .pptx (submit this, or upload to Google Slides if the organiser requires). The PDF comes from `--pdf` above (or File > Export in PowerPoint or Keynote). Check slides 5, 7 and 11 of the fallback for content touching the footer after any edit.
