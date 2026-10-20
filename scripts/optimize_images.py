"""Optimise the panel images for the web.

The three original sketches are 2400x1792 JPEGs at about 2.5 MB each, which is
a heavy landing page. This script writes web friendly derivatives into
``docs/img/`` and leaves the originals untouched in ``docs/``.

It needs Pillow, which is not part of the lab environment on purpose. Run it
with a throwaway virtual environment:

    python3 -m venv "$TMPDIR/imgtools"
    "$TMPDIR/imgtools/bin/pip" install pillow
    "$TMPDIR/imgtools/bin/python" scripts/optimize_images.py

What it writes:

- ``docs/img/<name>.jpg`` - 1600 pixels wide, quality 82, progressive
- ``docs/img/<name>.webp`` - the same picture, usually a third smaller
- ``docs/img/og.jpg`` - a 1200x630 card for the social preview
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    print("this script needs Pillow, see the docstring for the one liner")
    raise SystemExit(2) from exc

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ORIGINALS = DOCS / "originals"
OUT = DOCS / "img"

PANELS = {
    "rest-vs-graphql": "rest-vs-graphql.jpeg",
    "oltp-vs-olap": "oltp-vs-olap.jpeg",
    "mcp-with-codemode": "mcp-with-codemode.jpeg",
}

WIDTH = 1600
JPEG_QUALITY = 82
WEBP_QUALITY = 80

INK = (20, 24, 31, 255)
ORANGE = (242, 128, 60, 255)
WHITE = (255, 255, 255, 255)
GREY = (169, 180, 196, 255)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def optimise_panels() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, source in PANELS.items():
        path = ORIGINALS / source
        if not path.exists():
            print(f"missing {path}")
            continue
        image = Image.open(path).convert("RGB")
        if image.width > WIDTH:
            height = round(image.height * WIDTH / image.width)
            image = image.resize((WIDTH, height), Image.LANCZOS)
        jpeg_path = OUT / f"{name}.jpg"
        webp_path = OUT / f"{name}.webp"
        image.save(jpeg_path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        image.save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
        original = (path.stat().st_size / 1024) / 1024
        print(
            f"{source:<24} {original:.2f} MB  ->  "
            f"{jpeg_path.name} {jpeg_path.stat().st_size / 1024:.0f} KB  "
            f"{webp_path.name} {webp_path.stat().st_size / 1024:.0f} KB"
        )


def build_social_card() -> None:
    source = OUT / "mcp-with-codemode.jpg"
    if not source.exists():
        return
    card = Image.new("RGB", (1200, 630), INK)
    panel = Image.open(source).convert("RGB")
    panel = panel.resize((470, round(panel.height * 470 / panel.width)), Image.LANCZOS)
    card.paste(panel, (1200 - panel.width - 56, (630 - panel.height) // 2))

    draw = ImageDraw.Draw(card)
    draw.text((72, 168), "MCP + CODEMODE", font=font(25), fill=ORANGE)
    draw.text((72, 210), "rest.graphql.win", font=font(62), fill=WHITE)
    draw.text((72, 302), "MCP + CodeMode", font=font(30), fill=WHITE)
    draw.text((72, 344), "on top of REST vs GraphQL", font=font(30), fill=WHITE)
    draw.text((72, 398), "one lab, one dataset, measured", font=font(23), fill=GREY)
    draw.text((72, 432), "SQLite for OLTP, DuckDB for OLAP", font=font(23), fill=GREY)

    path = OUT / "og.jpg"
    card.save(path, "JPEG", quality=86, optimize=True, progressive=True)
    print(f"social card                ->  {path.name} {path.stat().st_size / 1024:.0f} KB")


def main() -> int:
    optimise_panels()
    build_social_card()
    return 0


if __name__ == "__main__":
    sys.exit(main())
