#!/usr/bin/env python
"""Stage 4 — h5ad -> AnnData-Zarr store laid out for Vitessce.

`X` is written as a dense array chunked (n_obs, VAR_CHUNK_SIZE) so fetching one
gene is a single chunk read rather than a scan of the whole matrix.

`vitessce.data_utils.optimize_adata` is used for obs/var/obsm, but NOT for X:
its `optimize_X=True` path densifies the entire matrix in memory first, which
for 135k x 59k float32 is 32 GB. We stream X in column blocks instead, so peak
memory stays at one block.

    python scripts/04_to_zarr.py [--dataset KEY] [--force] [--x-encoding float32|uint8]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np  # noqa: E402
import zarr  # noqa: E402
from numcodecs import Blosc  # noqa: E402
import anndata as ad  # noqa: E402
from scipy.sparse import issparse  # noqa: E402
from vitessce.data_utils import optimize_adata, VAR_CHUNK_SIZE  # noqa: E402

from common import (  # noqa: E402
    CHECK_DIR, H5AD_DIR, LOG_DIR, ZARR_DIR, Tee, add_common_args, dir_stats, human,
    load_pipeline_config, log, record_failure, select_datasets, write_json,
)

STAGE = "04_to_zarr"
FILE_COUNT_WARN = 50_000


def categoricalise(adata) -> list[str]:
    """String obs columns become pandas categoricals; float64 becomes float32."""
    made = []
    for col in adata.obs.columns:
        s = adata.obs[col]
        if s.dtype == object or str(s.dtype) == "string":
            adata.obs[col] = s.astype("category")
            made.append(col)
        elif str(s.dtype) == "float64":
            adata.obs[col] = s.astype("float32")
        elif str(s.dtype) == "int64":
            adata.obs[col] = s.astype("int32")
    return made


# A chunk should be worth a round trip. VAR_CHUNK_SIZE (10 genes) is right for
# the big datasets, but for a few hundred cells it produces chunks of a few
# hundred bytes and thousands of near-empty files, where request latency
# dominates the transfer entirely.
MIN_CHUNK_BYTES = 64 * 1024


def var_chunk_for(n_obs: int, itemsize: int = 4) -> int:
    wanted = -(-MIN_CHUNK_BYTES // max(1, n_obs * itemsize))          # ceil
    rounded = -(-wanted // VAR_CHUNK_SIZE) * VAR_CHUNK_SIZE           # keep a multiple
    return int(min(max(VAR_CHUNK_SIZE, rounded), 200))


def write_x_blocked(group, X, encoding: str, block: int, chunk_var: int) -> dict:
    """Write X as a dense chunked zarr array, one column block at a time."""
    n_obs, n_vars = X.shape
    dtype = np.uint8 if encoding == "uint8" else np.float32
    arr = group.zeros(
        "X",
        shape=(n_obs, n_vars),
        chunks=(n_obs, chunk_var),
        dtype=dtype,
        compressor=Blosc(cname="zstd", clevel=3, shuffle=Blosc.SHUFFLE),
        overwrite=True,
    )
    arr.attrs["encoding-type"] = "array"
    arr.attrs["encoding-version"] = "0.2.0"

    Xc = X.tocsc() if issparse(X) else X
    gene_max = np.zeros(n_vars, dtype=np.float32)
    t0 = time.time()
    for start in range(0, n_vars, block):
        end = min(start + block, n_vars)
        chunk = Xc[:, start:end]
        dense = np.asarray(chunk.todense() if issparse(chunk) else chunk, dtype=np.float32)
        gene_max[start:end] = dense.max(axis=0)
        if encoding == "uint8":
            # Per-gene 0-255 scaling; the scale factors go to uns so the values
            # remain interpretable.
            mx = np.where(gene_max[start:end] > 0, gene_max[start:end], 1.0)
            dense = np.clip(np.round(dense / mx * 255.0), 0, 255).astype(np.uint8)
        arr[:, start:end] = dense
        if (start // block) % 5 == 0:
            done = end / n_vars
            log(f"  X {end}/{n_vars} genes ({done:.0%}), {time.time() - t0:.0f}s elapsed")
        del dense, chunk
    log(f"  X written in {time.time() - t0:.0f}s")
    return {"gene_max": gene_max, "dtype": str(dtype.__name__)}


def verify_store(store_path: Path, h5ad_path: Path, encoding: str, gene_max, n_check: int = 20) -> list[str]:
    """Spot-check the zarr store against the h5ad it came from."""
    problems = []
    z = ad.read_zarr(store_path)
    src = ad.read_h5ad(h5ad_path)
    if z.n_obs != src.n_obs or z.n_vars != src.n_vars:
        problems.append(f"shape {z.shape} != {src.shape}")
    if list(z.obs_names[:5]) != list(src.obs_names[:5]):
        problems.append("obs_names differ")
    if list(z.var_names[:5]) != list(src.var_names[:5]):
        problems.append("var_names differ")

    rng = np.random.default_rng(0)
    cells = rng.integers(0, src.n_obs, n_check)
    genes = rng.integers(0, src.n_vars, n_check)
    srcX = src.X.tocsr()
    for c, g in zip(cells, genes):
        want = float(srcX[int(c), int(g)])
        got = float(np.asarray(z.X[int(c), int(g)]))
        if encoding == "uint8":
            mx = float(gene_max[int(g)]) or 1.0
            want = round(want / mx * 255.0)
            if abs(want - got) > 1:
                problems.append(f"X[{c},{g}] uint8 {got} != {want}")
        elif abs(want - got) > 1e-4 * max(1.0, abs(want)):
            problems.append(f"X[{c},{g}] {got} != {want}")
    del src, z
    return problems


def convert(key: str, cfg: dict, args) -> dict:
    h5ad_path = H5AD_DIR / f"{key}.h5ad"
    if not h5ad_path.exists():
        raise FileNotFoundError(f"No h5ad for {key} — run stage 3 first.")
    out = ZARR_DIR / f"{key}.zarr"
    tmp = ZARR_DIR / f"{key}.zarr.partial"
    if tmp.exists():
        shutil.rmtree(tmp)

    log(f"reading {h5ad_path.name} ({human(h5ad_path.stat().st_size)})")
    adata = ad.read_h5ad(h5ad_path)
    log(f"  {adata.n_obs} obs x {adata.n_vars} vars, X {type(adata.X).__name__} {adata.X.dtype}")

    made = categoricalise(adata)
    log(f"  categoricals: {len(made)} obs columns")

    obsm_keys = list(adata.obsm.keys())
    var_cols = [c for c in ["highly_variable"] if c in adata.var.columns]
    if not var_cols:
        raise ValueError("var/highly_variable missing — stage 3 should have written it")

    X = adata.X
    meta = optimize_adata(
        adata,
        obs_cols=list(adata.obs.columns),
        obsm_keys=obsm_keys,
        var_cols=var_cols,
        remove_X=True,          # X is streamed separately, see write_x_blocked
    )
    meta.uns["dataset_key"] = key
    meta.uns["title"] = cfg["datasets"].get(key, {}).get("title", key)
    colours = cfg["datasets"].get(key, {}).get("colours") or {}
    if colours:
        meta.uns["set_colours"] = colours

    tmp.parent.mkdir(parents=True, exist_ok=True)
    meta.write_zarr(tmp)
    log(f"  wrote obs/var/obsm ({len(meta.obs.columns)} obs cols, obsm {obsm_keys})")

    group = zarr.open_group(str(tmp), mode="r+")
    chunk_var = var_chunk_for(adata.n_obs, 1 if args.x_encoding == "uint8" else 4)
    if chunk_var != VAR_CHUNK_SIZE:
        log(f"  small dataset: X chunked {chunk_var} genes wide instead of {VAR_CHUNK_SIZE} "
            f"so chunks stay above {MIN_CHUNK_BYTES // 1024} KB")
    info = write_x_blocked(group, X, args.x_encoding, args.block_size, chunk_var)
    if args.x_encoding == "uint8":
        group.create_dataset("uns/X_gene_max", data=info["gene_max"], overwrite=True)

    problems = verify_store(tmp, h5ad_path, args.x_encoding, info["gene_max"])
    if problems:
        shutil.rmtree(tmp)
        raise ValueError("zarr verification failed: " + "; ".join(problems[:5]))

    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)

    n_files, n_bytes = dir_stats(out)
    n_chunks = -(-adata.n_vars // chunk_var)
    report = {
        "key": key,
        "store": str(out.relative_to(ZARR_DIR.parent.parent)),
        "n_obs": int(adata.n_obs),
        "n_vars": int(adata.n_vars),
        "x_encoding": args.x_encoding,
        "x_chunks": [int(adata.n_obs), int(chunk_var)],
        "x_chunk_count": int(n_chunks),
        "file_count": n_files,
        "size_bytes": n_bytes,
        "size_human": human(n_bytes),
        "h5ad_size_human": human(h5ad_path.stat().st_size),
        "obs_columns": list(meta.obs.columns),
        "obsm_keys": obsm_keys,
        "hvg_n": int(adata.var["highly_variable"].sum()),
        "file_count_warning": n_files > FILE_COUNT_WARN,
    }
    write_json(report, CHECK_DIR / f"{key}_zarr.json")
    log(f"  store: {human(n_bytes)} in {n_files} files ({n_chunks} X chunks)")
    if report["file_count_warning"]:
        log(f"  WARNING: {n_files} files exceeds {FILE_COUNT_WARN} — chunking is too fine "
            f"for practical sync and serving")
    return report


def main() -> int:
    ap = add_common_args(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--x-encoding", choices=["float32", "uint8"], default="float32",
                    help="float32 keeps exact values; uint8 is 4x smaller with per-gene scaling")
    ap.add_argument("--block-size", type=int, default=2000,
                    help="genes per write block (memory: n_obs * block * 4 bytes)")
    args = ap.parse_args()
    if args.block_size % VAR_CHUNK_SIZE:
        args.block_size = -(-args.block_size // VAR_CHUNK_SIZE) * VAR_CHUNK_SIZE

    cfg = load_pipeline_config()
    keys = select_datasets(cfg, args)
    log("datasets: " + ", ".join(keys))
    ZARR_DIR.mkdir(parents=True, exist_ok=True)

    rc = 0
    for key in keys:
        out = ZARR_DIR / f"{key}.zarr"
        if out.exists() and not args.force:
            log(f"skip (done): {key}")
            continue
        if args.dry_run:
            log(f"dry-run: would convert {key} -> {out}")
            continue
        with Tee(LOG_DIR / f"{STAGE}_{key}.log"):
            log(f"{STAGE}: {key}")
            try:
                convert(key, cfg, args)
            except Exception as exc:      # one dataset failing must not stop the rest
                log(f"ERROR: {exc}")
                record_failure(STAGE, key, exc)
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
