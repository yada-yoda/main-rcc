"""Generate the blog's share card and touch icon.

Run from blog-src:  python .scripts/make-images.py

Writes src/static/og.png (1200x630) and src/static/apple-touch-icon.png
(180x180), which Eleventy copies to /blog/og.png and /blog/apple-touch-icon.png.
Both are referenced by absolute https://rizzo.cc/blog/... URLs in the page head,
because social scrapers cannot use a data URI and iOS ignores SVG icons.

The look follows the Broadsheet design: paper body, navy ink, teal accent,
navy band with the cyan wordmark. Headline text is pulled from site.json so
the card cannot drift from the page it represents.
"""

import json
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "src", "static")

with open(os.path.join(ROOT, "src", "_data", "site.json"), encoding="utf-8") as fh:
    SITE = json.load(fh)

PAPER = (245, 241, 232)
NAVY = (44, 46, 61)
INK = (30, 32, 48)
MUTED = (91, 95, 114)
TEAL = (13, 138, 156)
CYAN = (0, 188, 212)
TOP_TEXT = (242, 242, 242)
TOP_MUTED = (182, 185, 196)
RULE = (196, 190, 178)

FONTS = "C:/Windows/Fonts/"


def font(name, size):
    return ImageFont.truetype(FONTS + name, size)


def text_width(draw, s, f):
    return draw.textbbox((0, 0), s, font=f)[2]


def tracked(draw, xy, s, f, fill, tracking):
    """Draw text with letter spacing, which PIL does not do on its own."""
    x, y = xy
    for ch in s:
        draw.text((x, y), ch, font=f, fill=fill)
        x += text_width(draw, ch, f) + tracking
    return x


def wrap(draw, s, f, max_width):
    lines, line = [], ""
    for word in s.split():
        trial = (line + " " + word).strip()
        if text_width(draw, trial, f) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_og(path):
    img = Image.new("RGB", (1200, 630), PAPER)
    d = ImageDraw.Draw(img)

    # Navy band with the same wordmark as the top bar of the section.
    d.rectangle([0, 0, 1200, 104], fill=NAVY)
    f_home = font("segoeuib.ttf", 30)
    f_mark = font("georgiab.ttf", 40)
    x = 72
    d.text((x, 34), SITE["domain"], font=f_home, fill=TOP_TEXT)
    x += text_width(d, SITE["domain"], f_home) + 16
    d.text((x, 32), "/", font=f_home, fill=TOP_MUTED)
    x += text_width(d, "/", f_home) + 16
    d.text((x, 28), SITE["section"], font=f_mark, fill=CYAN)

    # Kicker, uppercase and letterspaced like the page.
    f_kick = font("segoeuib.ttf", 22)
    tracked(d, (72, 180), SITE["kicker"].upper(), f_kick, TEAL, 5)

    # Headline in the display face.
    f_head = font("georgiab.ttf", 64)
    y = 228
    for line in wrap(d, SITE["headline"], f_head, 1056):
        d.text((72, y), line, font=f_head, fill=INK)
        y += 82

    # Double rule, the broadsheet signature.
    y = max(y + 26, 470)
    d.rectangle([72, y, 1128, y + 2], fill=RULE)
    d.rectangle([72, y + 8, 1128, y + 10], fill=RULE)

    # Footer line: where it lives, and the version the card was cut from.
    f_foot = font("segoeui.ttf", 24)
    d.text((72, y + 34), SITE["domain"] + SITE["pathPrefix"], font=f_foot, fill=MUTED)
    ver = "v" + SITE["version"]
    d.text((1128 - text_width(d, ver, f_foot), y + 34), ver, font=f_foot, fill=MUTED)

    img.save(path, "PNG", optimize=True)
    return path


def make_touch_icon(path):
    """Same mark as the inline SVG favicon: a ruled broadsheet column.

    Drawn at 4x and downsampled so the rules keep clean edges. Solid
    background because iOS composites transparency onto black.
    """
    scale = 4
    size = 180 * scale
    img = Image.new("RGB", (size, size), NAVY)
    d = ImageDraw.Draw(img)

    left = 40 * scale
    right = 140 * scale
    d.rectangle([left, 40 * scale, right, 57 * scale], fill=CYAN)
    for top in (78, 106, 134):
        end = right if top != 134 else left + 61 * scale
        d.rectangle([left, top * scale, end, (top + 11) * scale], fill=PAPER)

    img.resize((180, 180), Image.LANCZOS).save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":
    os.makedirs(STATIC, exist_ok=True)
    for made in (
        make_og(os.path.join(STATIC, "og.png")),
        make_touch_icon(os.path.join(STATIC, "apple-touch-icon.png")),
    ):
        print("wrote", made)
