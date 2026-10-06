"""Title cards for the demo video: 1920x1080 PNGs in deck/video-cards/, same palette as the deck.

Run from the repo root: python3 deck/video_cards.py     (needs Pillow, qrcode)
Cards: opener, five section cards matching the shot list in VIDEO.md, closing card with the two QR codes.
"""
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

OUT = "deck/video-cards"
W, H = 1920, 1080
BG, INK, AMBER, MUTED, SOFT = "#0B0B0C", "#F5F5F4", "#F59E0B", "#9CA3AF", "#E5E7EB"
PAD = 160

TITLE = "Emergency Green Corridor"
EYEBROW = "Google Cloud AI Builder Cup 2026"
OPENER_LINE = "Warning the junction constable before the siren arrives."
SECTIONS = [  # (file, title, one line) in shot-list order; VIDEO.md shots 1 / 2-6 / 7-9 / 10-11 / 12-14
    ("01-problem", "Problem", "Same ambulance, same traffic, two lanes."),
    ("02-how-a-cop-gets-warned", "How a cop gets warned", "Voice, tier, route, then a spoken alert."),
    ("03-rules-decide", "Rules decide", "Queue size sets the warning and the order."),
    ("04-the-hospital-knows", "The hospital knows", "The brief lands before the ambulance does."),
    ("05-from-constable-to-controller", "From constable to controller", "Cop alerts today; the signal adapter next."),
]
LINKS = [("Repository", "github.com/Nandish3010/ideal-disco", "https://github.com/Nandish3010/ideal-disco"),
         ("Live app", "green-corridor-2026.web.app", "https://green-corridor-2026.web.app")]

FONTS = [  # (regular, bold), first pair that exists wins
    ("/Applications/Arc.app/Contents/Resources/ARCClients_FontsManager.bundle/Contents/Resources/Inter-Regular.ttf",
     "/Applications/Arc.app/Contents/Resources/ARCClients_FontsManager.bundle/Contents/Resources/Inter-Bold.ttf"),
    ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/HelveticaNeue.ttc"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


def font(size, bold=False):
    for reg, bld in FONTS:
        path = bld if bold else reg
        if os.path.exists(path):
            return ImageFont.truetype(path, size, index=1 if (bold and path.endswith(".ttc")) else 0)
    return ImageFont.load_default()


def fit(draw, text, bold, size, width):
    while size > 40 and draw.textlength(text, font=font(size, bold)) > width:
        size -= 4
    return font(size, bold)


def spaced(draw, xy, text, f, fill, tracking=6):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking


def base():
    im = Image.new("RGB", (W, H), BG)
    return im, ImageDraw.Draw(im)


def footer(d, current=None):
    d.text((PAD, H - 110), TITLE, font=font(28), fill=MUTED)
    for i in range(len(SECTIONS)):
        x = W - PAD - (len(SECTIONS) - i) * 34
        d.ellipse((x, H - 104, x + 16, H - 88), fill=AMBER if i == current else "#2A2B2F")


def opener():
    im, d = base()
    spaced(d, (PAD, 390), EYEBROW.upper(), font(30, True), AMBER)
    d.rounded_rectangle((PAD, 462, PAD + 96, 470), 4, fill=AMBER)
    d.text((PAD, 500), TITLE, font=fit(d, TITLE, True, 132, W - 2 * PAD), fill=INK)
    d.text((PAD, 680), OPENER_LINE, font=fit(d, OPENER_LINE, False, 52, W - 2 * PAD), fill=SOFT)
    return im


def section(i, title, line):
    im, d = base()
    spaced(d, (PAD, 400), f"{i + 1} / {len(SECTIONS)}", font(34, True), AMBER)
    d.text((PAD, 470), title, font=fit(d, title, True, 128, W - 2 * PAD), fill=INK)
    d.text((PAD, 650), line, font=fit(d, line, False, 50, W - 2 * PAD), fill=SOFT)
    footer(d, i)
    return im


def qr(url, size=380):
    q = qrcode.QRCode(border=2, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    return q.make_image(fill_color="#111111", back_color="white").convert("RGB").resize((size, size), Image.NEAREST)


def closing():
    im, d = base()
    spaced(d, (PAD, 110), EYEBROW.upper(), font(28, True), AMBER)
    d.text((PAD, 160), TITLE, font=fit(d, TITLE, True, 92, W - 2 * PAD), fill=INK)
    panel, gap = 420, 320
    x0 = (W - (2 * panel + gap)) // 2
    for k, (label, shown, url) in enumerate(LINKS):
        x = x0 + k * (panel + gap)
        d.rounded_rectangle((x, 340, x + panel, 340 + panel), 28, fill="white")
        im.paste(qr(url, panel - 50), (x + 25, 365))
        lw = int(sum(d.textlength(c, font=font(26, True)) + 5 for c in label))
        uf = fit(d, shown, True, 40, panel + 280)
        uw = int(d.textlength(shown, font=uf))
        spaced(d, (x + (panel - lw) // 2, 810), label.upper(), font(26, True), AMBER, 5)
        d.text((x + (panel - uw) // 2, 855), shown, font=uf, fill=INK)
    return im


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    opener().save(f"{OUT}/00-opener.png", optimize=True)
    for i, (name, title, line) in enumerate(SECTIONS):
        section(i, title, line).save(f"{OUT}/{name}.png", optimize=True)
    closing().save(f"{OUT}/06-closing.png", optimize=True)
    print(sorted(os.listdir(OUT)))
