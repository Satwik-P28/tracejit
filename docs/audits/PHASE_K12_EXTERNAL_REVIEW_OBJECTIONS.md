# Phase K12 — Anticipated external-review objections

Each objection is answered with evidence and an honest residual risk. No marketing rebuttals.

## O1. “This is just Firebuild / a build cache.”

**Response:** Goal overlap with transparent command caching is real and attributed (`NOVELTY_MATRIX.md`). Observation differs (ptrace vs preload), and TraceJIT’s bar is Obs fail-closed reuse with adversarial false-HIT hunting. **No superiority claim** vs Firebuild (not installed on this host).

## O2. “Make/Ninja already solve this faster.”

**Response:** Agreed on identical rerun when the graph is correct (K8: ~1.3 ms vs TraceJIT ~14 ms). TraceJIT’s measured difference is content-correct recovery on mtime-preserved edits and corrupted outputs where Make/Ninja retained **WRONG** bytes.

## O3. “Your certificates prove equivalence.”

**Response:** Rejected. Ceiling is `CheckedByVerifier`. StrictCas only checks CAS presence/digest. Certificates do not re-run guards, do not close validate→restore TOCTOU, and refuse `FullEquivalenceProof` (K6).

## O4. “CEGAR means you auto-widen the model.”

**Response:** Rejected. `tracejit refine` proposals stay blocked or verified-offline-not-deployed; ignore/whitelist suggestions fail closed as `RejectedUnsafe` (K5).

## O5. “Warm hits are unsafe under concurrent mutation.”

**Response:** Partially open. Guards are synchronous before expose; TOCTOU between validate and restore remains a documented limitation. Concurrent restore staging contention fails closed (ENOENT) rather than serving wrong Obs; crash mid-restore is not atomic (K4).

## O6. “Adaptive admission is just a bandit / will skip safety.”

**Response:** Production `auto` is an expected-benefit cost model over tracing. Offline `ConfidenceBound` only ties CurrentAuto; bandit-as-default **rejected** (K9). Admission never skips guards or reuses ineligible classes.

## O7. “Performance engineering weakened durability.”

**Response:** Staging tempfile uses `sync_data` before rename; CAS object `put_bytes` still `sync_all`. Dropping fsync entirely was evaluated and **rejected** (K7 / Phase F).

## O8. “Independent audit reused the same Rust crates.”

**Response:** K2 oracle is CLI JSON + filesystem Obs in Python without importing TraceJIT libraries. K3 checker is a separate Python modelcheck. Residual: product regressions still live in-tree (necessary for CI).

## O9. “Short commands prove the system is useless.”

**Response:** Short ETL warm loss is retained (~1.6 → ~3.1 ms). Flagship is correctness under Obs, not universal speedup. CPU-heavy warm reuse remains the positive performance regime (Phase G/K7).

## O10. “Formal methods verify the binary.”

**Response:** No. TLA+ sketches + external checker cover typestate/crash soft properties. Full-system proof is **blocked** / non-goal.
