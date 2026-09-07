#!/usr/bin/env python
"""Run any pipeline stage through one entry point.

    python scripts/pipeline.py --stage 1            # inventory
    python scripts/pipeline.py --stage 2 --force    # trim
    python scripts/pipeline.py --stage all --dry-run
    python scripts/pipeline.py --stage 4 --dataset some_key

Stages 1-3 are R, stages 4-7 are Python; this dispatches to the right
interpreter and passes the common flags straight through.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RSCRIPT = "/Library/Frameworks/R.framework/Resources/bin/Rscript"
VENV_PY = ROOT / ".venv" / "bin" / "python"

STAGES = {
    "1": ("R", "01_inventory.R", "inventory Seurat objects"),
    "2": ("R", "02_trim.R", "trim to a minimal object"),
    "3": ("R", "03_to_h5ad.R", "convert to h5ad, verified"),
    "4": ("py", "04_to_zarr.py", "write AnnData-Zarr with Vitessce chunking"),
    "5": ("py", "05_configs.py", "generate Vitessce view configs"),
    "6": ("py", "06_validate.py", "validate stores and configs"),
    "7": ("py", "07_sync.py", "generate the S3 release layout"),
    "8": ("py", "08_site.py", "generate the static viewer site in docs/"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True,
                    help="stage number, comma-separated list, or 'all': " +
                         ", ".join(f"{k}={v[2]}" for k, v in STAGES.items()))
    ap.add_argument("--dataset")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true")
    ap.add_argument("--include-duplicates", dest="include_duplicates", action="store_true")
    args, extra = ap.parse_known_args()

    wanted = list(STAGES) if args.stage == "all" else [s.strip() for s in args.stage.split(",")]
    unknown = [s for s in wanted if s not in STAGES]
    if unknown:
        raise SystemExit(f"Unknown stage(s): {', '.join(unknown)}")

    common = []
    if args.dataset:
        common += ["--dataset", args.dataset]
    if args.force:
        common.append("--force")
    if args.dry_run:
        common.append("--dry-run")
    if args.include_duplicates:
        common.append("--include-duplicates")

    for s in wanted:
        kind, script, desc = STAGES[s]
        cmd = ([RSCRIPT, "--vanilla", str(ROOT / "scripts" / script)] if kind == "R"
               else [str(VENV_PY), str(ROOT / "scripts" / script)])
        cmd += common + extra
        print(f"\n=== stage {s}: {desc} ===\n{' '.join(cmd)}\n", flush=True)
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            print(f"stage {s} exited {rc}; see build/failures.json and build/logs/", file=sys.stderr)
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
