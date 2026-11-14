# Project state

## Thesis

Infer observable dependencies of an unmodified Linux process and reuse computation only when safety is enforced. Fail closed. Correctness beats performance.

## Safety invariants

- Reuse only `PROVEN` and `GUARDED`. `UNKNOWN`, `NONDETERMINISTIC`, and `EMPIRICALLY_STABLE` never reuse in V1.
- `PROVEN` requires seccomp plus Landlock ABI 3+ actually installed.
- Every guard must pass before cached stdout, stderr, exit status, or files are exposed.
- Writable file-backed `MAP_SHARED` is `UNKNOWN`. vDSO time is redirected or `UNKNOWN`.
- Uncertainty fails closed. Do not weaken safety for benchmarks.

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`  
Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards.

## Current main

- Tip: `29718cf55b7a9c937bd0c9147dfc650fbd2498f2` — Phase 3H/3I descriptor P0 merge (PR #8).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Hosted CI `validate` on `29718cf`: success (run `43380851411`).

## Reconciliation (2026-11-14)

| PR | State | Decision |
| --- | --- | --- |
| #4 Phase 3B | closed, merged | Keep |
| #5 Phase 3C | closed, merged | Keep |
| #6 Phase 3D retrieval | closed draft, **unmerged** | Reject; isolate |
| #7 Phase 3E epoll | closed draft, **unmerged** | Reject; isolate |
| #8 descriptor P0 | closed, merged | Keep |
| #9 controlled Python research | open draft | Reject for main |
| #10 Python v2 / hash-cache research | open draft | Reject for main |

Landed correctness: `/dev/null` read fstat identity (3F), inherited fd>2 refusal (3G), enumeration fail-closed + `dup2(fd,fd)` + dirent forget-on-reuse (3H/3I).

## Phase B stabilize (branch `cursor/phase-b-stabilize-1841`)

- Post-`Cache::open` inherited-descriptor re-scan so non-CLOEXEC cache fds cannot bypass the preflight.
- Regression: `cache_open_descriptors_are_close_on_exec`.
- Removed unused workspace dependency `tracing`.
- Phase A artifacts (store): `docs/reconciliation-report.md`, `docs/defect-register.md`, `internal/baseline-report.json`.

## Local baseline on audit host (ABI 6 Landlock)

Mandatory gates passed at `29718cf`: fmt, clippy `-D warnings`, **151** workspace tests, **53** linux_integration (including `proven-reuse PASS`), release build SHA-256 `f0ff68e83927306d35358c38bdb09fc48ab19686033ad92000f43bfe7de797e9`, `./scripts/demo.sh`. Soft-skip: sandbox unit `enforcement_refuses_when_landlock_is_absent` early-returns when Landlock is present (cargo `ok` ≠ proof of the absent-Landlock path).

## Benchmarks (do not invent)

- Committed short-command loss: `benchmarks/results/latest.md` at `63e33638709aacfaed896ab587435e64c0ecea62` (C ETL 7.396 ms → 7.957 ms, 0.929468x).
- Known-good transform/sweep commit: `e9684c1c01a7bbbab4cae50e2389105596d613f1`.
- Native real-workload census remains refuse-heavy; reusable wins are narrow (e.g. guarded gzip / controlled contracts). Research Python speedups are **not** native equivalence.

## Still isolated / not ready for main

- Phase 3D two-stage retrieval (no general win).
- Phase 3E epoll (incomplete fork/exec/`RLIMIT_NOFILE`/transfer obligations).
- Controlled CPython contracts (semantic counterexamples; keep draft).
- Multi-output restore remains pathname-visible under hard kill (documented limitation).

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```
