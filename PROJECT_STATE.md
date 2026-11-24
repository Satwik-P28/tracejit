# Project state

## Thesis

Infer observable dependencies of an unmodified Linux process and reuse computation only when safety is enforced. Fail closed. Correctness beats performance.

## Safety invariants

- Reuse only `PROVEN` and `GUARDED`. `UNKNOWN`, `NONDETERMINISTIC`, and `EMPIRICALLY_STABLE` never reuse in V1.
- `PROVEN` requires seccomp plus Landlock ABI 3+ actually installed.
- Every guard must pass before cached stdout, stderr, exit status, or files are exposed.
- Writable file-backed `MAP_SHARED` and anonymous `MAP_SHARED` are `UNKNOWN`. vDSO time is redirected or `UNKNOWN`.
- Path guards replay the pathname the process passed (no lexical `..` collapse). Uncertainty fails closed.
- Controlled execution (`--contract`) is a separate tier: its results are reproducible under that contract and are never mixed with native records.
- A status-flag rewrite is admitted only when it changes `O_NONBLOCK` alone, on a regular file this process opened, before it created any child.
- A descriptor-flag query is process-local only for a description this execution created; on an inherited descriptor the flags belong to whoever started us and are not guarded, so the query refuses.
- Admission (`--admission`) is an economic pre-trace decision only; it can never promote a record, bypass a guard, or change a classification.

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`
Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards.

## Current main

- `origin/main` tip while Phase AD was written: `68ba406` (Phase AC is **not** merged).
- Published beta: tag `v0.2.0-beta.1` at `7a594b9`. v0.3 remains **not qualified**.
- PR #44 (`research/phase-ab`) is open, **draft**, head `3f054ed`, CI green on that head. Phase AD
  branched from that verified head and preserved its corrections rather than dropping them.

## Phase AC (correctness recovery, output semantics, non-compiler workloads)

- PR #44's `tar-create` cold mismatch was a **benchmark fixture defect**: twins prepared at
  different wall-clock times, and `tar` serialises member mtimes. 81/120 reproduced, 0/200 after
  preparing once and cloning with metadata preserved; the harness now gates on a pre-state
  metadata comparison.
- Restored outputs keep their **recorded** mtime, so a `make`/`ar` chain can skip an archive
  update (reproduced on Lua 5.4.6 + zlib 1.3.1). Kept deliberately (`docs/OUTPUT_RESTORE_SEMANTICS.md`).
- Field-precise metadata guards audited and **not** adopted; a 9-mutation matrix shows the
  conservative guard is load-bearing.
- Non-compiler niche is real but narrow: `bzip2`/`gzip` on multi-megabyte artifacts, `sed` on
  large text (n=25 savings 85 %/65 %/51 %). `xz`, `tar`, `sort`, `awk`, `perl` refuse.

## Phase AD (`research/phase-ad`, based on `3f054ed`)

- Firebuild 0.8.2 (pinned Ubuntu debs, user prefix, no root) compared on this host: it does not
  cache timestamp-preserving file-output commands (`gzip -k`, `bzip2 -k`, `objcopy`) and it
  replays clock-dependent commands by default (`ignore-time-queries`) while TraceJIT refuses
  them. TraceJIT's artifact niche is 3–64× faster than native and faster than Firebuild; tuned
  Firebuild beats TraceJIT on `sed` and cheap stdout filters (`docs/FIREBUILD_COMPARISON.md`).
- Authentic artifact scale (Linux 6.6.50 archive, 1/10/100 MiB): integer break-even 2 for every
  compression workload, "never" for hash-only work ≤10 MiB, 9 at 100 MiB
  (`docs/ARTIFACT_BENCHMARKS.md`).
- Descriptor audit: `tar` blocks on inherited `F_GETFD` plus a realtime clock read and a socket
  control; `xz` blocks on `F_SETFL(O_NONBLOCK)` on its own pipes. Promoting inherited `F_GETFD`
  is sound but changed 0/48 census cells, so it was reverted; a unit test pins the refusal
  (`docs/INHERITED_DESCRIPTOR_SEMANTICS.md`).
- Admission audited (24-step mixed session: `always` 1229 ms, `auto` 1285 ms, `never` 1663 ms,
  direct 1639 ms, oracle 653 ms). No production change (`docs/ECONOMIC_ADMISSION.md`).
- TOCTOU window unchanged; no Landlock here (`capability,selinux`), so `PROVEN` is unenforced.
  Full report: `docs/PHASE_AD_REPORT.md`. Paper verdict **B**.

## Known limitations

- Metadata guards include `accessed_ns`, which the traced command's own reads update. Commands
  that `stat` before reading (`strip`, `objcopy`, `unzip`) classify `Guarded` then deoptimise.
- Cache-hit fixed cost is ~11 ms plus ~6 ms of strict hashing; commands under ~15 ms are net
  losses on a hit, which is what `--admission auto` exists for.
- Large-output restoration dominates big outputs; reflink is unavailable on ext4.
- Multi-output restore: single-path rename atomic; soft rollback verified; hard-kill is not
  crash-atomic. Restore-intent refuses the next HIT.
- Validate→restore TOCTOU residual remains; guards run once, immediately before the restore.
- `rustc` needs `statx`, `prctl`, create-only `eventfd2` and a procfs decision before eligibility.
- Landlock is unavailable on this host, so `PROVEN`/sandbox tests SKIP.
- Firebuild evidence is version- and host-specific (0.8.2, Linux 6.1.102); 0.8.6 may cache
  timestamp-preserving outputs.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --test-threads=4
cargo build --workspace --release
python3 scripts/modelcheck/check_state_machines.py
python3 benchmarks/realworld_v2/test_harness.py
bash scripts/phase_k4_restore_fault.sh
python3 benchmarks/realworld_v2/runner.py --tracejit target/release/tracejit --mode both \
  --policies native,compiler-runtime-v1 --splits dev --reps-scale 0.25 --output-dir /tmp/smoke \
  --vendor /tmp/ac-vendor
```

Historical phase narratives live in `docs/PHASE_*_REPORT.md`; gate evidence in
`benchmarks/results/`.
