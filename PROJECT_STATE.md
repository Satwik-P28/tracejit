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

- `origin/main` tip at the start of Phase AA: `e4f80adcbf3d1184bf27babc870a62c4daa8ff89` (PR #42 merged). Its CI status could not be queried from the authoring environment; see `docs/PHASE_AA_REPORT.md` §2. Published beta: tag `v0.2.0-beta.1` at `7a594b9`.
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`), `v0.2.0-beta.1` (`7a594b9`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated from `main`.

## Phase AA (`research/phase-aa`): real-world qualification

- Benchmark system is qualified; the product's real-world applicability is narrow and contract-dependent. Full evidence: `benchmarks/results/phaseaa/`, report: `docs/PHASE_AA_REPORT.md`.
- 59 workloads (50 tier A strict-native, 9 tier C declared adaptations), 177 (tier × policy) rows, splits frozen before the run (dev 21 / validation 22 / held-out 16).
- Eligibility, per cell and never summed: native **1/49** (2.0 %), `allocator-entropy-v1` **10/49** (20.4 %), `compiler-runtime-v1` **17/49** (34.7 %), tier C **0/5** under every policy. The beta's "1/32" is the native cell, not a general rate.
- Measured: 4 workloads with positive cumulative savings (best 30.6× warm, 13.1× over a 25-repeat session), 8 slower than native (worst 7.1×), 0 incorrect HITs, warm-hit floor 13–16 ms.
- Product fix: a missing output CAS object aborted the command instead of retracing (`c3f77d8`), with regression.
- Open findings: `TRACEJIT_CACHE_DIR` relocation invalidates every record; one `gcc` workload's classification flipped between identical runs; validate→restore TOCTOU unchanged; tracing an ineligible `make` costs +460 ms/invocation.
- Version label is unchanged (`0.2.0-beta.1`) while `main` carries post-beta contracts, so no artifact should be published from this line until it is bumped. v0.3 is **not** qualified: `docs/RELEASE_READINESS_V03.md`.

## Phase AA1 (`research/phase-aa`, audit of Phase AA): benchmark integrity

- Audit report `docs/PHASE_AA1_AUDIT.md`; next-phase plan `docs/PHASE_AB_PLAN.md`; evidence `benchmarks/results/phaseaa1/` (timing at `1c87e02`, clean tree, binary `daca8b0d…`; reproduction from a separate clone at `ae884c5`).
- Counts reconciled: 177 declared cells = 59 × 3; 15 `tool_unavailable` (5 workloads × 3) leave **162 attempted** (54 × 3); 129 refused, 5 eligible-but-no-hit, 28 verified HITs, 20 timed rows over 13 workloads, 0 incorrect HITs. AA had divided *reused* cells by attempted cells and called it eligibility: true eligibility is **2/49 native (4.1 %), 12/49 allocator (24.5 %), 19/49 compiler (38.8 %)**, tier C 0/5; reuse is 1/10/17.
- Timing defect found and fixed: the hit arm used `--json`, so TraceJIT serialised cached stdout and the harness parsed it inside the timer. `sed` was published at 0.17–0.18× and is **0.64–0.70×**; `cut` 0.15 → 0.20–0.25×; `gzip -6` 0.44–0.50 → 0.64–0.77×. Timed arm now runs plain mode with one `--json` calibration outside the timer, and each sample's stdout is verified.
- Attribution now reconciles: `runtime_ns` excludes decision persistence, so `wall = pre + runtime + persist + present` on disjoint intervals; hit-path residual ≤ 7 ms; tick-quantised startup never summed. The unexplained 15–50 ms was the `--json` channel.
- Classification instability quantified: `gcc-cc-small-tu` 94/100 `Guarded` (6/100 `Nondeterministic`), `zlib-compile-deflate` 98/100, `gcc-cc-heavy-tu` refused once under load after 100/100 in a quiet probe; determinant is `getrandom` at the gcc driver's pid (sequence 57 of 323). Refusal rules unchanged; refused timing attempts are now recorded and retried at most once.
- Corrected results: 4 workloads faster by CI (best **30.2–33.7×** `c-numeric`, `gcc-cc-heavy-tu` 7.35×, `zlib-compile-deflate` 7.24×, `adler32` 1.28× at break-even 14), 9 slower (worst `readelf` 0.15×), warm floor 8.1–17.3 ms, 4 of 13 with positive 25-repeat savings.
- Competitive evidence added: ccache 4.10.2 installed in user space and measured on the same zlib compile — **4.54 ms vs TraceJIT 65.18 ms** (108× vs 7.5×), 20/20 hits each, all objects byte-identical. The compile-speed argument is no longer defensible; the remaining claim is output-integrity repair and non-compiler commands.
- Benchmark hardening: 29 harness tests (oracle rejects stale/missing/extra/mode/symlink/hardlink/dir/stdout/stderr/exit; accounting rejects tampered rows; manifest independent of local cache), `validate.py` recomputes the ledger, and the W1 audit's fixed `/tmp` root was fixed after the clean-checkout run failed on a shared `/tmp`.
- Fresh-clone reproduction at `ae884c5` with empty `HOME`, separate scratch and vendor: exit 0, 42 cells, 0 incorrect hits, 13/13 counterexamples. Gates: fmt/clippy/workspace tests at `0a7d08b` (no Rust change after), integration 84/84, model check PASS, packaging after the final commit. Not run: differential fuzz, restore fault injection, `cargo audit`, GitHub CI (no credentials).

## Phase AB (`research/phase-ab`, from `fd6d004`): determinism, integrity, hit floor

Phase AB closed the intermittent gcc-classification question and measured the
product against a real build, rather than against microbenchmarks.

* **Root cause, closed.** glibc's `mkstemps` rejection-samples 8 bytes of
  `getrandom(GRND_NONBLOCK)` into a stack buffer to name the gcc driver's
  temporary assembly file; the bound `0xf49998db0aa753ff` gives a 4.45 % pass
  probability, and the compiler contract (which supplies `clock_gettime`) shifts
  the sampled value and measures **5.7 % in 1,000 direct trials** (95 % CI 4.3–7.1 %,
  57 refusals) and **2.3 % in a make-driven build** of 384 invocations. Every
  refusal costs exactly one extra unabsorbed read. Refusal is
  retained: the bytes become an application-visible path. `gcc -pipe` was
  measured and rejected (100/100 refused via pipe `fstat`).
* **One production change.** `Cache::restore_outputs` no longer writes a durable
  restore intent for records with no workspace outputs. Paired A/B: `cut`
  −1.9 ms, `gzip -6` −2.2 ms, `sed` −2.5 ms (95 % CIs exclude 0); compiler hits
  unaffected, as they must be. `gzip -6` moved from 0.77× to parity with native.
* **Persistence correction.** Steady-state hits write nothing; the durable
  decision write happens once per record (4.57 ms on the first hit). Phase AA1's
  "3.5–20 ms per hit" was the first-hit cost, and its 6.5–16 ms "pre-runtime"
  band was a residual that included the core's pre-runtime phases and the
  harness's own fork/exec.
* **Whole-build result.** Lua 5.4.6, 32 units: warm rebuild make 7.29 s,
  ccache 0.19 s, TraceJIT 3.20 s; cold TraceJIT 15.3–16.8 s. No cache repairs an
  artifact the build system does not rebuild, and TraceJIT's mtime-preserving
  restore can leave a stale archive member where ccache's fresh write corrects
  it. The integrity premium over ccache is negative.

Evidence: `docs/PHASE_AB_REPORT.md`, `docs/COMPILER_ENTROPY_INVESTIGATION.md`,
`docs/OUTPUT_INTEGRITY_ECONOMICS.md`, `docs/HIT_OVERHEAD_PROFILE.md`,
`docs/PHASE_AB_CORRECTNESS_AUDIT.md`, `benchmarks/results/phaseab/`.

## Development line (`development/v0.3`, Phase U)

- Cut from `7a594b9`; **not merged, not released, no version bump**.
- Native reuse eligibility is unchanged from the beta (1/31 on the original census, 0/20 held out). The phase's finding is that the remaining refusals are genuine nondeterminism, not model gaps.
- Contract tier (`--contract allocator-entropy-v1`): 7/31 original, 8/20 held out.
- New models: null device by device identity, create-only epoll, `O_NONBLOCK`-only status-flag rewrites, identity-guarded `prlimit64` queries, negative-descriptor `EBADF`, `TCGETS` on internal pipes.
- New corpus: `benchmarks/realworld/census_v03.py` (20 held-out workloads).
- Docs: `docs/COMPATIBILITY_V03.md` (blocker analysis, accepted/rejected models), `docs/PHASE_U_REPORT.md`.
- Evidence: `benchmarks/results/phaseu/`.
- Harness (Phase U2): no descriptor in the shared test process is modified; each spawn marks its
  own child's descriptors `FD_CLOEXEC` in `pre_exec`, and `invoke_inheriting` is the only way to
  hand TraceJIT a deliberately inherited descriptor.

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

## Research line, Phase Z (`research/phase-z`, from `6bab00b`, PR #42)

- The stale audited build is replaced on evidence and admission is stronger:
  `docs/PHASE_Z_REPORT.md`, `PHASE_Z_GLIBC_DIFF.md`, `PHASE_Z_CONTRACT.md`, `PHASE_Z_LEDGER.md`;
  source-level audit, corrections and new regressions in `docs/PHASE_Z1_AUDIT.md`.
- `2.39-0ubuntu8.12` joins `ALLOCATOR_ENTROPY_PROFILES` (`site 0xa9e69`, destination unchanged
  `0x20b178`); its audited function decodes identically to 8.9, and the only malloc change in
  8.10–8.12 is `_int_memalign`'s alignment check, which the contract does not touch. The destination
  is **derived** from the buffer load's displacement at record *and* guard time; ambiguity refuses.
  `doctor` reports `runtime allocator-entropy-v1 audited (<build id>)`.
- Compiler reuse restored (103.3 → 47.8 ms paired, byte-identical objects); sessions **1.83×** (27)
  and **2.82×** (48), all arms byte-identical. Contract tier newly eligible: census 1 → 7/30, held
  out 0 → 7/20; native tier unchanged at 1/30. Shortlist `sed` 11.02×, `sort --parallel=1` 8.29×,
  `gzip -9` 3.80×; `wc`/`sha256sum` rejected as slower; `awk`/threaded `sort`/`tar`/`python`
  ineligible. `ccache`/`sccache` unavailable here, so nothing is claimed against them.
- Phase Z1 audit: `tcache_key` has exactly two roles — `tcache_put` stores it in a freed chunk's
  `key` word, `_int_free` compares it there — so it does **not** feed safe-linking (which masks with
  the chunk address) and does **not** change heap layout. Contract split into claims A/B/C with
  explicit exclusions; allocator diagnostics are byte-identical to native on both double-free paths;
  an unaudited `.so` issuing the same probe is refused; four concurrent initialisations replay.
- Gates on the final head: **269 tests**, integration 80/80 at 1/8/default threads, fuzz seed 29
  (0 incorrect hits), model check, fault injection, `cargo audit`, fmt and clippy clean. CI run
  #270 on `e7d30b5` succeeded; PR #42 is pushed and green but still a draft — flipping it and
  merging need GitHub write access, which this environment does not have.

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
