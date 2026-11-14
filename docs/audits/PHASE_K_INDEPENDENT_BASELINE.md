# Phase K — Independent baseline (K0)

Date: 2026-11-14  
Auditor agent: `bc-bfd27a09-d08a-5ab4-bf28-cbc51b277fee`  
Role: independent senior systems / adversarial review. Prefer evidence of false-positive reuse over compatibility. Fail closed.

Prior completion report (`docs/final-completion-report.md` in the project store) was treated as **untrusted** and re-checked against live `origin/main` and local gates.

## 1. Live HEAD and host baseline

| Item | Value |
| --- | --- |
| `origin/main` HEAD (fetched) | `cf1013fd684f4893afafa50aab9609de5e09622d` |
| Matches prior “last reviewed” claim | yes |
| Tip subject | Merge PR #17 (Phase H–J docs) |
| Host | Linux `cursor` 6.12.113+ x86_64 |
| OS | Ubuntu 24.04.5 LTS (noble) |
| CPUs / RAM / disk | 4 / 15 Gi / 254G (`/` ~3% used) |
| `rustc` / `cargo` | 1.100.0 / 1.100.0 |
| Python | 3.12.3 |
| Landlock + seccomp | available (`proven-reuse PASS`, `sandbox PASS`) |

`PROJECT_STATE.md` on this tip still listed tip `b089d5e` (stale relative to `cf1013f`); code/docs tip is the merge of #17.

## 2. Independent validation (this host)

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace` | PASS |
| `cargo test -p tracejit-cli --test linux_integration -- --nocapture` | PASS — **55** tests; `proven-reuse PASS` |
| `cargo build --workspace --release` | PASS |
| `./scripts/demo.sh` | PASS (`RESULT explain PASS`, `RESULT mutation DEOPT`) |
| `./scripts/benchmark.sh` | PASS (harness ran; produced new `latest.*` locally — **not** committed in the K1 fix PR; used only for claim comparison) |

Claims ledger tip was `b089d5e`; gates still green on `cf1013f` (docs-only delta).

## 3. Reconstructed ~12-step flow and trust boundaries

Orchestration: `crates/tracejit-core/src/lib.rs` (`run`). Contract: `docs/research/EXECUTION_EQUIVALENCE.md`.

### Hit path

1. Identity / lookup key (`PreparedExecution`)
2. Cache open + inherited-fd refuse (pre/post open)
3. Candidate lookup (newest-first, LIMIT)
4. Optional admission skip → `run_direct`
5. Decode + contract match + `cache_eligible` (+ Proven-only if `--enforce`)
6. `validate_all` → typestate `GuardsPassed`
7. CAS verify stdout/stderr; inherited-stream seek probe
8. `restore_outputs`; apply inherited offsets
9. `expose_after_restore` → `ExposableHit`
10. CLI presents cached stdout/stderr/exit

### Miss path

11. ptrace execute → effects  
12. `classify` → optional PROVEN promotion → `compile_guards` → CAS store

### Trust boundaries (adversarial)

| Boundary | Risk |
| --- | --- |
| ptrace child ↔ parent | Inference of sandbox install; unmodeled success → UNKNOWN |
| Cache DB/CAS | Content rehashed; **classification/guards metadata not authenticated** (malicious cache owner out of model) |
| Classifier vs guards | Hit trusts **stored** class; `NoUnexpectedEffects` is a no-op on replay |
| Sandbox → PROVEN | Requires installed seccomp + Landlock ABI 3+; not full Obs equivalence |
| Hit typestate | Enforces expose order inside `run`; does not close external TOCTOU |

Detailed reconstruction: project-store `internal/phase-k-reuse-flow-adversarial-audit.md`.

## 4. Top-five highest-risk correctness assumptions

Ordered by false-positive reuse severity. Designed to be **disproved** by tests (not merely documented).

| # | Assumption | Disproof strategy |
| --- | --- | --- |
| R1 | `renameat2` may ignore flags / treat exchange as delete+rename | Minimal C: `RENAME_EXCHANGE`; compare warm HIT Obs vs native (both paths present, swapped). Expect: must be UNKNOWN / never HIT. |
| R2 | Successful terminal/ioctl queries on stdio are process-internal | Dup tty onto fd 1 or succeed `TIOCGWINSZ`/`TCGETS`; change winsize; expect no stale HIT. Failed ENOTTY probes must remain silent. |
| R3 | `newfstatat(AT_EMPTY_PATH)` may be answered by path fingerprint | Fixture must be UNKNOWN (align with faccessat). Rename-under-fd must not yield Guarded reuse. |
| R4 | `openat2` resolve flags need not be recorded | Non-zero `RESOLVE_*` → UNKNOWN until modeled. |
| R5 | Validate→restore TOCTOU / non-atomic multi-output | Concurrent mutator after guards; hard-kill mid-restore. Documented limitations; not closed by K1 refuses. |

Secondary (documented / experimental): Fast guard mode metadata forgery; execve identity race; hostname-as-Guarded content.

## 5. Initial K1 findings (pre-fix)

### Critical — demonstrated false-positive reuse

**`renameat2(RENAME_EXCHANGE)`** on tip `cf1013f` **before** the K1 fix:

| Run | `a` | `b` | Decision |
| --- | --- | --- | --- |
| Native / cold Exec | `BBB` | `AAA` | Executed, **Guarded**, eligible |
| Warm HIT (bug) | **MISSING** | `AAA` | **Reused** |
| Correct Obs | `BBB` | `AAA` | — |

Reproducer: `/tmp/rename_exchange` under `TRACEJIT_CACHE_DIR` (see K1 report).  
**False-positive reuse: YES (demonstrated).**

### Critical / High — modeling holes (not all demonstrated end-to-end on this host)

- Stdio `ioctl` success swallowed as `None` (failed ENOTTY OK for piped isatty).
- `newfstatat(AT_EMPTY_PATH)` fixture expected Guarded (unsound vs descriptor inode).
- `openat2` ignored `open_how.resolve`.
- `fchmodat`/`fchownat` ignored `AT_SYMLINK_NOFOLLOW` / `AT_EMPTY_PATH`.

Full write-up: project-store `internal/phase-k1-false-positive-reuse-audit.md`.

### Accepted limitations (not treated as new product defects)

- Guard→restore TOCTOU; non-crash-atomic multi-output restore; certificates ≠ full proofs; Fast mode experimental; research PRs #6/#7/#9/#10 isolated.

## 6. K1 remediation plan (this branch)

Branch: `cursor/phase-k-equivalence-hardening-7fee`

Fail closed only — **do not** broaden reuse:

1. `renameat2` flags ≠ 0 → UNKNOWN (+ regression: never HIT, Obs matches native).
2. Successful stdio terminal/ioctl → UNKNOWN; failed probe stays silent.
3. `newfstatat(AT_EMPTY_PATH)` → UNKNOWN; fixture expectation flipped.
4. `openat2` resolve ≠ 0 → UNKNOWN.
5. `fchmodat`/`fchownat` NOFOLLOW/EMPTY_PATH → UNKNOWN.

Then: gates, focused PR, CI, continue K2+.

## 7. Claims ledger spot-check

| Claim | Independent check |
| --- | --- |
| Reuse only PROVEN/GUARDED | Confirmed in `cache_eligible` + hit loop |
| EMPIRICALLY_STABLE never reuse | Enum present; **no production assignment path** (doc/code drift, not a reuse hole) |
| PROVEN needs seccomp+Landlock | `proven-reuse PASS` on this host |
| Differential/adversarial Phase D | Prior artifacts cited; not re-run in K0 (scheduled K2 oracle) |
| Short ETL loss / warm transform win | Harness runnable; numbers not re-asserted as new claims here |
| Competitive ninja/ccache skipped | Tools still absent unless installed later |

## 8. Next implementation PR plan

1. **PR A (this):** equivalence hardening refuses + regressions (K1). Merge when CI green.
2. **PR B:** independent oracle / differential seeds against fixed tip (K2).
3. **PR C+:** restoration/CEGAR/certificate depth only where evidence shows a concrete defect or verified strengthening — no safety weakening for benchmarks.
