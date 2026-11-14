# P1 §8 — Compatibility census (≥25 workflows)

Date: 2026-11-14  
Harness tip SHA recorded in artifact: `026e660f6722ee7dddbf8ec00caaf52a817c36cf`  
Raw: `benchmarks/results/final_p1/census/{census.json,census.md}`  
Command:

```bash
cargo build --workspace --release
python3 benchmarks/realworld/census.py --runs 2 --warmups 1 \
  --output-dir benchmarks/results/final_p1/census
```

## Scope

32 realistically selected workflows spanning compilers/linkers/archivers, gzip/bzip2/xz, awk/sed/sort/wc, groff docs, Pillow image (host lacked PIL → workload_failed), jq/perl scripts, make, rustc, digests, dd/od, and a multi-file compile→ar→hash pipeline. Defaults are unmodified unless a workload is explicitly marked controlled (`python-csv-json-seeded` sets `PYTHONHASHSEED=0`).

## Measured aggregate

| Metric | Value |
| --- | ---: |
| Requested | 32 |
| Attempted | 32 |
| Reused (verified HIT) | **1** (`gzip-compress-stdout`) |
| Refused | 30 |
| Workload failed | 1 (`pil-image-transform`, no Pillow) |
| Eligibility rate | **0.031** |

Dominant blockers (from artifact): **randomness** (22 workloads), **clock** (9), process identity / system information / pipes / unmodeled syscalls (`fstat`, `ioctl`, `fcntl`, …).

## Pareto / priority (honest)

Semantic improvements should target high-frequency refusals only with a minimal model + oracle + chaos coverage. This census does **not** expand eligibility. Randomness/clock refusals remain correct fail-closed behavior for unmodified tools.

## Non-claims

- Sanitized/controlled runs are not compared as ordinary defaults.
- Missing tools are not scored as TraceJIT refusals (Pillow recorded as workload_failed).
- No claim that 1/32 eligibility is a product win; it is a measured boundary.
