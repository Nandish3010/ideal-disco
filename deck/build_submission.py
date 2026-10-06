"""Fill the organiser's template with the Green Corridor content (design pass).

Run from the repo root:
    python3 deck/build_submission.py            # builds the .pptx
    python3 deck/build_submission.py --pdf      # also exports the PDF (PowerPoint via AppleScript, then shrinks it)

Needs python-pptx, Pillow, qrcode (and PyMuPDF for --pdf). Reads data/eval/synthetic/results.md at build
time, renders deck/img/architecture.svg with `npx sharp-cli` unless a PNG path is given as an argument.
Slide order, section headings, header/footer artwork, slide 2 and slides 15-16 come from the template untouched;
everything in the body areas is drawn here. All copy and numbers live in DATA below.
"""
import copy
import io
import os
import re
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import qrcode
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

TEMPLATE = "deck/template/Submission-Template-AI-Builder-Cup.pptx"
OUT = "deck/Green-Corridor-Submission.pptx"
PDF = "deck/Green-Corridor-Submission.pdf"
IMG = "deck/img/"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
FONT = "Google Sans Flex"

# ---------- palette and type scale ----------
def rgb(h):
    return RGBColor.from_string(h)


INK, TILE, AMBER, AMBER_D, AMBER_PALE = rgb("111111"), rgb("16171A"), rgb("F59E0B"), rgb("B45309"), rgb("FEF3C7")
MID, GREY, BORDER, PALE, WHITE = rgb("374151"), rgb("6B7280"), rgb("D9DADD"), rgb("F6F6F4"), rgb("FFFFFF")
ON_DARK = rgb("E5E7EB")
HEAD, BODY, CAP, LABEL, NUM = 22, 14, 11, 12, 36  # headline, body, captions, diagram labels, tile numbers

LEFT, RIGHT = 0.39, 9.61  # aligned with the template heading text; 0.39 in margins
W = RIGHT - LEFT

# ---------- copy and numbers ----------
DATA = {
    "eyebrow": "Google Cloud AI Builder Cup 2026 · Sustainability & Social Impact",
    "tagline": "Warning the junction constable before the siren arrives.",
    "team": {
        "Team name:": "Green Corridor",
        "Team leader name:": "Nandish",
        "Problem Statement:": "Sustainability & Social Impact — emergency vehicles stuck at red signals; the junction constable is never told",
    },
    "headlines": {
        3: "Warn the junction constable early, sized to the queue",
        4: "Not a fixed radius, and not waiting for new hardware",
        5: "Six screens and the engines behind them",
        6: "From the crew’s words to the constable’s phone",
        7: "Real screens from the running prototype",
        8: "Rules decide; Google Cloud services extract and explain",
        9: "A Google Cloud stack, from model to delivery",
        10: "About ₹155 per vehicle-hour, almost all of it Routes",
        11: "The loop, mid-run, from the live rehearsal",
        12: "Synthetic-voice results, scripted-run timings",
        13: "From constable to controller, in three steps",
        14: "Try it, read the code, watch the demo",
    },
    # slide 3
    "saved_min": "16.5",  # scripted-scenario replay total, README "replay" section
    "lead_long_min": "4",  # alert lead at the ~400 m J3 queue (cop alert capture / rehearsal)
    "lead_short_min": "1",  # alert lead at the short J4 queue
    "queue_m": "400",
    "brief_caption": "Scripted scenario and synthetic voices, not field results.",
    # slide 4
    "opp": [
        ("≠", "How it differs", "Warning sized to the queue, not a fixed radius"),
        ("✓", "How it solves", "The constable clears the queue before the siren"),
        ("★", "USP", "Rules decide, Gemini explains; no hardware needed"),
    ],
    # slide 5: (image, (fx, fy, fw), title, line)
    "screens": [
        ("triage-gemini.png", (0.5, 0.48, 1.0), "Voice triage", "Speak, confirm the tier"),
        ("cop-alert.png", (0.5, 0.30, 1.0), "Spoken cop alert", "PREPARE, then STOP"),
        ("hospital.png", (0.5, 0.385, 0.3125), "Hospital live brief", "Live log, ATMIST"),
        ("control.png", (0.5, 0.34, 1.0), "Control room board", "Junctions and escalations"),
        ("sim-split.png", (0.5, 0.40, 1.0), "With-vs-without replay", "Minutes saved"),
        ("agent-trace.png", (0.5, 0.744, 0.39), "Routing agent trace", "Tool-call trace"),
    ],
    "engines": ["Lead time", "Sequencing", "Cop voice", "ATMIST", "After-action", "Eval harness"],
    # slide 6: (label, lane) in order; index 5 is the SignalAdapter
    "flow": [
        "Crew speaks", "Gemini extracts", "Crew confirms tier", "Queue sizes alert",
        "Cop hears, ACKs", "SignalAdapter (simulated)",
    ],
    "flow_hospital": "Hospital brief at ETA−5",
    "flow_caption": "Amber seam: simulated today.",
    # slide 7
    "wire": [("triage-gemini.png", "Voice triage"), ("cop-alert.png", "Spoken alert"), ("hospital.png", "Hospital brief")],
    "wire_caption": "Live rehearsal captures; synthetic patients.",
    # slide 8
    "arch_caption": "Rules engine on Cloud Run, Firestore event bus; the amber SignalAdapter seam is where a real controller plugs in.",
    # slide 9
    "tech": [
        ("AI", ["Gemini on Vertex AI", "Google ADK", "BigQuery ML"]),
        ("Run & data", ["Cloud Run", "Firestore", "BigQuery"]),
        ("Maps & speech", ["Routes API", "Text-to-Speech", "Translation"]),
        ("Delivery", ["Firebase Hosting", "Cloud Build", "Secret Manager"]),
    ],
    "tech_also": "Also: Storage, Scheduler, Logging",
    # slide 10 (list-price estimates, per vehicle-hour)
    "cost": [("Routes", "3 calls/min", 3 * 60 * 0.85), ("Gemini", "17 calls", 17 * 0.02), ("Text-to-Speech", "~1,000 chars", 1.0 * 1.3)],
    "cost_caption": "List prices; Routes is ~98 % of the bill.",
    # slide 12
    "tests": "412 Python, 161 web tests; 98 % API coverage",
    "load": ("17 / 37", "/location p50 / p95, offline single instance"),  # api/loadtest/RESULTS.md
    "perf_caption": "not field recordings.",
    # slide 13
    "roadmap": [
        ("Today", "Constable alerts", "Spoken alert, one ACK."),
        ("Phase 2", "Signal controllers via the adapter", "Constables no longer clear queues by hand."),
        ("Phase 3", "Learning controller on logged junction data", "Peak-hour spans already logged."),
    ],
    # slide 14
    "links": {
        "github": ("GitHub Public Repository", "github.com/Nandish3010/ideal-disco", "https://github.com/Nandish3010/ideal-disco"),
        "video": ("Demo Video (3 minutes)", "[link]", None),
        "app": ("Final Product", "green-corridor-2026.web.app", "https://green-corridor-2026.web.app"),
    },
}


# ---------- eval numbers, read at build time ----------
def half_up(x, nd=1):
    return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def eval_numbers():
    txt = open("data/eval/synthetic/results.md").read()
    rows = [l.split("|")[1:-1] for l in txt.splitlines() if l.startswith("| clip")]
    triage = [r for r in rows if r[2].strip() == "/triage"]
    field = [int(r[6].strip().rstrip("%")) for r in triage]
    tier_ok = sum("✓" in r[5] for r in triage)
    lat = [float(r[7].strip().split()[0]) for r in rows]  # all clips, as in results.json latency_mean_s
    return dict(
        field=round(sum(field) / len(field)),
        tier=round(100 * tier_ok / len(triage)),
        clips=len(triage),
        latency=half_up(round(sum(lat) / len(lat), 4), 1),
    )


EV = eval_numbers()


# ---------- low-level helpers ----------
def style_run(r, size, bold=False, color=INK, font=FONT):
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
    r.font.color.rgb = color
    rpr = r._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", font)


def add_shadow(shape, blur=8, dist=2, alpha=16):
    sp = shape._element.spPr
    for old in sp.findall(qn("a:effectLst")):
        sp.remove(old)
    eff = etree.SubElement(sp, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad=str(int(blur * 12700)), dist=str(int(dist * 12700)), dir="5400000", algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val="000000")
    etree.SubElement(clr, qn("a:alpha"), val=str(alpha * 1000))


def fill_runs(p, parts, size, color, bold=False):
    """parts: str or list of (text, {size, bold, color})."""
    if isinstance(parts, str):
        parts = [(parts, {})]
    for text, o in parts:
        r = p.add_run()
        r.text = text
        style_run(r, o.get("size", size), o.get("bold", bold), o.get("color", color))
        if o.get("link"):
            r.hyperlink.address = o["link"]


def fill_frame(tf, paras, size=BODY, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, after=0, margins=(0, 0, 0, 0)):
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = (Inches(m) for m in margins)
    for i, parts in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(after)
        fill_runs(p, parts, size, color, bold)


def text(slide, x, y, w, h, paras, name=None, **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    if isinstance(paras, str):
        paras = [paras]
    fill_frame(tb.text_frame, paras, **kw)
    return tb


def box(slide, x, y, w, h, fill=WHITE, line=BORDER, lw=0.75, dash=False, shadow=True, radius=0.06, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(lw)
        if dash:
            etree.SubElement(s.line._get_or_add_ln(), qn("a:prstDash"), val="dash")
    s.shadow.inherit = False
    if shadow:
        add_shadow(s)
    return s


def shape_text(s, paras, **kw):
    if isinstance(paras, str):
        paras = [paras]
    kw.setdefault("margins", (0.12, 0.08, 0.12, 0.08))
    fill_frame(s.text_frame, paras, **kw)


def line(slide, x1, y1, x2, y2, head=False, color=GREY, w=1.5):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(w)
    if head:
        etree.SubElement(c.line._get_or_add_ln(), qn("a:tailEnd"), type="triangle")
    return c


def circle_glyph(slide, x, y, d, glyph, fill=TILE, color=AMBER, size=16):
    c = box(slide, x, y, d, d, fill=fill, line=None, shadow=False, shape=MSO_SHAPE.OVAL)
    shape_text(c, [glyph], size=size, color=color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
    return c


# ---------- images (screenshots are downscaled, cropped, JPEG q80) ----------
def prep(path, spec=None, aspect=None, maxw=1600, q=80):
    """spec = (fx, fy, fw): crop centred at fractions (fx, fy) of the image, fw of its width, with the given aspect."""
    im = Image.open(path).convert("RGB")
    if spec and aspect:
        fx, fy, fw = spec
        cw = fw * im.width
        ch = cw / aspect
        if ch > im.height:
            ch = im.height
            cw = ch * aspect
        left = min(max(fx * im.width - cw / 2, 0), im.width - cw)
        top = min(max(fy * im.height - ch / 2, 0), im.height - ch)
        im = im.crop((int(left), int(top), int(left + cw), int(top + ch)))
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    buf.seek(0)
    return buf, im.size


def shot(slide, path, x, y, w, h=None, spec=None, aspect=None, frame=True):
    """Place a screenshot with a thin dark frame and soft drop shadow. h is derived from the (cropped) aspect when omitted."""
    if h is None and aspect is None:
        aspect = Image.open(path).size[0] / Image.open(path).size[1]
    if aspect is None:
        aspect = w / h
    buf, (iw, ih) = prep(path, spec, aspect)
    h = w * ih / iw if h is None else h
    pic = slide.shapes.add_picture(buf, Inches(x), Inches(y), Inches(w), Inches(h))
    if frame:
        pic.line.color.rgb = rgb("2B2D31")
        pic.line.width = Pt(0.75)
        add_shadow(pic, blur=10, dist=3, alpha=28)
    return pic, h


def qr_png(url):
    q = qrcode.QRCode(border=1, box_size=12, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image(fill_color="#111111", back_color="white").save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


# ---------- slide scaffolding ----------
def heading_shape(slide):
    return next(s for s in slide.shapes if s.has_text_frame and s.name.startswith("Google Shape") and s.text_frame.text.strip())


def eyebrow(slide):
    """Restyle the template's section heading as a small spaced-caps eyebrow; the text itself is untouched."""
    sh = heading_shape(slide)
    tf = sh.text_frame
    for p in tf.paragraphs[1:]:  # slides 4 and 14 carry template prompts below the heading
        p._p.getparent().remove(p._p)
    p0 = tf.paragraphs[0]
    for br in p0._p.findall(qn("a:br")):
        p0._p.remove(br)
    sh.top, sh.height = Inches(0.66), Inches(0.3)
    bp = tf._txBody.find(qn("a:bodyPr"))
    for k in ("tIns", "bIns"):
        bp.set(k, "0")
    for r in p0.runs:
        r.font.size = Pt(CAP)
        r.font.bold = True
        r.font.color.rgb = AMBER_D
        rpr = r._r.get_or_add_rPr()
        rpr.set("spc", "120")
        rpr.set("cap", "all")
    return sh


def headline(slide, n):
    return text(slide, LEFT - 0.05 + 0.0, 0.93, W + 0.1, 0.5, [[(DATA["headlines"][n], {})]], name="Headline", size=HEAD, bold=True, anchor=MSO_ANCHOR.TOP, margins=(0.05, 0, 0.05, 0))


def stat_tile(slide, x, y, w, h, num, label, unit="", grey=False, amber=False):
    if grey:
        s = box(slide, x, y, w, h, fill=rgb("F3F4F6"), line=rgb("9CA3AF"), lw=1, dash=True, shadow=False)
        paras = [[(num, {"size": BODY, "bold": True, "color": GREY})], [(label, {"size": CAP, "color": GREY})]]
        shape_text(s, paras, anchor=MSO_ANCHOR.MIDDLE, margins=(0.2, 0.1, 0.2, 0.1))
        return s
    s = box(slide, x, y, w, h, fill=AMBER if amber else TILE, line=None, radius=0.1)
    numc, labc = (INK, INK) if amber else (AMBER, ON_DARK)
    top = [(num, {"size": NUM + 4 if len(num) < 5 else NUM, "bold": True, "color": numc})]
    if unit:
        top.append((" " + unit, {"size": 18, "bold": True, "color": numc}))
    shape_text(s, [top, [(label, {"size": BODY, "color": labc})]], anchor=MSO_ANCHOR.TOP, margins=(0.22, max(0.15, (h - 1.1) / 2), 0.18, 0.1), after=2)
    return s


def word_count(slide):
    """Body words: everything except template headings, the headline and display numerals (runs >= 20 pt)."""
    n = 0

    def runs_of(tf):
        for p in tf.paragraphs:
            for r in p.runs:
                if r.font.size is None or r.font.size.pt < 20:
                    yield r.text

    for sh in slide.shapes:
        if sh.name.startswith("Google Shape") or sh.name == "Headline":
            continue
        frames = []
        if sh.has_text_frame:
            frames.append(sh.text_frame)
        if sh.has_table:
            frames += [c.text_frame for row in sh.table.rows for c in row.cells]
        for tf in frames:
            n += sum(len(re.findall(r"[A-Za-z0-9₹]+", t)) for t in runs_of(tf))
    return n


# ======================================================================
prs = Presentation(TEMPLATE)
S = list(prs.slides)

# ---------- 1 cover: eyebrow, tagline, team details ----------
box1 = next(s for s in S[0].shapes if s.has_text_frame and s.text_frame.text.strip())
text(S[0], 0.29, 3.1, 9.4, 0.25, [[(DATA["eyebrow"], {})]], size=CAP, bold=True, color=AMBER_D, margins=(0.1, 0, 0, 0))
S[0].shapes[-1]._element.xpath(".//a:rPr")[0].set("spc", "120")
S[0].shapes[-1]._element.xpath(".//a:rPr")[0].set("cap", "all")
text(S[0], 0.29, 3.36, 9.4, 0.5, [[(DATA["tagline"], {})]], size=HEAD + 2, bold=True, margins=(0.1, 0, 0, 0))
for p in list(box1.text_frame.paragraphs):
    if not p.text.strip():
        p._p.getparent().remove(p._p)
box1.top, box1.height = Inches(4.0), Inches(1.4)
for p in box1.text_frame.paragraphs:
    k = p.text.strip()
    for r in p.runs:
        r.font.size = Pt(BODY + 2 if k == "Team Details" else BODY)
    for key, v in DATA["team"].items():
        if k == key:
            r = p.runs[0]
            r.text = key + " "
            nr = copy.deepcopy(r._r)
            r._r.addnext(nr)
            from pptx.text.text import _Run

            run = _Run(nr, p)
            run.text = v
            run.font.bold = True
            p.runs[0].font.bold = False

# ---------- 3 brief: pitch headline + three stat tiles ----------
s = S[2]
eyebrow(s), headline(s, 3)
tw, th, ty = (W - 0.4) / 3, 2.1, 1.95
tiles = [
    (DATA["saved_min"], "saved on the scripted scenario", "min"),
    (DATA["lead_long_min"], f"warning at a {DATA['queue_m']} m queue", "min"),
    (str(EV["tier"]), f"tier accuracy on {EV['clips']} synthetic clips", "%"),
]
for i, (num, lab, unit) in enumerate(tiles):
    stat_tile(s, LEFT + i * (tw + 0.2), ty, tw, th, num, lab, unit)
text(s, LEFT, ty + th + 0.25, W, 0.3, [DATA["brief_caption"]], size=CAP, color=GREY)

# ---------- 4 opportunities: three labelled columns ----------
s = S[3]
eyebrow(s), headline(s, 4)
cw, cy, ch = (W - 0.4) / 3, 1.85, 2.5
for i, (glyph, label, line_) in enumerate(DATA["opp"]):
    x = LEFT + i * (cw + 0.2)
    dark = i == 2
    box(s, x, cy, cw, ch, fill=TILE if dark else WHITE, line=None if dark else BORDER, radius=0.1)
    circle_glyph(s, x + 0.25, cy + 0.25, 0.52, glyph, fill=AMBER if dark else TILE, color=INK if dark else AMBER, size=18)
    text(s, x + 0.25, cy + 1.0, cw - 0.5, 0.3, [label], size=BODY, bold=True, color=AMBER if dark else AMBER_D)
    text(s, x + 0.25, cy + 1.4, cw - 0.5, 0.9, [line_], size=BODY, color=ON_DARK if dark else INK)

# ---------- 5 features: 2x3 screen cards + engine strip ----------
s = S[4]
eyebrow(s), headline(s, 5)
cw, cy0, chh, gy = (W - 0.4) / 3, 1.5, 1.62, 0.14
for i, (fn, spec, title, line_) in enumerate(DATA["screens"]):
    r_, c_ = divmod(i, 3)
    x, y = LEFT + c_ * (cw + 0.2), cy0 + r_ * (chh + gy)
    box(s, x, y, cw, chh, radius=0.08)
    shot(s, IMG + fn, x + 0.09, y + 0.09, cw - 0.18, h=0.92, spec=spec, aspect=(cw - 0.18) / 0.92, frame=True)
    text(s, x + 0.09, y + 1.05, cw - 0.18, 0.25, [[(title, {})]], size=LABEL, bold=True)
    text(s, x + 0.09, y + 1.3, cw - 0.18, 0.22, [[(line_, {})]], size=CAP, color=GREY)
chip_y, gap = cy0 + 2 * chh + gy + 0.16, 0.1
cwid = (W - gap * (len(DATA["engines"]) - 1)) / len(DATA["engines"])
for i, e in enumerate(DATA["engines"]):
    c = box(s, LEFT + i * (cwid + gap), chip_y, cwid, 0.3, fill=PALE, line=None, shadow=False, radius=0.15)
    shape_text(c, [e], size=CAP, color=MID, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margins=(0.03, 0, 0.03, 0))

# ---------- 6 process flow: seven numbered boxes, two lanes ----------
s = S[5]
eyebrow(s), headline(s, 6)
lane1_y, lane1_h, lane2_y, lane2_h = 1.55, 1.5, 3.2, 1.25
for (y, h, lab) in ((lane1_y, lane1_h, "Road"), (lane2_y, lane2_h, "Hospital")):
    box(s, LEFT, y, W, h, fill=PALE, line=None, shadow=False, radius=0.1)
    text(s, LEFT + 0.15, y + 0.08, 2, 0.22, [lab], size=10.5, bold=True, color=GREY)
    s.shapes[-1]._element.xpath(".//a:rPr")[0].set("cap", "all")
    s.shapes[-1]._element.xpath(".//a:rPr")[0].set("spc", "100")
bw, bh, step = 1.32, 0.92, 1.5
x0, by = LEFT + 0.16, lane1_y + 0.4
for i, lab in enumerate(DATA["flow"]):
    x = x0 + i * step
    seam = i == len(DATA["flow"]) - 1
    b = box(s, x, by, bw, bh, fill=AMBER_PALE if seam else WHITE, line=AMBER if seam else BORDER, lw=2 if seam else 0.75, radius=0.08)
    shape_text(b, [[(str(i + 1), {"size": 10.5, "bold": True, "color": AMBER_D})], [(lab, {"size": 11, "bold": True})]], margins=(0.1, 0.07, 0.05, 0.05), after=1)
    if i < len(DATA["flow"]) - 1:
        line(s, x + bw + 0.02, by + bh / 2, x + step - 0.02, by + bh / 2, head=True)
hx, hy, hw, hh = x0 + 3 * step, lane2_y + 0.35, 2.9, 0.72
hb = box(s, hx, hy, hw, hh, radius=0.08)
shape_text(hb, [[("7", {"size": 10.5, "bold": True, "color": AMBER_D})], [(DATA["flow_hospital"], {"size": 11, "bold": True})]], margins=(0.1, 0.05, 0.08, 0.04), after=1)
cx3 = x0 + 2 * step + bw / 2
line(s, cx3, by + bh + 0.02, cx3, hy + hh / 2, color=GREY)
line(s, cx3, hy + hh / 2, hx - 0.02, hy + hh / 2, head=True)
text(s, LEFT, 4.65, W, 0.3, [DATA["flow_caption"]], size=CAP, color=GREY)

# ---------- 7 wireframes: device frames ----------
s = S[6]
eyebrow(s), headline(s, 7)
ph_h = 2.85
fy = 1.55


def phone(slide, fn, x):
    buf, (iw, ih) = prep(IMG + fn, maxw=900)
    pw = ph_h * iw / ih
    f = box(slide, x, fy, pw + 0.18, ph_h + 0.18, fill=rgb("1B1C20"), line=rgb("3A3C42"), lw=1, radius=0.22)
    add_shadow(f, blur=12, dist=4, alpha=30)
    slide.shapes.add_picture(buf, Inches(x + 0.09), Inches(fy + 0.09), Inches(pw), Inches(ph_h))
    return pw + 0.18


x = LEFT + 0.2
widths = []
for fn, cap_ in DATA["wire"][:2]:
    wd = phone(s, fn, x)
    text(s, x - 0.3, fy + ph_h + 0.28, wd + 0.6, 0.25, [cap_], size=CAP, bold=True, color=MID, align=PP_ALIGN.CENTER)
    x += wd + 0.55
lap_w = RIGHT - 0.2 - x
scr_w = lap_w - 0.2
scr_h = scr_w * 9 / 16
lap_y = fy + (ph_h + 0.18 - (scr_h + 0.2 + 0.12)) / 2
f = box(s, x, lap_y, lap_w, scr_h + 0.2, fill=rgb("1B1C20"), line=rgb("3A3C42"), lw=1, radius=0.1)
add_shadow(f, blur=12, dist=4, alpha=30)
buf, _ = prep(IMG + DATA["wire"][2][0], (0.5, 0.5, 0.5), 16 / 9)
s.shapes.add_picture(buf, Inches(x + 0.1), Inches(lap_y + 0.1), Inches(scr_w), Inches(scr_h))
base = box(s, x - 0.2, lap_y + scr_h + 0.2, lap_w + 0.4, 0.1, fill=rgb("3A3C42"), line=None, shadow=False, radius=0.05)
text(s, x - 0.3, fy + ph_h + 0.28, lap_w + 0.6, 0.25, [DATA["wire"][2][1]], size=CAP, bold=True, color=MID, align=PP_ALIGN.CENTER)
text(s, LEFT, 5.08, W, 0.25, [DATA["wire_caption"]], size=CAP, color=GREY, align=PP_ALIGN.CENTER)

# ---------- 8 architecture ----------
s = S[7]
eyebrow(s), headline(s, 8)
if ARGS:
    arch = ARGS[0]
else:
    arch = os.path.join(tempfile.gettempdir(), "gc-architecture.png")
    subprocess.run(["npx", "-y", "sharp-cli", "-i", IMG + "architecture.svg", "-o", arch, "--density", "300", "resize", "1800"], check=True, capture_output=True)
aw, ah = Image.open(arch).size
dw = min(W, 3.3 * aw / ah)
s.shapes.add_picture(arch, Inches(LEFT + (W - dw) / 2), Inches(1.45), Inches(dw), Inches(dw * ah / aw))
text(s, LEFT, 4.9, W, 0.45, [DATA["arch_caption"]], size=CAP, color=GREY)

# ---------- 9 technologies: grouped product grid ----------
s = S[8]
eyebrow(s), headline(s, 9)
ry, rstep, rh = 1.55, 0.72, 0.58
pw3 = (RIGHT - (LEFT + 2.0) - 0.4) / 3
for r_, (grp, items) in enumerate(DATA["tech"]):
    y = ry + r_ * rstep
    circ = box(s, LEFT, y + 0.2, 0.16, 0.16, fill=AMBER, line=None, shadow=False, shape=MSO_SHAPE.OVAL)
    text(s, LEFT + 0.28, y, 1.7, rh, [grp], size=BODY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    for c_, name in enumerate(items):
        p_ = box(s, LEFT + 2.0 + c_ * (pw3 + 0.2), y, pw3, rh, radius=0.08)
        shape_text(p_, [name], size=BODY, anchor=MSO_ANCHOR.MIDDLE, margins=(0.15, 0, 0.1, 0))
text(s, LEFT, ry + 4 * rstep + 0.02, W, 0.28, [DATA["tech_also"]], size=CAP, color=GREY)

# ---------- 10 cost: small table + amber tile ----------
s = S[9]
eyebrow(s), headline(s, 10)
total = sum(c[2] for c in DATA["cost"])
rows = [("Service", "Basis", "\u20b9 per hour")] + [(a, b, f"\u20b9{v:.0f}" if v >= 10 else f"\u20b9{v:.2f}") for a, b, v in DATA["cost"]]
tbl_w, rh_ = 5.5, 0.58
gs = s.shapes.add_table(len(rows), 3, Inches(LEFT), Inches(1.85), Inches(tbl_w), Inches(rh_ * len(rows)))
tbl = gs.table
gs._element.graphic.graphicData.tbl.tblPr.set("firstRow", "0")
gs._element.graphic.graphicData.tbl.tblPr.set("bandRow", "0")
for i, cwi in enumerate((2.0, 2.2, 1.3)):
    tbl.columns[i].width = Inches(cwi)
for ri, row in enumerate(rows):
    tbl.rows[ri].height = Inches(rh_)
    for ci, val in enumerate(row):
        cell = tbl.cell(ri, ci)
        cell.margin_left, cell.margin_right = Inches(0.12), Inches(0.1)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.fill.solid()
        cell.fill.fore_color.rgb = PALE if ri == 0 else WHITE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT if ci == 2 else PP_ALIGN.LEFT
        r = p.add_run()
        r.text = val
        style_run(r, BODY, bold=(ri == 0 or ci == 0), color=GREY if ri == 0 else INK)
        # hairline under every row
        tcPr = cell._tc.get_or_add_tcPr()
        for edge in ("a:lnL", "a:lnR", "a:lnT"):
            etree.SubElement(tcPr, qn(edge), w="0").append(etree.Element(qn("a:noFill")))
        ln = etree.SubElement(tcPr, qn("a:lnB"), w="9525")
        sf = etree.SubElement(ln, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr"), val="D9DADD")
        # fill must come after the line elements in tcPr
        fill_el = tcPr.find(qn("a:solidFill"))
        if fill_el is not None:
            tcPr.remove(fill_el)
            tcPr.append(fill_el)
stat_tile(s, LEFT + tbl_w + 0.35, 1.85, W - tbl_w - 0.35, 2.32, f"≈ ₹{total:.0f}", "per vehicle-hour (estimate)", amber=True)
text(s, LEFT, 1.85 + rh_ * len(rows) + 0.2, tbl_w, 0.3, [DATA["cost_caption"]], size=CAP, color=GREY)

# ---------- 11 snapshots: 2x2 ----------
s = S[10]
eyebrow(s), headline(s, 11)
snaps = [("control.png", (0.5, 0.34, 1.0), "Control room"), ("sim-split.png", (0.5, 0.40, 1.0), "Replay simulator"),
         ("agent-trace.png", (0.5, 0.744, 0.39), "Routing trace"), ("hospital.png", (0.5, 0.40, 0.42), "Hospital log")]
iw_, ih_ = (W - 0.3) / 2, 1.5
for i, (fn, spec, cap_) in enumerate(snaps):
    r_, c_ = divmod(i, 2)
    x, y = LEFT + c_ * (iw_ + 0.3), 1.5 + r_ * (ih_ + 0.42)
    shot(s, IMG + fn, x, y, iw_, h=ih_, spec=spec, aspect=iw_ / ih_)
    text(s, x, y + ih_ + 0.1, iw_, 0.25, [cap_], size=CAP, bold=True, color=MID)

# ---------- 12 performance: four tiles, grey placeholder, footprint ----------
s = S[11]
eyebrow(s), headline(s, 12)
tw4 = (W - 0.6) / 4
perf = [
    (str(EV["field"]), "field accuracy", "%"),
    (str(EV["tier"]), "tier accuracy", "%"),
    (EV["latency"], "mean extraction", "s"),
    (f"{DATA['lead_long_min']} vs {DATA['lead_short_min']}", "min alert lead, long vs short queue", ""),
]
for i, (num, lab, unit) in enumerate(perf):
    stat_tile(s, LEFT + i * (tw4 + 0.2), 1.6, tw4, 1.55, num, lab, unit)
text(s, LEFT, 3.25, W, 0.28, [f"{EV['clips']} synthetic clips; " + DATA["perf_caption"]], size=CAP, color=GREY)
stat_tile(s, LEFT, 3.7, 4.4, 1.5, DATA["load"][0], DATA["load"][1], unit="ms")
text(s, LEFT + 4.7, 3.7, W - 4.7, 1.5, [DATA["tests"]], size=BODY, anchor=MSO_ANCHOR.MIDDLE)

# ---------- 13 future: three-step roadmap ----------
s = S[12]
eyebrow(s), headline(s, 13)
bw3, ar = 2.62, (W - 3 * 2.62) / 2
for i, (tag, title, line_) in enumerate(DATA["roadmap"]):
    x = LEFT + i * (bw3 + ar)
    dark, mid = i == 0, i == 1
    b = box(s, x, 1.85, bw3, 2.3, fill=TILE if dark else (AMBER_PALE if mid else WHITE), line=None if dark else (AMBER if mid else rgb("9CA3AF")),
            lw=2 if mid else 1, dash=(i == 2), shadow=dark or mid, radius=0.1)
    tagc, titc, linc = (AMBER, WHITE, ON_DARK) if dark else (AMBER_D, INK, MID)
    shape_text(b, [[(tag, {"size": CAP, "bold": True, "color": tagc})], [(title, {"size": BODY, "bold": True, "color": titc})], [(line_, {"size": BODY, "color": linc})]],
               margins=(0.22, 0.22, 0.2, 0.15), after=9)
    b.text_frame.paragraphs[0]._p.xpath(".//a:rPr")[0].set("cap", "all")
    b.text_frame.paragraphs[0]._p.xpath(".//a:rPr")[0].set("spc", "100")
    if i < 2:
        line(s, x + bw3 + 0.1, 3.0, x + bw3 + ar - 0.1, 3.0, head=True, color=AMBER_D, w=2)

# ---------- 14 links: three tiles, QR codes ----------
s = S[13]
eyebrow(s), headline(s, 14)
tw_, ty_, th_ = (W - 0.4) / 3, 1.75, 3.35
for i, key in enumerate(("github", "video", "app")):
    label, shown, url = DATA["links"][key]
    x = LEFT + i * (tw_ + 0.2)
    box(s, x, ty_, tw_, th_, dash=(url is None), line=BORDER if url else rgb("9CA3AF"), radius=0.1)
    text(s, x + 0.25, ty_ + 0.2, tw_ - 0.5, 0.25, [label], size=CAP, bold=True, color=GREY)
    s.shapes[-1]._element.xpath(".//a:rPr")[0].set("cap", "all")
    s.shapes[-1]._element.xpath(".//a:rPr")[0].set("spc", "80")
    if url:
        q = 1.95
        s.shapes.add_picture(qr_png(url), Inches(x + (tw_ - q) / 2), Inches(ty_ + 0.6), Inches(q), Inches(q))
        text(s, x + 0.2, ty_ + 2.75, tw_ - 0.4, 0.4, [[(shown, {"link": url})]], size=10, color=INK, bold=False, align=PP_ALIGN.CENTER)
    else:
        text(s, x + 0.25, ty_ + 1.0, tw_ - 0.5, 0.8, [[(shown, {"size": 32, "bold": True, "color": GREY})]], size=NUM, align=PP_ALIGN.CENTER)

# ---------- finish ----------
for n, sl in enumerate(S, 1):
    if n in DATA["headlines"]:
        c = word_count(sl)
        print(f"slide {n:2d}: {c:3d} body words" + ("  <-- over 35" if c > 35 else ""))
cp = prs.core_properties
cp.author = cp.last_modified_by = "Nandish"
cp.title = "Emergency Green Corridor: submission deck"
prs.save(OUT)
print("saved", OUT, EV, f"total={total:.2f}")


# ---------- optional PDF export ----------
def export_pdf():
    import fitz

    src, tmp = os.path.abspath(OUT), os.path.abspath(PDF)
    # PowerPoint is sandboxed: write into its container, then move the file out
    box_dir = os.path.expanduser("~/Library/Containers/com.microsoft.Powerpoint/Data")
    stage = os.path.join(box_dir, "gc-export.pdf") if os.path.isdir(box_dir) else tmp
    script = f'''
tell application "Microsoft PowerPoint"
  open POSIX file "{src}"
  set p to active presentation
  save p in POSIX file "{stage}" as save as PDF
  close p saving no
end tell'''
    subprocess.run(["osascript", "-e", script], check=True)
    if stage != tmp:
        os.replace(stage, tmp)
    doc = fitz.open(tmp)
    doc.rewrite_images(dpi_threshold=170, dpi_target=150, quality=78)
    doc.save(tmp + ".small", deflate=True, garbage=3)
    doc.close()
    os.replace(tmp + ".small", tmp)
    print("pdf", tmp, os.path.getsize(tmp), "bytes")


if "--pdf" in sys.argv:
    export_pdf()
