# Manuscript

*The Cost of Conservative Reuse: Correctness and Performance Trade-offs in Automatic Command
Caching.*

```bash
make            # regenerate tables from benchmarks/results/**, then build the PDF
make check      # fail if a table disagrees with the committed evidence
```

Requirements: `pdflatex` and `bibtex` (TeX Live), plus `python3` for the table generator. No LaTeX
package outside a standard TeX Live installation is used (`booktabs`, `amsmath`, `microtype`,
`hyperref`).

## Structure

| file | content |
| --- | --- |
| `main.tex` | preamble, title, section includes |
| `sections/00-abstract.tex` | abstract |
| `sections/01-introduction.tex` | problem, research question, contributions, non-claims |
| `sections/02-background.tex` | primary-source background and the execution model |
| `sections/03-model-architecture.tex` | tracing, classification, guards, CAS, replay, enforcement |
| `sections/04-correctness.tex` | tested invariants, model-checked properties, the residual race |
| `sections/05-methodology-results.tex` | methodology, results, all tables |
| `sections/06-negative-limitations.tex` | negative results and limitations |
| `sections/07-related-conclusion.tex` | positioning, conclusion, artifact availability |
| `refs.bib` | bibliography, primary sources only |
| `tables/` | **generated**; do not edit |

## Rules this manuscript follows

1. Every number in `tables/` is generated from a committed JSON file by
   `benchmarks/phase_af/build_tables.py`. `make check` fails if a document's headline disagrees
   with the rows.
2. Every performance number names its arm, its session mode (`cold`/`steady`), its tool version and
   its host class, or it does not appear.
3. `PROVEN` is described as "the policy was installed". It is never described as equivalence,
   correctness, atomicity or race-freedom.
4. Negative results are part of the evaluation, not an appendix: cheap commands, compiler caches,
   Firebuild's advantages, low native eligibility, and the residual race are all reported.
5. No claim of independent external reproduction. CI-hosted execution is described as what it is.
6. The verified-replay figure is a measured serial cost model, not a lower bound.

## State

Working draft, written for the `v0.3.0-alpha.1` research prerelease. It has not been submitted
anywhere. `docs/PAPER_REVIEW_AUDIT.md` records the adversarial review of this draft and an honest
venue assessment.
