#!/usr/bin/env python
"""Assemble the Application Note figure from viewer screenshots.

Screenshots are captured headlessly against the local preview server, so the
figure shows the real interface rather than a mock-up:

    python scripts/serve_local.py &
    bash scripts/capture_screenshots.sh
    python scripts/make_figure.py

    python scripts/make_figure.py --out paper/figure1.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PANELS = [
    ("A", "viewer_night.png", "Two linked embeddings: metadata (left) and gene expression (right)"),
    ("B", "shot_cosmx.png", "The same interface on spatial data (CosMx, 18 tissue tiles)"),
    ("C", "index_page.png", "Publication index; each dataset is one Zarr store"),
]
LABEL_H = 34
PAD = 14
BG = (255, 255, 255)


def load_font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="paper/figure1.png")
    ap.add_argument("--width", type=int, default=1800, help="output width in px")
    args = ap.parse_args()

    missing = [f for _, f, _ in PANELS if not (ROOT / f).exists()]
    if missing:
        raise SystemExit("missing screenshots: " + ", ".join(missing))

    font = load_font(21)
    small = load_font(18)

    # A spans the full width; B and C share the row beneath it.
    top = Image.open(ROOT / PANELS[0][1]).convert("RGB")
    bottom = [Image.open(ROOT / f).convert("RGB") for _, f, _ in PANELS[1:]]

    inner = args.width - 2 * PAD
    top_h = round(top.height * inner / top.width)
    top = top.resize((inner, top_h), Image.LANCZOS)

    # Scale the bottom panels to a common height rather than a common width:
    # they have different aspect ratios, and matching widths leaves a band of
    # empty page under the shorter one.
    row_h = min(round(im.height * (inner / 2) / im.width) for im in bottom)
    scaled = [im.resize((round(im.width * row_h / im.height), row_h), Image.LANCZOS)
              for im in bottom]
    row_w = sum(im.width for im in scaled) + PAD
    if row_w > inner:                       # shrink the row to fit the page width
        f = inner / row_w
        row_h = round(row_h * f)
        scaled = [im.resize((round(im.width * f), row_h), Image.LANCZOS) for im in scaled]
        row_w = sum(im.width for im in scaled) + PAD
    bottom, bottom_h = scaled, row_h
    x_start = PAD + (inner - row_w) // 2

    height = PAD + LABEL_H + top_h + PAD + LABEL_H + bottom_h + PAD
    canvas = Image.new("RGB", (args.width, height), BG)
    draw = ImageDraw.Draw(canvas)

    y = PAD
    draw.text((PAD, y), PANELS[0][0], fill=(0, 0, 0), font=font)
    draw.text((PAD + 26, y + 2), PANELS[0][2], fill=(60, 60, 60), font=small)
    y += LABEL_H
    canvas.paste(top, (PAD, y))
    y += top_h + PAD

    xs, x = [], x_start
    for im in bottom:
        xs.append(x); x += im.width + PAD
    for i, (label, _f, caption) in enumerate(PANELS[1:]):
        x = xs[i]
        draw.text((x, y), label, fill=(0, 0, 0), font=font)
        draw.text((x + 26, y + 2), caption, fill=(60, 60, 60), font=small)
    y += LABEL_H
    for i, im in enumerate(bottom):
        canvas.paste(im, (xs[i], y))

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, dpi=(300, 300))
    print(f"wrote {out} ({canvas.width}x{canvas.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
