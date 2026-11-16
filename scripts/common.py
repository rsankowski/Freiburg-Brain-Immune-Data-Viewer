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


# Resolve from the working directory first so the R and Python halves agree:
# the R stages derive the project root from getwd(), and the self-test runs both
# inside a sandbox whose scripts/ is a symlink back here.
try:
    ROOT = find_root(Path.cwd())
except SystemExit:
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


# --------------------------------------------------------------------------
# Harmonised metadata labels
#
# Authors name the same concept a dozen ways (cell_type, Celltype, celltype;
# condition, Condition; seurat_clusters, cluster). The viewer shows one label per
# concept. Only the *display name* changes: the obs/<column> path in the zarr
# store is untouched, so stores need no rebuild. A dataset can override any
# label with "obs_labels": {"<column>": "<label>"} in pipeline.json.
# --------------------------------------------------------------------------

import re as _re

# Keys are lower-cased column names with "." and "_" folded to "_".
OBS_LABELS = {
    # cell type
    "cell_type": "Cell type", "celltype": "Cell type", "celltypes": "Cell type",
    "final_celltype": "Cell type (final)",
    "cell_subtype_final": "Cell subtype (final)",
    "celltype_azimuth": "Cell type (Azimuth)",
    "azimuth_identity": "Cell type (Azimuth)",
    "azimuth_identity_doublets": "Cell type (Azimuth, incl. doublets)",
    "celltype_cor": "Cell type (correlation)",
    "celltypes_fetal": "Cell type (fetal reference)",
    "singler_labels": "Cell type (SingleR)",
    "predicted_celltype": "Predicted cell type",
    "predicted_celltype2": "Predicted cell type 2",
    "predicted_celltype3": "Predicted cell type 3",
    "predicted_celltype_l1": "Predicted cell type (level 1)",
    "predicted_celltype_l2": "Predicted cell type (level 2)",
    "predicted_celltype_l3": "Predicted cell type (level 3)",
    "predicted_id": "Predicted cell type (label transfer)",
    "cp_predicted_id": "Predicted cell type (CP reference)",
    "predicted_class": "Predicted class",
    "predicted_subclass": "Predicted subclass",
    "predicted_cluster": "Predicted cluster",
    "predicted_cross_species_cluster": "Predicted cross-species cluster",
    "annotation": "Annotation",
    "class_id": "Class ID",
    "subclass_id": "Subclass ID",
    "subclass_label": "Subclass",
    "subclass_label_final": "Subclass (final)",
    "new_identity": "Identity (revised)",
    "idents_with_mg_clusters": "Identity (with microglia clusters)",
    # cluster
    "cluster": "Cluster", "clusters": "Cluster", "seurat_clusters": "Cluster",
    "seurat_clusters_original": "Cluster (original)",
    "seurat_clusters_dim_30": "Cluster (30 dims)",
    "relabelled_clusters": "Cluster (relabelled)",
    "relabelled_clusters_mouse": "Cluster (relabelled, mouse)",
    "clusters_ic3": "Cluster (IC3)", "cluster_id_ic3": "Cluster (IC3)",
    "merged_clusters_paris": "Cluster (merged, Paris)",
    "max_10x_mg_cluster_mapped": "Cluster (mapped 10x microglia)",
    "sub_cluster": "Subcluster",
    "module_label": "Module", "topmodule": "Module (top)",
    "human_module": "Module (human)", "mouse_module": "Module (mouse)",
    "merged_module": "Module (merged)",
    # condition / disease
    "condition": "Condition",
    "condition_label": "Condition (label)",
    "disease_condition": "Condition (disease)",
    "model_condition": "Condition (model)",
    "diagnosis": "Diagnosis",
    "clinical_brain_diagnosis": "Diagnosis (clinical)",
    "clinical_brain_diagnosis_short": "Diagnosis (clinical, short)",
    "neuropathology_diagnosis": "Diagnosis (neuropathological)",
    "pathology": "Pathology",
    "disease_region": "Region (disease)",
    "genotype": "Genotype", "treatment": "Treatment", "group": "Group",
    "timepoint": "Timepoint", "stage": "Stage", "model": "Model",
    # sample / individual
    "sample": "Sample", "sample_id": "Sample",
    "sample_id_disease": "Sample (disease)",
    "orig_ident": "Sample (orig.ident)",
    "old_ident": "Identity (previous)",
    "pat_id": "Donor", "subject_id": "Donor",
    "majoritysinglet_individual_assignment": "Donor (demultiplexed)",
    "mouse": "Animal", "mouseid": "Animal",
    "id": "ID",
    "batch": "Batch", "experiment": "Experiment", "run": "Run",
    "lane": "Lane", "library": "Library", "repository": "Repository",
    "cmo_label": "CMO label", "demultiplexed": "Demultiplexed",
    # demographics
    "sex": "Sex", "gender": "Sex", "final_sex": "Sex",
    "reported_sex": "Sex (reported)", "gex_sex": "Sex (from expression)",
    "age": "Age", "age_original": "Age (original)",
    "race": "Race", "manner_of_death": "Manner of death", "species": "Species",
    # anatomy
    "region": "Region", "region_ind": "Region (individual)",
    "tissue": "Tissue", "tissue_label": "Tissue (label)",
    "tissue_type": "Tissue type", "tissue_region": "Tissue region",
    "compartment": "Compartment", "compartment_cor": "Compartment (correlation)",
    "compartment_ind": "Compartment (individual)",
    "localization": "Localisation", "hemisphere": "Hemisphere",
    "context": "Context", "context_region": "Context (region)",
    "context_stagewise": "Context (stagewise)",
    "context_stagewise_controls_merged": "Context (stagewise, controls merged)",
    "origin": "Origin", "fov": "FOV",
    # QC / technical
    "phase": "Cell cycle phase",
    "dfclass": "Doublet class", "doublet_class": "Doublet class",
    "majoritysinglet_droplettype": "Droplet type",
    "sort_gate": "Sort gate", "gfp_positive": "GFP positive",
    "cd11c_status": "CD11c status",
    "pathway": "Pathway", "pathway_plot": "Pathway (plot)",
    "pathway_model_plot": "Pathway (model, plot)",
}

# Seurat clustering at a given resolution: RNA_snn_res.0.8, wsnn_res.1, ...
_RES = _re.compile(r"^(?P<assay>.*?)_?(?P<graph>w?snn)_res\.(?P<res>[\d.]+)$", _re.I)
_ASSAY = {"rna": "RNA", "sct": "SCT", "integrated": "integrated",
          "peaks": "peaks", "called_peaks": "called peaks", "": ""}


def _fold(col: str) -> str:
    return _re.sub(r"[._]+", "_", col.strip()).lower()


def _fallback(col: str) -> str:
    words = [w for w in _re.split(r"[._\s]+", col) if w]
    out = []
    for i, w in enumerate(words):
        keep = w.isupper() or any(ch.isdigit() for ch in w) or w[1:] != w[1:].lower()
        w2 = w if keep else w.lower()
        out.append(w2[:1].upper() + w2[1:] if i == 0 else w2)
    return " ".join(out) or col


def obs_label(col: str, overrides: dict | None = None) -> str:
    """Harmonised display label for an obs column."""
    if overrides and col in overrides:
        return overrides[col]
    hit = OBS_LABELS.get(_fold(col))
    if hit:
        return hit
    m = _RES.match(col)
    if m:
        graph = "WNN" if m["graph"].lower() == "wsnn" else None
        assay = graph or _ASSAY.get(m["assay"].lower(), m["assay"])
        return f"Cluster ({assay + ', ' if assay else ''}res. {m['res']})"
    return _fallback(col)


def obs_labels(cols: list[str], overrides: dict | None = None) -> dict[str, str]:
    """{column: label}, unique within one dataset. When two columns collapse to
    the same label (e.g. cluster + seurat_clusters), each gets its raw column
    name appended so neither is hidden."""
    labels = {c: obs_label(c, overrides) for c in cols}
    seen: dict[str, list[str]] = {}
    for c, l in labels.items():
        seen.setdefault(l, []).append(c)
    for l, cs in seen.items():
        if len(cs) > 1:
            for c in cs:
                if not (overrides and c in overrides):
                    labels[c] = f"{l} [{c}]"
    return labels
