# Submission deck

Marp Markdown with a custom theme (`theme.css`, `corridor`). Slides are in `slides.md`; diagrams and screenshots live in `img/` (see `img/README.md`; the PNGs are placeholders until captured from the live app). Items in `[brackets]` are placeholders to fill before export.

Export (run from the repo root):

```
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --pdf --allow-local-files --no-stdin -o deck/slides.pdf </dev/null
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --html --allow-local-files --no-stdin -o deck/slides.html </dev/null
```

Live preview: `npx -y @marp-team/marp-cli -s deck/ --theme deck/theme.css`. Speaker notes are HTML comments and are not rendered in the PDF.


## Before export

Fill or confirm each of these, then export and re-read the PDF:

- [ ] **Placeholders to replace** (all of them, in one pass):
  - `[fill at freeze]` (3 places, the BigQuery `traffic_spans` row count N at freeze; retrain the BigQuery ML model first): `README.md` "Real data", the architecture slide's footnote, and slide 10 ("Rows so far").
  - `[link, 3 minutes]` (2 places, the unlisted video URL): the last slide of `slides.md` and the upload step in `VIDEO.md`.
  - The minutes-saved figure (`<!-- update from replay test -->` notes): slide 3 and `README.md`, copied from the replay test (`web/src/__tests__/replay.test.js`); also write it in the shot 1 caption in `VIDEO.md`.
- [ ] Screenshots in `img/` captured from the deployed app (they are placeholders until then).
- [ ] The agent-trace slide still matches the live trace in `/vehicle` (currently the Jayadeva, 373 s trace).
