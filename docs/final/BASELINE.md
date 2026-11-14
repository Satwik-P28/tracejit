# TraceJIT final adversarial baseline (§1)

Date: 2026-11-14  
Auditor: final-adversarial worker `bc-588fb4be-c738-5f4a-b110-e4d753a36ed7`  
Role: live inventory before any new product edits. Prefer evidence of false-positive reuse over compatibility. Fail closed.

## 1. Exact revision and tree

| Item | Value |
| --- | --- |
| Worktree | `/agent/repos/tracejit-final-adv` |
| Branch | `cursor/final-adversarial-baseline-6ed7` |
| `origin/main` SHA (fetched) | `4421f8be60cdd50231e2cf5662130511fdd1c175` |
| Worktree HEAD | `4421f8be60cdd50231e2cf5662130511fdd1c175` |
| Dirty | clean at baseline measurement |
| Tip subject | Merge PR #25 (Phase K8–K14 research package) |
| Reference SHA in mandate | `4421f8b…` — matches live tip; not used as a pin |

Sibling worktrees on this host: `/agent/repos/tracejit` (`main` @ same SHA).

Remote research/isolated branches present (`cursor/phase-*`, `freebuff/*`, etc.) — **not merged** into this baseline; research PRs #6/#7/#9/#10 stay isolated.

## 2. Host / toolchain / sandbox

| Item | Value |
| --- | --- |
| Kernel | Linux `6.12.113+` x86_64 (`#1 SMP PREEMPT_DYNAMIC Fri Nov 13 20:22:28 UTC 2026`) |
| OS | Ubuntu 24.04.5 LTS (noble) |
| glibc | 2.39-0ubuntu8.9 |
| Filesystem | `ext4` on `/dev/vdc`, mount opts `rw,relatime` |
| CPUs | 4 × Intel Xeon (1 thread/core), 1 NUMA node |
| CPU governor / freq | **unavailable** (`/sys/.../cpufreq` absent — cloud VM; do not invent) |
| Memory | 15 GiB; swap 0 |
| Disk | 254G, ~4% used |
| `rustc` / `cargo` | 1.100.0 / 1.100.0 |
| Python | 3.12.3 |
| Caps | CapEff empty; CapBnd broad; Seccomp mode 0; NoNewPrivs 0 |
| Landlock headers | present (`/usr/include/linux/landlock.h`) |
| seccomp headers | present |
| Proven path | `RESULT proven-reuse PASS`; `RESULT sandbox PASS: seccomp and Landlock ABI 3+ available` |
| Competitor tools | `make` present; **ninja / ccache / sccache / strace / perf ABSENT** |

Unsupported / not pretend-green:

- Hardware PMU / `perf` attribution — tools absent.
- Ninja / ccache / sccache competitive arms — absent (report skipped, not worse).
- CPU governor pinning — unavailable on this host.
- Bind-mount `/dev/null` substitution — historically blocked by `unshare -m` EPERM (claims ledger).

## 3. Validation gates (this SHA, this host)

| Gate | Exit | Notes |
| --- | ---: | --- |
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test --workspace` | 0 | PASS; **0 ignored** across crates |
| `cargo build --workspace --release` | 0 | PASS |
| `cargo test -p tracejit-cli --test linux_integration -- --nocapture` | 0 | **57** tests PASS; `proven-reuse PASS`; `sandbox PASS`; `renameat2_exchange_is_unknown_and_never_reused` PASS; phase-k2 oracle `incorrect_hits=0` |
| `./scripts/demo.sh` | 0 | `RESULT explain PASS`; `RESULT mutation DEOPT` |

Raw gate logs (host-local, not committed): `/tmp/baseline-gates/`.

Workspace unit/integration aggregate (non-doc): 28+5+1+57+6+1+1+23+24+36+4+20 ≈ **206** passing crate tests in this run (plus nested sandbox child filters). No `#[ignore]` tests found in crates.

## 4. Crate / path inventory

| Crate | Role |
| --- | --- |
| `tracejit-effects` | Effect records, `classify`, certificates helpers, CEGAR/refine |
| `tracejit-guards` | Guard compile + `validate_all` |
| `tracejit-cache` | SQLite index, BLAKE3 CAS, restore / staging |
| `tracejit-trace` | Linux x86_64 ptrace lifecycle (`linux.rs`) |
| `tracejit-sandbox` | seccomp + Landlock install / probe |
| `tracejit-core` | Orchestration `run`, hit typestate, admission |
| `tracejit-cli` | CLI + linux_integration / phase_d / fidelity tests |

Key paths: effect observation (`trace/linux.rs`), guards (`guards/lib.rs`), CAS/SQLite (`cache/lib.rs`), restore (`cache` restore_outputs), sandbox (`sandbox/lib.rs`), admission (`core` + `admission_research.rs`), refine/CEGAR (`effects/{refinement,cegar}.rs`), independent oracle (`benchmarks/oracle/independent_obs.py`), modelcheck (`scripts/modelcheck/`), crash harness (`scripts/phase_k4_restore_fault.sh`), benchmarks (`scripts/benchmark.sh`, `benchmarks/harness/`).

`unsafe` sites: ~105 matches under `crates/` (ptrace/FFI expected; not audited line-by-line in §1).

## 5. Feature truth table (V1 product on this tip)

| Feature | Truth |
| --- | --- |
| Whole-command reuse for `GUARDED` / `PROVEN` only | **true** (`cache_eligible`) |
| `UNKNOWN` / `NONDETERMINISTIC` / `EMPIRICALLY_STABLE` never reuse | **true** |
| `PROVEN` needs installed seccomp + Landlock ABI 3+ | **true** on this host |
| Synchronous guards before first cached byte | **true** (typestate) |
| `renameat2` non-zero flags (incl. `RENAME_EXCHANGE`) → UNKNOWN / never HIT | **true** (Phase K1 regression green) |
| Independent Obs oracle (seed 7 path in linux_integration) | **true** (`incorrect_hits=0`) |
| Soft restore failure rollback + retrace | **true** (K4) |
| Crash-atomic multi-output restore | **false** (documented limitation) |
| Inode-preserving restore | **false** |
| Validate→restore TOCTOU closed | **false** |
| Certificates = full equivalence proofs | **false** (refuse `FullEquivalenceProof`) |
| Fast guard mode | **experimental** opt-in |
| Research #6/#7/#9/#10 on main | **false** (isolated) |
| Bandit default admission | **rejected** |

## 6. Old measurements (not reasserted as current-HEAD claims)

Committed `benchmarks/results/latest.md` is pinned to older commit `94c64c709dfb0bec433dacf83cc967aeee6a1f1b` (short C ETL: warm hit **slower** than direct — ~0.41×). That is **not** a fresh measurement of `4421f8b`.

Phase K7 micro (`benchmarks/results/phase_k7/`) measured tip after K5 levers — warm wall still multi-ms; short ETL remains a loss vs direct. Phase K8 competitive notes ninja/ccache skips when tools absent.

**§1 does not invent new speedups.** Fresh e2e numbers require a later harness run on this SHA with explicit provenance.

Demo on this SHA (qualitative only): warm guarded hit then mutation → `DEOPT`; not a statistical benchmark.

## 7. Docs freshness

| Doc | Status vs `4421f8b` |
| --- | --- |
| `PROJECT_STATE.md` | **Stale tip** listed `364331b` (pre-#25); corrected in this PR |
| `docs/research/CLAIMS_LEDGER.md` | Tip note still mentions K8–K14 “in flight”; content otherwise matches merged #25 — refresh with baseline |
| `EXECUTION_EQUIVALENCE.md` | Aligns with implemented K1 refuses |
| Phase K audits K0–K14 | Present under `docs/audits/` |

## 8. Ranked defects / open obligations (pre-edit)

Severity is false-HIT / Obs divergence first.

| Rank | Defect / obligation | Severity | Status on tip |
| ---: | --- | --- | --- |
| D1 | Validate→restore TOCTOU (external mutator after guards) | **critical contract gap** | Documented; not closed |
| D2 | Multi-output restore not crash-atomic under hard kill; no durable journal | **high** | Soft rollback verified; hard-kill mixed workspace accepted limitation |
| D3 | Inode / hardlink / metadata identity not preserved across restore | **high** (contract exclusion) | Pathname-visible only |
| D4 | Broad unmodeled syscall surface (io_uring, SCM_RIGHTS, pidfd_getfd, …) must stay UNKNOWN | **high** if silently omitted | Must be inventory-falsified in §3 suite — not assumed complete |
| D5 | Classifier trusts stored class; `NoUnexpectedEffects` is weak on replay | **medium** | Known trust boundary |
| D6 | Cache metadata not cryptographically authenticated (malicious cache owner OOM) | **medium** (threat model) | Same-user corruption partially covered |
| D7 | Short-command / short-ETL warm hit loses to direct | **perf** | Honest loss; admission AUTO mitigates |
| D8 | Competitive Firebuild/sccache/ninja matched numbers | **blocked** | Tools absent |
| D9 | `EMPIRICALLY_STABLE` enum with no production assignment | **doc/code drift** | Not a reuse hole |
| D0 | `renameat2(RENAME_EXCHANGE)` false HIT | **was critical** | **Fixed** Phase K1; regression must remain green forever |

## 9. Reproducible demo (this host)

```bash
git rev-parse HEAD   # expect 4421f8be60cdd50231e2cf5662130511fdd1c175 at baseline
cargo build --workspace --release
./scripts/demo.sh
# expect: RESULT explain PASS ; RESULT mutation DEOPT
```

## 10. Next steps (execution, not roadmap prose)

1. Publish `docs/final/INVARIANTS.yaml` (I1–I7) mapping to code/tests/gaps.
2. P0 §§3–5: adversarial process-semantics fixtures; resource-identity / TOCTOU honesty; restore durability — minimal safe fixes only; preserve RENAME_EXCHANGE refuse.
3. P1 and release docs only after P0 critical false-HIT class is clear or honestly deferred.
