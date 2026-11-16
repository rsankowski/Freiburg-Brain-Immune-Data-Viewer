# Freiburg Brain Immune Data Viewer — conversion pipeline

Converts published Seurat objects into **AnnData-Zarr** stores and Vitessce view
configs, ready to serve statically from S3 with no backend.

Nothing is uploaded by this repo. Stage 7 *generates* the sync commands; you run them.

## Layout

```
data/<paper_id>/<file>       inputs (git-ignored, never committed)
scripts/                     pipeline stages
config/pipeline.json         the only file you normally edit
build/                       manifest, logs, intermediates, stores (git-ignored)
configs/                     Vitessce view configs + index.json (committed)
release/                     generated S3 sync scripts, policy, CORS, README, LICENSE
```

## Setup

R packages (Seurat 5, reticulate, jsonlite) are read from the system library;
versions are recorded in `renv.lock`. The Python side lives in a local venv:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`vitessce` is pinned to **3.4.0**: 3.8.x hard-imports `spatialdata` and `negspy`
in `data_utils/__init__`, which drags in a zarr 3 stack.

## Self-test

No real data needed — builds a synthetic dataset, runs all eight stages in a
sandbox under `build/selftest/`, and asserts on the outputs:

```bash
bash scripts/selftest.sh
```

Set `RSCRIPT_BIN` / `PYTHON_BIN` if your interpreters live elsewhere;
`PIPELINE_VENV_PYTHON` points the R stages at the Python used for conversion.

## Running

```bash
python3 scripts/pipeline.py --stage all          # or --stage 1,2,3
python3 scripts/pipeline.py --stage 4 --force --dataset <key>
```

Every stage takes `--dataset`, `--force`, `--dry-run`, `--include-duplicates`,
is resumable (existing output is skipped unless `--force`), writes
`build/logs/<stage>_<dataset>.log`, and records failures to
`build/failures.json` without stopping the remaining datasets.

| Stage | Script | What it does |
|---|---|---|
| 1 | `01_inventory.R` | walks `data/` for `*.rds`/`*.qs`/`*.qs2`/`*.h5seurat`/`*.RData(.gz)`/`*.Robj` (case-insensitive), derives dataset keys, records cells/features/assays/layers/reductions/metadata types and md5 fingerprints |
| 2 | `02_trim.R` | RNA `data` layer only, embeddings only, plottable metadata only, 4000-gene HVG flag |
| 3 | `03_to_h5ad.R` | anndataR → sceasy → direct reticulate writer, each **verified** before acceptance |
| 4 | `04_to_zarr.py` | AnnData-Zarr, `X` dense and chunked `(n_cells, VAR_CHUNK_SIZE)`, widened for small datasets so no chunk falls below 64 KB |
| 5 | `05_configs.py` | one Vitessce config per dataset + `configs/index.json`, absolute URLs from `base_url` |
| 8 | `08_site.py` | static viewer site into `docs/` for GitHub Pages |
| 6 | `06_validate.py` | zarr metadata, timed single-gene fetches, config path resolution, privacy screen |
| 7 | `07_sync.py` | writes `release/` — sync commands, bucket policy, CORS, README, LICENSE |

Stages 1–3 run each dataset in a child R process, so only one Seurat object is
ever resident and the parent can measure the child's true peak RSS.

## Notes on two implementation choices

**Stage 3 verifies, then accepts.** Each writer's output is re-read and checked
(dims, `obs_names`/`var_names`, embedding shapes, `var/highly_variable`, and 100
random expression values, half forced onto non-zero entries). sceasy fails this
check on these objects — it emits `obsm/X_ref.umap` instead of `X_ref_umap` and
drops `highly_variable` — so the direct writer is used instead.

**Stage 4 does not use `optimize_X=True`.** That path calls `todense()` on the
whole matrix first: 135k × 59k float32 is 32 GB of RAM. `optimize_adata` still
handles obs/var/obsm; `X` is streamed to the chunked zarr array in column
blocks, so peak memory is one block.

## Per-dataset settings

`config/pipeline.json` carries one entry per dataset. Beyond title/description
and the metadata overrides, the keys that matter for heterogeneous inputs:

| key | why it exists |
|---|---|
| `assay` | CosMx keeps its panel in a `Nanostring` assay, not `RNA`. Stage 2 renames whatever it keeps to `RNA` so later stages are uniform. |
| `default_obs_set` | which column the maps open coloured by |
| `obs_labels` | `{column: label}` overriding the harmonised display name of a metadata column |
| `default_gene` | opening marker; stage 5 checks it exists in `var` and falls back rather than opening on an empty map (mouse symbols are capitalised differently) |
| `default_embedding` | `X_spatial` makes a dataset open in tissue space instead of UMAP |
| `spatial_group` | metadata column whose values define spatial tiles (see below) |
| `embedding_pattern` | per-dataset override; the default also keeps any 2-D reduction, which is how the cross-species object's `integrated.rpca` survives despite having no UMAP |
| `skip` | build the dataset but keep it off the site |

Datasets found in `data/` with no config entry are built with defaults; add an
entry to give them a title, an opening colour column and an opening gene.

## Spatial data

Stage 2 lifts per-cell coordinates out of `@images` into an `X_spatial`
embedding, so spatial datasets use the same two-map UI with the embedding
selector switching between tissue and UMAP. Y is flipped, since image
coordinates start at the top left.

Images are consumed in order and each contributes only the cells not already
covered — VisiumHD ships both whole-slide and per-sample FOVs of the same spots,
and counting those twice would duplicate cells. Coverage must reach 100% or the
embedding is skipped rather than written with holes.

Tiles are then laid out:

- **default** — one tile per source image, gridded only if their extents
  overlap. VisiumHD's five TMAs all start near the origin, so they get gridded;
  without it they would stack on top of each other.
- **`spatial_group`** — tiles are groups of images instead. CosMx's 73 FOVs are
  already positioned in global slide coordinates, so true geometry is preserved
  *within* a sample while the empty slide between samples is removed. Grouping
  by `Sample` turns a mostly-blank slide into 18 readable tissue tiles.

Cluster labels are drawn on the map for UMAP-style embeddings but suppressed on
spatial ones, where every cell type spans every tile and the centroids collapse
into the middle. The legend strip covers it there.

## Config

`config/pipeline.json` drives everything: `base_url`, bucket, site origins for
CORS, HVG target, categorical cardinality cutoff, embedding pattern, the
`exclude` list of keys to drop from discovery, and per-dataset
title/description/skip flags plus metadata overrides
(`obs_keep_extra`, `obs_drop`, `obs_numeric_coerce`, `default_obs_set`).
Changing hosts is a `base_url` edit and `--stage 5 --force`.

## Input formats

`.rds`, `.qs`, `.qs2`, `.H5Seurat` (via SeuratDisk) and `.RData`/`.rda`/`.Robj`,
gzipped or not. An `.RData` holding several objects contributes the Seurat one
(the largest, if there are several). A [RaceID](https://cran.r-project.org/web/packages/RaceID/vignettes/RaceID.html)
`SCseq` object is converted to Seurat on load, so the rest of the pipeline never
sees the difference.

Two traps worth knowing about, both hit in practice:

- Some `.RData.gz` files are **gzipped twice** — an already-compressed `.RData`
  that was gzipped again. `load()` peels one layer and then finds gzip bytes
  where it expects the serialisation magic, so the loader retries through
  `gzcon()`.
- Extensions are matched case-insensitively; the first datasets here were all
  `.RDS`, and a case-sensitive pattern silently finds nothing.

A file under `data/` that is not a dataset at all — a saved raw count matrix
sitting next to the RaceID object built from it — would fail stage 1 on every
run. List its key under `exclude` in `config/pipeline.json` and it is dropped
from discovery. This is distinct from a dataset's `skip`, which still builds the
dataset and only keeps it off the site.

## RaceID objects

`SCseq` keeps counts in `expdata` and normalised values in `ndata`, and the two
RaceID generations in `data/` disagree about what `ndata` means:

| | `ndata` columns sum to | `counts` slot |
|---|---|---|
| 2017–19 objects (Jordão, Masuda 2019, Sankowski 2019) | the smallest cell's total | absent |
| later objects (Masuda 2020, Wieghofer 2021) | 1 (fractions) | per-cell factor |

So the rescale factor is `min(counts)` when that slot exists and 1 otherwise —
in both cases the `data` layer ends up as `log1p` of counts, not of fractions,
which is what makes the colour scale readable. The older objects also carry
RaceID's 0.1 pseudocount on every entry, so their `X` has no true zeros and the
gene colour scale starts just above 0 (`log1p(0.1)` = 0.095). Those are the
authors' published values and are kept as they are.

Three further quirks of the older objects, all handled in `raceid_to_seurat()`:

- Features are named `SYMBOL__chrN`, with multi-mapped symbols joined by `|`
  (`ABHD14A-ACY1__chr3|ACY1__chr3`). The suffix is dropped and the first symbol
  kept, which puts them on the same footing as the newer objects' bare symbols.
  Roughly 500 of 43,000 names then collide — small RNAs, snoRNAs and clone
  identifiers, no protein-coding genes — and are separated by `make.unique()`.
- `CreateSeuratObject()` rewrites `_` and `|` in feature names itself, so a
  `data` layer added afterwards under the original names shares no feature with
  the object and the conversion fails outright. The substitution is applied once,
  up front, to both layers.
- `ndata` may be a `data.frame`, which stage 2's dense-to-sparse conversion
  cannot coerce (`invalid type 'list'`), so the type is settled on load.

## The site

`python scripts/08_site.py` writes `docs/` (GitHub Pages: Settings → Pages →
main branch, `/docs`) as three levels:

```
index.html              publications, with dataset counts and total cells
<paper-slug>.html       that publication's datasets
viewer.html?dataset=KEY the viewer itself
```

Publications come from the `paper` field in `config/pipeline.json`, falling back
to the `data/` folder name. "All datasets" in the viewer returns to the
publications index.

## The viewer

`python scripts/08_site.py` writes `docs/` (GitHub Pages: Settings → Pages →
main branch, `/docs`).

Layout, top to bottom:

- two rasterised UMAPs sharing pan and zoom — left coloured by the selected
  metadata column, right by the selected gene
- a legend strip above them, built from the config's own colour table and
  refreshed on every `onConfigChange`, so it follows whichever column is selected
- cell-set and gene pickers
- cell-set sizes and per-set expression violin side by side, toggled by the
  **Summary plots** checkbox (choice persisted in `localStorage`)
- a **Day/Night** toggle; the default follows the OS setting

Cluster labels are drawn at set centroids only when the opening column has 20
sets or fewer, and never on spatial maps.

Colours: every categorical column ships explicit colours in the config. The four
columns whose palettes the authors stored in the Seurat object
(`Subclass_label_final`, `Tissue_label`, `Condition_label`, `Module_label`) keep
those exact colours; the rest get a colour-blind-safe generated palette. Because
the colours are in the config rather than assigned at runtime, the legend is
always accurate.

`view_layout` in `config/pipeline.json` switches between `dual-umap` (default),
`single-umap` and `heatmap`. The heatmap is not recommended here: it pulls the
whole filtered matrix into the browser, which at 135k cells x 4k HVGs is ~2 GB,
so it stays empty. Colouring a UMAP by a gene reads a single chunk instead.

To demo before the S3 sync has run:

```bash
python scripts/serve_local.py
```

which serves `docs/` and `build/zarr/` with CORS on port 8787 and opens the
viewer pointed at the local store.

## Paper

`paper/` holds the draft *Bioinformatics* Application Note, its figure, the
benchmark table and a submission checklist. Figure and table are regenerated
from the build rather than hand-copied:

```bash
python scripts/serve_local.py &
bash scripts/capture_screenshots.sh
python scripts/make_figure.py
python scripts/make_benchmarks.py
```

## Citing

See `CITATION.cff`. Add the Zenodo DOI once a release is archived.

## Licence

Code: MIT (`LICENSE`). Converted data: CC-BY-4.0 (`release/LICENSE`); cite the
source publication for each dataset.

## Metadata labels

Metadata columns are shown under harmonised names (`scripts/common.py`,
`OBS_LABELS`): `cell_type`/`Celltype`/`celltype` → **Cell type**,
`condition`/`Condition` → **Condition**, `seurat_clusters`/`cluster` → **Cluster**,
`RNA_snn_res.0.8` → **Cluster (RNA, res. 0.8)**, `sample`/`sample_id` → **Sample**,
`pat_id`/`Subject_ID` → **Donor**, etc. Only display names change; `obs/<column>`
paths in the stores are untouched, so no rebuild or re-upload is needed — rerun
stages 5 and 8. When two columns in one dataset map to the same label and hold
identical per-cell values, stage 5 shows only one; if they differ, both are kept
with the raw column name appended.
