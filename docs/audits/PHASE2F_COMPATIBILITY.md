# Phase 2F: compatibility, measurements and the `getrandom` wall

This phase implemented three dependency models and fixed two soundness defects. It did **not** reach
the mission's primary target of two additional reusable workload categories. This report states
what changed, what is measured, and exactly why the target is unmet.

All figures are from the final code commit `be94f38` unless a raw artifact is explicitly attributed
to `5db741f`. Raw data: `benchmarks/results/phase2f/`.

## 1. Implementation commits

| Commit | Content |
| --- | --- |
| `5db741f` | `statfs`/`fstatfs`, directory enumeration byte streams, inherited regular-file stdin, `creat`, credential + access-mode hardening of `DirectoryOpened`, narrowed `lseek`, CLI `explain` kinds |
| `be94f38` | `..` resolved through symlinks before recording (`normalize_join`) |

## 2. Compatibility, unchanged denominators

Direct-execution suite (16 workloads, no shell, fixed denominator), 5 runs per workload, two
independent sessions started from a clean tree:

| Session | Reused | Output equivalent | Result |
| --- | ---: | ---: | --- |
| session-a | **1 / 16** (`gzip`) | 16 / 16 | PASS |
| session-b | **1 / 16** (`gzip`) | 16 / 16 | PASS |

Nine-workload historical census (unchanged denominators), 3 runs with 1 warmup:

| Session | Eligible | Refused | Execution failures | Output equivalent |
| --- | ---: | ---: | ---: | ---: |
| census-a | **0 / 9** | 9 | 0 | 9 / 9 |
| census-b | **0 / 9** | 9 | 0 | 9 / 9 |

Both are identical to Phase 2E. Per-workload decisions did not change: `sed`, `tar` and `tr` moved
from their old blockers to `getrandom`; `grep` remains `Unknown` at `/proc/self/maps`; the Python
workloads remain `Nondeterministic`.

## 3. The refusal chains after the new models

Captured with `explain` at `5db741f` (`benchmarks/results/phase2f/explain-*.txt`):

| Workload | Old first refusal | New first refusal | New dependency visible |
| --- | --- | --- | --- |
| `sed` | `statfs` | `getrandom` | `FSSTAT /sys/fs/selinux` |
| `tar` | `statfs`, enumeration | `getrandom` | `FSSTAT`, `DIRLIST` |
| `tr` (regular-file stdin) | inherited descriptor | `getrandom` | `STDIN /tmp/.../in.txt [0..375762]` |
| `nm` | enumeration | `getrandom`, `prlimit64` | `DIRLIST .../bfd-plugins (4 calls)` |

The specific blockers the phase targeted are gone. Each command now stops at allocator entropy.

## 4. The `getrandom` finding

This is the central result of Phase 2F and the reason the target is unmet.

Every candidate surveyed — `sed`, `tar`, `tr`, `nm`, `ar`, `grep`, `sort`, `base64`, `md5sum`, `wc`,
`jq`, `strip`, `perl`, `make`, `groff`, `zip`, `unzip`, `gcc`, plus the rest of the direct suite —
calls `getrandom` before main-line work, from **inside the C library allocator**:

```
getrandom(8, GRND_NONBLOCK)
  <- libc timer_settime+0x1079
  <- malloc+0x215
  <- textdomain / freelocale / __duplocale
  <- setlocale
```

glibc seeds its per-thread cache/allocator state from the kernel random pool on first use. The
value perturbs pointer addresses and allocator layout, which a program can observe through
`malloc`-returned addresses, hash-table iteration order, or output that embeds addresses. It is not
"entropy that cannot affect output"; it is unguarded mutable process state that the brief
explicitly forbids ignoring.

Attempts made, all negative:

- `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `glibc.malloc.tcache_max=0` — the call remains.
- Preloading or intercepting `getrandom` — would change the program's execution, which is not
  transparent reuse, and would not prove the value unobservable.
- Treating the call as internal because glibc "only" uses it for layout — this is precisely a global
  whitelist of a nondeterministic syscall, forbidden by the brief and unsound in general.

`gzip` is the exception: its file-to-stdout path does not reach the allocating locale path, which is
why it remains the only reusable workload. `gzip -dc` (stdin) does not.

**Consequence:** the two-additional-category objective is **unmet**, and the blocker is not a missing
syscall handler. It requires either (a) a defensible execution contract that pins libc allocator
state across tracing and reuse, or (b) a sound noninterference argument for the specific read, or
(c) a different class of workload that does not use glibc's locale/allocator setup (a static or
musl binary, or a direct-syscall program). Option (c) is the most tractable and is the recommended
next experiment; it is not claimed here because it was not implemented or measured.

## 5. Performance at `be94f38`

Direct suite, 5 runs, 20 000-line text input, `gzip -9 -c` (the only reusable workload):

| Session | Direct median | Direct p95 | Warm hit median | Warm p95 | Cold traced | Speedup | Saved per hit | Hits to repay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| session-a | 28.89 ms | 29.16 ms | 4.33 ms | 7.23 ms | 40.79 ms | 6.67x | 24.56 ms | 0.48 |
| session-b | 29.00 ms | 29.03 ms | 4.06 ms | 6.96 ms | 42.49 ms | 7.14x | 24.94 ms | 0.54 |

Tracing penalty (cold − direct): 11.90 ms and 13.49 ms. The warm hit is ~4.2 ms and includes CLI
startup, guard validation, output restoration and the cache lookup; the three components are **not
separately instrumented**, so no per-component attribution is claimed. There are no invalidations in
these sessions (the only reusable workload has none), and no new workload contributes a measurement,
because none reached `Reused`.

Cache footprint: not separately instrumented. The raw result directory is 428 KB; the per-entry CAS
size for this workload was not measured in this phase and is not estimated here.

### Earlier session, same code family (`5db741f`)

For comparison with Phase 2E (same 20 000-line payload, 5 runs): session-a direct 30.01 ms / warm
3.95 ms / cold 42.33 ms / 7.60x / 0.47 hits; session-b direct 28.94 / warm 4.03 / cold 46.95 /
7.18x / 0.72 hits. The difference between the two commits is within this VM's variance; `be94f38`
changes only `..` path resolution, which this workload does not use.

## 6. Verification

- `cargo fmt --all -- --check` — clean.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` — clean.
- `cargo test --workspace` — **100 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 26 Linux
  integration + 7 core + 5 effects + 24 guards + 4 sandbox + 13 trace).
- Direct suite and census as above, both sessions PASS / 0 failures.
- Adversarial coverage: capacity-field mutation invalidates `statfs`; a new directory entry
  invalidates enumeration; a different stdin file is refused; `O_PATH` replay without read
  permission succeeds; a credential-less directory record is refused.
- `PROVEN`/Landlock: **BLOCKED**. This host is kernel 6.1.102 with LSM `capability,selinux` and no
  Landlock, so the enforcement path was not executed and is not claimed. No skipped test is reported
  as a pass.

## 7. Reproduction

From the repository root at `be94f38`:

```bash
cargo build --workspace --release

python3 benchmarks/realworld/direct_suite.py --runs 5 \
  --output-dir benchmarks/results/phase2f/session-a
python3 benchmarks/realworld/direct_suite.py --runs 5 \
  --output-dir benchmarks/results/phase2f/session-b

python3 benchmarks/realworld/census.py --runs 3 --warmups 1 \
  --output-dir benchmarks/results/phase2f/census-a
python3 benchmarks/realworld/census.py --runs 3 --warmups 1 \
  --output-dir benchmarks/results/phase2f/census-b
```

`explain` artifacts were captured at `5db741f` from the cache produced by tracing `sed`, `nm` and
`tr`; the rendered lines are stable, but the recorded `DIRLIST` path now canonicalises
`/usr/bin/../lib/...` to `/usr/lib/...` after `be94f38`.

## 8. Remaining correctness limitations

1. **Allocator entropy** blocks glibc-linked workloads (see §4). No model exists in this tree.
2. **`/proc/self/maps`** still refuses `grep`; process memory identity is unmodelled.
3. **`getrusage`** still refuses compilers/assemblers; per-run consumption cannot be guarded.
4. **`prlimit64`** appears in `nm`'s chain after `getrandom`; not modelled.
5. **Mount-namespace changes after a path open** are not modelled for path guards (documented in the
   directory audit); `statfs` and enumeration do bind namespace identity.
6. **Enumeration is capped at 1 MiB** and refuses a non-zero start offset; large trees are refused.
7. **Validation-to-restore TOCTOU** applies to every guard; restoration is not crash-atomic.
8. **`PROVEN` has never executed**, here or on any host used so far.

## 9. Phase 3 readiness

Not ready for performance engineering as the primary focus, for one measured reason: there is
exactly one reusable workload, so guard-cost optimisation would be tuned to `gzip` alone. The
measured warm hit is already ~4.2 ms against 28.9 ms direct on a 20 000-line input, and ~4 ms
against 1 500 ms on the Phase 2E large input, so guard validation is not the dominant cost for
non-trivial work; process startup and cache I/O are.

The dominant restriction is the **deterministic execution contract**, not guard speed. The first
experiment should therefore be a workload class that avoids glibc's allocator entropy (static/musl
binary or direct-syscall tool) measured end to end; if that produces a second and third category,
Phase 3 should profile the hit path across those categories before choosing between faster
validation, lower ptrace overhead, and cache-admission changes. No research contribution is claimed:
the enumeration byte-stream replay and the all-field `statfs` comparison are engineering choices
justified by observation, not novel mechanisms, and no comparison against prior art was run in this
phase.
