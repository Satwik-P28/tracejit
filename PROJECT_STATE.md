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

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`
Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards.

## Current main

- `origin/main` tip: `fc82b3a`. Published beta: tag `v0.2.0-beta.1` at `7a594b9` (merge of `release/v0.2.0-beta.1` into `main`; `origin/main` was not advanced past the release merge point in this workspace's refs).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`), `v0.2.0-beta.1` (`7a594b9`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated from `main`.

## Development line (`development/v0.3`, Phase U)

- Cut from `7a594b9`; **not merged, not released, no version bump**.
- Native reuse eligibility is unchanged from the beta (1/31 on the original census, 0/20 held out). The phase's finding is that the remaining refusals are genuine nondeterminism, not model gaps.
- Contract tier (`--contract allocator-entropy-v1`): 7/31 original, 8/20 held out.
- New models: null device by device identity, create-only epoll, `O_NONBLOCK`-only status-flag rewrites, identity-guarded `prlimit64` queries, negative-descriptor `EBADF`, `TCGETS` on internal pipes.
- New corpus: `benchmarks/realworld/census_v03.py` (20 held-out workloads).
- Docs: `docs/COMPATIBILITY_V03.md` (blocker analysis, accepted/rejected models), `docs/PHASE_U_REPORT.md`.
- Evidence: `benchmarks/results/phaseu/`.
- Harness (Phase U2): no descriptor in the shared test process is modified. Each spawn marks its
  own forked child's descriptors `FD_CLOEXEC` with one `close_range` call in `pre_exec`, and
  `invoke_inheriting` is the only way to hand TraceJIT a deliberately inherited descriptor. A
  regression re-executes the binary with 142/145/1500 inheritable to reproduce the CI condition.
  Production is unchanged (release binary byte-identical).

## Research line (`research/phase-w`, from `cb4783f`)

- The two-deoptimisation penalty after an input edit was **record construction**, not the contract.
  The tracer's own pre-`unlink`/pre-`rename` snapshot was recorded as an ordinary `Read(File)` input
  dependency, so every record was pinned to the bytes it destroyed (the object `cc` replaces).
  `FileRead`/`FileMetadataRead` now carry `prestate_snapshot`; `reconstruct_dependencies` drops such
  a snapshot only when the same execution recreates the path (its last write is not `Delete`). A
  path deleted for good keeps the exact content guard. Old records deserialize as program reads.
- Measured: 27-invocation rebuild session 13.544 s → 9.239 s (`main` → candidate, native 14.774 s),
  1.09× → 1.60×; one deopt per edit instead of two. `docs/PHASE_W_REPORT.md`,
  `benchmarks/phase_w/{transitions,session}.py`, `benchmarks/results/phasew/`.
- Competition, measured: ccache 5.371 s and sccache 5.860 s on the same 27 invocations. TraceJIT's
  whole-command contract cannot beat a compiler-specific cache on compile workloads; the report says
  so explicitly.
- Revisiting an earlier *input state* still deoptimises for `cc`, and correctly so: gcc `stat`s its
  header (PCH probe) and that metadata-only guard has no content fallback. The barrier is the
  compiler's own observation, not candidate selection (records are retained per identity).
- Rejected: parallel guard validation (8 threads hashed 45.7 MB in 15 ms instead of 30 ms, but the
  354-guard sequential walk dominated; 111.7 → 110.6 ms median). Reverted.
- New tests: `superseded_delete_does_not_pin_the_next_run_to_the_old_bytes`,
  `terminal_delete_still_requires_the_deleted_bytes`, and three dependency unit tests.

## Research line, Phase W1 audit (`research/phase-w`)

- Independent audit of the elision rule found one unsound case and repaired it: the **source** of a
  `rename` is content that moves into the destination output, not pre-state that disappears. When
  the program moved an object aside and re-created it (`mv out.o out.o.bak`), both snapshots were
  elided and a warm run restored the *previous* object bytes into the backup name — an incorrect
  HIT, reproduced end to end. `record_snapshot` now records the rename source as an ordinary
  content read; the destination stays superseded pre-state, and `delete` is unchanged.
- Adversarial matrix `benchmarks/phase_w1/audit.py` (13 cases, native vs warm): successful/failed
  unlink and rename, rename destinations, partial execution, terminal delete,
  delete→create→delete, multiple writes, program reads, symlink and hard-link aliases, replaced
  inode. 13/13 observationally equal to native, 0 incorrect hits; `docs/PHASE_W1_AUDIT.md`.
- Regression: `rename_source_bytes_are_an_input_even_when_the_source_is_recreated`, plus two
  dependency unit tests (destination elided, legacy records without the marker stay strict).
- Re-measured after the repair: 27 invocations 14.714 s → 10.164 s (1.02× → 1.48× native),
  48 invocations 17.298 s → 13.748 s (1.58× → 1.98×); 12 → 6 deoptimisations in both,
  one per edit. ccache/sccache/make/ninja remain faster (5.0–6.0 s). No version bump.

## Research line, Phase X (`research/phase-x`, from `c720112`)

- Guard validation was measured, not guessed: `TRACEJIT_GUARD_PROFILE=1` reports per-kind counts,
  `stat`/`open`/`read`/`readlink`/access/directory-probe counts and time, bytes hashed, and a
  breakdown per validation pass (`crates/tracejit-guards/src/profile.rs`). A compiler warm hit
  interpreted 389 guards **twice** (56.1 ms + 49.7 ms), hashing 107.2 MB per pass.
- Accepted: the initial candidate check and the pre-restore recheck were the same work. A candidate
  is now validated **once**, immediately before the output restore, with the same typestate gating
  cached streams. Paired warm hits 116.7 → 67.3 ms (**1.73×**); 27-invocation session 9.44 → 8.67 s,
  48-invocation 12.53 → 9.94 s; identical decisions, objects byte-identical to native.
- Rejected with evidence: per-pass digest sharing (107 MB → 43 MB, another 1.5×) is unsound — a
  same-size rewrite inside one timestamp tick leaves mtime/ctime/size identical, so a cached digest
  yields a false HIT. The counterexample is now a permanent regression; ccache documents the same
  hazard and refuses to cache on too-new timestamps. Also rejected on measurement: batched
  `statx`/`io_uring` (metadata is 0.52 ms of 43.5 ms) and dependency-plan compilation (91 % of the
  pass is `read`+BLAKE3). `inotify`/`fanotify` invalidation stays research-only.
- Remaining hit cost is contract: 39.5 ms of hashing for 107 MB, of which 66 MB is the same compiler
  read three times under different guard kinds; 8.3 ms of process start-up; 2.4 ms of candidate
  decode (records carry their effect list). `docs/PHASE_X_REPORT.md`.

## Phase X1 audit (`research/phase-x`, from `e8abc16`)

- Single-pass validation audited: the removed pass could only reject executions that matched at the
  pre-restore pass but not earlier, and the one newly accepted class (an input changed and put back
  before the surviving pass) is safe because every guard is a state predicate. Argument, hit-path
  state machine and the 16-row adversarial matrix: `docs/PHASE_X1_AUDIT.md`.
- Fixed: a missing CAS object was a fatal error for a command that succeeds when simply re-run (now
  deopts and retraces; `get_bytes` maps `ENOENT` to `CorruptObject`). Also fixed: the guard profiler
  did not reset its counters in `take()` and used unsigned deltas that could underflow (now
  `swap(0)` plus saturating deltas).
- CI flakiness: two *different* steps have failed on runners whose published annotation is the
  audited glibc build (`2.39-0ubuntu8.9`) while sibling runs of the same tree passed — #254 (`Tests`,
  the two allocator-entropy tests) and #259 (single-threaded integration, test name not public). The
  contract tests now assert the documented refusal when the runtime is unaudited; `ci.yml` publishes
  the runner's libc build ID and annotates a failing integration test by name. #259's root cause is
  unresolved (no public log) and recorded as runner-side resource sensitivity, not a product defect.
- Re-verified here: paired warm hit 126.5 → 79.2 ms (**1.60×**), 27-inv 8.40 → 6.66 s, 48-inv
  12.44 → 10.60 s; ETL 1.16×, `true` 1.35×, `sort-small` 1.07×. Gates: 241 tests, integration 75/75
  at 1/2/4/8 threads and 10/10 default runs, fuzz seed 29 (0 incorrect hits), model check, fault
  injection, audit clean. Phase Y plan: `docs/PHASE_Y_RESEARCH_PLAN.md` (fs-verity first).

## Research line, Phase Y (`research/phase-y`, from `6bab00b`)

- Question: can a warm hit replace 105 MB of dependency hashing with an equally defensible proof of
  content identity? **Design sound, mechanism absent, nothing promoted.** Report
  `docs/PHASE_Y_REPORT.md`; matrix `docs/VERITY_CAPABILITY_MATRIX.md`; ledger `docs/PHASE_Y_LEDGER.md`.
- fs-verity is the only per-file, constant-time, unprivileged-to-observe content identity on Linux,
  and this host has none of it: `CONFIG_FS_VERITY` is unset and the ext4 root has no `verity`
  feature, so `FS_IOC_MEASURE_VERITY` returns `EOPNOTSUPP` (a mis-numbered request returns `ENOTTY`).
  `scripts/phase_y_verity_probe.py` reproduces this; no verity-capable guest was reachable (no root,
  no `CAP_SYS_ADMIN`, `/dev/kvm` group-restricted, ext4 is not `FS_USERNS_MOUNT`).
- Added `Guard::VerityContentIdentity` (pinned kernel digest + BLAKE3; `Proven` / `Contradicted` /
  fall-back-to-hash), a pure decision function, a `doctor` capability line and 12 regressions. It
  never becomes a metadata-only check: without a kernel answer it hashes, at 493 ns of ioctl each.
- Cost ledger: `cc1` is hashed **3×** per compiler pass and is **87 %** of the 105,031,035 content
  bytes (56 guards, 41.3 MB distinct, 2.545× redundant, ≈47.4 ms) — the redundancy Phase X proved
  unsound to remove and fs-verity would make sound. Promotion rejected on gates 4 and 5 (no
  measurable gain, ~0 applicability). No-regression measured instead: ETL 0.987×, `true` 0.996×.
- Compiler warm hits no longer reproduce here: glibc moved from the audited `2.39-0ubuntu8.9` to
  `2.39-0ubuntu8.12`, so `allocator-entropy-v1` refuses and the 48-invocation session is 48 misses on
  both arms — direct evidence that the audited profile goes stale.
- Gates: 253 tests, integration 75/75 at 1/2/4/8 threads, fuzz seed 29 (0 incorrect hits), model
  check, fault injection, `cargo audit` clean. CI run #264 on `da48bae`: success. Its runner is also
  glibc `2.39-0ubuntu8.12`, so no CI runner exercises the `allocator-entropy-v1` reuse path now.

## Known limitations

- Metadata guards include `accessed_ns`, which the traced command's own reads update. Commands that
  `stat` an input before reading it (`strip`, `objcopy`, `unzip`) classify `Guarded` and then deoptimize on the next run. Sound, but a permanent miss until guards become field-precise. Phase W measured the same effect for `cc`: gcc's PCH probe `stat`s the header, so a byte-identical rewrite (new mtime) deoptimises even with the candidate fix applied.
- Cache-hit fixed cost on this host is ~11 ms plus ~6 ms of strict dependency hashing; commands under ~15 ms are net losses on a hit, which is what `--admission auto` exists for.
- Large-output restoration remains the dominant cost for big outputs; reflink is unavailable on ext4 and was not adopted without a measurable gain.
- Multi-output restore: single-path rename atomic; soft rollback verified; hard-kill not crash-atomic / not inode-preserving. Restore-intent refuses the next HIT.
- Validate→restore TOCTOU residual remains; guards run once, immediately before the restore.
- `rustc` needs `statx`, `prctl`, create-only `eventfd2`, and a decision on process-relative procfs before it can be eligible.
- Landlock is unavailable on the local host, so `PROVEN`/sandbox tests SKIP here.
- The integration suite is sensitive to host process pressure: 67/67 pass at `--test-threads=4`; at the default 8 threads the tagged beta already failed 2/62 on this VM.

## Validation

```bash
./scripts/check-version-consistency.sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --test-threads=4
cargo build --workspace --release
cargo audit
./scripts/demo.sh
python3 scripts/modelcheck/check_state_machines.py
python3 benchmarks/realworld/census.py --tracejit target/release/tracejit --output-dir /tmp/census
python3 benchmarks/realworld/census_v03.py --tracejit target/release/tracejit --output-dir /tmp/heldout
```

Gate evidence: `benchmarks/results/final_stab_pr4/gates/GATES_SUMMARY.md` (beta) and
`benchmarks/results/phaseu/` (this phase).
