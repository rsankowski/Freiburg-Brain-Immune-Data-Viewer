#!/usr/bin/env python
"""Build config/publications.json from data/freiburg-data-viewer.csv.

Article titles are not in the CSV, so they are resolved through CrossRef by DOI
(publisher pages redirect to auth providers and cannot be scraped). A DOI is
derived from the paper URL where possible; anything else is looked up by
bibliographic search and reported for checking.

Existing titles are reused unless --refresh is passed, so re-running after a CSV
edit costs no network calls for papers already resolved.

    python scripts/make_publications.py [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, ROOT, log, read_json, write_json  # noqa: E402

CSV = DATA_DIR / "freiburg-data-viewer.csv"
OUT = ROOT / "config" / "publications.json"
UA = {"User-Agent": "freiburg-brain-immune-data-viewer/1.0 (https://github.com/rsankowski)"}


def doi_from(url: str) -> str | None:
    url = url.strip()
    m = re.search(r"nature\.com/articles/([^/?#]+)", url)
    if m:
        return "10.1038/" + m.group(1)
    m = re.search(r"elifesciences\.org/articles/(\d+)", url)
    if m:
        return f"10.7554/eLife.{m.group(1)}"
    m = re.search(r"(10\.\d{4,9}/[^\s?&#]+)", url)
    return m.group(1).rstrip(".,;") if m else None


def crossref(doi: str) -> dict:
    u = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
        d = json.load(r)["message"]
    return {"title": (d.get("title") or [""])[0],
            "journal": (d.get("container-title") or [""])[0],
            "year": (d.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "doi": d.get("DOI")}


def search(query: str) -> dict | None:
    u = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query.bibliographic": query, "rows": 1})
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
        items = json.load(r)["message"]["items"]
    if not items:
        return None
    d = items[0]
    return {"title": (d.get("title") or [""])[0],
            "journal": (d.get("container-title") or [""])[0],
            "year": (d.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "doi": d.get("DOI")}


def accession_label(u: str) -> str:
    m = re.search(r"acc=(GSE\d+)", u)
    if m:
        return m.group(1)
    if "ega-archive" in u:
        m = re.search(r"studies/(\w+)", u)
        return f"EGA {m.group(1)}" if m else "EGA"
    if "zenodo" in u:
        m = re.search(r"zenodo\.(\d+)", u)
        return f"Zenodo {m.group(1)}" if m else "Zenodo"
    return (u.rstrip("/").split("/")[-1] or u)[:24]


def links(field: str) -> list[dict]:
    return [{"label": accession_label(u.strip()), "url": u.strip()}
            for u in (field or "").split(";") if u.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-resolve titles already known")
    args = ap.parse_args()

    if not CSV.exists():
        raise SystemExit(f"missing {CSV}")
    previous = read_json(OUT, {}) or {}
    out = {}
    for row in csv.DictReader(open(CSV)):
        paper = (row.get("dataset") or "").strip()
        if not paper:
            continue
        url = (row.get("paper-link") or "").strip()
        rec = {"journal_csv": row.get("journal", "").strip(), "paper_url": url,
               "graphical_abstract": (row.get("graphical-abstract") or "").strip(),
               "raw_data": links(row.get("raw-data-link", "")),
               "processed_data": links(row.get("processed-data-link", ""))}

        old = previous.get(paper, {})
        if old.get("title") and not args.refresh:
            rec.update({k: old.get(k) for k in ("title", "journal", "year", "doi")})
            log(f"  {paper}: reusing title")
        else:
            doi = doi_from(url)
            got = None
            try:
                got = crossref(doi) if doi else search(f"{paper.replace('-', ' ')} {rec['journal_csv']}")
            except Exception as exc:
                log(f"  {paper}: lookup failed ({exc})")
            if got:
                rec.update(got)
                log(f"  {paper}: {got['title'][:70]}")
            else:
                rec.update({"title": None, "journal": rec["journal_csv"], "year": None, "doi": doi})
                log(f"  {paper}: TITLE UNRESOLVED - fill in config/publications.json by hand")
            time.sleep(0.3)
        rec["journal_short"] = rec["journal_csv"]
        out[paper] = rec

    write_json(out, OUT)
    missing = [k for k, v in out.items() if not v.get("title")]
    log(f"wrote {OUT.relative_to(ROOT)}: {len(out)} publications"
        + (f", {len(missing)} without a title: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
