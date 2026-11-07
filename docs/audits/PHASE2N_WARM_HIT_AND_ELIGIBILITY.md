# Phase 2N: warm-hit latency and developer eligibility

Base `7dd37cf`. Measured binary for this phase: `88d528d4`, SHA-256
`eb11091e8d2037b4...` (fresh release build). Host: Linux 6.1.102, 8 vCPU.

## 1. CI verification status

Local only: `cargo fmt --all -- --check`, Clippy with `-D warnings`, and
`cargo test --workspace` (113 tests) pass. `tracejit doctor` still reports `landlock no`,
`proven no`, so `PROVEN` remains blocked and was not weakened.

The four seccomp properties are asserted by the sandbox suite, not assumed:
`apply_seccomp` sets `PR_SET_NO_NEW_PRIVS` before the filter, reports
`set no_new_privs before seccomp: <errno>` and `seccomp installation failed: <error>` to stderr,
denies `socket(AF_INET, SOCK_STREAM)` and `ptrace(PTRACE_TRACEME)` with `EPERM`, permits `/dev/null`
writes, and asserts `PR_GET_NO_NEW_PRIVS == 1`. `apply_landlock` and the `apply` order are untouched.

**Blocker:** GitHub Actions cannot be executed. The branch head is not pushed (Phase 2M's
"no push without authorization" still applies), so the only run that exists is
[42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118) at `c7f2c68`, which
failed before the fix. No green CI is claimed.

## 2. Warm-hit latency profile

Harness `benchmarks/repos/warm_hit_profile.py`: one 2.4 MB stdin, 25 interleaved warm runs per
shape, a fresh cache per shape (so no shape can read another stdout target's record), stage timers
from `TRACEJIT_PHASE_TIMING=1`. Full data in `benchmarks/results/phase2n/warm-hit/`.

| Shape | before (ms) | after (ms) |
| --- | --- | --- |
| native gzip → file | 250.22 | 251.67 |
| native gzip → /dev/null | 254.08 | 251.35 |
| tracejit → file | 17.41 | **12.79** |
| tracejit → /dev/null | 14.08 | **10.39** |
| tracejit `--json` → file | 85.24 | **61.86** |
| tracejit inside make (forced) | invalid\* | **17.74** |
| native make (forced) | 2.33\* | 258.91 |
| tracejit `run -- /bin/true` | 14.34 | **5.30** |

\* The first harness version let make consider the output up to date; the shape was fixed with a
`FORCE` prerequisite. The invalid row is kept because deleting a bad measurement silently is how
methodology errors survive.

Isolated A/B (`/tmp/tracejit-before` vs `88d528d`) with a fresh cache and 40/15/8 repetitions:
bare hit 7.82 → **4.73 ms**, gzip hit 17.62 → **9.62 ms**, `--json` hit 80.11 → **58.66 ms** and the
report shrank from 8,704,201 to 3,610,260 bytes.

After-profile stage medians for a gzip hit (ms): guard validation 4.97, process startup 5.77 (this
field is quantised by `/proc` start time at 10 ms ticks and is not trustworthy below that),
stdio replay 1.52, report presentation 1.44, SQLite open 0.22, schema 0.38, record decode 0.25,
query 0.22, identity 0.25, cache prepare 0.03, decision persist 0.0 (only the first hit persists).
`strace -f -c` shows **no fsync or fdatasync on a hit**; SQLite writes are WAL page writes.

### Why 4 ms became 30 ms

There is no 30 ms engine path. The difference is four measured effects:

1. The 4 ms figure came from the synthetic transform, whose inputs and stdout are tiny. Hit cost
   scales with the payload: hashing a 2.4 MB stdin alone is 4.6-5.0 ms.
2. The wrap experiment's 30 ms was per child of a real build: a 4.6 MB stdin to hash, a 1 MB output
   to restore, and a `make`/`sh` fork around each wrapper.
3. Its probes used `--json`, where pretty-printing the captured 1 MB stdout as a JSON byte array cost
   ~70 ms. That was reporting, not reuse.
4. Interleaving eight shapes with per-run phase files measured 17.4 ms where the same hit in
   isolation measured 10.9 ms: harness writes and cache churn, not TraceJIT work.

## 3. Implemented improvements (all justified by the profile)

1. `--json` now emits compact JSON. Same keys and values, 27% less hit time and 58% smaller report.
2. The human report is assembled and written once instead of one unbuffered `eprintln!` per line.
3. A hit under `--admission always` no longer reads and upserts the admission row. `always` never
   consults it and `never` never hits, so the sample was pure warm-path cost.
4. The SQLite schema batch (`CREATE TABLE`, `ALTER`, WAL pragma) runs once, selected by
   `PRAGMA user_version`; the schema and WAL mode are persistent.

No durability was traded: output restoration still verifies every CAS object and fsyncs staged files
before rename, and the hit path itself never wrote with fsync. Regression coverage is the existing
suite: 113 tests pass, including 36 `linux_integration` cases that reuse under the default `always`
policy with no admission rows, cache reopen tests that exercise the version stamp, and the
execution-fidelity matrix. Differential fuzzing seed 7: 120 cases, 120 ok, **0 incorrect hits**.

## 4. Developer-workload refusal matrix

`tracejit analyze --json` on real commands, native medians from 7 runs:

| Workload | native | class | first refusal | following blockers | saving if eligible |
| --- | --- | --- | --- | --- | --- |
| `cc -c -O2 hello.c` | 28.79 ms | Unknown | unmodeled syscall 98 `getrusage` (`as`, RUSAGE_SELF) | `getrandom` in `cc`/`cc1`/`as`, `prlimit64`, `sysinfo`, temp files | ~24 ms/TU |
| `cc -fsyntax-only hello.c` | 16.27 ms | Nondeterministic | `getrandom` | `prlimit64`, `sysinfo`, realtime clock | ~12 ms |
| `rustc --edition 2021 hello.rs` | not measured | Unknown | unmodeled syscall 7 `poll` | `/proc/self/maps`, `/proc/self/cgroup`, `statx`, 204 unmodeled effects | large, furthest |
| `python3 -m unittest pkg.test_util` | 56.68 ms | Unknown | `lseek` on inherited fd 0 (`/dev/null`) | with a regular stdin: `getpid`, `getrandom`, `getppid`, monotonic clock, `gettid`, realtime | ~52 ms/run |
| `python3 pkg/util.py` | 19.18 ms | Unknown | same fd 0 model | same identity/clock/randomness chain | ~15 ms |
| `python3 -m compileall -q pkg` | 47.73 ms | Unknown | same fd 0 model | same | ~43 ms |

The fd 0 refusal is an artifact of a `/dev/null` stdin: with an empty regular file the Python
workloads move straight to process identity, randomness and clocks, which are the same blockers as
the compilers. `getrusage` is not a frequency problem; it is the first effect that blocks the highest
value workload.

## 5. Attempted compatibility breakthrough: C compilation

Attribution with `strace -f -e getrusage,getrandom`:

- `as` calls `getrusage(RUSAGE_SELF)` once per assembly (`ru_utime` 3010 µs in one run, 3095 µs in
  the next: values change every run).
- `cc`, `cc1` and `as` each call `getrandom(..., 8, GRND_NONBLOCK)` once, returning different bytes
  every run.

An exact-value guard therefore cannot match across runs, and ignoring these reads would violate the
contract: compiler output can contain them (`-ftime-report`, generated random seeds). `prlimit64`
values are stable and could be guarded, but they are not the first refusal and unblock nothing on
their own; `sysinfo.freeram` is mutable and cannot be pinned. `rustc` additionally reads
`/proc/self/maps`, `/proc/self/cgroup` and `statx` 204 times in unmodeled ways.

**Conclusion: no sound whole-command reuse exists for `cc`, `rustc` or `python3` startup under V1's
model.** The safe implementation is to refuse, which is what happens. The concrete alternatives are
(a) an explicit determinism contract that virtualises these reads (fixed epoch, zeroed rusage, seeded
randomness) and is labelled as changing timing introspection, or (b) an input-keyed compiler cache
such as ccache/sccache. Neither is whole-command reuse; both are outside this phase's mandate.
ccache and sccache are not installed here, so no specialist baseline could be produced. Next most
promising workload: none of the examined ones is nearer than C `-c`, and it fails on irreducible
nondeterminism, so no further handler is attempted.

## 6. Real-repository measurements

`real_sessions.py` with pristine trees and the standard configure/build/edit/test workload; native
`direct` and `never` bracket environmental noise. Binary `88d528d`, policies direct/never/always/auto.

| Repository | session | direct | never | always | auto | valid |
| --- | --- | --- | --- | --- | --- | --- |
| zlib 51b7f2a | n1 | 2591.05 ms | 2788.96 (0.929x) | 5982.52 (0.433x) | **2186.72 (1.185x)** | yes |
| zlib | n3 | 2628.26 | 2713.38 (0.969x) | 5637.10 (0.466x) | **2193.55 (1.198x)** | yes |
| bzip2 6a8690f | n1 | 3645.60 | 3732.93 (0.977x) | 4967.83 (0.734x) | 3515.10 (1.037x) | yes |
| bzip2 | n3 | 3503.28 | 3566.72 (0.982x) | 4849.90 (0.722x) | 3456.03 (1.014x) | yes |
| libpng ed217e3 | n2 | 9329.74 | 9518.08 (0.980x) | 31869.46 (0.293x) | 9908.97 (0.942x) | yes |
| lz4 5ff8396 | n2 | 14849.13 | 15182.71 (0.978x) | 20041.89 (0.741x) | 15511.68 (0.957x) | yes |

All arms produced identical artifacts. Cache-hit coverage is unchanged: zlib compression and
decompression, bzip2 compression and decompression, nothing under libpng `auto` (its only eligible
command is 7 ms and is declined), and nothing for lz4 (`NONDETERMINISTIC`).

Against Phase 2M at the same host and commits: zlib `auto` 1.173/0.970 → 1.185/1.198, bzip2
0.980/0.976 → 1.037/1.014. The improvement is modest end to end because the build dominates and the
`never` control already spans 0.929-0.982. The large, repeatable gain is the 30-45% reduction in hit
latency, which is 400 ms per zlib session and 130-190 ms per bzip2 session in cumulative cached work.

Limitations: one session per repository this phase (two for zlib/bzip2), fixed policy order, shared
8-vCPU VM, and peak RSS unavailable. `rustc` was not timed meaningfully (the direct invocation used
an absolute path that exited 126); its analysis result is still valid.

## 7. `tracejit wrap` evaluation

Not implemented. `tracejit run` already is the transparent wrapper: it inherits stdin, forwards the
child's stdout, stderr and exit status, and requires no engine change. A `wrap` subcommand would only
default `--admission auto`, which is ergonomic but adds a second command surface without capability;
the measured obstacle is eligibility, not invocation. The compact `--json` change does make existing
wrapper-style use cheaper. Revisit `wrap` only if users ask for a default-auto alias.

## 8. Enforcement and correctness

Unchanged: seccomp standalone install with `no_new_privs`, Landlock path untouched, controlled
allocator entropy still opt-in, `PROVEN` blocked until verified on a Landlock-capable runner.
Process-tree storms, descriptor regressions, the 14-workload fidelity matrix, fmt, Clippy and the
workspace suite all pass; the differential fuzzer found 0 incorrect hits in 120 cases.

## Reproduce

```bash
cargo build --workspace --release
python3 benchmarks/repos/warm_hit_profile.py --iterations 25 \
  --output-dir benchmarks/results/phase2n/warm-hit
python3 benchmarks/repos/real_sessions.py --session n1 --repos zlib,bzip2 \
  --policies direct,never,always,auto --output-dir benchmarks/results/phase2n/sessions
python3 benchmarks/differential/fuzz.py --seed 7 \
  --output benchmarks/results/phase2n/fuzz-seed7.json
```
