#!/usr/bin/env python
"""Stage 5 — Vitessce view configs.

One config JSON per dataset in configs/, plus configs/index.json listing every
dataset. All data references are absolute HTTPS URLs derived from a single
BASE_URL (config/pipeline.json -> base_url), so moving hosts is a one-line
change and a re-run of this stage.

Layout: scatterplot (UMAP) + obs sets + feature list + heatmap.

    python scripts/05_configs.py [--dataset KEY] [--base-url URL] [--force]
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

from vitessce import (  # noqa: E402
    AnnDataWrapper, Component as cm, CoordinationType as ct, VitessceConfig,
)

from common import (  # noqa: E402
    CHECK_DIR, CONFIG_DIR, ZARR_DIR, add_common_args, human, load_manifest,
    load_pipeline_config, log, read_json, record_failure, select_datasets, write_json,
)

TRIM_DIR = ZARR_DIR.parent / "trimmed"

STAGE = "05_configs"
SCHEMA_VERSION = "1.0.16"

# obs columns that make sense as cell sets: categorical, and not so fine-grained
# that the set list becomes unusable.
MAX_SET_CARDINALITY = 60


def hex_to_rgb(h: str) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def store_categories(key: str, col: str) -> list[str]:
    """Category values for one obs column, read from the built zarr store."""
    import zarr
    z = zarr.open_group(str(ZARR_DIR / f"{key}.zarr"), mode="r")
    node = z["obs"][col]
    if "categories" not in node:
        return []
    return [str(v) for v in node["categories"][:]]


# Colour-blind-safe base (Okabe-Ito, extended). Beyond this, hues are spaced by
# the golden angle so even a 200-level column stays visually separable.
BASE_PALETTE = [
    "#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9",
    "#F0E442", "#8C564B", "#7B3294", "#4DAF4A", "#984EA3", "#FF7F00",
    "#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02",
    "#A6761D", "#666666",
]


def generated_palette(n: int) -> list[str]:
    if n <= len(BASE_PALETTE):
        return BASE_PALETTE[:n]
    import colorsys
    out = list(BASE_PALETTE)
    for i in range(n - len(BASE_PALETTE)):
        h = ((i + 1) * 0.61803398875) % 1.0
        light = 0.42 + 0.16 * ((i // 3) % 3)
        sat = 0.55 + 0.2 * (i % 2)
        r, g, b = colorsys.hls_to_rgb(h, light, sat)
        out.append("#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255)))
    return out


def set_colours(key: str, obs_sets: list[str]) -> tuple[list[dict], dict[str, list[str]], list[str]]:
    """Vitessce obsSetColor entries for every categorical column.

    Columns whose palette the authors shipped inside the Seurat object (lifted
    out of obs by stage 2) keep those exact colours; the rest get a generated
    palette. Shipping colours for all of them means the page's legend is always
    accurate, instead of depending on what Vitessce assigns at runtime.
    """
    trim = read_json(TRIM_DIR / f"{key}_report.json", {}) or {}
    palettes = trim.get("colour_maps") or {}
    entries, used, published = [], {}, []
    for col in obs_sets:
        cats = store_categories(key, col)
        if not cats:
            continue
        group = col.replace("_", " ")
        pal = palettes.get(col) or {}
        if pal and all(c in pal for c in cats):
            colours = [pal[c] for c in cats]
            published.append(col)
        else:
            colours = generated_palette(len(cats))
        for cat, hexcol in zip(cats, colours):
            entries.append({"path": [group, cat], "color": hex_to_rgb(hexcol)})
        used[col] = cats
    return entries, used, published


def dataset_url(base_url: str, prefix: str, key: str) -> str:
    parts = [base_url.rstrip("/")]
    if prefix:
        parts.append(prefix.strip("/"))
    parts.append(f"{key}.zarr")
    return "/".join(parts)


def pick_obs_sets(key: str, zarr_report: dict, manifest: dict, dcfg: dict) -> list[str]:
    """Categorical obs columns worth exposing as selectable cell sets."""
    inv = manifest["datasets"][key]["inventory"]["meta_columns"]
    trim = read_json(ZARR_DIR.parent / "trimmed" / f"{key}_report.json", {}) or {}
    decisions = trim.get("obs_decisions", {})
    out = []
    for col in zarr_report["obs_columns"]:
        d = decisions.get(col, {})
        if d.get("type") != "categorical":
            continue
        card = inv.get(col, {}).get("cardinality")
        if card is None:
            # derived columns (e.g. Age_original) are not in the stage 1 inventory
            card = int(str(d.get("reason", "")).split()[-1]) if d.get("reason", "").startswith("cardinality") else None
        if card is not None and card > MAX_SET_CARDINALITY and col not in (dcfg.get("obs_keep_extra") or []):
            continue
        out.append(col)
    preferred = dcfg.get("default_obs_set")
    if preferred in out:
        out.remove(preferred)
        out.insert(0, preferred)
    return out


def build_config(key: str, cfg: dict, manifest: dict) -> dict:
    zarr_report = read_json(CHECK_DIR / f"{key}_zarr.json")
    if zarr_report is None:
        raise FileNotFoundError(f"No stage 4 report for {key} — run stage 4 first.")
    dcfg = cfg["datasets"].get(key, {})
    url = dataset_url(cfg["base_url"], cfg.get("s3_prefix", ""), key)

    obs_sets = pick_obs_sets(key, zarr_report, manifest, dcfg)
    embeddings = [k for k in zarr_report["obsm_keys"]]
    # The first embedding is the one the page opens on: X_umap by default, or
    # whatever the dataset names (spatial datasets open in tissue space).
    preferred = dcfg.get("default_embedding", "X_umap")
    embeddings.sort(key=lambda k: (k != preferred, k != "X_umap", k))
    emb_names = [k.replace("X_", "").replace("_", " ").upper() for k in embeddings]

    title = dcfg.get("title", key)
    vc = VitessceConfig(
        schema_version=SCHEMA_VERSION,
        name=title,
        description=dcfg.get("description", ""),
    )
    dataset = vc.add_dataset(name=title, uid=key[:32]).add_object(
        AnnDataWrapper(
            adata_url=url,
            obs_feature_matrix_path="X",
            initial_feature_filter_path="var/highly_variable",
            obs_set_paths=[f"obs/{c}" for c in obs_sets],
            obs_set_names=[c.replace("_", " ") for c in obs_sets],
            obs_embedding_paths=[f"obsm/{e}" for e in embeddings],
            obs_embedding_names=emb_names,
            obs_embedding_dims=[[0, 1] for _ in embeddings],
        )
    )

    layout_kind = cfg.get("view_layout", "dual-umap")

    # A default gene that is not in this dataset's var would open the page on an
    # empty map (mouse symbols are capitalised differently, panels are small).
    gene = dcfg.get("default_gene")
    if gene:
        import zarr
        z = zarr.open_group(str(ZARR_DIR / f"{key}.zarr"), mode="r")
        names = [str(v) for v in z["var/_index"][:]]
        if gene not in names:
            lower = {n.lower(): n for n in names}
            alt = lower.get(gene.lower())
            if alt:
                log(f"  {key}: default_gene {gene} not found, using {alt}")
                gene = alt
            else:
                log(f"  {key}: default_gene {gene} not in var — opening without a gene selected")
                gene = None
    sets = vc.add_view(cm.OBS_SETS, dataset=dataset)
    genes = vc.add_view(cm.FEATURE_LIST, dataset=dataset)

    # Summary views under the maps: cell counts per set, and the selected gene's
    # expression distribution per set. Both are cheap -- the first reuses the
    # loaded cell sets, the second needs only the one gene column.
    sizes = vc.add_view(cm.OBS_SET_SIZES, dataset=dataset)
    dist = vc.add_view(cm.OBS_SET_FEATURE_VALUE_DISTRIBUTION, dataset=dataset)

    if layout_kind == "single-umap":
        umap_gene = vc.add_view(cm.SCATTERPLOT, dataset=dataset, mapping=emb_names[0])
        umap_meta = umap_gene
        vc.layout((umap_gene | (sets / genes)) / sizes / dist)
        vc.link_views([umap_gene, genes], [ct.OBS_COLOR_ENCODING], ["geneSelection"])
        scatter_views = [umap_gene]
    else:
        # Two rasterised UMAPs side by side: the left one coloured by whichever
        # metadata column is selected, the right one by the selected gene. Both
        # share pan/zoom so they stay comparable.
        umap_meta = vc.add_view(cm.SCATTERPLOT, dataset=dataset, mapping=emb_names[0])
        umap_gene = vc.add_view(cm.SCATTERPLOT, dataset=dataset, mapping=emb_names[0])
        vc.layout((umap_meta | umap_gene) / (sets | genes) / sizes / dist)
        vc.link_views([umap_meta, sets, sizes], [ct.OBS_COLOR_ENCODING], ["cellSetSelection"])
        vc.link_views([umap_gene, genes, dist], [ct.OBS_COLOR_ENCODING], ["geneSelection"])
        vc.link_views([umap_meta, umap_gene],
                      [ct.EMBEDDING_ZOOM, ct.EMBEDDING_TARGET_X, ct.EMBEDDING_TARGET_Y],
                      [None, None, None])
        scatter_views = [umap_meta, umap_gene]

    all_views = [umap_meta, umap_gene, sets, genes, sizes, dist]
    if gene:
        # Open on a marker gene so the page shows expression immediately rather
        # than an unpainted grey embedding.
        vc.link_views(all_views, [ct.FEATURE_SELECTION], [[gene]])

    # Published colours + an initial selection, so the maps come up coloured by
    # cell type with a populated legend instead of uniform grey.
    colour_entries, palette_cols, published_cols = set_colours(key, obs_sets)
    default_col = dcfg.get("default_obs_set")
    selection = None
    if default_col and default_col in obs_sets:
        cats = palette_cols.get(default_col) or store_categories(key, default_col)
        if cats:
            selection = [[default_col.replace("_", " "), c] for c in cats]
    if colour_entries or selection:
        types, values = [], []
        if colour_entries:
            types.append(ct.OBS_SET_COLOR)
            values.append(colour_entries)
        if selection:
            types.append(ct.OBS_SET_SELECTION)
            values.append(selection)
        vc.link_views(all_views, types, values)

    # Set labels drawn at set centroids on the metadata map. Meaningless on a
    # spatial map, where one cell type is spread across every tissue tile and all
    # the centroids collapse into the middle -- the legend strip covers it there.
    # Labels help on a UMAP with a handful of clusters; past ~20 they overlap into
    # an unreadable pile, and on a spatial map every type spans every tile so the
    # centroids collapse into the middle. The legend strip covers both cases.
    labels_on = preferred != "X_spatial" and len(selection or []) <= 20
    vc.link_views([umap_meta], [ct.EMBEDDING_OBS_SET_LABELS_VISIBLE, ct.EMBEDDING_OBS_SET_LABEL_SIZE],
                  [labels_on, 12])

    out = vc.to_dict()

    # Vertical budget: maps get half, pickers and summary plots a quarter each.
    # 12 rows: maps, pickers, then the two summary plots side by side.
    ROWS = {"scatterplot": (0, 6, None), "obsSets": (6, 3, None), "featureList": (6, 3, None),
            "obsSetSizes": (9, 3, (0, 6)), "obsSetFeatureValueDistribution": (9, 3, (6, 6))}
    for v in out.get("layout", []):
        spec = ROWS.get(v["component"])
        if not spec:
            continue
        v["y"], v["h"] = spec[0], spec[1]
        if spec[2]:                      # violin spans the full width
            v["x"], v["w"] = spec[2]

    # `legendVisible` and `obsSetExpansion` are understood by the Vitessce JS
    # runtime but are absent from the Python package's CoordinationType enum, so
    # they are injected here. Expanding the default set group makes the Cell Sets
    # panel show a colour swatch per cluster, i.e. a legend for the left map.
    cspace = out.setdefault("coordinationSpace", {})
    cspace.setdefault("legendVisible", {})["A"] = True
    for v in out.get("layout", []):
        if v["component"] in ("scatterplot", "obsSetSizes", "obsSetFeatureValueDistribution"):
            v.setdefault("coordinationScopes", {})["legendVisible"] = "A"

    if selection:
        group = selection[0][0]
        cspace.setdefault("obsSetExpansion", {})["A"] = [[group]]
        for v in out.get("layout", []):
            if v["component"] == "obsSets":
                v.setdefault("coordinationScopes", {})["obsSetExpansion"] = "A"
    # Vitessce writes relative paths when no base_url is given at build time;
    # every fileUid here must be an absolute URL so the site has no implicit host.
    for ds in out.get("datasets", []):
        for f in ds.get("files", []):
            if not str(f.get("url", "")).startswith("http"):
                f["url"] = url
    return {
        "config": out,
        "summary": {
            "key": key,
            "title": title,
            "paper": dcfg.get("paper"),
            "description": dcfg.get("description", ""),
            "url": url,
            "n_cells": zarr_report["n_obs"],
            "n_genes": zarr_report["n_vars"],
            "store_size": zarr_report["size_human"],
            "embeddings": emb_names,
            "obs_sets": obs_sets,
            "colour_columns": sorted(palette_cols),
            "published_palette_columns": sorted(published_cols),
            "default_gene": dcfg.get("default_gene"),
            "view_layout": layout_kind,
            "config_path": f"configs/{key}.json",
        },
    }


def main() -> int:
    ap = add_common_args(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--base-url", help="override config/pipeline.json base_url")
    args = ap.parse_args()

    cfg = load_pipeline_config()
    if args.base_url:
        cfg["base_url"] = args.base_url
    manifest = load_manifest()
    keys = select_datasets(cfg, args)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log(f"base_url: {cfg['base_url']}")

    index = []
    rc = 0
    for key in keys:
        out_path = CONFIG_DIR / f"{key}.json"
        if out_path.exists() and not args.force and not args.dry_run:
            log(f"reusing existing config: {key}")
            existing = read_json(CONFIG_DIR / "index.json", {}) or {}
            prev = next((d for d in existing.get("datasets", []) if d["key"] == key), None)
            if prev:
                index.append(prev)
                continue
        if args.dry_run:
            log(f"dry-run: would write {out_path}")
            continue
        try:
            built = build_config(key, cfg, manifest)
        except Exception as exc:
            log(f"ERROR building config for {key}: {exc}")
            record_failure(STAGE, key, exc)
            rc = 1
            continue
        write_json(built["config"], out_path)
        index.append(built["summary"])
        s = built["summary"]
        log(f"{key}: {s['n_cells']:,} cells, {len(s['obs_sets'])} cell-set columns, "
            f"embeddings {', '.join(s['embeddings'])} -> {out_path.name}")

    if args.dry_run:
        log("dry-run: index.json left untouched")
        return rc

    write_json({
        "title": cfg.get("collection_title", "Datasets"),
        "base_url": cfg["base_url"],
        "license": cfg.get("license"),
        "n_datasets": len(index),
        "datasets": index,
    }, CONFIG_DIR / "index.json")
    log(f"wrote configs/index.json with {len(index)} dataset(s)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
