#!/usr/bin/env python3
"""Render the link-preview image and the touch icon for the web app.

og-image.png (1200×630) is what LinkedIn, Teams, Slack and X show when someone
pastes a link to the converter; index.html and the content pages reference it.
apple-touch-icon.png (180×180) is the home-screen icon. Both reuse the arrows of
frontend/public/favicon.svg.

Usage (needs Pillow and the DejaVu fonts):
  python3 tools/generate_og_image.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"

WIDTH, HEIGHT = 1200, 630
SLATE_TOP = (30, 41, 59)
SLATE_BOTTOM = (2, 6, 23)
BLUE = (59, 130, 246)
LIGHT_BLUE = (147, 197, 253)
WHITE = (255, 255, 255)
SLATE_200 = (226, 232, 240)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
REGULAR = FONT_DIR / "DejaVuSans.ttf"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise SystemExit(f"font not found: {path} (install fonts-dejavu)")
    return ImageFont.truetype(str(path), size)


def icon(size: int) -> Image.Image:
    """favicon.svg at ``size`` px: blue rounded square, two opposite arrows (drawn at 4× and scaled down)."""
    s = size * 4
    k = s / 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(14 * k), fill=BLUE)
    w = int(5 * k)
    for line in (
        [(14, 24), (44, 24)],
        [(44, 24), (37, 17)],
        [(50, 40), (20, 40)],
        [(20, 40), (27, 47)],
    ):
        pts = [(x * k, y * k) for x, y in line]
        d.line(pts, fill=WHITE, width=w)
        for x, y in pts:
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def og_image() -> Image.Image:
    grad = Image.new("RGB", (1, HEIGHT))
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        grad.putpixel((0, y), tuple(int(SLATE_TOP[i] + (SLATE_BOTTOM[i] - SLATE_TOP[i]) * t) for i in range(3)))
    img = grad.resize((WIDTH, HEIGHT))
    glow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(glow).ellipse((-380, -520, 780, 360), fill=40)
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (37, 99, 235)), img, glow)

    draw = ImageDraw.Draw(img)
    mark = icon(208)
    img.paste(mark, (80, 150), mark)

    x = 336
    draw.text((x, 154), "TPT  ·  FUNDSXML 4  ·  OPENFUNDS", font=font(BOLD, 24), fill=LIGHT_BLUE)
    draw.text((x, 196), "Fund Data", font=font(BOLD, 72), fill=WHITE)
    draw.text((x, 290), "Converter · every direction", font=font(BOLD, 38), fill=LIGHT_BLUE)
    draw.line((x, 362, x + 300, 362), fill=(71, 85, 105), width=3)
    draw.text((x, 390), "TPT V7/V8, FundsXML 4 and openfunds as", font=font(REGULAR, 28), fill=SLATE_200)
    draw.text((x, 432), "Excel, CSV or XML. Lossless, XSD report.", font=font(REGULAR, 28), fill=SLATE_200)

    draw.line((80, 536, WIDTH - 80, 536), fill=(51, 65, 85), width=2)
    draw.text((80, 560), "Fund data, one converter", font=font(BOLD, 26), fill=WHITE)
    free = "Free · no login · files not stored"
    f = font(REGULAR, 26)
    draw.text((WIDTH - 80 - draw.textlength(free, font=f), 560), free, font=f, fill=LIGHT_BLUE)
    return img


if __name__ == "__main__":
    og_image().save(PUBLIC / "og-image.png", "PNG", optimize=True)
    touch = Image.new("RGB", (180, 180), WHITE)
    mark = icon(180)
    touch.paste(mark, (0, 0), mark)
    touch.save(PUBLIC / "apple-touch-icon.png", "PNG", optimize=True)
    for name in ("og-image.png", "apple-touch-icon.png"):
        print(f"wrote frontend/public/{name} ({(PUBLIC / name).stat().st_size // 1024} KB)")
