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
  denominator is stated explicitly in the output. A tool that is *present but
  lacking a required capability* — this host ships `groff` without its `html`
  output device — is recorded the same way, with the reason, because it says
  nothing about TraceJIT's compatibility.
- When TraceJIT reports a workload as eligible but the harness cannot obtain a
  hit, or an observation does not match the direct run, the record says so and
  the process exits non-zero. An equivalence mismatch is never silently recorded
  as a pass.
- When TraceJIT reports a workload as eligible, the harness must obtain a real
  cache hit and compare exit status, stdout, stderr, and the hashes of every
  declared output file against a direct run. A mismatch fails the census.
- Unsupported syscalls are reported as numbers, with a name attached only when
  the host actually ships the kernel syscall header.

## Workloads

The harness defines **≥25** workloads (currently 32) spanning compilers/linkers/archivers,
gzip/bzip2/xz, awk/sed/sort/wc, digests, jq/perl, make, rustc, groff, Pillow, and multi-file
pipelines. See `workloads()` in `census.py` and `docs/final/P1_COMPATIBILITY_CENSUS.md`.

| Workload | Class | What it is |
| --- | --- | --- |
| `cc-compile-fixture` | compiler | The repository's own adversarial C fixture compiled with the system `cc`. |
| `cc-compile-large` | compiler | A generated 300-function translation unit, compiled whole. |
| `clang-compile-large` | compiler | Same TU with `clang`. |
| `cc-link-binary` | linker | Compile + link via `cc`. |
| `ar-static-archive` / `tar-create-archive` | archiver | `ar` / `tar` packaging. |
| `gzip-*` / `bzip2-*` / `xz-*` | compress | Compression family (stdout or round-trip). |
| `shell-pipeline` | shell | `awk \| sort \| uniq -c` over a generated integer list. |
| `python-csv-json` | python | CPython CSV to JSON aggregation with interpreter defaults. |
| `python-csv-json-seeded` | python | The same with `PYTHONHASHSEED=0` (explicitly controlled). |
| `awk-codegen` | codegen | `awk` generating a C header from a TSV schema. |
| `groff-manpage-html` | documentation | `groff -T<device> -man` on a troff man page. |
| `pil-image-transform` | image | Grayscale, posterize, and downsample a PNG with Pillow. |
| `cc-syntax-only-lint` | lint | `cc -fsyntax-only -Wall -Wextra -Werror` over the C fixture. |
| `sed` / `awk` / `sort` / `wc` / digests / `dd` / `od` / `jq` / `perl` / `make` / `rustc` | mixed | Text, scientific awk, data, build, and Rust-related workflows. |
| `multi-file-compile-ar-hash` | multi_file | compile → ar → sha256sum pipeline. |

Tools that were probed and were not present on the census host are listed in
`census.json` under `blocked_missing_tool` with the tool names. Where a common
tool for a category was absent (`pandoc`, ImageMagick, `m4`, `bison`, `flex`,
`clang`, `shellcheck`, `cppcheck`), the workload uses an available equivalent and
says so, instead of silently dropping the category. Where the available tool
itself lacks a capability (`groff` without `-Thtml`), the missing capability is
recorded instead of the workload failing.

## Output

`census.json` holds every per-workload record, including refusal reasons and
counts. `census.md` is the human-readable report. Both are written to the
`--output-dir` given on the command line; nothing in `benchmarks/results/` is
overwritten by default unless that directory is named explicitly.
