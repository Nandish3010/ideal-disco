# Submission deck

Marp Markdown with a custom theme (`theme.css`, `corridor`). Slides are in `slides.md`; diagrams and screenshots live in `img/` (see `img/README.md`; the PNGs are placeholders until captured from the live app). Items in `[brackets]` are placeholders to fill before export.

Export (run from the repo root):

```
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --pdf --allow-local-files -o deck/slides.pdf
npx -y @marp-team/marp-cli deck/slides.md --theme deck/theme.css --html --allow-local-files -o deck/slides.html
```

Live preview: `npx -y @marp-team/marp-cli -s deck/ --theme deck/theme.css`. Speaker notes are HTML comments and are not rendered in the PDF.
