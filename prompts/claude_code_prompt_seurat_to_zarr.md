# Claude Code prompt: Seurat → AnnData-Zarr → Vitessce (AWS Open Data)

> Paste everything below the line into Claude Code from the repo root.
> Fill in the `ENVIRONMENT` block first — that's the only part you must edit.

---

## Goal

Build a reproducible, resumable pipeline that converts a collection of Seurat
objects into Vitessce-ready AnnData-Zarr stores, generates view configs, and
prepares an S3 bucket layout suitable for submission to the **AWS Open Data
Sponsorship Program**.

The end state: a static Vitessce site where each dataset can be browsed by
UMAP, cell-type sets, and per-gene expression, with no backend server.

## ENVIRONMENT (edit me)

- R version and library path: `/Library/Frameworks/R.framework/Resources/bin/R`
- Seurat version used to create the objects: `v5`
- Python env / conda env name: `<fill in>`
- Machine: `Macbook pro Max`
- Target S3 bucket name: `s3://freburg-immune-data-viewer-544227292049-us-east-1-an`
- Public site origin (for CORS): `https://github.com/rsankowski/Freiburg-Brain-Immune-Data-Viewer.git`

## Input layout

Seurat objects live under `data/`, nested by paper then by dataset:

```
data/<paper_id>/<dataset_id>/<something>.rds
```

Do **not** hardcode the depth. Walk `data/` recursively for `*.rds` and
`*.qs`/`*.qs2` files, and derive a stable dataset key from the path relative to
`data/`, joining components with `__` and slugifying
(lowercase, non-alphanumerics → `_`). Example:

```
data/Neftel2019/GBM_malignant/obj.rds  →  neftel2019__gbm_malignant
```

If a folder contains more than one `.rds`, treat each as a separate dataset and
append the filename stem to the key. Write the discovered mapping to
`build/manifest.json` **before doing any conversion**, and stop there on the
first run so I can eyeball it.

## Pipeline stages

Implement as separate, independently runnable scripts driven by a small CLI
(`--stage`, `--dataset`, `--force`, `--dry-run`). Every stage must be resumable:
skip work whose output already exists unless `--force`.

### Stage 1 — inventory (`scripts/01_inventory.R`)

For each object, without keeping it in memory afterwards, record to
`build/manifest.json`:

- n cells, n features, assay names, default assay
- available layers/slots (counts, data, scale.data)
- reductions present and their dimensions
- `colnames(obj@meta.data)` with inferred type (categorical / numeric) and
  cardinality for categoricals
- estimated in-memory size

Load one object at a time, `rm()` and `gc()` between iterations. Log peak RSS
per object so I can see which ones will be a problem.

### Stage 2 — trim (`scripts/02_trim.R`)

Produce a minimal object per dataset:

- keep the normalized `data` layer of the RNA assay only
- drop `scale.data`, drop integration/SCT assays, drop raw `counts` unless the
  manifest says `data` is missing
- keep all reductions that look like embeddings (`umap`, `tsne`, `pca`)
- keep only metadata columns that are plottable: categoricals with cardinality
  between 2 and 100, plus numeric QC columns
- compute and store a highly-variable-gene boolean in `var` (target ~4000 genes)
  if one is not already present — Vitessce needs this for the heatmap

Report the before/after size for each dataset.

### Stage 3 — convert to h5ad (`scripts/03_to_h5ad.R`)

Use `anndataR` if available, falling back to `sceasy`. Verify the round trip:
after writing, re-read the h5ad and assert that `n_obs`, `n_vars`, embedding
dimensions, and a random sample of 100 expression values match the source.
Fail loudly on mismatch rather than continuing.

Watch for the known failure modes and handle them explicitly: Seurat v5 layered
assays needing `JoinLayers` first, factor columns becoming integer codes, and
`obsm` key naming (`X_umap`, not `umap`).

### Stage 4 — h5ad → Zarr (`scripts/04_to_zarr.py`)

This is the step that determines whether the site feels fast. Use
`vitessce.data_utils.optimize_adata` with `VAR_CHUNK_SIZE`, so a single-gene
fetch is a small number of chunk reads rather than hundreds.

- keep `X` as the normalized matrix
- write `obsm` embeddings as float32
- write categorical `obs` columns as proper categoricals
- write the HVG boolean to `var/highly_variable`
- report resulting chunk count and total store size per dataset

Flag any dataset whose store exceeds ~50k files — that's a sign the chunking is
too fine and it will be slow to sync and slow to serve.

### Stage 5 — configs (`scripts/05_configs.py`)

Emit one Vitessce view config JSON per dataset into `configs/`, plus an
`index.json` listing all datasets with their titles, cell counts, and source
paper. Configs must reference data by **absolute HTTPS URL** built from a single
`BASE_URL` constant, so switching hosts is a one-line change.

Layout per dataset: scatterplot (UMAP) + obs sets + feature list + heatmap.

### Stage 6 — validate (`scripts/06_validate.py`)

Before anything is uploaded, for each store:

- assert `.zattrs`, `.zgroup`, `.zarray` metadata files exist at expected paths
- open the store and time fetching 20 random single genes; report p50/p95
- assert every path referenced in the config actually resolves
- assert no `obs` column contains free-text or potential identifiers
  (print anything that looks like a date, an ID, or has cardinality ≈ n_cells
  for me to review manually)

### Stage 7 — S3 layout (`scripts/07_sync.sh`)

Generate but **do not execute** the sync. Produce:

- `aws s3 sync` commands, one per dataset, with `--size-only`
- a bucket policy granting public `s3:GetObject`
- a CORS configuration allowing GET/HEAD from the site origin, exposing
  `Content-Length` and `Content-Range`
- a `README.md` and `LICENSE` at the bucket root — the AWS Open Data program
  expects a described, openly licensed, cloud-optimized dataset

## Hard constraints

- Never hold more than one Seurat object in memory at a time.
- Every stage writes a log to `build/logs/<stage>_<dataset>.log`.
- No stage may silently skip a dataset; failures go to
  `build/failures.json` with the error and traceback, and the run continues.
- Pin versions in `renv.lock` and `requirements.txt`.
- No data files committed to git — add `data/`, `build/`, and `*.zarr` to
  `.gitignore`.

## Non-goals

- Do not build the Vitessce frontend yet; configs only.
- Do not re-run clustering, integration, or dimensionality reduction. Use what
  is in the objects as-is.
- Do not upload anything. I will run the sync myself after reviewing.

## Start here

Run stage 1 only, show me `build/manifest.json`, and wait for my confirmation
before writing any conversion code. If the discovered dataset keys look wrong,
I will correct the derivation rule and we re-run.
