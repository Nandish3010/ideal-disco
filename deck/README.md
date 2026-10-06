# Submission deck

Marp Markdown with a custom theme (`theme.css`, `corridor`). Slides are in `slides.md`; diagrams and screenshots live in `img/` (see `img/README.md`; the PNGs are placeholders until captured from the live app). Items in `[brackets]` are placeholders to fill before export.

Export (run from the repo root):

```
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --pdf --allow-local-files --no-stdin -o deck/slides.pdf </dev/null
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --html --allow-local-files --no-stdin -o deck/slides.html </dev/null
```

Live preview: `npx -y @marp-team/marp-cli -s deck/ --theme deck/theme.css`. Speaker notes are HTML comments and are not rendered in the PDF.


## Before export

The submission deck is `Green-Corridor-Deck.pdf`, built by `build_deck.py` (the template-based `Green-Corridor-Submission.pdf` is the fallback). `slides.md` is an appendix of longer Marp notes: it is not submitted and its numbers are not kept current. Check each of these before you export or submit:

- [ ] **Row count and date range.** `bq query --nouse_legacy_sql 'SELECT COUNT(*), MIN(ts), MAX(ts), COUNTIF(jam_m>0) FROM corridor.traffic_spans'`; put the real count (and the non-zero count, stated honestly) in `README.md` "Real data" and on the deck's data slide. Retrain the BigQuery ML model first (`jobs/bqml/run.sh`).
- [ ] **Video link.** After the unlisted YouTube upload, set it in the Links slide of the submission deck (the `DATA` entry in `build_deck.py`), rebuild, and paste it into the submission form.
- [ ] **Minutes-saved figure** copied from the replay test (`web/src/__tests__/replay.test.js`) into the deck, `README.md` and the beat 2 caption in `VIDEO.md`.
- [ ] **Recording prep done in order** (see `VIDEO.md` section 3): warm `/health`, `python3 scripts/demo_reset.py --apply`, one scenario run with the cop ACKing, `python3 scripts/pin_showcase.py --apply`, then record.
- [ ] Screenshots in `img/` captured from the deployed app (placeholders until then).
- [ ] The routing-trace slide still matches the live TraceCard in `/vehicle`.
- [ ] Re-read the exported PDF end to end.
