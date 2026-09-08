# Freiburg Brain Immune Data Viewer

Cloud-optimised single-cell RNA-seq datasets in **AnnData-Zarr** format, ready to
stream into [Vitessce](http://vitessce.io/) or read with `anndata` / `zarr`
without downloading the whole store.

## Datasets

| Store | Title | Cells | Genes | Size | Source |
|---|---|---|---|---|---|
| `amann_et_al_2024.zarr` | Harmony-integrated atlas | 24,497 | 19,821 | 192.7 MB | Amann et al. 2024 |
| `ardura_fabregat_et_al_2025__dataset_1.zarr` | Dataset 1 | 2,003 | 53,647 | 3.9 MB | Ardura-Fabregat et al. 2025 |
| `ardura_fabregat_et_al_2025__dataset_2_with_index_data.zarr` | Dataset 2 (with index data) | 2,520 | 53,647 | 4.3 MB | Ardura-Fabregat et al. 2025 |
| `chhatbar_et_al_2026__figure_2_nanostring_cosmx_v1.zarr` | CosMx spatial transcriptomics | 68,327 | 990 | 35.9 MB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_4_human_visiumhd_compressed_v1.zarr` | Visium HD human brain | 96,409 | 18,085 | 109.0 MB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_5_mouse_myeloid_atlas_v1.zarr` | Mouse myeloid atlas | 172,497 | 56,884 | 1.8 GB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_6_cross_species_microglia_integrated.zarr` | Cross-species microglia | 270,493 | 17,219 | 2.1 GB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_7_eae_microglia_manipulation.zarr` | EAE microglia manipulation | 17,760 | 56,884 | 399.4 MB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_e10_a_pathways_manipulation_mouse.zarr` | Pathway manipulation (mouse) | 64,066 | 56,884 | 967.5 MB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__figure_e10_d_lps_microglia_manipuliation.zarr` | LPS microglia manipulation | 26,433 | 56,884 | 271.9 MB | Chhatbar et al. 2026 |
| `chhatbar_et_al_2026__immune_final_2_23012025.zarr` | Human brain immune atlas | 135,067 | 59,462 | 1.4 GB | Chhatbar et al. 2026 |
| `fliegauf_et_al_2026__fig2_scrnaseq.zarr` | CNS macrophages after injury (Fig. 2) | 39,838 | 35,918 | 556.0 MB | Fliegauf et al. 2026 |
| `fliegauf_et_al_2026__fig5_scrnaseq_full_dataset.zarr` | Full scRNA-seq dataset (Fig. 5) | 21,402 | 56,888 | 228.3 MB | Fliegauf et al. 2026 |
| `fliegauf_et_al_2026__fig5_scrnaseq_microglia.zarr` | Microglia (Fig. 5) | 11,147 | 56,888 | 127.2 MB | Fliegauf et al. 2026 |
| `fliegauf_et_al_2026__fig5_scrnaseq_sdcams.zarr` | sdCAMs (Fig. 5) | 8,683 | 56,888 | 81.9 MB | Fliegauf et al. 2026 |
| `fliegauf_et_al_2026__fig6_scatacseq.zarr` | scATAC-seq gene activity (Fig. 6) | 10,224 | 21,821 | 459.7 MB | Fliegauf et al. 2026 |
| `friedrich_et_al_2021__gse166418_seurat_integration_wt_rh_gbm_final.zarr` | Myeloid cells in IDH-mutant glioma | 4,460 | 23,183 | 27.8 MB | Friedrich et al. 2021 |
| `friedrich_et_al_2021__seurat_integration_10x_wt_rh_gbm.zarr` | 10x integration, wild-type and IDH-mutant | 55,754 | 16,726 | 174.3 MB | Friedrich et al. 2021 |
| `frosch_et_al_2025__all_cells_001.zarr` | All cells | 44,957 | 33,709 | 491.0 MB | Frosch et al. 2025 |
| `frosch_et_al_2025__immune_cells.zarr` | Immune cells | 3,371 | 33,697 | 29.8 MB | Frosch et al. 2025 |
| `frosch_et_al_2025__microglia.zarr` | Microglia | 3,097 | 33,697 | 27.5 MB | Frosch et al. 2025 |
| `masuda_et_al_2020.zarr` | Hexb-based microglia atlas | 3,825 | 30,956 | 78.8 MB | Masuda et al. 2020 |
| `masuda_et_al_2022.zarr` | Masuda et al. 2022 | 483 | 14,610 | 5.7 MB | Masuda et al. 2022 |
| `petry_et_al_2025.zarr` | Embryonic microglia progenitors | 483 | 14,610 | 5.7 MB | Petry et al. 2025 |
| `sankowski_et_al_2021__seurat_all_without_doublets.zarr` | All myeloid cells | 2,745 | 19,488 | 17.7 MB | Sankowski et al. 2021 |
| `sankowski_et_al_2021__seurat_cp.zarr` | Choroid plexus | 487 | 19,488 | 3.6 MB | Sankowski et al. 2021 |
| `sankowski_et_al_2021__seurat_men.zarr` | Meninges | 545 | 19,488 | 3.9 MB | Sankowski et al. 2021 |
| `sankowski_et_al_2021__seurat_micr.zarr` | Microglia | 828 | 19,488 | 5.6 MB | Sankowski et al. 2021 |
| `sankowski_et_al_2021__seurat_pvm.zarr` | Perivascular macrophages | 885 | 19,488 | 5.8 MB | Sankowski et al. 2021 |
| `sankowski_et_al_2024__figure_1_gse245311_multimodal_harmony_integrated_controls.zarr` | Multimodal control atlas (Fig. 1) | 11,166 | 30,512 | 134.1 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_2_gse245311_reference_mapped_celseq2_ctrl_cd206_gate_no_lowq_cells.zarr` | CD206-gated CEL-Seq2 controls (Fig. 2) | 1,962 | 60,649 | 5.3 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_4_b_gse245311_harmony_integrated_nucseq_all_cells.zarr` | Single-nucleus atlas (Fig. 4b) | 59,053 | 36,601 | 819.3 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_4_d_gse245311_immune_combined_with_braun_yang_et_al.zarr` | Immune cells with Braun & Yang et al. (Fig. 4d) | 13,807 | 36,601 | 191.0 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_5_i_gse245311_micr_ffpe.zarr` | FFPE microglia (Fig. 5i) | 363 | 18,082 | 400.5 KB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_6_g_gse245311_reference_mapped_fetal.zarr` | Fetal reference-mapped cells (Fig. 6g) | 4,332 | 27,723 | 17.8 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_6_gse245311_multimodal_harmony_integrated_gb.zarr` | Multimodal glioblastoma atlas (Fig. 6) | 11,681 | 30,071 | 132.6 MB | Sankowski et al. 2024 |
| `sankowski_et_al_2024__figure_e7_gse245311_all_cells_ffpe.zarr` | All cells, FFPE (Fig. E7) | 9,035 | 18,082 | 6.9 MB | Sankowski et al. 2024 |
| `wieghofer_et_al_2021__cb_cornea.zarr` | Cornea and ciliary body | 432 | 32,760 | 5.5 MB | Wieghofer et al. 2021 |
| `wieghofer_et_al_2021__retina.zarr` | Retina | 530 | 32,936 | 7.0 MB | Wieghofer et al. 2021 |

## Layout

```
freburg-immune-data-viewer-544227292049-us-east-1-an/
  <dataset>.zarr/        AnnData-Zarr store
    X/                   normalised expression, dense, chunked (n_cells, 10)
    obs/                 per-cell metadata (categoricals + numeric QC)
    var/                 per-gene metadata, incl. highly_variable
    obsm/X_umap          UMAP embedding
  configs/               Vitessce view configs, one JSON per dataset
  configs/index.json     dataset index
  README.md, LICENSE
```

`X` is chunked so that fetching one gene across all cells is a single chunk read.

## Access

No credentials required.

```bash
aws s3 ls --no-sign-request s3://freburg-immune-data-viewer-544227292049-us-east-1-an/
```

```python
import anndata as ad
adata = ad.read_zarr("https://freburg-immune-data-viewer-544227292049-us-east-1-an.s3.us-east-1.amazonaws.com/amann_et_al_2024.zarr")   # or a fsspec mapper for lazy access
```

```python
from vitessce import VitessceConfig
import json, urllib.request
cfg = json.load(urllib.request.urlopen("https://freburg-immune-data-viewer-544227292049-us-east-1-an.s3.us-east-1.amazonaws.com/configs/amann_et_al_2024.json"))
VitessceConfig.from_dict(cfg).widget()
```

## Provenance

Converted from the authors' Seurat objects with the pipeline in
<https://github.com/rsankowski/Freiburg-Brain-Immune-Data-Viewer>.
No re-clustering, re-integration or re-embedding was performed: cell annotations
and embeddings are the published ones. Conversion keeps the normalised
expression matrix, plottable cell metadata and the published embeddings.

## Licence

CC-BY-4.0 — see `LICENSE`. Please cite the source publication.

Last updated: 2026-09-08
