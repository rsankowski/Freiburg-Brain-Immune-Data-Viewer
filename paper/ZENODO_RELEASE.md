# Archiving v1.0.0 on Zenodo

The Application Note's availability statement needs a permanent DOI for the
exact code version it describes. Zenodo mints one automatically for every
GitHub release once the repository is linked.

Metadata comes from `.zenodo.json` (title, description, creators, licence,
keywords). Zenodo reads it in preference to `CITATION.cff`, so keep the two in
sync when either changes.

## Before the release

- [x] **Authors.** Fang, Liu, Prinz and Sankowski are in *both*
      `.zenodo.json` (`creators`) and `CITATION.cff` (`authors`) with ORCIDs;
      affiliations for all four. The record
      cannot be corrected retroactively for the archived version, only for
      later ones.
      `.zenodo.json` entry format:
      `{"name": "Family, Given", "orcid": "0000-0000-0000-0000", "affiliation": "..."}`
- [x] **Decide what goes into the archive.** Done: `.gitattributes` excludes both. Zenodo stores the GitHub source
      archive of the tag, i.e. every tracked file. That currently includes
      `prompts/` (LLM prompts and responses) and the unsubmitted manuscript in
      `paper/`. To leave them out of the archive while keeping them in git, add
      to `.gitattributes`:
      ```
      prompts/ export-ignore
      paper/   export-ignore
      ```
- [ ] **Clean checkout passes.** `bash scripts/selftest.sh` on a fresh clone.

## Steps

1. ~~Log in at <https://zenodo.org> with GitHub.~~ Done.
2. ~~**Account → GitHub**, switch on `rsankowski/Freiburg-Brain-Immune-Data-Viewer`.~~
   Done: repository linked to the Zenodo account.
3. On GitHub, **Releases → Draft a new release**: tag `v1.0.0` on `main`,
   title `v1.0.0`, and paste the release notes below. Publish.
4. Within a few minutes Zenodo shows the new record with two DOIs:
   - **version DOI** (this release only): cite this in the paper;
   - **concept DOI** (always resolves to the latest release): use for the
     README badge.
5. Fill the version DOI into:
   - `paper/overleaf/main.tex`: replace `DOI~TODO` in the availability statement;
   - `paper/application_note.md`: replace `_[Zenodo DOI]_`;
   - `CITATION.cff`: uncomment `doi` and `date-released`.
6. Commit those edits. They land after the tag, which is expected: the
   archived snapshot cannot contain its own DOI.

## Release notes (paste into the GitHub release)

```markdown
First archived release, accompanying the Application Note
"A serverless browser for published single-cell and spatial datasets".

Converts Seurat and RaceID objects into cloud-optimised AnnData-Zarr stores
and generates a static Vitessce viewer over them; no application server is
needed, only a static file host.

**Pipeline** (eight resumable stages, one CLI: `python scripts/pipeline.py`)
- Inventory of `.rds`, `.qs`, `.qs2`, `.H5Seurat`, `.RData`/`.rda` and `.Robj`
  inputs, with md5 fingerprints that detect re-exported duplicates.
- Trimming to normalised expression, plottable metadata and 2-D embeddings;
  authors' colour palettes carried into the viewer.
- Verified conversion: each writer's output is re-read and checked before it
  is accepted.
- Gene-axis chunking so one gene is one chunk request; streaming writes keep
  peak memory to one block.
- Harmonised metadata labels across datasets (Cell type, Condition, Cluster,
  Sample, Donor, ...), display-only.
- Validation, static site generation, and generated (never executed) S3 sync,
  bucket policy and CORS files.

**Applied to** 53 datasets from 16 publications: 1,342,207 cells across
scRNA-seq, snRNA-seq, CITE-seq, scATAC-seq, Nanostring CosMx and Visium HD,
in human, mouse and Drosophila.

**Try it without data:** `bash scripts/selftest.sh` builds a synthetic
dataset and runs all eight stages.

Code under MIT; data under CC-BY-4.0 (see `release/LICENSE`).
```

## Data record (separate from the software release)

The Zarr stores go into their own Zenodo *dataset* record (CC-BY-4.0), linked
to the software DOI and the 16 source publications. `scripts/zenodo_data.py`
zips each store (uncompressed; zarr/anndata read it without unpacking),
verifies it, writes `README.md`, `configs.zip` and `MD5SUMS`, and uploads to a
**draft** that you publish yourself.

```bash
python scripts/zenodo_data.py build                    # -> build/zenodo/ (56 files, 12.6 GB)
export ZENODO_TOKEN=...                                # Zenodo: Applications -> Personal access tokens
                                                       #   scopes: deposit:write, deposit:actions
python scripts/zenodo_data.py upload --sandbox         # optional dry run (needs a sandbox token)
python scripts/zenodo_data.py upload                   # real draft, access restricted
python scripts/zenodo_data.py upload --access open     # ...or open, once consent is confirmed
python scripts/zenodo_data.py upload --deposition ID   # resume after an interruption
```

- [ ] Confirm consent/ethics permit archiving the human donor metadata openly;
      otherwise keep `--access restricted` (files visible on request).
- [ ] Review the draft on Zenodo, publish, then add a *Data availability*
      sentence with the dataset DOI to the manuscript.
