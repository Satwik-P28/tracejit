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

## Current state (end of Phase AF)

- `origin/main` tip: `68ba406`, the merge of PR #44 (`research/phase-ab`).
- Phase AF work is on `research/phase-af`, branched from `b81242d`.
- PR #45 is open. Its head was verified as `b81242d` with four successful workflows (push CI
  `45573894337`, PR CI `45573903654`, benchmark v2 `45573903647`, environment `45573903708`).
- Version under qualification: **`0.3.0-alpha.1`**, a research prerelease. The published beta
  `v0.2.0-beta.1` (`7a594b9`) is untouched and is not replaced.
- Enforcement was qualified on a Landlock ABI 8 host in Phase AF, including enforced reuse; the
  earlier "no Landlock anywhere" statements were true only of the hosts they named.
- The authoritative contract is `docs/FINAL_CORRECTNESS_CONTRACT.md`; the phase summary is
  `docs/PHASE_AF_REPORT.md`; release evidence is `docs/RELEASE_QUALIFICATION_V03.md`.

## Phase AF (from `b81242d`)

- Enforcement lifecycle qualified end to end on a capable host: GUARDED → `PROVEN` → Reused
  `PROVEN` → mutation → deopt → `PROVEN`. Producer-style commands still cannot reach `PROVEN`.
- Four sandbox policy tests plus two integration regressions added; `PROVEN` redefined in public
  docs as "the policy was installed and the execution observed under it", not as an equivalence
  proof.
- Publication tables are generated from raw evidence (`benchmarks/phase_af/build_tables.py`,
  8 tables, 10 integrity tests); no benchmark number in the paper is transcribed by hand.
- Claims corrected: 5.22× / 80.84% for the bzip2 session against native, Firebuild 3119.4 ms as an
  applicability baseline only, four explicit break-even definitions, and the 95 ms replay figure
  restated as a serial cost model rather than a lower bound.
- `scripts/phase_k4_restore_fault.sh` repaired: its fault hooks are environment variables, and the
  environment is part of the cache key, so the old version never reached the restore path; the
  cache also lived inside the observed directory. The soft-fail scenario now proves it reached
  `restore_outputs`; the hard-kill scenario reports `SKIP` here.
- `0.3.0-alpha.1` packaged, installed from the archive, and qualified; nothing published.

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

## Phase AE (`research/phase-ad`, from `98cbb84`)

- Corrected Phase AD's measurement defects: cold-inclusive and steady-state sessions are now
  separate; every invocation carries its own engine decision, exit status, output oracle and
  cache size; break-even is `ceil((C-H)/(D-H))` with a floor of 2; cache footprint and peak RSS
  are measured per arm and defined (`docs/PHASE_AE_REPORT.md`).
- Firebuild 0.8.2 (pinned debs) and 0.8.6.2 (pinned source build) both measured. 0.8.6.2
  **does** cache `gzip -k` (1.67× faster than TraceJIT there) and still refuses `bzip2 -k`;
  `docs/FIREBUILD_CROSS_VERSION_RESULTS.md`.
- Phase AD's "Firebuild performs unvalidated reuse" claim is **retracted**: Firebuild validates
  recorded inputs by content hash at reuse. Two measured distinctions survive: default Firebuild
  replays stale clock output, and it replays a corrupted cached blob
  (`docs/COMPETITIVE_EVIDENCE_AUDIT.md`).
- Two userspaces on one kernel (glibc 2.39 guarded reuse works; glibc 2.42 correct but no reuse
  because `allocator-entropy-v1` is libc-build specific); no Landlock anywhere, so `--enforce`
  never reuses and never labels `PROVEN` (`docs/MULTI_ENVIRONMENT_VALIDATION.md`).
- TOCTOU corrected: one surviving validation pass; a mutation after it serves stale bytes. The
  race is measured, not assumed (`docs/TOCTOU_CORRECTNESS_BOUNDARY.md`).
- Verified replay profiled against measured bounds; no product optimisation promoted
  (`docs/VALIDATED_REPLAY_PERFORMANCE.md`).

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
- Firebuild evidence is version-, configuration- and host-specific: 0.8.2, 0.8.6.2, default /
  tuned / strict, Linux 6.1.102, one operator. 0.8.6.2 caches `gzip -k` and not `bzip2 -k`.
- Reuse on an unaudited libc is unavailable for malloc-using programs; `allocator-entropy-v1`
  is admitted only for the audited 2.39 build.

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
