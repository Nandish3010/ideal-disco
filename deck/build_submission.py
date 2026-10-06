"""Fill the organiser's template with the Green Corridor content.

Run from the repo root: python3 deck/build_submission.py [architecture.png]
Needs python-pptx. Reads data/eval/synthetic/results.md at build time.
"""
import copy
import os
import re
import sys

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

TEMPLATE = "deck/template/Submission-Template-AI-Builder-Cup.pptx"
OUT = "deck/Green-Corridor-Submission.pptx"
IMG = "deck/img/"
ARCH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/architecture.png"
FONT = "Google Sans Flex"

DARK, GREY, LIGHT = RGBColor(0x21, 0x21, 0x21), RGBColor(0x59, 0x59, 0x59), RGBColor(0xEE, 0xEE, 0xEE)
BLUE, TEAL, AMBER, WHITE = RGBColor(0x42, 0x85, 0xF4), RGBColor(0x00, 0x97, 0xA7), RGBColor(0xFF, 0xAB, 0x40), RGBColor(255, 255, 255)

LEFT, RIGHT = 0.29, 9.71
TOP, BOTTOM = 1.38, 5.42  # safe area between header (0.55) / title and footer (5.55)


# ---------- helpers ----------
def style_run(r, size, bold=False, color=DARK, font=FONT):
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
    r.font.color.rgb = color
    rpr = r._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):  # keep east-asian/complex face in step, as the template does
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", font)


def textbox(slide, x, y, w, h, paras, size=13, color=DARK, space_after=4, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT):
    """paras: list of str | list of (text, bold) runs. A leading '- ' makes a bullet."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    first = True
    for p_spec in paras:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        runs = [(p_spec, False)] if isinstance(p_spec, str) else p_spec
        bullet = runs[0][0].startswith("- ")
        if bullet:
            runs = [(runs[0][0][2:], runs[0][1])] + list(runs[1:])
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(Inches(0.18)))
            pPr.set("indent", str(-Inches(0.18)))
            bf = etree.SubElement(pPr, qn("a:buFont"))
            bf.set("typeface", "Arial")
            bu = etree.SubElement(pPr, qn("a:buChar"))
            bu.set("char", "•")
        p.alignment = align
        p.space_after = Pt(space_after)
        for text, bold in runs:
            style_run(p.add_run(), size, bold, color)
            p.runs[-1].text = text
    return tb


def card(slide, x, y, w, h, fill=LIGHT, line=None, dash=False, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1.5)
        if dash:
            ln = s.line._get_or_add_ln()
            d = etree.SubElement(ln, qn("a:prstDash"))
            d.set("val", "dash")
    s.shadow.inherit = False
    return s


def shape_text(s, text, size=12, color=DARK, bold=False):
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    style_run(r, size, bold, color)


def picture_fit(slide, path, x, y, w, h, frame=True):
    """Place a picture inside the box (x, y, w, h), keeping its aspect ratio, centred."""
    from PIL import Image

    iw, ih = Image.open(path).size
    sc = min(w / iw, h / ih)
    pw, ph = iw * sc, ih * sc
    pic = slide.shapes.add_picture(path, Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2), Inches(pw), Inches(ph))
    if frame:
        pic.line.color.rgb = RGBColor(0xBD, 0xBD, 0xBD)
        pic.line.width = Pt(1)
    return pic, (x + (w - pw) / 2, y + (h - ph) / 2, pw, ph)


def caption(slide, x, y, w, text, size=11):
    return textbox(slide, x, y, w, 0.3, [text], size=size, color=GREY, space_after=0, align=PP_ALIGN.CENTER)


def arrow(slide, x1, y1, x2, y2, head=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = GREY
    c.line.width = Pt(1.75)
    if head:
        ln = c.line._get_or_add_ln()
        t = etree.SubElement(ln, qn("a:tailEnd"))
        t.set("type", "triangle")
    return c


def table(slide, x, y, w, col_w, rows, size=12, row_h=0.3, header=True):
    gs = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    tbl = gs.table
    # drop the default style banding so our fills rule
    tblPr = tbl._tbl.tblPr
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = Inches(cw)
    for ri, row in enumerate(rows):
        tbl.rows[ri].height = Inches(row_h)
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            is_head = header and ri == 0
            cell.fill.fore_color.rgb = DARK if is_head else (LIGHT if ri % 2 else WHITE)
            p = cell.text_frame.paragraphs[0]
            r = p.add_run()
            r.text = val
            style_run(r, size, bold=is_head or ci == 0, color=WHITE if is_head else DARK)
    return gs


def get(slide, idx):
    return [s for s in slide.shapes if s.has_text_frame and s.name.startswith("Google Shape;")][idx]


def title_box(slide):
    return next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip())


def append_runs(p, parts, size, bold_first=False):
    for i, (t, b) in enumerate(parts):
        r = p.add_run()
        r.text = t
        style_run(r, size, b)


# ---------- eval numbers, read at build time ----------
def eval_numbers():
    txt = open("data/eval/synthetic/results.md").read()
    rows = [l.split("|")[1:-1] for l in txt.splitlines() if l.startswith("| clip")]
    triage = [r for r in rows if r[2].strip() == "/triage"]
    field = [int(r[6].strip().rstrip("%")) for r in triage]
    tier_ok = sum("✓" in r[5] for r in triage)
    lat = [float(r[7].strip().split()[0]) for r in rows]
    per_field = [
        (a.strip(), b.strip())
        for a, b in (l.split("|")[1:-1] for l in txt.splitlines() if re.match(r"\| (age|sex|complaint|conscious|breathing|vitals|trapped_persons) ", l))
    ]
    return dict(
        field=round(sum(field) / len(field)),
        tier=round(100 * tier_ok / len(triage)),
        tier_n=f"{tier_ok}/{len(triage)}",
        clips=len(rows),
        latency=f"{sum(lat) / len(lat):.1f}",
        per_field=per_field,
    )


EV = eval_numbers()

prs = Presentation(TEMPLATE)
S = list(prs.slides)

# ---------- 1 Team details (fill the template's own lettered lines) ----------
box = title_box(S[0])
vals = {
    "Team name:": "Green Corridor",
    "Team leader name:": "Nandish",
    "Problem Statement:": "Sustainability & Social Impact — emergency vehicles stuck at red signals; the junction constable is never told",
}
for p in box.text_frame.paragraphs:
    for k, v in vals.items():
        if p.text.strip() == k:
            r = p.runs[0]
            r.text = k + " "
            nr = copy.deepcopy(r._r)
            r._r.addnext(nr)
            from pptx.text.text import _Run

            run = _Run(nr, p)
            run.text = v
            run.font.bold = True
            p.runs[0].font.bold = False
# the two spacer paragraphs and 18pt lines overflow with the longer problem statement: tighten
for p in box.text_frame.paragraphs:
    if p.text.strip().startswith("Problem Statement"):
        for r in p.runs:
            r.font.size = Pt(16)

# ---------- 3 Brief ----------
s = S[2]
textbox(
    s, LEFT, TOP, 9.42, 2.3,
    [
        "Ambulances, fire engines and police vehicles sit at red signals while the officer at the junction has no idea they are coming.",
        "Emergency Green Corridor warns that officer early enough, sized to the queue that is really there, with a spoken alert on their phone; rules decide the order and Gemini extracts and explains.",
        "A crew speaks the patient's condition, one tap confirms the tier, and from then on GPS drives the alerts, the multi-vehicle sequencing and a live hospital handover.",
    ],
    size=15, space_after=9,
)
c = card(s, LEFT + 0.05, 3.95, 9.32, 1.1, fill=LIGHT, line=TEAL)
shape_text(c, "Honest scope: the signals are simulated behind an adapter today; constable alerts are deployable now, on a phone, with no hardware.", size=15)

# ---------- 4 Opportunities ----------
s = S[3]
box = title_box(s)
box.height = Inches(4.5)
box.width = Inches(9.42)
answers = {
    "How different": (
        "Warning time is sized to the queue, not a fixed radius. Several vehicles are sequenced with shared greens, alerts are spoken, the hospital gets a live handover, and none of it needs hardware."
    ),
    "How will it be": (
        "The constable clears exactly the queue that is there, minutes before the siren arrives."
    ),
    "USP": (
        "Rules decide; Gemini explains and extracts. Deployable to a constable's phone today, adapter-ready for signal controllers."
    ),
}
for p in box.text_frame.paragraphs:
    t = p.text.strip()
    for k, a in answers.items():
        if t.startswith(k):
            for r in p.runs:
                r.font.bold = True
            br = p.add_line_break()
            r = p.add_run()
            r.text = a
            style_run(r, 13, False, DARK)
            p.space_after = Pt(9)
            p.space_before = Pt(4)
# drop trailing empty paragraphs
for p in list(box.text_frame.paragraphs):
    if not p.text.strip():
        p._p.getparent().remove(p._p)

# ---------- 5 Features ----------
s = S[4]
textbox(s, LEFT, TOP, 4.55, 0.3, [[("Six screens", True)]], size=14, color=TEAL)
textbox(
    s, LEFT, TOP + 0.35, 4.55, 3.4,
    [
        "- /vehicle: voice or photo triage, tier tap",
        "- /cop: spoken two-stage alert, one ACK",
        "- /hospital: live log, brief, countdown",
        "- /control: runs, junction board, escalations",
        "- /sim: with-vs-without replay, minutes saved",
        "- /dispatch: incident IDs",
    ],
    size=13, space_after=6,
)
textbox(s, 5.1, TOP, 4.6, 0.3, [[("Engines", True)]], size=14, color=TEAL)
textbox(
    s, 5.1, TOP + 0.35, 4.6, 3.4,
    [
        "- Lead time: queue metres to PREPARE / STOP",
        "- Sequencing and platoon, shared greens",
        "- Cop voice back-channel to rule actions",
        "- Hospital routing agent (ADK) with guard",
        "- ATMIST brief at ETA−5",
        "- After-action report, per-run report cards",
        "- Evaluation harness on voice clips",
    ],
    size=13, space_after=6,
)

# ---------- 6 Process flow ----------
s = S[5]
labels = [
    ("Crew speaks", TEAL), ("Gemini extracts (fixed schema)", BLUE), ("Crew confirms tier", TEAL),
    ("Vehicle GPS", LIGHT), ("Routes traffic", LIGHT), ("Queue metres", LIGHT),
    ("PREPARE / STOP alert (spoken)", LIGHT), ("Cop ACK / voice note", TEAL),
    ("SignalAdapter request-green (simulated)", LIGHT), ("Hospital brief at ETA−5", BLUE), ("Report card", LIGHT),
]
bw, gap, bh = 1.28, 0.348, 0.95
ys = (1.6, 3.35)
boxes = []
for i, (txt, col) in enumerate(labels):
    row, colx = divmod(i, 6)
    x = LEFT + colx * (bw + gap)
    b = card(s, x, ys[row], bw, bh, fill=col, line=AMBER if i == 8 else None, dash=(i == 8))
    shape_text(b, txt, size=12, color=WHITE if col in (TEAL, BLUE) else DARK)
    boxes.append((x, ys[row]))
for i in range(10):
    (x1, y1), (x2, y2) = boxes[i], boxes[i + 1]
    if y1 == y2:
        arrow(s, x1 + bw, y1 + bh / 2, x2, y2 + bh / 2)
# wrap from the end of row 1 to the start of row 2
(xa, ya), (xb, yb) = boxes[5], boxes[6]
mid = (ya + bh + yb) / 2
arrow(s, xa + bw / 2, ya + bh, xa + bw / 2, mid, head=False)
arrow(s, xa + bw / 2, mid, xb + bw / 2, mid, head=False)
arrow(s, xb + bw / 2, mid, xb + bw / 2, yb)
# legend
lx = LEFT + 5 * (bw + gap)
for j, (lab, col) in enumerate([("Gemini", BLUE), ("People", TEAL), ("Rules / APIs", LIGHT)]):
    sw = card(s, lx, 3.38 + j * 0.3, 0.18, 0.18, fill=col, shape=MSO_SHAPE.RECTANGLE)
    textbox(s, lx + 0.22, 3.31 + j * 0.3, 1.1, 0.3, [lab], size=12, space_after=0)
textbox(
    s, LEFT, 4.6, 9.42, 0.7,
    ["Rules decide every safety step; Gemini only extracts and explains. Signals are simulated behind SignalAdapter (dashed)."],
    size=13, color=GREY,
)

# ---------- 7 Wireframes ----------
s = S[6]
H = 2.8
x = 0.6
y0 = 1.5
items = [("vehicle.png", "/vehicle: voice triage"), ("cop-alert.png", "/cop: alert + ACK"), ("hospital.png", "/hospital: live log, vitals, ATMIST brief")]
from PIL import Image

for fn, cap in items:
    iw, ih = Image.open(IMG + fn).size
    w = H * iw / ih
    picture_fit(s, IMG + fn, x, y0, w, H)
    capw = max(w, 1.9)
    caption(s, x + w / 2 - capw / 2, y0 + H + 0.08, capw, cap, size=11)
    x += w + 0.35
textbox(s, LEFT, 4.95, 9.42, 0.4, ["Screens captured from the live rehearsal run: synthetic patients, scripted scenario."], size=12, color=GREY, align=PP_ALIGN.CENTER)

# ---------- 8 Architecture ----------
s = S[7]
picture_fit(s, ARCH, LEFT, 1.35, 9.42, 3.75, frame=False)
textbox(
    s, LEFT, 5.08, 9.42, 0.35,
    ["Clients and Firestore event bus around a Cloud Run rules engine; Google services on the right; the SignalAdapter seam is where a real controller plugs in."],
    size=11, color=GREY, align=PP_ALIGN.CENTER, space_after=0,
)

# ---------- 9 Technologies ----------
s = S[8]
rows = [
    ("Layer", "Technology"),
    ("Generative AI", "Gemini on Vertex AI: 3.1 Flash Lite (extraction), 3 Flash (text)"),
    ("Agents", "Agent Development Kit (hospital routing agent)"),
    ("Compute", "Cloud Run, Cloud Run Jobs, Cloud Scheduler"),
    ("Data", "Firestore (event bus), Cloud Storage, BigQuery + BigQuery ML"),
    ("Hosting", "Firebase Hosting (PWA)"),
    ("Maps", "Routes API, Maps JavaScript API"),
    ("Language", "Cloud Text-to-Speech, Cloud Translation"),
    ("Security and delivery", "Secret Manager, Cloud Build, Artifact Registry, Workload Identity Federation"),
    ("Operations", "Cloud Logging, Monitoring, Trace"),
    ("Frontend / backend", "React + Vite  /  FastAPI (Python 3.12)"),
]
table(s, LEFT, 1.4, 9.42, [2.1, 7.32], rows, size=12, row_h=0.355)

# ---------- 10 Cost ----------
s = S[9]
c1 = card(s, LEFT, 1.4, 4.0, 2.55, fill=LIGHT)
textbox(
    s, LEFT + 0.1, 1.45, 3.8, 2.45,
    [
        [("Measured call budget", True)],
        "- ≈3 Routes calls per vehicle-minute",
        "- ~17 Gemini + TTS calls per full run",
        "- Cloud Run scales to zero; AI side effects run off the request path",
    ],
    size=13, space_after=6,
)
c2 = card(s, 4.5, 1.4, 5.21, 2.55, fill=LIGHT)
textbox(
    s, 4.6, 1.45, 5.0, 2.45,
    [
        [("Pilot estimate per vehicle-hour (list prices)", True)],
        "- Routes: 3 × 60 × ₹0.85 = ₹153",
        "- Gemini Flash Lite: 17 × ₹0.02 = ₹0.34",
        "- TTS: ~1,000 chars × ₹1.3/1k = ₹1.30",
        [("Total ≈ ₹155 per vehicle-hour (estimate)", True)],
    ],
    size=13, space_after=6,
)
textbox(
    s, LEFT, 4.15, 9.42, 1.0,
    ["City scale: Routes is ~98% of the bill, so 100 vehicle-hours a day is about ₹15,500 a day; fetching one span per junction and sharing it across vehicles is the lever."],
    size=13, color=GREY,
)

# ---------- 11 Snapshots ----------
s = S[10]
pw_h = 3.72
pic, (px, py, pw, ph) = picture_fit(s, IMG + "triage-gemini.png", 0.8, 1.4, 1.8, pw_h)
caption(s, px + pw / 2 - 0.9, py + ph + 0.04, 1.8, "Gemini extraction", size=10)
cw, ch = 3.1, 3.1 * 9 / 16
gx = [2.95, 6.3]
gy = [1.4, 3.42]
grid = [("control.png", "/control: junction board, ACK, escalation"), ("sim-split.png", "/sim: with vs without corridor"),
        ("agent-trace.png", "/vehicle: routing agent tool trace")]
for k, (fn, cap) in enumerate(grid):
    r_, c_ = divmod(k, 2)
    picture_fit(s, IMG + fn, gx[c_], gy[r_], cw, ch)
    caption(s, gx[c_] - 0.1, gy[r_] + ch + 0.02, cw + 0.2, cap, size=10)

textbox(s, gx[1], gy[1] + 0.3, cw, 1.2, ["Captured from the live rehearsal run: synthetic patients, scripted scenario."], size=12, color=GREY, align=PP_ALIGN.CENTER)

# ---------- 12 Performance ----------
s = S[11]
f = EV["per_field"]
rows = [("Field", "Accuracy")] + [(a, b) for a, b in f]
textbox(s, LEFT, 1.33, 4.4, 0.55, [[(f"Extraction, synthetic voices ({EV['clips']} clips): field {EV['field']}%, tier {EV['tier']}% ({EV['tier_n']})", True)]], size=12, space_after=0)
table(s, LEFT, 1.95, 3.0, [1.75, 1.25], rows, size=12, row_h=0.3)
textbox(
    s, 3.5, 1.95, 1.3, 2.4,
    ["Not field recordings; tier misses are complaint wording."],
    size=11, color=GREY,
)
textbox(
    s, 5.0, 1.33, 4.71, 3.7,
    [
        f"- Extraction latency: mean {EV['latency']} s per clip",
        "- Rehearsal: J3 alert 4 min out (long queue), J4 alert 1 min out",
        "- 16.5 min saved on the scripted scenario; baseline per junction: cycle/4 + queue/2 m/s (simulated)",
        "- Tests: ≈250 Python, 45 web; 98% API coverage",
        "- [load test p50/p95: fill at freeze]",
    ],
    size=12, space_after=6,
)

# ---------- 13 Future ----------
s = S[12]
textbox(s, LEFT, 1.3, 9.42, 0.4, [[("From constable to controller", True)]], size=16, color=TEAL)
phases = [
    ("Today", "The alert goes to a person: no city hands a hackathon its signal API. A spoken PREPARE / STOP on a phone, one ACK."),
    ("Phase 2", "Integrate the city's adaptive signal controllers. The same request-green call already flows through the SignalAdapter seam, so the green fires automatically and constables supervise exceptions."),
    ("Phase 3", "A learning controller trained on junction data we already log: peak-hour Routes spans to BigQuery."),
]
pw3 = 3.02
for i, (h, t) in enumerate(phases):
    x = LEFT + i * (pw3 + 0.18)
    card(s, x, 1.8, pw3, 2.35, fill=LIGHT)
    textbox(s, x + 0.08, 1.87, pw3 - 0.16, 2.2, [[(h, True)], t], size=12, space_after=6)
textbox(
    s, LEFT, 4.35, 9.42, 0.9,
    ["Also planned: agency rosters, FCM push, production mode, Kannada/Telugu switchable by corridor."],
    size=13, color=GREY,
)

# ---------- 14 Links ----------
s = S[13]
box = title_box(s)
box.height = Inches(4.3)
links = {
    "GitHub": ("https://github.com/Nandish3010/ideal-disco", True),
    "Demo Video": ("[link, 3 minutes — fill]", False),
    "Final Product": ("https://green-corridor-2026.web.app", True),
}
for p in box.text_frame.paragraphs:
    for k, (v, is_link) in links.items():
        if p.text.strip().startswith(k):
            for r in p.runs:
                r.font.size = Pt(14)
            p.add_line_break()
            r = p.add_run()
            r.text = v
            style_run(r, 13, False, BLUE if is_link else DARK)
            if is_link:
                r.hyperlink.address = v
            p.space_after = Pt(8)
# API health as a fourth entry, copied from the "Final Product" paragraph
for p in box.text_frame.paragraphs:
    if p.text.strip().startswith("Final Product"):
        new = copy.deepcopy(p._p)
        p._p.addnext(new)
        from pptx.text.text import _Paragraph

        np_ = _Paragraph(new, p._parent)
        runs = np_.runs
        runs[0].text = "API health"
        for r in runs[1:]:
            if r.text.startswith("http"):
                r.text = "https://corridor-api-919512130399.asia-south1.run.app/health"
                r.hyperlink.address = r.text
        break

prs.save(OUT)
print("saved", OUT, EV["field"], EV["tier"], EV["latency"])
