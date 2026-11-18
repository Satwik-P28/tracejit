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

## Known limitations

- Metadata guards include `accessed_ns`, which the traced command's own reads update. Commands that `stat` an input before reading it (`strip`, `objcopy`, `unzip`) classify `Guarded` and then deoptimize on the next run. Sound, but a permanent miss until guards become field-precise.
- Cache-hit fixed cost on this host is ~11 ms plus ~6 ms of strict dependency hashing; commands under ~15 ms are net losses on a hit, which is what `--admission auto` exists for.
- Large-output restoration remains the dominant cost for big outputs; reflink is unavailable on ext4 and was not adopted without a measurable gain.
- Multi-output restore: single-path rename atomic; soft rollback verified; hard-kill not crash-atomic / not inode-preserving. Restore-intent refuses the next HIT.
- Validate→restore TOCTOU residual after recheck remains.
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
