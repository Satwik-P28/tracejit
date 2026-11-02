# The first real-world cache hit

Commit: `bd59a0e` (code under test). Host: Linux 6.1.102, x86-64, 2 vCPU. Reproduce with
`python3 benchmarks/realworld/direct_suite.py`.

## The workload

```bash
gzip -9 -c /path/to/data.txt > /dev/null        # 18,000,000-byte text input
```

Compression is an ordinary developer action: build artifacts, logs, release tarballs, test fixtures.
It is not a synthetic loop and not a fixture built for this project.

## Result

| | |
| --- | --- |
| Classification | **`GUARDED`**, `eligible_for_reuse: true` |
| Recorded dependencies | 9 |
| Processes in the tree | 1 |
| First run | `Executed` — no eligible cached execution matched the pre-execution identity |
| Second run | **`Reused`** — all guards passed and cached outputs were restored |
| 20 consecutive runs | **20/20 `Reused`** |
| Output equivalence | byte-identical to a direct run |

This is the first time an unmodified, useful program has been skipped by TraceJIT on this branch.

## Why it is safe, and what is actually checked

`gzip` reads its input, its own executable and the C library, and reads no clock, no randomness and
no process identity — verified by the trace, not assumed: `analyze` reports only guardable
dependencies. The compressed stream embeds the input's modification time and name, and both arrive
through `stat`, which is recorded as a metadata dependency.

Every guard must therefore hold before a single cached byte is exposed:

| Change | Expected | Observed |
| --- | --- | --- |
| Content appended to the input | deoptimize, emit the new stream | `Deoptimized`, bytes equal a fresh direct run |
| Re-run after that | reuse the new stream | `Reused`, bytes stable |
| `mtime`-only change (`utime`) | deoptimize, because gzip stores the timestamp | `Deoptimized`, output differs from the previous stream exactly as a direct run's does |
| `GZIP=-1` added to the environment | not reused | `Ineligible`; the command ran and matched a direct run |
| Second run on a symlinked executable | reuse | `Reused` |
| Symlink repointed at a different program | refuse, never replay the old bytes | ran the impostor, output matched the impostor |
| Interrupted cache / corrupt object | out of scope here; covered by the Phase 1.5 recovery tests | — |

The `GZIP=-1` row deserves a note: gzip ignores `GZIP` when a level is given on the command line, so
the compressed bytes are identical either way. TraceJIT executed the command instead of reusing the
record — a conservative miss, not a wrong answer, and the output matched a direct run. Requiring a
fresh run when the environment changed is the intended behaviour.

## Performance

20 measured runs each, stdout to `/dev/null`, medians, same session, no competing load:

| Condition | Median | p95 |
| --- | ---: | ---: |
| Direct `gzip -9 -c` | 259.41 ms | 272.03 ms |
| Cold traced run | 504.25 ms | — (single sample) |
| Cached reuse | **10.88 ms** | 14.05 ms |

- Speedup: **23.84x**
- Median time saved per run: **248.53 ms**
- Hits needed to repay one cold trace: **1.99** (two repeated uses break even)

The 10.88 ms hit is consistent with the ~4 ms floor measured on tiny workloads plus hashing an 18 MB
input: BLAKE3 over 18 MB at roughly 2–3 GB/s accounts for most of the difference.

## What this does *not* establish

- It does not make the nine-workload census eligible. That suite is unchanged and remains 0 of 9; the
  reasons are in `PHASE2C_PIPE_SOUNDNESS.md` and `PHASE2B_CENSUS_DELTA.md`.
- It does not establish that compression is *representative*. Compression is a favourable case: one
  process, no clocks, no randomness. Most of the other candidate commands probed
  (`sort`, `base64`, `md5sum`, `tr`, `wc`, `head`) read `getrandom` during startup and were therefore
  `NONDETERMINISTIC`; `sed` hit unmodeled `statfs`; `grep` opened `/proc/self/maps`.
- It does not change the enforcement story: `PROVEN` is still unexercised, and this hit is `GUARDED`.

## Methodological finding: the census wrapper is part of the measurement

The census invokes most workloads as `sh -c "…"`, so the trace contains the shell as well as the
workload. Probing the same kinds of commands under `bash -c` added `/dev/tty` (`ENXIO`),
`getpeername` (`ENOTSOCK`), `statfs` and `getrandom` — all from the shell, none from the workload.
`gzip` invoked directly is fully guardable; `bash -c "gzip …"` is not.

That is a real property of wrapping commands in a shell, and it is a legitimate thing to refuse, but
it means the census's 0/9 currently measures "shell-wrapped command plus its workload". The suite was
**not** changed — its denominator stays fixed for longitudinal comparison — and a direct-invocation
suite was added alongside it (`benchmarks/realworld/direct_suite.py`) so the two effects can be told
apart.
