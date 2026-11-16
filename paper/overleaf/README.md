# Overleaf project — Bioinformatics Application Note

Upload this folder to Overleaf (**New Project → Upload Project**, after zipping
it) and set `main.tex` as the main document. It compiles as-is.

## Files

| File | Role |
|---|---|
| `main.tex` | Front matter, figure, table include, back matter. **Edit the TODOs.** |
| `sections.tex` | Manuscript body. Class-independent — survives a switch to the OUP class. |
| `stats.tex` | *Generated.* Headline numbers as macros (`\NumCells`, `\MedianPfifty`, …). |
| `supplementary.tex` | Supplementary information; compile separately. Landscape, holds Table S1. |
| `table_s1.tex` | *Generated.* Supplementary Table S1, all datasets (longtable). |
| `references.bib` | Bibliography. Three entries are marked `VERIFY`. |
| `figure1.png` | *Generated.* Two-panel print figure, 2400 px wide at 300 dpi. |

Regenerate the three generated files from the repository root:

```bash
python scripts/serve_local.py &          # needed for the HTTP timings
python scripts/make_benchmarks.py --latex
python scripts/make_figure.py --layout print --out paper/overleaf/figure1.png --width 2400
```

`stats.tex` exists so the prose and Supplementary Table S1 cannot disagree: the abstract and
Results section quote macros, not typed-in numbers. Re-run the benchmark script
immediately before submission.

## Why the article class rather than a journal class

The journal's author guidelines state that TeX manuscripts should use the
article class with two-column text and 86 mm columns, which is what `main.tex`
sets (`textwidth=178mm`, `columnsep=6mm`). This needs no journal class file, so
it compiles anywhere, including a minimal local TeX installation.

If you prefer the official OUP template, it is on CTAN as
[`oup-authoring-template`](https://ctan.org/pkg/oup-authoring-template) and in
Overleaf's gallery. To switch: start a project from that template, copy
`sections.tex`, `stats.tex`, `references.bib` and `figure1.png`, plus
`supplementary.tex` and `table_s1.tex` for the supplement,
into it, replace the template's body with `\input{sections}`, and move the
title, authors, abstract and keywords into the template's own front-matter
macros. Nothing outside `main.tex` needs changing.

## Current state: 3 pages, limit is 2

Compiled locally the PDF is 3 pages: body and abstract fill roughly two, and
the back matter and references take the third (Table 1 has moved to the
supplement and the figure now sits atop page 2). Two things will help
before you start cutting:

1. **Times.** This project uses Times when `times.sty` is available. It was not
   available on the machine that compiled the draft, so the local PDF is set in
   Computer Modern, which runs about 5–8% longer. Overleaf has Times.
2. **The OUP class** sets more text per page than the article class does.

If it is still over after that, in the order I would cut:

- ~~Move Table 1 to supplementary.~~ Done: it is now Supplementary Table S1.
- Merge *Discovery, inventory and memory containment* with *Trimming and
  verified conversion* (~80 words of headings and transitions).
- Cut the last paragraph of the Discussion (~60 words); the ontology point can
  live in one sentence.
- Drop the CosMx panel from the figure and run it single-column.

## Before submitting

- Replace every `TODO`: author list, affiliations, corresponding email,
  acknowledgements, funding, and the Zenodo DOI in the availability statement.
- Resolve the three `VERIFY` entries in `references.bib`. They currently print
  the word VERIFY in the reference list, so you cannot miss them.
- **Check for Type 3 fonts.** A minimal TeX install produces bitmap Type 3
  fonts, which many journals reject. On Overleaf with Times you will get Type 1
  or TrueType; verify with `pdffonts main.pdf` that no line says `Type 3`.
- See `../SUBMISSION_CHECKLIST.md` for the non-LaTeX blockers, including the
  ethics and data-availability items.
