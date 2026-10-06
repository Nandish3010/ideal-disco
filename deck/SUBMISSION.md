# Submission deck

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

## Fill before submitting

- Slide 14: demo video link (the "[link]" tile; add a QR for it with `qr_png` in the script).
- Slide 12: re-check the load-test tile (`DATA["load"]`, from `api/loadtest/RESULTS.md`: 17 / 37 ms), the test counts (`DATA["tests"]`: 344 Python, 138 web, 98% API coverage, from the CI run on main) and the rehearsal numbers (16.5 min saved, J3 4 min, J4 1 min) at freeze.
- Slide 10: the rupee figures are list-price estimates, labelled as such; re-check against current price lists.

## Export

Keep the file as .pptx (submit this, or upload to Google Slides if the organiser requires). The PDF comes from `--pdf` above (or File > Export in PowerPoint or Keynote). Check slides 5, 7 and 11 for content touching the footer after any edit.
