#!/usr/bin/env python
"""Regenerate the Application Note benchmark table from build artefacts.

Writes paper/table1.tsv and prints a summary. Single-gene latency is measured
over HTTP against the local preview server when it is running (that is the path
the browser actually takes); otherwise the local-disk figures recorded by
stage 6 are used and the column is labelled accordingly.

    python scripts/serve_local.py &          # optional, for HTTP timings
    python scripts/make_benchmarks.py
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import CHECK_DIR, CONFIG_DIR, ROOT, log, read_json  # noqa: E402

PREVIEW = "http://localhost:8787"
N_GENES = 20


def http_latency(key: str, n_vars: int, chunk_w: int) -> tuple[float, float, float] | None:
    """p50, p95 (ms) and mean bytes for N_GENES single-gene chunk fetches."""
    rng = random.Random(0)
    times, sizes = [], []
    for _ in range(N_GENES):
        chunk = rng.randrange(n_vars) // chunk_w
        url = f"{PREVIEW}/zarr/{key}.zarr/X/0.{chunk}"
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read()
        except (urllib.error.URLError, OSError):
            return None
        times.append((time.perf_counter() - t0) * 1000)
        sizes.append(len(body))
    return (
        st.quantiles(times, n=100)[49],
        st.quantiles(times, n=100)[94],
        st.mean(sizes),
    )


def main() -> int:
    index = read_json(CONFIG_DIR / "index.json")
    if not index:
        raise SystemExit("configs/index.json missing — run stage 5 first.")

    rows, http_ok = [], False
    for entry in sorted(index["datasets"], key=lambda e: -e["n_cells"]):
        key = entry["key"]
        z = read_json(CHECK_DIR / f"{key}_zarr.json", {}) or {}
        v = read_json(CHECK_DIR / f"{key}_validate.json", {}) or {}
        chunk_w = (z.get("x_chunks") or [0, 10])[1]
        http = http_latency(key, z.get("n_vars", 1), chunk_w)
        if http:
            http_ok = True
        rows.append({
            "dataset": entry["title"],
            "publication": entry.get("paper", ""),
            "cells": z.get("n_obs"),
            "genes": z.get("n_vars"),
            "source_mb": None,
            "store": z.get("size_human"),
            "files": z.get("file_count"),
            "chunk_genes": chunk_w,
            "p50_ms": round(http[0], 1) if http else v.get("single_gene_fetch", {}).get("p50_ms"),
            "p95_ms": round(http[1], 1) if http else v.get("single_gene_fetch", {}).get("p95_ms"),
            "kb_per_gene": round(http[2] / 1024, 1) if http else None,
        })

    manifest = read_json(ROOT / "build" / "manifest.json", {}) or {}
    for r, entry in zip(rows, sorted(index["datasets"], key=lambda e: -e["n_cells"])):
        ds = (manifest.get("datasets") or {}).get(entry["key"], {})
        if ds.get("file_size_bytes"):
            r["source_mb"] = round(ds["file_size_bytes"] / 1024 ** 2)

    out = ROOT / "paper" / "table1.tsv"
    out.parent.mkdir(exist_ok=True)
    cols = list(rows[0])
    with open(out, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")

    total_cells = sum(r["cells"] for r in rows)
    total_files = sum(r["files"] for r in rows)
    p50 = [r["p50_ms"] for r in rows if r["p50_ms"] is not None]
    log(f"wrote {out.relative_to(ROOT)}")
    log(f"{len(rows)} datasets, {total_cells:,} cells, {total_files:,} objects")
    log(f"single-gene latency ({'HTTP' if http_ok else 'local disk'}): "
        f"median p50 {st.median(p50):.1f} ms, max p50 {max(p50):.1f} ms")
    if http_ok:
        kb = [r["kb_per_gene"] for r in rows if r["kb_per_gene"]]
        log(f"transfer per gene: {min(kb):.0f}-{max(kb):.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
