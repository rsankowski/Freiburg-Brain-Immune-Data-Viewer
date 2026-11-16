#!/usr/bin/env python
"""Package the AnnData-Zarr stores for Zenodo and upload them to a DRAFT record.

Zenodo allows at most 100 files per record, and a store is thousands of small
chunk files, so each store becomes one uncompressed zip (chunks are already
compressed). Zarr reads a store straight from such a zip:

    import zarr; zarr.open_group(zarr.ZipStore("<key>.zarr.zip", mode="r"), mode="r")

Two steps:

    python scripts/zenodo_data.py build                  # -> build/zenodo/
    ZENODO_TOKEN=... python scripts/zenodo_data.py upload --sandbox   # dry run
    ZENODO_TOKEN=... python scripts/zenodo_data.py upload             # real draft

`upload` creates (or, with --deposition ID, resumes) a draft, sets its metadata
and uploads every file in build/zenodo/, skipping files the draft already holds
with the same checksum. It NEVER publishes: review the draft on Zenodo and
press Publish yourself. The token needs the deposit:write and deposit:actions
scopes and is read only from the ZENODO_TOKEN environment variable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import CONFIG_DIR, ROOT, ZARR_DIR, human, log, read_json  # noqa: E402

OUT = ROOT / "build" / "zenodo"
SOFTWARE_DOI = "10.5281/zenodo.24281489"
SITE = "https://rsankowski.github.io/Freiburg-Brain-Immune-Data-Viewer/"
API = {"zenodo": "https://zenodo.org/api", "sandbox": "https://sandbox.zenodo.org/api"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def publications() -> dict[str, dict]:
    """Publication metadata keyed by normalised paper name ("amannetal2024")."""
    pubs = read_json(ROOT / "config" / "publications.json", {}) or {}
    return {_norm(k): v for k, v in pubs.items()}


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def zip_dir(src: Path, dest: Path) -> int:
    """Uncompressed zip with the store root at the archive root (ZipStore layout)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    n = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())
                n += 1
    tmp.replace(dest)
    return n


def verify_zip(path: Path, n_obs: int) -> None:
    import zarr
    store = zarr.ZipStore(str(path), mode="r")
    try:
        g = zarr.open_group(store, mode="r")
        if g["X"].shape[0] != n_obs:
            raise ValueError(f"{path.name}: X has {g['X'].shape[0]} rows, expected {n_obs}")
        g["X"][:, 0]  # one real chunk read
    finally:
        store.close()


def readme(entries: list[dict], pubs: dict[str, dict]) -> str:
    lines = [
        "# Freiburg Brain Immune Data Viewer: AnnData-Zarr stores",
        "",
        f"Converted data behind the viewer at {SITE}, produced by the pipeline",
        f"archived at https://doi.org/{SOFTWARE_DOI}.",
        "",
        "Each `<key>.zarr.zip` is one dataset: an AnnData-Zarr store (expression in",
        "`X`, chunked along genes; metadata in `obs`; embeddings in `obsm`), zipped",
        "without compression. Open it without unpacking:",
        "",
        "```python",
        "import zarr, anndata",
        'store = zarr.ZipStore("<key>.zarr.zip", mode="r")',
        "adata = anndata.read_zarr(store)",
        "```",
        "",
        "`configs.zip` holds the Vitessce view configurations; `MD5SUMS` the checksums.",
        "Annotations are the original authors'. Cite the source publication when",
        "using a dataset. Licence: CC-BY-4.0.",
        "",
        "| File | Dataset | Publication | DOI | Cells | Genes |",
        "|---|---|---|---|---:|---:|",
    ]
    for e in entries:
        pub = pubs.get(_norm(e["paper"] or ""), {})
        doi = pub.get("doi") or ""
        lines.append(f"| `{e['key']}.zarr.zip` | {e['title']} | {e['paper']} | "
                     f"{doi} | {e['n_cells']:,} | {e['n_genes']:,} |")
    return "\n".join(lines) + "\n"


def cmd_build(args) -> int:
    index = read_json(CONFIG_DIR / "index.json")
    if not index:
        raise SystemExit("configs/index.json missing; run stage 5 first.")
    all_entries = sorted(index["datasets"], key=lambda e: (e["paper"] or "", e["key"]))
    entries = all_entries
    if args.dataset:
        wanted = set(args.dataset.split(","))
        entries = [e for e in entries if e["key"] in wanted]
    OUT.mkdir(parents=True, exist_ok=True)
    pubs = publications()

    for e in entries:
        src = ZARR_DIR / f"{e['key']}.zarr"
        dest = OUT / f"{e['key']}.zarr.zip"
        if not src.is_dir():
            raise SystemExit(f"missing store {src}")
        if dest.exists() and not args.force:
            log(f"skip {dest.name} (exists; --force to rebuild)")
            continue
        n = zip_dir(src, dest)
        verify_zip(dest, e["n_cells"])
        log(f"{dest.name}: {n:,} files, {human(dest.stat().st_size)}, verified")

    with zipfile.ZipFile(OUT / "configs.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(CONFIG_DIR.glob("*.json")):
            zf.write(p, f"configs/{p.name}")
    (OUT / "README.md").write_text(readme(all_entries, pubs))

    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "MD5SUMS"
                   and not p.name.endswith(".part"))
    (OUT / "MD5SUMS").write_text("".join(f"{md5(p)}  {p.name}\n" for p in files))
    total = sum(p.stat().st_size for p in OUT.iterdir() if p.is_file())
    n_files = len(list(OUT.iterdir()))
    log(f"{OUT.relative_to(ROOT)}: {n_files} files, {human(total)}")
    if n_files > 100:
        log("WARNING: more than 100 files; Zenodo's default per-record limit is 100.")
    return 0


def metadata(access: str, pubs: dict[str, dict]) -> dict:
    software = json.loads((ROOT / ".zenodo.json").read_text())
    index = read_json(CONFIG_DIR / "index.json")["datasets"]
    n_cells = sum(e["n_cells"] for e in index)
    papers = sorted({e["paper"] for e in index if e.get("paper")})
    related = [
        {"identifier": SOFTWARE_DOI, "relation": "isSupplementTo",
         "resource_type": "software", "scheme": "doi"},
        {"identifier": SITE, "relation": "isDocumentedBy", "scheme": "url"},
    ]
    for p in papers:
        doi = pubs.get(_norm(p), {}).get("doi")
        if doi:
            related.append({"identifier": doi, "relation": "isDerivedFrom",
                            "resource_type": "publication-article", "scheme": "doi"})
    meta = {
        "upload_type": "dataset",
        "title": "Freiburg Brain Immune Data Viewer: AnnData-Zarr stores of "
                 f"{len(index)} published single-cell and spatial datasets",
        "description": (
            f"<p>AnnData-Zarr stores for {len(index)} datasets from {len(papers)} "
            f"publications ({n_cells:,} cells summed over datasets), as served by the "
            f"viewer at <a href=\"{SITE}\">{SITE}</a>. Each file is one dataset, an "
            "uncompressed zip of its store that zarr and anndata read directly; see "
            "README.md. Produced by the conversion pipeline archived at "
            f"<a href=\"https://doi.org/{SOFTWARE_DOI}\">doi:{SOFTWARE_DOI}</a>.</p>"
            "<p>Annotations, embeddings and normalised expression are the original "
            "authors'. Please cite the source publication of each dataset.</p>"),
        "creators": software["creators"],
        "license": "cc-by-4.0",
        "access_right": access,
        "keywords": software["keywords"],
        "related_identifiers": related,
    }
    if access == "restricted":
        meta["access_conditions"] = (
            "Access is granted for research use on request to the corresponding "
            "author. The human datasets contain donor-level metadata.")
    return meta


def cmd_upload(args) -> int:
    import requests

    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        raise SystemExit("Set ZENODO_TOKEN (scopes deposit:write, deposit:actions).")
    if not (OUT / "MD5SUMS").exists():
        raise SystemExit("Run `build` first.")
    api = API["sandbox" if args.sandbox else "zenodo"]
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"

    if args.deposition:
        r = s.get(f"{api}/deposit/depositions/{args.deposition}")
    else:
        r = s.post(f"{api}/deposit/depositions", json={})
    r.raise_for_status()
    dep = r.json()
    if dep.get("submitted"):
        raise SystemExit(f"Deposition {dep['id']} is already published; refusing to modify.")
    log(f"draft {dep['id']}: {dep['links']['html']}")

    r = s.put(f"{api}/deposit/depositions/{dep['id']}",
              json={"metadata": metadata(args.access, publications())})
    if not r.ok:
        raise SystemExit(f"metadata rejected ({r.status_code}): {r.text}")
    log(f"metadata set (access: {args.access})")

    existing = {f["filename"]: f["checksum"] for f in
                s.get(f"{api}/deposit/depositions/{dep['id']}/files").json()}
    bucket = dep["links"]["bucket"]
    sums = dict(reversed(l.split("  ", 1)) for l in (OUT / "MD5SUMS").read_text().splitlines())
    files = sorted(p for p in OUT.iterdir() if p.is_file() and not p.name.endswith(".part"))
    for p in files:
        want = sums.get(p.name) or md5(p)
        if existing.get(p.name, "").removeprefix("md5:") == want:
            log(f"skip {p.name} (already uploaded)")
            continue
        log(f"upload {p.name} ({human(p.stat().st_size)})")
        with open(p, "rb") as fh:
            r = s.put(f"{bucket}/{p.name}", data=fh,
                      headers={"Content-Length": str(p.stat().st_size)}, timeout=None)
        r.raise_for_status()
        got = r.json().get("checksum", "").removeprefix("md5:")
        if got != want:
            raise SystemExit(f"{p.name}: checksum mismatch after upload ({got} != {want})")

    log(f"done. Review and publish the draft yourself: {dep['links']['html']}")
    log(f"resume with: --deposition {dep['id']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="zip, verify and checksum the stores into build/zenodo/")
    b.add_argument("--dataset", help="comma-separated keys (default: all)")
    b.add_argument("--force", action="store_true", help="rebuild existing zips")
    u = sub.add_parser("upload", help="upload build/zenodo/ to a Zenodo draft (never publishes)")
    u.add_argument("--sandbox", action="store_true", help="use sandbox.zenodo.org")
    u.add_argument("--deposition", type=int, help="resume an existing draft")
    u.add_argument("--access", choices=["open", "restricted"], default="restricted",
                   help="default restricted until consent for open archiving is confirmed")
    args = ap.parse_args()
    return cmd_build(args) if args.cmd == "build" else cmd_upload(args)


if __name__ == "__main__":
    sys.exit(main())
