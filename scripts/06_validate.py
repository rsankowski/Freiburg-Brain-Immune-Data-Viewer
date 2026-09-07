#!/usr/bin/env python
"""Stage 6 — validate stores and configs before anything is uploaded.

Per dataset:
  * required zarr metadata (.zgroup/.zattrs/.zarray) exists at the expected paths
  * 20 random single-gene fetches, timed (p50/p95)
  * every path referenced by the config resolves inside the store
  * obs columns are screened for free text, dates and potential identifiers

Hard failures (missing metadata, unresolvable config paths) exit non-zero.
Privacy findings are reported for manual review, never silently dropped.

    python scripts/06_validate.py [--dataset KEY] [--n-genes 20]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np  # noqa: E402
import zarr  # noqa: E402

from common import (  # noqa: E402
    CHECK_DIR, CONFIG_DIR, ZARR_DIR, add_common_args, human, load_pipeline_config,
    log, read_json, select_datasets, write_json,
)

STAGE = "06_validate"

DATE_RE = re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
ID_RE = re.compile(r"^[A-Za-z]{0,4}[-_]?\d{4,}$|^[0-9a-f]{8,}$", re.I)
PII_NAME_RE = re.compile(r"subject|patient|donor|individual|sample_?id|barcode|name|email|dob|birth|date",
                         re.I)


def zarr_paths_exist(root: Path, paths: list[str]) -> list[str]:
    missing = []
    for p in paths:
        target = root / p
        if not target.exists():
            missing.append(p)
            continue
        if not any((target / m).exists() for m in (".zarray", ".zgroup")):
            missing.append(f"{p} (no .zarray/.zgroup)")
    return missing


def config_data_paths(config: dict) -> list[str]:
    """Every store-relative path the config asks Vitessce to fetch."""
    paths = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("Path") and isinstance(v, str):
                    paths.add(v)
                elif k == "path" and isinstance(v, str):
                    paths.add(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(config)
    return sorted(paths)


def time_gene_fetches(store: Path, n: int, seed: int = 0) -> dict:
    z = zarr.open_group(str(store), mode="r")
    X = z["X"]
    n_vars = X.shape[1]
    rng = np.random.default_rng(seed)
    genes = rng.integers(0, n_vars, n)
    times = []
    for g in genes:
        t0 = time.perf_counter()
        col = X[:, int(g)]
        times.append((time.perf_counter() - t0) * 1000)
        del col
    times = np.array(times)
    return {
        "n": int(n),
        "p50_ms": round(float(np.percentile(times, 50)), 1),
        "p95_ms": round(float(np.percentile(times, 95)), 1),
        "max_ms": round(float(times.max()), 1),
        "chunk_shape": list(X.chunks),
        "dtype": str(X.dtype),
    }


def screen_obs(store: Path, n_obs: int) -> dict:
    """Look for free text, dates and identifier-shaped values in obs."""
    z = zarr.open_group(str(store), mode="r")
    obs = z["obs"]
    findings = []
    for col in list(obs.array_keys()) + list(obs.group_keys()):
        if col.startswith("_"):
            continue
        node = obs[col]
        if isinstance(node, zarr.hierarchy.Group) and "categories" in node:
            values = [str(v) for v in node["categories"][:]]
            card = len(values)
            kind = "categorical"
        elif isinstance(node, zarr.core.Array):
            if node.dtype.kind in "fiu":
                continue
            values = [str(v) for v in node[: min(5000, node.shape[0])]]
            card = len(set(values))
            kind = "string"
        else:
            continue

        reasons = []
        if card >= 0.5 * n_obs:
            reasons.append(f"cardinality {card} ~ n_cells {n_obs} (per-cell identifier?)")
        if any(DATE_RE.search(v) for v in values[:500]):
            reasons.append("values look like dates")
        if values and sum(bool(ID_RE.match(v)) for v in values[:500]) > 0.5 * min(500, len(values)):
            reasons.append("values look like opaque IDs")
        if values and np.mean([len(v) for v in values[:500]]) > 40:
            reasons.append("long free-text values")
        if PII_NAME_RE.search(col):
            reasons.append("column name suggests personal/identifying data")
        if reasons:
            findings.append({
                "column": col, "kind": kind, "cardinality": card,
                "examples": values[:5], "reasons": reasons,
            })
    return {"n_columns_flagged": len(findings), "findings": findings}


def validate(key: str, cfg: dict) -> dict:
    store = ZARR_DIR / f"{key}.zarr"
    if not store.exists():
        raise FileNotFoundError(f"No zarr store for {key} — run stage 4 first.")
    config_path = CONFIG_DIR / f"{key}.json"
    config = read_json(config_path)
    if config is None:
        raise FileNotFoundError(f"No config for {key} — run stage 5 first.")

    errors = []

    # 1. required zarr metadata
    for required in (".zgroup", ".zattrs", "X/.zarray", "obs/.zattrs", "var/.zattrs"):
        if not (store / required).exists():
            errors.append(f"missing {required}")

    # 2. every path the config references must resolve
    paths = config_data_paths(config)
    data_paths = [p for p in paths if p.startswith(("obs/", "obsm/", "var/", "X"))]
    missing = zarr_paths_exist(store, data_paths)
    for m in missing:
        errors.append(f"config references missing path: {m}")

    # 3. the config's URLs must all point at this dataset's store
    urls = [f["url"] for d in config.get("datasets", []) for f in d.get("files", [])]
    for u in urls:
        if not u.startswith("http"):
            errors.append(f"non-absolute url in config: {u}")
        elif not u.rstrip("/").endswith(f"{key}.zarr"):
            errors.append(f"url does not point at {key}.zarr: {u}")

    # 4. timing
    z = zarr.open_group(str(store), mode="r")
    n_obs = z["X"].shape[0]
    timing = time_gene_fetches(store, args_n_genes)

    # 5. privacy screen
    privacy = screen_obs(store, n_obs)

    n_files, n_bytes = 0, 0
    for p in store.rglob("*"):
        if p.is_file():
            n_files += 1
            n_bytes += p.stat().st_size

    report = {
        "key": key,
        "store": str(store),
        "n_obs": int(n_obs),
        "n_vars": int(z["X"].shape[1]),
        "file_count": n_files,
        "size_human": human(n_bytes),
        "config_paths_checked": data_paths,
        "single_gene_fetch": timing,
        "privacy_screen": privacy,
        "errors": errors,
        "passed": not errors,
    }
    write_json(report, CHECK_DIR / f"{key}_validate.json")

    log(f"{key}: {'PASS' if not errors else 'FAIL'} — {n_files} files, {human(n_bytes)}")
    log(f"  single-gene fetch: p50 {timing['p50_ms']} ms, p95 {timing['p95_ms']} ms "
        f"(chunk {timing['chunk_shape']}, {timing['dtype']})")
    log(f"  config paths checked: {len(data_paths)}, unresolved: {len(missing)}")
    for e in errors:
        log(f"  ERROR {e}")
    if privacy["findings"]:
        log(f"  privacy screen flagged {len(privacy['findings'])} column(s) for manual review:")
        for f in privacy["findings"]:
            log(f"    - {f['column']} ({f['kind']}, card {f['cardinality']}): {'; '.join(f['reasons'])}")
            log(f"      e.g. {', '.join(map(str, f['examples'][:3]))}")
    else:
        log("  privacy screen: nothing flagged")
    return report


def main() -> int:
    global args_n_genes
    ap = add_common_args(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--n-genes", type=int, default=20, help="single-gene fetches to time")
    args = ap.parse_args()
    args_n_genes = args.n_genes

    cfg = load_pipeline_config()
    keys = select_datasets(cfg, args)
    rc = 0
    for key in keys:
        try:
            r = validate(key, cfg)
            rc = rc or (0 if r["passed"] else 1)
        except Exception as exc:
            log(f"ERROR validating {key}: {exc}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
