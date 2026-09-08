# Submission checklist — Bioinformatics Application Note

Status of `paper/application_note.md`. Everything marked **blocking** must be
resolved before submission; the draft carries `_[...]_` placeholders at each spot.

## Blocking — content

- [ ] **Author list, affiliations, ORCIDs.** Who contributed to the software, as
      distinct from the datasets. Application Notes credit tool authorship.
- [ ] **Corresponding author email.** The address in the draft is a guess.
- [ ] **Funding statement** and **Acknowledgements**.
- [ ] **Ethics.** The collection includes human brain tissue with donor-level
      metadata (diagnosis, sex, age, post-mortem interval, region, donor ID) and
      fetal samples. Confirm the governing consent/IRB permits open
      redistribution, and decide whether donor identifiers stay in the public
      stores. Stage 6 flags `Subject_ID`, `Sample_id` and
      `MajoritySinglet_Individual_Assignment` for exactly this review.
- [ ] **Co-author sign-off for unpublished data.** Chhatbar *et al.* 2026 appears
      to be unpublished; publishing a viewer over it may precede the primary
      paper. Confirm the timing with those authors.
- [ ] **Verify all references.** Items 1, 3 and 7 are flagged in the draft — the
      Vitessce, anndata and CELLxGENE citations need volume/pages/DOI confirmed
      against the actual publications.

## Blocking — availability (journal requirement)

- [ ] **Public repository.** The GitHub repo must be public before submission.
- [ ] **Archived release with a DOI.** Tag a release and archive it on Zenodo,
      then fill the DOI into `CITATION.cff` and the abstract's availability
      statement. Journals require a permanent archive, not just a Git host.
- [ ] **Licence.** `LICENSE` is MIT (code). Data under CC-BY-4.0
      (`release/LICENSE`). Confirm MIT is what you want.
- [ ] **Clean-machine test.** Fresh clone → `python3 -m venv .venv` →
      `pip install -r requirements.txt` → `bash scripts/selftest.sh`. Do this on
      a machine that has never run the pipeline; it is the single most common
      reviewer complaint about tool papers.
- [ ] **A live URL.** The paper is much stronger if the viewer is reachable. Needs
      the S3 sync plus GitHub Pages enabled.

## Non-blocking but worth doing

- [ ] **Continuous integration.** A GitHub Actions workflow running
      `scripts/selftest.sh` on push demonstrates the tool works from a clean
      checkout, and reviewers do look.
- [ ] **Pin the R side properly.** `renv.lock` is generated from installed
      versions; Seurat and SeuratObject are development builds
      (`5.3.1.9999`, `5.1.9999`). Pin to released versions if possible, since a
      reviewer cannot install `.9999`.
- [ ] **Reduce transfer per gene for the largest stores.** At 270k cells one
      chunk carries 1.6 MB. Narrowing the chunk width for large datasets would
      cut per-gene transfer roughly tenfold at the cost of more objects; worth
      benchmarking before the paper quotes final numbers.
- [ ] **Consider depositing in CZ CELLxGENE Discover as well.** Reviewers will
      ask why not; having done both turns the question into a strength.
- [ ] **Suggested reviewers** (3–5), avoiding conflicts.

## LaTeX

The Overleaf project is in `paper/overleaf/` (see its README). It compiles;
the current PDF is 3 pages against a 2-page limit, and the README lists what to
cut, in order, after accounting for Times and the OUP class.

- [ ] Check `pdffonts main.pdf` reports no Type 3 fonts.
- [ ] Re-run `python scripts/make_benchmarks.py --latex` immediately before
      submission so the quoted numbers match Table 1.

## Formatting

- [ ] Two-page limit. The draft body is ~1,120 words plus abstract, one figure,
      one table and seven references — that is about right, but confirm against
      the journal template.
- [ ] Structured abstract with **Summary**, **Availability and implementation**,
      **Contact**, **Supplementary information** — already in the draft.
- [ ] Figure at ≥300 dpi (`paper/figure1.png` is 1800 px wide at 300 dpi).
      Check panel text is legible at print width.
- [ ] Table 1 (`paper/table1.tsv`) formatted to the journal's table style, or
      moved to supplementary if it exceeds the page budget.

## Regenerating the artefacts

```bash
python scripts/serve_local.py &          # needed for HTTP timings and screenshots
bash scripts/capture_screenshots.sh      # viewer screenshots
python scripts/make_figure.py            # paper/figure1.png
python scripts/make_benchmarks.py        # paper/table1.tsv
bash scripts/selftest.sh                 # end-to-end check on synthetic data
```
