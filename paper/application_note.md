# A serverless browser for published single-cell and spatial datasets

**Authors:** Jincheng Fang, Yun Liu, Marco Prinz, Roman Sankowski\*

**Affiliations:** Institute of Neuropathology, Faculty of Medicine, University of Freiburg, Freiburg, Germany

**Corresponding author:** Roman Sankowski (roman.sankowski@uniklinik-freiburg.de)

---

## Abstract

**Summary:** Single-cell datasets accompanying a publication are usually shared
as serialised R objects that only readers with a matching software stack and
enough memory can open. We present a pipeline that converts collections of
Seurat and RaceID objects into cloud-optimised AnnData-Zarr stores and generates a static
web viewer over them. Expression is stored as a dense array chunked along the
gene axis, so colouring an embedding by any gene is a single chunk read; nothing
but a static file host is required to serve it. Applied to 53 datasets from 16
publications — 1,342,207 cells spanning plate-based and droplet scRNA-seq,
snRNA-seq, CITE-seq, scATAC-seq, Nanostring CosMx and Visium HD, in human, mouse
and *Drosophila* — the conversion reduces 66.9 GB of serialised objects to
12.5 GB of stores, and a single-gene query completes in a median of 2.7 ms over
HTTP. Every conversion is verified against its source
object before it is accepted, and the pipeline ships an end-to-end self-test on
synthetic data.

**Availability and implementation:** Source code, documentation and the
synthetic self-test are at https://github.com/rsankowski/Freiburg-Brain-Immune-Data-Viewer
under the MIT licence, archived at _[Zenodo DOI]_. R ≥ 4.4 and Python ≥ 3.11.

**Contact:** roman.sankowski@uniklinik-freiburg.de

**Supplementary information:** Supplementary data are available at
*Bioinformatics* online.

---

## 1 Introduction

Making a single-cell dataset genuinely reusable is harder than depositing it.
Count matrices in GEO require the reader to rebuild an analysis before they can
look at anything; the `.rds` files that accompany many papers preserve the
authors' embeddings and annotations but demand a compatible Seurat version and,
for larger objects, tens of gigabytes of memory. In the collection described
here, one 135,067-cell object occupied 14.9 GB in memory. A reader who wants to
check whether one gene marks one cluster should not have to pay that cost.

Interactive browsers address this, but the established options impose their own
constraints. Hosted platforms such as CZ CELLxGENE Discover and the UCSC Cell
Browser require datasets to be submitted and conformed to a schema, and control
of the presentation passes to the host. Self-hosted browsers such as cellxgene
in server mode need a process running per dataset, which is a poor fit for a lab
that wants a link to outlive a grant. Vitessce (Keller *et al.*) removes the
server requirement by reading Zarr stores directly in the browser, but leaves
the conversion, chunking and configuration to the user — the step that in
practice determines whether the result is usable.

We provide that step. The pipeline is deliberately conservative: it re-runs no
clustering, integration or embedding, and preserves published annotations and
coordinates verbatim, so what a reader sees is what the paper reported.

## 2 Implementation

The pipeline runs as eight resumable stages (≈3,800 lines of R and Python)
driven by one CLI. Stages 1–3 are R, working with Seurat objects; stages 4–8 are
Python, working with AnnData and Zarr.

**Discovery and inventory.** `data/` is walked for `.rds`, `.qs`, `.qs2`,
`.H5Seurat`, `.RData`/`.rda` and `.Robj` files, compressed or not, and a stable
key is derived from each path. RaceID objects, used for the earlier plate-based
studies in the collection, are converted to Seurat on load, so later stages see
a single object type. Stage 1 records cells, features, assays, layers,
reductions and per-column metadata types, plus md5 fingerprints of barcodes,
features and embeddings — which identified one object re-exported under a
second name, and one dataset deposited with two publications.

**Memory containment.** Objects here reach 18.5 GB resident. Stages 1–3 run each
dataset in a child R process, so only one object is ever in memory, the operating
system reclaims it between datasets, and the parent measures the child's true
peak RSS rather than estimating it.

**Trimming.** Stage 2 keeps the normalised `data` layer of one assay,
plottable metadata, and 2-D embeddings, and computes a highly-variable-gene flag
if absent. Colour columns of the form `Subclass_color` are matched to the label
column they determine — by functional dependency, not by name or cardinality,
both of which give wrong answers on real objects — and lifted into the view
configuration so the viewer reproduces the authors' own palettes. Character
columns that are really numeric are coerced only when they parse cleanly; where
coercion would silently delete values (fetal ages recorded as `pcw_14` alongside
numeric years) the verbatim column is retained alongside.

**Verified conversion.** Stage 3 tries `anndataR`, then `sceasy`, then a direct
`reticulate` writer, and accepts a writer's output only after re-reading it and
confirming dimensions, barcode and feature names, embedding shapes, the
highly-variable flag, and 100 random expression values, half of them forced onto
non-zero entries. On these objects `sceasy` fails that check — it writes
`obsm/X_ref.umap` where scanpy conventions require `X_ref_umap`, and drops the
`highly_variable` column — so the direct writer is used. Without the check the
defect would have reached the browser as a missing embedding.

**Chunking.** Stage 4 writes `X` as a dense array chunked `(n_cells, k)` genes,
so one gene is one chunk read rather than a scan. Vitessce's `optimize_adata`
helper is used for `obs`, `var` and `obsm`, but not for `X`: its densification
path materialises the whole matrix, which for 135,067 × 59,462 float32 is 32 GB.
We stream `X` into the Zarr array in column blocks instead, so peak memory is one
block. `k` defaults to 10 and widens for small datasets so that no chunk falls
below 64 KB; at 363 cells the default produced 1,940 files for 484 KB of data.

**Configuration and site.** Stage 5 emits one Vitessce configuration per dataset
with absolute URLs derived from a single base URL. Colours for every categorical
column are written into the configuration rather than assigned at runtime, which
is what allows the interface to display a legend that is guaranteed to match the
plot. Metadata columns are displayed under harmonised names — `cell_type`,
`Celltype` and `celltype` all appear as *Cell type*, `RNA_snn_res.0.8` as
*Cluster (RNA, res. 0.8)* — changing only the label, not the stored column;
columns that collapse to the same label with identical values are shown once. Stage 8 generates a static site: a publication index, one page per
publication, and a viewer showing two linked embeddings — one coloured by a
metadata column, one by a gene — with cell-set and gene pickers and per-set
summary plots (Fig. 1). Spatial datasets expose tissue coordinates as an
additional embedding, so the same interface serves dissociated and spatial data.

**Validation and release.** Stage 6 checks Zarr metadata, times single-gene
fetches, confirms every path referenced by a configuration resolves, and screens
`obs` for free text, dates and identifier-shaped columns for manual review before
release. Stage 7 generates — but never executes — the S3 synchronisation
commands, bucket policy and CORS configuration.

## 3 Results

Applied to 53 datasets from 16 publications (2019–2026; Supplementary Table S1), the pipeline
produced 12.5 GB of stores from 66.9 GB of serialised objects, across 156,142
objects and 1,342,207 cells (summed over datasets, several of which are subsets
of a larger one). Single-gene queries over HTTP had a median p50 of 2.7 ms and a
maximum p50 of 12.1 ms; transfer per gene ranged from under 1 KB to 1.6 MB, the upper end being
the 270,493-cell dataset, where one chunk carries 10 genes for every cell.
Conversion is a one-off cost of seconds to minutes per dataset.

Correctness is enforced rather than asserted: the round-trip check in stage 3
rejected one of three candidate writers on this collection. A self-test builds a
synthetic dataset, runs all eight stages and makes 19 assertions about the
outputs, so the pipeline can be exercised without access to any real data.

## 4 Discussion

The approach trades flexibility for durability. A static store cannot filter or
recompute server-side; what it offers is a resource that costs nothing to keep
running and cannot break when a server is decommissioned. Two limitations follow
from the chunking. Genes are stored densely, so the store is larger than a sparse
representation for very sparse data; and a fixed chunk width means large datasets
transfer more per gene than they strictly need. The Vitessce heatmap view is not
practical at this scale, since it requires the whole filtered matrix — about
2 GB for a 135k × 4k selection — and colouring an embedding by a gene is used
instead.

Metadata column names are harmonised for display, but the pipeline preserves
each dataset's own annotation values, so cell-type vocabularies still differ
between studies. Mapping them to a shared ontology would make the
collection analysable rather than merely browsable, and is the natural extension.

## Acknowledgements

_[to complete]_

## Funding

_[to complete]_

## Conflict of Interest

None declared.

## References

_Details to be verified against the journal's reference style before submission._

1. Keller MS, *et al.* Vitessce: integrative visualization of multimodal and
   spatially resolved single-cell data. *Nature Methods* (2025). _[verify volume/pages]_
2. Hao Y, *et al.* Dictionary learning for integrative, multimodal and scalable
   single-cell analysis. *Nature Biotechnology* 42:293–304 (2024).
3. Virshup I, *et al.* anndata: Access and store annotated data matrices.
   *Journal of Open Source Software* 9:4371 (2024). _[verify]_
4. Wolf FA, Angerer P, Theis FJ. SCANPY: large-scale single-cell gene expression
   data analysis. *Genome Biology* 19:15 (2018).
5. Moore J, *et al.* OME-NGFF: a next-generation file format for expanding
   bioimaging data-access strategies. *Nature Methods* 18:1496–1498 (2021).
6. Speir ML, *et al.* UCSC Cell Browser: visualize your single-cell data.
   *Bioinformatics* 37:4578–4580 (2021).
7. CZI Single-Cell Biology Program. CZ CELLxGENE Discover: a single-cell data
   platform for scalable exploration, analysis and modeling of aggregated data.
   *Nucleic Acids Research* (2025). _[verify]_

---

## Figure legend

**Fig. 1.** The generated viewer. (**A**) Two linked embeddings of a
135,067-cell human brain immune atlas: coloured by cell type on the left, by
*P2RY12* expression on the right, with a legend built from the authors' own
palette and per-cell-set summary plots beneath. (**B**) The same interface on
Nanostring CosMx data, with tissue coordinates as the embedding; fields of view
from 18 samples are laid out side by side, preserving within-sample geometry. (**C**) The publication index; each
dataset is a single AnnData-Zarr store addressed by URL.

## Supplementary Table S1

`paper/table_s1.tsv` (typeset in `paper/overleaf/supplementary.tex`) — per dataset: publication, cells, genes, source object size, store size,
object count, chunk width, single-gene p50/p95 latency over HTTP, and transfer
per gene. Regenerate with `python scripts/make_benchmarks.py --latex`.
