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

- [ ] `{MINUTES}`: the minutes-saved figure on slide 3 and in `README.md`, copied from the replay test (`web/src/__tests__/replay.test.js`); remove the `<!-- update from replay test -->` notes. Also write it in the shot 1 caption in `VIDEO.md`.
- [ ] `N` rows (`[fill at freeze]`): the BigQuery `traffic_spans` row count at freeze, on slide 10, the architecture slide's footnote and `README.md` "Real data". Retrain the BigQuery ML model first.
- [ ] `[link, 3 minutes]`: the unlisted video URL on the last slide.
- [ ] Screenshots in `img/` captured from the deployed app (they are placeholders until then).
- [ ] The agent-trace slide still matches the live trace in `/vehicle`.
