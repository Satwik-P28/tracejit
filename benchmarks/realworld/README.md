# Real-world compatibility census

`census.py` runs recognizable developer workloads through TraceJIT and records
what it classifies, what it refuses, and why. It is deliberately separate from
`benchmarks/harness/`, which measures timing on one controlled workload. This
suite answers a different question: *how much useful work can TraceJIT V1
actually reuse?*

```bash
cargo build --workspace --release
python3 benchmarks/realworld/census.py --runs 5 --warmups 1 \
  --output-dir benchmarks/results/phase1
```

## Properties

- No workload is tuned to make TraceJIT pass. Eligibility is reported, never
  engineered, and the tracer is not changed to accept a workload.
- Every workload runs in a scratch directory outside the repository, so the
  census does not mutate tracked files or workload outputs.
- Tool-missing and workload-failed entries are recorded separately from a
  TraceJIT refusal. They are excluded from the eligibility rate, and the
  denominator is stated explicitly in the output.
- When TraceJIT reports a workload as eligible, the harness must obtain a real
  cache hit and compare exit status, stdout, stderr, and the hashes of every
  declared output file against a direct run. A mismatch fails the census.
- Unsupported syscalls are reported as numbers, with a name attached only when
  the host actually ships the kernel syscall header.

## Workloads

| Workload | Class | What it is |
| --- | --- | --- |
| `cc-compile-fixture` | compiler | The repository's own adversarial C fixture compiled with the system `cc`. |
| `cc-compile-large` | compiler | A generated 300-function translation unit, compiled whole. |
| `shell-pipeline` | shell | `awk \| sort \| uniq -c` over a generated integer list. |
| `python-csv-json` | python | CPython CSV to JSON aggregation with interpreter defaults. |
| `python-csv-json-seeded` | python | The same with `PYTHONHASHSEED=0`. |
| `awk-codegen` | codegen | `awk` generating a C header from a TSV schema. |
| `groff-manpage-html` | documentation | `groff -Thtml -man` on a troff man page. |
| `pil-image-transform` | image | Grayscale, posterize, and downsample a PNG with Pillow. |
| `cc-syntax-only-lint` | lint | `cc -fsyntax-only -Wall -Wextra -Werror` over the C fixture. |

Tools that were probed and were not present on the census host are listed in
`census.json` under `blocked_missing_tool` with the tool names. Where a common
tool for a category was absent (`pandoc`, ImageMagick, `m4`, `bison`, `flex`,
`clang`, `shellcheck`, `cppcheck`), the workload uses an available equivalent and
says so, instead of silently dropping the category.

## Output

`census.json` holds every per-workload record, including refusal reasons and
counts. `census.md` is the human-readable report. Both are written to the
`--output-dir` given on the command line; nothing in `benchmarks/results/` is
overwritten by default unless that directory is named explicitly.
