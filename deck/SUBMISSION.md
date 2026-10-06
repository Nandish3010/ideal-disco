# Submission deck

`Green-Corridor-Submission.pptx` is the organiser's 16-slide template (`template/Submission-Template-AI-Builder-Cup.pptx`) filled with the Green Corridor content: slides 1 and 3-14 are filled, slides 2 (template note), 15 and 16 are untouched. `Green-Corridor-Submission.pdf` is its export.

Regenerate (reads `data/eval/synthetic/results.md` at build time, so rerun after the eval numbers change):

```
npx -y sharp-cli -i deck/img/architecture.svg -o /tmp/architecture.png --density 300 resize 2400
python3 deck/build_submission.py /tmp/architecture.png   # needs python-pptx, Pillow
```

## Fill before submitting

- Slide 12: load test p50/p95 (`[load test p50/p95: fill at freeze]`; `api/loadtest/RESULTS.md` does not exist yet).
- Slide 14: demo video link (`[link, 3 minutes — fill]`).
- Slide 12: re-check the test counts (about 250 Python, 45 web, 98% API coverage) and the rehearsal numbers (16.5 min saved, J3 4 min, J4 1 min) at freeze.
- Slide 10: the rupee figures are list-price estimates, labelled as such; re-check against current price lists.

## Export

Keep the file as .pptx (submit this, or upload to Google Slides if the organiser requires). For PDF: open in PowerPoint or Keynote and File > Export to PDF, or `soffice --headless --convert-to pdf deck/Green-Corridor-Submission.pptx`. Check slides 6, 7 and 11 for text touching the header or footer images after any edit.
