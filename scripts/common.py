"""Shared helpers for the Python stages of the pipeline."""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def find_root(start: Path | None = None) -> Path:
    d = (start or Path.cwd()).resolve()
    while True:
        if (d / "scripts").is_dir() and (d / "data").is_dir():
            return d
        if d.parent == d:
            raise SystemExit("Could not locate project root (needs scripts/ and data/).")
        d = d.parent


ROOT = find_root(Path(__file__).parent)
DATA_DIR = ROOT / "data"
BUILD_DIR = ROOT / "build"
LOG_DIR = BUILD_DIR / "logs"
H5AD_DIR = BUILD_DIR / "h5ad"
ZARR_DIR = BUILD_DIR / "zarr"
CHECK_DIR = BUILD_DIR / "checks"
CONFIG_DIR = ROOT / "configs"
MANIFEST = BUILD_DIR / "manifest.json"
FAILURES = BUILD_DIR / "failures.json"
PIPELINE_CONFIG = ROOT / "config" / "pipeline.json"


def log(*parts: object) -> None:
    print(f"[{datetime.now():%H:%M:%S}] " + "".join(str(p) for p in parts), flush=True)


class Tee:
    """Mirror stdout to a per-dataset log file, as the R stages do."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("w")
        self._stdout = sys.stdout
        outer = self

        class _T:
            def write(self, s):
                outer._stdout.write(s)
                outer.fh.write(s)

            def flush(self):
                outer._stdout.flush()
                outer.fh.flush()

        sys.stdout = _T()
        return self

    def __exit__(self, *exc):
        sys.stdout = self._stdout
        self.fh.close()
        return False


def read_json(path: Path, default=None):
    if not Path(path).exists():
        return default
    with open(path) as fh:
        return json.load(fh)


def write_json(obj, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2, default=str)
    tmp.replace(path)
    return path


def record_failure(stage: str, dataset: str, err: BaseException | str, tb: str | None = None) -> None:
    cur = read_json(FAILURES, []) or []
    cur.append({
        "stage": stage,
        "dataset": dataset,
        "error": str(err),
        "traceback": tb if tb is not None else traceback.format_exc(),
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    write_json(cur, FAILURES)


def load_pipeline_config() -> dict:
    cfg = read_json(PIPELINE_CONFIG)
    if cfg is None:
        raise SystemExit(f"Missing {PIPELINE_CONFIG}")
    return cfg


def load_manifest() -> dict:
    m = read_json(MANIFEST)
    if m is None:
        raise SystemExit("Missing build/manifest.json — run stage 1 first.")
    return m


def select_datasets(cfg: dict, args) -> list[str]:
    """Manifest datasets minus config-skipped/duplicate ones, honouring --dataset."""
    keys = list(load_manifest()["datasets"].keys())
    if getattr(args, "dataset", None):
        wanted = [k.strip() for k in args.dataset.split(",")]
        sel = [k for k in keys if k in wanted]
        missing = set(wanted) - set(sel)
        if missing:
            raise SystemExit(f"Unknown dataset key(s): {', '.join(sorted(missing))}")
        return sel
    if getattr(args, "include_duplicates", False):
        return keys
    out = []
    for k in keys:
        d = cfg["datasets"].get(k, {})
        if d.get("skip") or d.get("duplicate_of"):
            log(f"skip {k} (", "duplicate of " + d["duplicate_of"] if d.get("duplicate_of") else "config skip", ")")
            continue
        out.append(k)
    return out


def add_common_args(parser):
    parser.add_argument("--dataset", help="comma-separated dataset keys")
    parser.add_argument("--force", action="store_true", help="redo work whose output exists")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--include-duplicates", dest="include_duplicates", action="store_true")
    return parser


def dir_stats(path: Path) -> tuple[int, int]:
    """(file count, total bytes) for a directory tree."""
    n = total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            n += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return n, total


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
