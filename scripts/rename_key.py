#!/usr/bin/env python
"""Move a dataset's build artefacts and config entry to a new key.

Dataset keys are derived from file paths, so renaming a file in data/ changes
its key and orphans everything built under the old one. This migrates instead
of rebuilding, which matters when the source object is tens of gigabytes.

Only use it when the file contents are unchanged (a pure rename). Verify with
the byte size shown before confirming.

    python scripts/rename_key.py OLD_KEY NEW_KEY [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import BUILD_DIR, CONFIG_DIR, ROOT, log, read_json, write_json  # noqa: E402

DOCS_CONFIGS = ROOT / "docs" / "configs"


def targets(key: str) -> list[Path]:
    return [
        BUILD_DIR / "inventory" / f"{key}.json",
        BUILD_DIR / "trimmed" / f"{key}.rds",
        BUILD_DIR / "trimmed" / f"{key}_report.json",
        BUILD_DIR / "h5ad" / f"{key}.h5ad",
        BUILD_DIR / "zarr" / f"{key}.zarr",
        BUILD_DIR / "checks" / f"{key}_h5ad.json",
        BUILD_DIR / "checks" / f"{key}_zarr.json",
        BUILD_DIR / "checks" / f"{key}_validate.json",
        CONFIG_DIR / f"{key}.json",
        DOCS_CONFIGS / f"{key}.json",
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old_key")
    ap.add_argument("new_key")
    ap.add_argument("--apply", action="store_true", help="without this, only report")
    args = ap.parse_args()

    moves = [(src, Path(str(dst).replace(args.old_key, args.new_key)))
             for src, dst in ((p, p) for p in targets(args.old_key)) if src.exists()]
    if not moves:
        log(f"nothing found for {args.old_key}")
        return 1

    for src, dst in moves:
        log(f"  {'move' if args.apply else 'would move'} {src.relative_to(ROOT)} -> {dst.name}")
        if args.apply:
            if dst.exists():
                shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
            src.rename(dst)

    # The key is also recorded inside several of the JSON files.
    if args.apply:
        for p in (BUILD_DIR / "inventory" / f"{args.new_key}.json",
                  BUILD_DIR / "trimmed" / f"{args.new_key}_report.json",
                  BUILD_DIR / "checks" / f"{args.new_key}_h5ad.json",
                  BUILD_DIR / "checks" / f"{args.new_key}_zarr.json",
                  BUILD_DIR / "checks" / f"{args.new_key}_validate.json"):
            if not p.exists():
                continue
            txt = p.read_text().replace(args.old_key, args.new_key)
            p.write_text(txt)
            log(f"  rewrote key inside {p.name}")

        cfg_path = ROOT / "config" / "pipeline.json"
        cfg = read_json(cfg_path)
        if cfg and args.old_key in cfg["datasets"]:
            cfg["datasets"][args.new_key] = cfg["datasets"].pop(args.old_key)
            write_json(cfg, cfg_path)
            log("  moved config/pipeline.json entry")
    log("done" if args.apply else "dry run; pass --apply to perform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
