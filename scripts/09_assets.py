#!/usr/bin/env python
"""Stage 9 — prepare publication assets for the site.

Reads config/publications.json, rasterises PDF graphical abstracts, resizes
everything to a web-sensible width and writes docs/assets/<paper-slug>.jpg plus
docs/assets/publications.json (the metadata the site actually consumes).

    python scripts/09_assets.py [--width 1200]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, log, read_json, write_json  # noqa: E402

from PIL import Image  # noqa: E402

# These are the lab's own figures, read from disk, so the decompression-bomb
# guard is not protecting us from anything here -- and one of them is a
# 93-megapixel PNG that trips the default limit.
Image.MAX_IMAGE_PIXELS = None

DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
PUBS = ROOT / "config" / "publications.json"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def rasterise_pdf(src: Path, width: int) -> Image.Image:
    """First page of a PDF as an image, via poppler."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "1",
             "-scale-to-x", str(width), "-scale-to-y", "-1", str(src), str(out)],
            check=True, capture_output=True)
        pages = sorted(Path(tmp).glob("page*.png"))
        if not pages:
            raise RuntimeError(f"pdftoppm produced no page for {src.name}")
        return Image.open(pages[0]).convert("RGB")


SUPPORTED = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf")


def resolve_abstract(rel: str) -> Path | None:
    """The CSV records one filename, but the file's extension changes when a
    figure is re-exported (a PDF replaced by a PNG). Fall back to any sibling
    with the same stem."""
    src = ROOT / rel
    if src.exists():
        return src
    for ext in SUPPORTED:
        alt = src.with_suffix(ext)
        if alt.exists():
            return alt
    return None


def prepare(paper: str, rel: str, width: int) -> tuple[str, list[int]] | None:
    src = resolve_abstract(rel)
    if src is None:
        log(f"  {paper}: graphical abstract missing: {rel}")
        return None
    if src != ROOT / rel:
        log(f"  {paper}: CSV says {Path(rel).name}, using {src.name}")
    if src.suffix.lower() == ".pdf":
        im = rasterise_pdf(src, width)
        log(f"  {paper}: rasterised {src.name} ({im.width}x{im.height})")
    else:
        im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    # A flat white margin is common in these figures; trim it so cards crop evenly.
    out = ASSETS / f"{slug(paper)}.jpg"
    im.save(out, "JPEG", quality=86, optimize=True)
    return out.name, [im.width, im.height]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--width", type=int, default=1200)
    args = ap.parse_args()

    pubs = read_json(PUBS)
    if not pubs:
        raise SystemExit("config/publications.json missing")
    ASSETS.mkdir(parents=True, exist_ok=True)

    site = {}
    for paper, rec in pubs.items():
        entry = {k: rec[k] for k in
                 ("title", "journal_short", "year", "doi", "paper_url",
                  "raw_data", "processed_data")}
        # The folder name carries the year the lab cites the paper by. CrossRef
        # reports the online-first year, which differs for issue-delayed papers
        # (Sankowski et al. is online 2023, in the 2024 issue), so the folder
        # wins and CrossRef is the fallback.
        m = re.search(r"(19|20)\d{2}", paper)
        if m:
            folder_year = int(m.group(0))
            if entry.get("year") and int(entry["year"]) != folder_year:
                log(f"  {paper}: year {entry['year']} (CrossRef) -> {folder_year} (folder name)")
            entry["year"] = folder_year
        ga = rec.get("graphical_abstract")
        if ga:
            got = prepare(paper, ga, args.width)
            if got:
                entry["image"], entry["image_size"] = got
        site[paper] = entry

    write_json(site, ASSETS / "publications.json")
    n_img = sum(1 for v in site.values() if v.get("image"))
    log(f"wrote docs/assets/publications.json ({len(site)} publications, {n_img} with images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
