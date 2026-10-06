"""Submission deck in our own design (16:9, 13.33 x 7.5 in), covering every section of the organiser's template in order.

Run from the repo root:
    python3 deck/build_deck.py            # deck/Green-Corridor-Deck.pptx
    python3 deck/build_deck.py --pdf      # also deck/Green-Corridor-Deck.pdf (PowerPoint via AppleScript, then PyMuPDF recompress)

Needs python-pptx, Pillow, qrcode (+ PyMuPDF for --pdf). Copy and numbers come from DATA in build_submission.py (read with ast so
that script is not executed); eval numbers are read from data/eval/synthetic/results.md. Renders deck/img/architecture.svg via `npx sharp-cli`.
"""
import ast
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

OUT, PDF, IMG = "deck/Green-Corridor-Deck.pptx", "deck/Green-Corridor-Deck.pdf", "deck/img/"
FONT, MONO = "Arial", "Courier New"  # ponytail: Arial renders true-to-width everywhere; Inter is not installed in PowerPoint


# ---------- data: reuse DATA + eval helpers from build_submission.py without running it ----------
def load_shared():
    src = open("deck/build_submission.py").read()
    tree = ast.parse(src)
    ns = {"Decimal": Decimal, "ROUND_HALF_UP": ROUND_HALF_UP}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("half_up", "eval_numbers"):
            exec(compile(ast.Module([node], []), "bs", "exec"), ns)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DATA":
            ns["DATA"] = eval(compile(ast.Expression(node.value), "bs", "eval"), {})
    return ns["DATA"], ns["eval_numbers"]()


DATA, EV = load_shared()
DATA["cover_stat"] = "of Karnataka 108 cardiac, stroke, respiratory calls missed the 10-minute target"
DATA["links"]["deck"] = ("Submission deck", "green-corridor-2026.web.app/deck.pdf", "https://green-corridor-2026.web.app/deck.pdf")
DATA["cover_cite"] = "Source: CAG audit of Karnataka 108 EMS, 2014–19"

# ---------- palette and type ----------
def rgb(h):
    return RGBColor.from_string(h)


DARK, TILE, AMBER, AMBER_D, AMBER_PALE = rgb("0B0D10"), rgb("14171B"), rgb("F59E0B"), rgb("B45309"), rgb("FEF3C7")
INK, MID, GREY, BORDER, PALE, WHITE, ON_DARK = rgb("111111"), rgb("374151"), rgb("6B7280"), rgb("D9DADD"), rgb("F5F6F7"), rgb("FFFFFF"), rgb("E5E7EB")
SW, SH, MX = 13.333, 7.5, 0.7
CW = SW - 2 * MX
TOP = 2.15  # content top
N_SLIDES = 16

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
prs.core_properties.author = prs.core_properties.last_modified_by = "Nandish"
prs.core_properties.title = "Emergency Green Corridor: submission deck"
BLANK = prs.slide_layouts[6]


# ---------- helpers ----------
def style_run(r, size, bold=False, color=INK, font=FONT, caps=False, spc=None):
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
    r.font.color.rgb = color
    rpr = r._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", font)
    if caps:
        rpr.set("cap", "all")
    if spc:
        rpr.set("spc", str(spc))


def fill_frame(tf, paras, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, after=0, margins=(0, 0, 0, 0), font=FONT, caps=False, spc=None):
    """paras: list of str | list of (text, opts) runs."""
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = (Inches(m) for m in margins)
    for i, parts in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment, p.space_after = align, Pt(after)
        if isinstance(parts, str):
            parts = [(parts, {})]
        for t, o in parts:
            r = p.add_run()
            r.text = t
            style_run(r, o.get("size", size), o.get("bold", bold), o.get("color", color), o.get("font", font), o.get("caps", caps), o.get("spc", spc))
            if o.get("link"):
                r.hyperlink.address = o["link"]


def text(slide, x, y, w, h, paras, name="Text", **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = name
    fill_frame(tb.text_frame, [paras] if isinstance(paras, str) else paras, **kw)
    return tb


def add_shadow(shape, blur=10, dist=3, alpha=18):
    sp = shape._element.spPr
    for old in sp.findall(qn("a:effectLst")):
        sp.remove(old)
    eff = etree.SubElement(sp, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad=str(int(blur * 12700)), dist=str(int(dist * 12700)), dir="5400000", algn="t", rotWithShape="0")
    etree.SubElement(etree.SubElement(sh, qn("a:srgbClr"), val="000000"), qn("a:alpha"), val=str(alpha * 1000))


def box(slide, x, y, w, h, fill=WHITE, line=BORDER, lw=0.75, dash=False, shadow=False, radius=0.08, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name="Box"):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.name = name
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb, s.line.width = line, Pt(lw)
        if dash:
            etree.SubElement(s.line._get_or_add_ln(), qn("a:prstDash"), val="dash")
    s.shadow.inherit = False
    if shadow:
        add_shadow(s)
    return s


def shape_text(s, paras, **kw):
    kw.setdefault("margins", (0.15, 0.1, 0.15, 0.1))
    fill_frame(s.text_frame, [paras] if isinstance(paras, str) else paras, **kw)


def line(slide, x1, y1, x2, y2, head=False, color=GREY, w=1.75):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.name = "Connector"
    c.line.color.rgb, c.line.width = color, Pt(w)
    if head:
        etree.SubElement(c.line._get_or_add_ln(), qn("a:tailEnd"), type="triangle")
    etree.SubElement(c._element.spPr, qn("a:effectLst"))  # no theme shadow on lines
    return c


def prep(path, spec=None, aspect=None, maxw=1600, q=80):
    """Crop around fractions spec=(fx, fy, fw) of the image at `aspect`, downscale, JPEG."""
    im = Image.open(path).convert("RGB")
    if spec and aspect:
        fx, fy, fw = spec
        cw = fw * im.width
        ch = cw / aspect
        if ch > im.height:
            ch, cw = im.height, im.height * aspect
        left = min(max(fx * im.width - cw / 2, 0), im.width - cw)
        top = min(max(fy * im.height - ch / 2, 0), im.height - ch)
        im = im.crop((int(left), int(top), int(left + cw), int(top + ch)))
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    buf.seek(0)
    return buf, im.size


def shot(slide, fn, x, y, w, h=None, spec=None, frame=True, maxw=1600):
    path = IMG + fn
    aspect = (w / h) if h else Image.open(path).size[0] / Image.open(path).size[1]
    buf, (iw, ih) = prep(path, spec, aspect if spec or h else None, maxw)
    h = w * ih / iw if h is None else h
    pic = slide.shapes.add_picture(buf, Inches(x), Inches(y), Inches(w), Inches(h))
    pic.name = "Screenshot"
    if frame:
        pic.line.color.rgb, pic.line.width = rgb("2B2D31"), Pt(0.75)
        add_shadow(pic, blur=12, dist=3, alpha=26)
    return h


def qr_png(url):
    q = qrcode.QRCode(border=1, box_size=12, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image(fill_color="#111111", back_color="white").save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


# ---------- slide scaffolding ----------
def new_slide(dark=False):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = DARK if dark else WHITE
    return s


def content_slide(section, lede, sub=None, footer_section=None):
    """Masthead (eyebrow, title, thin amber rule, lede) and slim footer. `sub` = grey parenthetical after the section name."""
    s = new_slide()
    n = len(prs.slides)
    text(s, MX, 0.4, CW, 0.25, DATA["eyebrow"], name="Masthead eyebrow", size=11, bold=True, color=AMBER_D, caps=True, spc=120)
    title = [(section, {})] + ([(" " + sub, {"size": 18, "bold": False, "color": GREY})] if sub else [])
    text(s, MX, 0.7, CW, 0.62, [title], name="Title", size=34, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    r = line(s, MX, 1.4, MX + CW, 1.4, color=AMBER, w=1.25)
    r.name = "Masthead rule"
    text(s, MX, 1.52, CW, 0.4, lede, name="Lede", size=18, color=MID)
    text(s, MX, 7.0, 8, 0.25, f"Green Corridor · {footer_section or section}", name="Footer", size=10, color=GREY)
    text(s, SW - MX - 2, 7.0, 2, 0.25, f"{n} / {N_SLIDES}", name="Page", size=10, color=GREY, align=PP_ALIGN.RIGHT)
    return s


def dark_footer(s, label):
    n = len(prs.slides)
    text(s, MX, 7.0, 8, 0.25, f"Green Corridor · {label}", name="Footer", size=10, color=rgb("9CA3AF"))
    text(s, SW - MX - 2, 7.0, 2, 0.25, f"{n} / {N_SLIDES}", name="Page", size=10, color=rgb("9CA3AF"), align=PP_ALIGN.RIGHT)


def stat_tile(slide, x, y, w, h, num, label, unit="", amber=False, num_size=54):
    s = box(slide, x, y, w, h, fill=AMBER if amber else TILE, line=None, radius=0.14, name="Stat tile")
    numc, labc = (INK, INK) if amber else (AMBER, ON_DARK)
    top = [(num, {"size": num_size, "bold": True, "color": numc})] + ([(" " + unit, {"size": 22, "bold": True, "color": numc})] if unit else [])
    shape_text(s, [top, [(label, {"size": 16, "color": labc})]], anchor=MSO_ANCHOR.MIDDLE, margins=(0.3, 0.1, 0.25, 0.1), after=4)
    return s


def glyph_circle(slide, x, y, d, glyph, fill=TILE, color=AMBER, size=20):
    c = box(slide, x, y, d, d, fill=fill, line=None, shape=MSO_SHAPE.OVAL, name="Icon")
    shape_text(c, [glyph], size=size, color=color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))


def word_count(slide):
    """Body words: all text except masthead, footer, lede, 'Figure*' shapes and display numerals (runs >= 30 pt)."""
    n = 0
    for sh in slide.shapes:
        if sh.name in ("Masthead eyebrow", "Cover eyebrow", "Title", "Lede", "Footer", "Page") or sh.name.startswith("Figure") or not sh.has_text_frame:
            continue
        for p in sh.text_frame.paragraphs:
            n += sum(len(re.findall(r"[A-Za-z0-9₹]+(?:[.,][0-9]+)*", r.text)) for r in p.runs if r.font.size is None or r.font.size.pt < 30)
    return n


# ======================================================================
# 1 cover (dark)
s = new_slide(dark=True)
text(s, MX, 1.9, 11.5, 0.3, DATA["eyebrow"], name="Cover eyebrow", size=12, bold=True, color=AMBER, caps=True, spc=140)
line(s, MX, 2.4, MX + 0.9, 2.4, color=AMBER, w=3)
text(s, MX, 2.75, 6.3, 1.9, "Emergency Green Corridor", name="Cover title", size=54, bold=True, color=rgb("F5F5F4"))
text(s, MX, 4.75, 6.0, 0.9, DATA["tagline"], name="Cover tagline", size=22, color=ON_DARK)
text(s, MX, 6.2, 6.2, 0.3, "Nandish · green-corridor-2026.web.app", name="Cover byline", size=13, color=rgb("9CA3AF"))
st = box(s, 7.45, 2.5, 5.2, 3.3, fill=TILE, line=None, radius=0.16, name="Cover stat")
shape_text(st, [[("60 %+", {"size": 72, "bold": True, "color": AMBER})], [(DATA["cover_stat"], {"size": 17, "color": ON_DARK})]],
           anchor=MSO_ANCHOR.MIDDLE, margins=(0.4, 0.2, 0.35, 0.2), after=6)
text(s, 7.45, 5.95, 5.2, 0.6, DATA["cover_cite"], name="Cover citation", size=11, color=rgb("9CA3AF"))

# 2 team details
s = content_slide("Team details", "A solo entry, built end to end by one contributor.")
tw = (CW - 0.4) / 3
box(s, MX, TOP + 0.1, tw, 1.9, fill=PALE, line=None, radius=0.14, name="Card")
text(s, MX + 0.3, TOP + 0.35, tw - 0.6, 0.3, "Team name", size=12, bold=True, color=AMBER_D, caps=True, spc=100)
text(s, MX + 0.3, TOP + 0.85, tw - 0.6, 0.8, "Green Corridor", size=28, bold=True)
box(s, MX + tw + 0.2, TOP + 0.1, tw, 1.9, fill=PALE, line=None, radius=0.14, name="Card")
text(s, MX + tw + 0.5, TOP + 0.35, tw - 0.6, 0.3, "Team leader", size=12, bold=True, color=AMBER_D, caps=True, spc=100)
text(s, MX + tw + 0.5, TOP + 0.85, tw - 0.6, 0.8, "Nandish", size=28, bold=True)
b = box(s, MX + 2 * (tw + 0.2), TOP + 0.1, tw, 1.9, fill=TILE, line=None, radius=0.14, name="Card")
text(s, MX + 2 * (tw + 0.2) + 0.3, TOP + 0.35, tw - 0.6, 0.3, "Contributors", size=12, bold=True, color=AMBER, caps=True, spc=100)
text(s, MX + 2 * (tw + 0.2) + 0.3, TOP + 0.85, tw - 0.6, 0.8, "Sole contributor", size=28, bold=True, color=WHITE)
pb = box(s, MX, TOP + 2.35, CW, 2.25, fill=TILE, line=None, radius=0.14, name="Problem card")
text(s, MX + 0.4, TOP + 2.65, 6, 0.3, "Problem statement", size=12, bold=True, color=AMBER, caps=True, spc=100)
text(s, MX + 0.4, TOP + 3.1, CW - 0.8, 1.3, "Sustainability & Social Impact: emergency vehicles stuck at red signals while the junction constable is never told.", size=26, bold=True, color=WHITE)

# 3 brief
s = content_slide("Brief about the idea", DATA["headlines"][3])
tw3, th3 = (CW - 0.4) / 3, 3.4
for i, (num, lab, unit, amber) in enumerate([
    ("≈ 7.9", "saved for the critical ambulance", "min", True),
    (f"{DATA['lead_long_min']} vs {DATA['lead_short_min']}", f"warning at a {DATA['queue_m']} m queue vs a 100 m queue", "min", False),
    (DATA["saved_min"], "three-vehicle total, simulated baseline", "min", False),
]):
    stat_tile(s, MX + i * (tw3 + 0.2), TOP + 0.1, tw3, th3, num, lab, unit, amber=amber, num_size=60)
text(s, MX, TOP + th3 + 0.45, CW, 0.3, DATA["brief_caption"], size=13, color=GREY)

# 4 opportunities
s = content_slide("Opportunities", DATA["headlines"][4], sub="(how it differs / how it solves / USP)")
cw3, ch3 = (CW - 0.4) / 3, 4.0
OPP = [("≠", "How it differs", "Warning sized to the queue", "vs fixed-radius alerts"),
       ("✓", "How it solves", "Queue cleared before the siren", "vs manual green corridors"),
       ("★", "USP", "Rules decide, Gemini explains; no hardware", "vs IR/GPS preemption")]
for i, (g, label, ln, vs) in enumerate(OPP):
    x, dark = MX + i * (cw3 + 0.2), i == 2
    box(s, x, TOP + 0.1, cw3, ch3, fill=TILE if dark else WHITE, line=None if dark else BORDER, radius=0.14, shadow=not dark, name="Card")
    glyph_circle(s, x + 0.35, TOP + 0.4, 0.7, g, fill=AMBER if dark else TILE, color=INK if dark else AMBER, size=24)
    text(s, x + 0.35, TOP + 1.3, cw3 - 0.7, 0.35, label, size=16, bold=True, color=AMBER if dark else AMBER_D, caps=True, spc=80)
    text(s, x + 0.35, TOP + 1.8, cw3 - 0.7, 1.4, ln, size=24, bold=True, color=WHITE if dark else INK)
    v = box(s, x + 0.35, TOP + 3.25, cw3 - 0.7, 0.45, fill=AMBER_PALE if not dark else rgb("2A2D33"), line=None, radius=0.22, name="Versus chip")
    shape_text(v, [vs], size=14, bold=True, color=AMBER_D if not dark else AMBER, anchor=MSO_ANCHOR.MIDDLE, margins=(0.2, 0, 0.1, 0))

# 5 features
s = content_slide("List of features", DATA["headlines"][5])
cw3, chh, gy = (CW - 0.4) / 3, 1.95, 0.15
FIX = {"triage-gemini.png": (0.5, 0.468, 1.0), "agent-trace.png": (0.5, 0.775, 0.39)}
for i, (fn, spec, title, _) in enumerate(DATA["screens"]):
    spec = FIX.get(fn, spec)
    r_, c_ = divmod(i, 3)
    x, y = MX + c_ * (cw3 + 0.2), TOP + r_ * (chh + gy)
    box(s, x, y, cw3, chh, radius=0.1, name="Card")
    shot(s, fn, x + 0.1, y + 0.1, cw3 - 0.2, h=1.35, spec=spec)
    text(s, x + 0.12, y + 1.55, cw3 - 0.24, 0.3, title, size=14, bold=True)
chip_y, gap = TOP + 2 * chh + gy + 0.25, 0.12
cwid = (CW - gap * 5) / 6
for i, e in enumerate(DATA["engines"]):
    c = box(s, MX + i * (cwid + gap), chip_y, cwid, 0.38, fill=PALE, line=None, radius=0.19, name="Chip")
    shape_text(c, [e], size=12, color=MID, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margins=(0.04, 0, 0.04, 0))

# 6 process flow
s = content_slide("Process flow", DATA["headlines"][6])
l1y, l1h, l2y, l2h = TOP, 2.0, TOP + 2.2, 1.95
for y, h, lab in ((l1y, l1h, "Road"), (l2y, l2h, "Hospital")):
    box(s, MX, y, CW, h, fill=PALE, line=None, radius=0.12, name="Swimlane")
    text(s, MX + 0.2, y + 0.12, 2, 0.25, lab, size=11, bold=True, color=GREY, caps=True, spc=100)
bw, bh = 1.62, 1.1
gapx = (CW - 0.4 - 6 * bw) / 5
x0, by = MX + 0.2, l1y + 0.55
flow = DATA["flow"]
for i, lab in enumerate(flow):
    x, seam = x0 + i * (bw + gapx), i == len(flow) - 1
    b = box(s, x, by, bw, bh, fill=AMBER_PALE if seam else WHITE, line=AMBER if seam else BORDER, lw=2.5 if seam else 0.75, radius=0.1, name="Flow step")
    shape_text(b, [[(str(i + 1), {"size": 12, "bold": True, "color": AMBER_D})], [(lab, {"size": 14, "bold": True})]], margins=(0.12, 0.1, 0.08, 0.06), after=2)
    if i < len(flow) - 1:
        line(s, x + bw + 0.03, by + bh / 2, x + bw + gapx - 0.03, by + bh / 2, head=True)
hx, hy, hw, hh = x0 + 3 * (bw + gapx), l2y + 0.55, 2 * bw + gapx, 0.9
hb = box(s, hx, hy, hw, hh, name="Flow step")
shape_text(hb, [[("7", {"size": 12, "bold": True, "color": AMBER_D})], [(DATA["flow_hospital"], {"size": 14, "bold": True})]], margins=(0.15, 0.1, 0.1, 0.06), after=2)
cx3 = x0 + 2 * (bw + gapx) + bw / 2
line(s, cx3, by + bh + 0.03, cx3, hy + hh / 2, color=GREY)
line(s, cx3, hy + hh / 2, hx - 0.03, hy + hh / 2, head=True)
text(s, MX, TOP + 4.35, CW, 0.3, DATA["flow_caption"], size=12, color=GREY)

# 7 wireframes
s = content_slide("Wireframes", DATA["headlines"][7])
ph_h, fy = 3.65, TOP + 0.05


def phone(slide, fn, x):
    buf, (iw, ih) = prep(IMG + fn, maxw=900)
    pw = ph_h * iw / ih
    box(slide, x, fy, pw + 0.2, ph_h + 0.2, fill=rgb("1B1C20"), line=rgb("3A3C42"), lw=1, radius=0.26, shadow=True, name="Phone frame")
    slide.shapes.add_picture(buf, Inches(x + 0.1), Inches(fy + 0.1), Inches(pw), Inches(ph_h)).name = "Screenshot"
    return pw + 0.2


x = MX + 0.3
for fn, cap in (("triage-gemini.png", "Voice triage"), ("cop.png", "PREPARE alert")):
    wd = phone(s, fn, x)
    text(s, x - 0.4, fy + ph_h + 0.38, wd + 0.8, 0.3, cap, size=13, bold=True, color=MID, align=PP_ALIGN.CENTER)
    x += wd + 0.7
lap_w = MX + CW - 0.3 - x
scr_w = lap_w - 0.24
scr_h = scr_w * 9 / 16
lap_y = fy + (ph_h + 0.2 - (scr_h + 0.24)) / 2
box(s, x, lap_y, lap_w, scr_h + 0.24, fill=rgb("1B1C20"), line=rgb("3A3C42"), lw=1, radius=0.12, shadow=True, name="Laptop frame")
buf, _ = prep(IMG + "hospital-handover.png", (0.5, 0.45, 0.8), 16 / 9)
s.shapes.add_picture(buf, Inches(x + 0.12), Inches(lap_y + 0.12), Inches(scr_w), Inches(scr_h)).name = "Screenshot"
box(s, x - 0.25, lap_y + scr_h + 0.24, lap_w + 0.5, 0.12, fill=rgb("3A3C42"), line=None, radius=0.06, name="Laptop base")
text(s, x - 0.4, fy + ph_h + 0.38, lap_w + 0.8, 0.3, "Hospital handover", size=13, bold=True, color=MID, align=PP_ALIGN.CENTER)
text(s, MX, TOP + 4.5, CW, 0.3, DATA["wire_caption"], size=12, color=GREY, align=PP_ALIGN.CENTER)

# 8 architecture
s = content_slide("Architecture", DATA["headlines"][8])
arch = os.path.join(tempfile.gettempdir(), "gc-architecture-deck.png")
subprocess.run(["npx", "-y", "sharp-cli", "-i", IMG + "architecture-deck.svg", "-o", arch, "--density", "300", "resize", "2400"], check=True, capture_output=True)
aw, ah = Image.open(arch).size
dw = min(CW, 4.3 * aw / ah)
pic = s.shapes.add_picture(arch, Inches(MX + (CW - dw) / 2), Inches(TOP - 0.05), Inches(dw), Inches(dw * ah / aw))
pic.name = "Figure architecture"
text(s, MX, TOP + 4.4, CW, 0.4, DATA["arch_caption"], size=12, color=GREY)

# 9 technologies
s = content_slide("Technologies", DATA["headlines"][9], sub="(Google Cloud)")
TECH = [("AI & language", ["Gemini on Vertex AI", "Google ADK", "Cloud Translation"]),
        ("Maps & speech", ["Routes API", "Text-to-Speech", "Cloud Storage"]),
        ("Run & data", ["Cloud Run", "Firestore", "BigQuery"]),
        ("Delivery", ["Firebase Hosting", "Cloud Build", "Secret Manager"])]
rstep, rh = 0.88, 0.7
pw3 = (CW - 2.6 - 0.4) / 3
for r_, (grp, items) in enumerate(TECH):
    y = TOP + 0.05 + r_ * rstep
    box(s, MX, y + 0.23, 0.24, 0.24, fill=AMBER, line=None, shape=MSO_SHAPE.OVAL, name="Marker")
    text(s, MX + 0.45, y, 2.1, rh, grp, size=18, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    for c_, nm in enumerate(items):
        p_ = box(s, MX + 2.6 + c_ * (pw3 + 0.2), y, pw3, rh, radius=0.1, name="Pill")
        shape_text(p_, [nm], size=18, anchor=MSO_ANCHOR.MIDDLE, margins=(0.25, 0, 0.1, 0))
by = TOP + 0.05 + 4 * rstep + 0.1
bq = box(s, MX, by, CW, 0.7, fill=PALE, line=rgb("9CA3AF"), dash=True, radius=0.1, name="BigQuery ML note")
shape_text(bq, [[("BigQuery ML  ", {"bold": True}), ("pipeline in place; model retrained on peak rows before submission", {"color": MID})]], size=16, anchor=MSO_ANCHOR.MIDDLE, margins=(0.25, 0, 0.2, 0))

# 10 cost
s = content_slide("Estimated implementation cost", DATA["headlines"][10])
total = sum(c[2] for c in DATA["cost"])
run20 = total * 20 / 60
tw3 = (CW - 0.4) / 3
stat_tile(s, MX, TOP + 0.1, tw3, 1.85, f"≈ ₹{total:.0f}", "per vehicle-hour (estimate)", amber=True, num_size=44)
stat_tile(s, MX + tw3 + 0.2, TOP + 0.1, tw3, 1.85, f"≈ ₹{round(run20, -1):.0f}", "per 20-min run", num_size=44)
stat_tile(s, MX + 2 * (tw3 + 0.2), TOP + 0.1, tw3, 1.85, f"≈ ₹{round(round(run20, -1) * 100, -2):,.0f}", "city-month at 100 runs (illustrative)", num_size=44)
CROWS = [("Routes", "3/min × 60 × ₹0.85", f"₹{DATA['cost'][0][2]:.0f}"), ("Gemini", "17 × ₹0.02", f"₹{DATA['cost'][1][2]:.2f}"),
         ("Text-to-Speech", "", f"₹{DATA['cost'][2][2]:.2f}")]
cols, rh_ = (2.6, 3.6, 1.6), 0.62
for ri, row in enumerate(CROWS):
    y, cx = TOP + 2.25 + ri * rh_, MX
    for ci, val in enumerate(row):
        text(s, cx + 0.1, y, cols[ci] - 0.2, rh_, val, name="Cost cell", size=16, bold=(ci == 0), anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.RIGHT if ci == 2 else PP_ALIGN.LEFT)
        cx += cols[ci]
    line(s, MX, y + rh_, MX + sum(cols), y + rh_, color=BORDER, w=0.75)
lv = box(s, MX + sum(cols) + 0.4, TOP + 2.25, CW - sum(cols) - 0.4, 3 * rh_, fill=AMBER_PALE, line=None, radius=0.12, name="Lever")
shape_text(lv, [[("Lever: cache Routes beyond today's 20 s", {"bold": True})]], size=16, anchor=MSO_ANCHOR.MIDDLE, margins=(0.25, 0.1, 0.2, 0.1), after=4)

# 11 snapshots
s = content_slide("Snapshots of the prototype", DATA["headlines"][11])
lw_, lh_ = 6.6, 3.7
shot(s, "sim-split.png", MX, TOP + 0.05, lw_, h=lh_, spec=(0.5, 0.45, 1.0))
text(s, MX, TOP + 0.05 + lh_ + 0.1, lw_, 0.3, "Replay simulator", size=13, bold=True, color=MID)
rx, rw_ = MX + lw_ + 0.4, CW - lw_ - 0.4
shot(s, "control.png", rx, TOP + 0.05, rw_, h=1.6, spec=(0.5, 0.34, 1.0))
text(s, rx, TOP + 1.75, rw_, 0.3, "Control room", size=13, bold=True, color=MID)
shot(s, "cop-alert.png", rx, TOP + 2.2, rw_, h=1.55, spec=(0.5, 0.30, 1.0))
text(s, rx, TOP + 3.85, rw_, 0.3, "STOP alert, spoken", size=13, bold=True, color=MID)

# 12 snapshots: agent trace
s = content_slide("Snapshots of the prototype", "Live routing trace: Jayadeva chosen, two alternatives rejected", sub="(routing agent)")
trace = ["required_capabilities(critical) -> cath_lab", "list_hospitals(blr) -> 3 hospitals", "check_diversion(Jayadeva) -> accepting",
         "check_diversion(Apollo) -> on diversion", "eta_to(Jayadeva) -> 373 s, 2.6 km", "Added to baseline: icu"]
tb = box(s, MX, TOP + 0.1, 6.6, 3.9, fill=TILE, line=None, radius=0.14, name="Figure trace")
paras = [[(f"{i + 1}  ", {"color": AMBER, "bold": True}), (t, {"color": ON_DARK})] for i, t in enumerate(trace)]
paras.append([("Destination Jayadeva, confidence 1.0", {"color": AMBER, "bold": True, "font": FONT, "size": 16})])
shape_text(tb, paras, size=14, font=MONO, anchor=MSO_ANCHOR.MIDDLE, margins=(0.35, 0.2, 0.25, 0.2), after=12)
shot(s, "agent-trace.png", MX + 6.9, TOP + 0.1, CW - 6.9, spec=(0.5, 0.75, 0.39), h=3.4)
text(s, MX + 6.9, TOP + 3.65, CW - 6.9, 0.6, "The trace as shown in /vehicle.", size=13, color=GREY)

# 13 performance
s = content_slide("Performance report / benchmarking", DATA["headlines"][12])
tw4 = (CW - 0.4) / 3
for i, (num, lab, unit) in enumerate([
    (str(EV["field"]), "field accuracy", "%"), (str(EV["tier"]), "tier accuracy", "%"), (EV["latency"], "mean extraction", "s"),
]):
    stat_tile(s, MX + i * (tw4 + 0.2), TOP + 0.05, tw4, 1.9, num, lab, unit, num_size=54)
text(s, MX, TOP + 2.1, CW, 0.5, f"{EV['clips']} synthetic clips, the ones the fix targeted; real clips pending. Before the fix: 87 % / 73 %.", size=12, color=GREY)
stat_tile(s, MX, TOP + 2.65, 5.6, 1.8, DATA["load"][0], "/location p50 / p95, offline", unit="ms", num_size=48)
t = box(s, MX + 5.9, TOP + 2.65, CW - 5.9, 1.8, fill=TILE, line=None, radius=0.14, name="Stat tile")
shape_text(t, [[("344", {"bold": True, "size": 32, "color": AMBER}), (" Python · ", {"color": ON_DARK}), ("138", {"bold": True, "size": 32, "color": AMBER}), (" web tests", {"color": ON_DARK})],
               [("98 %", {"bold": True, "size": 32, "color": AMBER}), (" coverage", {"color": ON_DARK})]], size=18, anchor=MSO_ANCHOR.MIDDLE, margins=(0.3, 0.1, 0.2, 0.1), after=6)

# 14 additional details / future development
s = content_slide("Additional details / future development", DATA["headlines"][13])
bw3 = 3.35
ar = (CW - 3 * bw3) / 2
SHORT = ["Constable alerts", "Signal controllers", "Learning controller"]
for i, (tag, title, ln) in enumerate(DATA["roadmap"]):
    title = SHORT[i]
    x = MX + i * (bw3 + ar)
    dark, mid = i == 0, i == 1
    b = box(s, x, TOP + 0.1, bw3, 2.5, fill=TILE if dark else (AMBER_PALE if mid else WHITE), line=None if dark else (AMBER if mid else rgb("9CA3AF")),
            lw=2 if mid else 1, dash=(i == 2), shadow=dark or mid, radius=0.14, name="Roadmap step")
    tagc, titc, linc = (AMBER, WHITE, ON_DARK) if dark else (AMBER_D, INK, MID)
    shape_text(b, [[(tag, {"size": 12, "bold": True, "color": tagc, "caps": True, "spc": 100})], [(title, {"size": 20, "bold": True, "color": titc})], [(ln, {"size": 16, "color": linc})]],
               margins=(0.3, 0.3, 0.25, 0.2), after=12)
    if i < 2:
        line(s, x + bw3 + 0.12, TOP + 1.55, x + bw3 + ar - 0.12, TOP + 1.55, head=True, color=AMBER_D, w=2.25)
lim = box(s, MX, TOP + 2.95, CW, 1.1, fill=PALE, line=None, radius=0.12, name="Limits")
shape_text(lim, [[("Signals simulated, patients synthetic, minutes saved estimated.", {})]],
           size=16, anchor=MSO_ANCHOR.MIDDLE, margins=(0.35, 0.1, 0.35, 0.1))

# 15 links
s = content_slide("Links", DATA["headlines"][14])
tw_, th_ = (CW - 0.9) / 4, 4.4
for i, key in enumerate(("github", "video", "app", "deck")):
    label, shown, url = DATA["links"][key]
    x = MX + i * (tw_ + 0.3)
    box(s, x, TOP + 0.05, tw_, th_, dash=(url is None), line=BORDER if url else rgb("9CA3AF"), radius=0.14, name="Link tile")
    text(s, x + 0.3, TOP + 0.3, tw_ - 0.6, 0.3, label, size=12, bold=True, color=GREY, caps=True, spc=80)
    if url:
        q = 2.2
        qp = s.shapes.add_picture(qr_png(url), Inches(x + (tw_ - q) / 2), Inches(TOP + 0.8), Inches(q), Inches(q))
        qp.name = "QR"
        qp.click_action.hyperlink.address = url
        text(s, x + 0.15, TOP + 3.3, tw_ - 0.3, 0.8, shown, size=12, bold=True, align=PP_ALIGN.CENTER)
    else:
        text(s, x + 0.3, TOP + 1.4, tw_ - 0.6, 1.4, "[link + QR at submission]", size=22, bold=True, color=GREY, align=PP_ALIGN.CENTER)

# 16 closing (dark)
s = new_slide(dark=True)
text(s, MX, 2.1, 10, 0.3, DATA["eyebrow"], name="Cover eyebrow", size=12, bold=True, color=AMBER, caps=True, spc=140)
line(s, MX, 2.6, MX + 0.9, 2.6, color=AMBER, w=3)
text(s, MX, 2.9, 11.5, 1.8, ["Warn the constable", "before the siren arrives."], name="Closing title", size=54, bold=True, color=rgb("F5F5F4"))
text(s, MX, 4.9, 11, 0.9, ["Try it: green-corridor-2026.web.app", "Read it: github.com/Nandish3010/ideal-disco"], name="Closing links", size=20, color=AMBER, after=6)
text(s, MX, 6.2, 8, 0.3, "Built by Nandish", name="Closing byline", size=13, color=rgb("9CA3AF"))
dark_footer(s, "Thank you")

assert len(prs.slides) == N_SLIDES, len(prs.slides)
for n, sl in enumerate(prs.slides, 1):
    c = word_count(sl)
    print(f"slide {n:2d}: {c:3d} body words" + ("  <-- over 35" if c > 35 else ""))
prs.save(OUT)
print("saved", OUT, EV, f"total={total:.2f}")


def export_pdf():
    import fitz

    src, tmp = os.path.abspath(OUT), os.path.abspath(PDF)
    box_dir = os.path.expanduser("~/Library/Containers/com.microsoft.Powerpoint/Data")  # PowerPoint is sandboxed
    stage = os.path.join(box_dir, "gc-deck-export.pdf") if os.path.isdir(box_dir) else tmp
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
