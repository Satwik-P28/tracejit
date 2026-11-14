# TraceJIT: Conservative Effect-Aware Memoization of Linux Processes

**Technical design and evidence report | 14 November 2026 | Non-peer-reviewed**

**Inspected product tip for this rewrite:** `origin/main` `b089d5e774d6481a83ec3f308f479d551ed50ce7` (merge of Phase G PR [#16](https://github.com/Satwik-P28/tracejit/pull/16)). Historical measurements retain their original commits. This document is not a peer-reviewed publication and does not claim production adoption.

Status vocabulary (Part XXII §58): **implemented+verified**, **implemented but not fully verified**, **experimental**, **rejected**, **deferred**, **blocked**. Feature table: [CLAIMS_LEDGER.md](CLAIMS_LEDGER.md).

## 1. Abstract

TraceJIT is a Linux x86_64 Rust prototype that memoizes whole unmodified commands. It observes modeled syscalls with `ptrace`, classifies effects, and reuses a prior result only when the record is `GUARDED` or `PROVEN` and every synchronous guard passes before any cached stdout, stderr, exit status, or output file is exposed. Uncertainty fails closed.

On a controlled host (kernel `6.12.113+`), a CPU-heavy C transform warmed from **36.136 ms** direct to **3.116 ms** reused (~11.6×; Phase G session A). The official short C ETL harness on the same lineage remains a net loss (**1.455 ms** baseline vs **3.571 ms** cached, **0.407×**; `benchmarks/results/latest.md` at `94c64c7`). Make can win identical-rerun latency while returning incorrect bytes after mtime-preserved edits or corrupted outputs; TraceJIT recovers correctly on those cases. The contribution is fail-closed observed-dependency reuse with testable refusals, not general-purpose acceleration.

## 2. Motivation

Build systems and compiler caches reuse work when inputs are declared or toolchain-specific. Many developer commands are already built binaries whose dependencies are not written down. Replaying an earlier stdout/fileset without observing what the process actually depended on is a correctness hazard. TraceJIT asks whether those dependencies can be inferred from kernel crossings and checked before replay, and whether the answer is still useful when clocks, randomness, networks, and unmodeled syscalls force refusal.

## 3. Problem formulation

Let command identity \(E\) be the executable content hash, argv, cwd, full inherited environment, runtime identity, and optional contract id. Let \(\mathrm{Exec}(E)\) be native execution and \(\mathrm{Obs}(E)\) the observable result TraceJIT promises to match on a hit: exit status, captured stdout/stderr bytes, and recorded regular-file outputs (pathname-visible). Input file *contents* are guards, not key bits ([EXECUTION_EQUIVALENCE.md](EXECUTION_EQUIVALENCE.md)).

A reuse \(\mathrm{Reuse}(E,R)\) from record \(R\) is admitted only if classification eligibility holds and every compiled guard of \(R\) passes under the current filesystem sample. Formal full-system equivalence is **blocked** / non-goal. The thin TLA+ sketch `docs/research/formal/reuse_hit.tla` is **experimental** (typestate mapping only).

## 4. Execution semantics

Implemented contract (Phase C, PR [#12](https://github.com/Satwik-P28/tracejit/pull/12), merge `325f8a8`):

| Class | V1 reuse | Meaning |
| --- | --- | --- |
| `PROVEN` | yes | `GUARDED` plus seccomp and Landlock ABI 3+ actually installed |
| `GUARDED` | yes | Modeled deps have synchronous guards |
| `EMPIRICALLY_STABLE` | **no** | Not admitted |
| `UNKNOWN` | **no** | Unmodeled/unsafe effect |
| `NONDETERMINISTIC` | **no** | Clocks, entropy, process identity, network, similar |

Hit-path order: eligibility → all guards → verify stdout/stderr CAS → seek probes → restore outputs → apply inherited-stream offsets → then expose cached bytes (typestate `GuardsPassed`). Anonymous `MAP_SHARED` and hard-link creation are `UNKNOWN`. Deleted `/proc/.../fd/n` pathnames are not live `InheritedFile`s. Path guards replay the pathname the process passed (no lexical `..` collapse).

## 5. Threat model

Assumptions: a single trusted operator on local Linux x86_64; the cache may hold secrets (stdout/env/outputs) without encryption; concurrent writers may mutate inputs between validate and restore (TOCTOU); multi-output restore is pathname-visible and not crash-atomic under hard kill; `PROVEN` confines the traced process, not the rest of the machine. Adversarial goals considered in fixtures: stale hits after content/mtime/symlink/hardlink/permission changes, CAS/SQLite corruption, output presence steering, inherited-descriptor substitution, `/dev/null` identity confusion. Bind-mount `/dev/null` substitution remains **blocked** here (`unshare -m` EPERM; defect D-B9).

## 6. System architecture

Crate boundary (unchanged V1): `effects → guards → cache → trace → sandbox → core → cli`. Observation uses `ptrace`; artifacts use BLAKE3 content-addressed storage; metadata uses SQLite schema v2 with bounded candidates per lookup key (default 8). Optional `--enforce` installs seccomp-BPF and Landlock. No daemon. Strict content hashing is default; `--guard-mode fast` is an explicit opt-in.

```text
identity → SQLite candidates → validate guards
  → hit: verify streams, restore CAS outputs, replay result
  → miss: ptrace → classify → compile guards → persist if eligible
```

## 7. Effect abstraction

Syscalls and process events normalize to read/write/control/unknown effects with the five determinism classes above. Writable file-backed `MAP_SHARED` and anonymous `MAP_SHARED` are `UNKNOWN`. vDSO clock entry points are redirected to syscalls or the run is `UNKNOWN`. Descriptor state tracks numeric fds with separate pipe identity; inherited fds above stderr fail closed at preflight (Phase 3G/3H). Semantic registry for touched classes: `crates/tracejit-effects/src/registry.rs` (**implemented+verified**, Phase E).

## 8. Guard obligations

Guards are compiled from observed dependencies (file metadata/hash, executable hash, absent paths, directory identity, filesystem stats, symlink metadata, inherited streams). Default strict mode re-hashes content. Fast mode may skip content hash after matching metadata fingerprint. Every guard must pass before exposure ([SAFETY.md](../../SAFETY.md), [CORRECTNESS_OBLIGATIONS.md](CORRECTNESS_OBLIGATIONS.md)). `NoUnexpectedEffects` always passes by construction: unmodeled effects never produce a reusable record.

## 9. Reuse certificates

Phase E (**implemented+verified**): `tracejit.reuse-certificate.v1` records contract id, candidate/lookup key, classification, guard evidence, content identities, descriptor obligations, CAS refs, restore preconditions, and explicit limitations ([REUSE_CERTIFICATES.md](REUSE_CERTIFICATES.md); `crates/tracejit-core/src/certificate.rs`). Claim ladder:

| Level | Status |
| --- | --- |
| `CheckableEvidence` | structural fields present |
| `CheckedByVerifier` | `verify_certificate` consistency |
| `FullEquivalenceProof` | **never** granted |

Certificates re-sample the same mutable filesystem as the hit path; they do not close TOCTOU.

## 10. Counterexample-guided refinement

Phase E workflow (**implemented+verified**): observe → abstract → counterexample → minimize → refine → retest (`crates/tracejit-effects/src/refinement.rs`; [CEGAR_REFINEMENT.md](CEGAR_REFINEMENT.md)). Worked cycle: DirectoryOpened over-abstraction → sibling-create CE → identity-only directory guard (historical product fix). **Rejected:** treating `getrusage` as ignorable/whitelistable (`getrusage_refinement_rejected`). No claim that CEGAR itself is novel; no new product syscall admits in Phase E (**deferred**).

## 11. Adaptive admission

Policies choose whether to **pay for tracing**; they never skip guards or invent eligibility ([ADMISSION_POLICIES.md](ADMISSION_POLICIES.md)).

Expected benefit for costs \(C = (\mathrm{direct},\mathrm{cold},\mathrm{hit})\) with hit probability \(p\) estimated from measured hits/(hits+deopts), and \(p=0\) when unsampled:

\[
\mathbb{E}[B] = p\cdot\max(\mathrm{direct}-\mathrm{hit},0) - (1-p)\cdot\max(\mathrm{cold}-\mathrm{direct},0)
\]

Production `auto` remains the shipped policy. Offline comparison on a held-out synthetic matrix (`tracejit admission-eval`) preferred `CurrentAuto` at regret **49 000 000 ns** vs oracle; `ConfidenceBound` tied and lost on simplicity; bandit-as-default **rejected** (Phase E RESULT lines). Phase G ablation: `auto` skips short ETL reuse while still caching the CPU-heavy transform after measurement.

## 12. Crash recovery

Normal restore failures roll back staged outputs. There is **no** durable multi-file journal. Hard kill during multi-output restore can leave a mixed pathname-visible workspace; recovery is re-execution. Phase D adds detectability/fail-closed tests and keeps honest wording in `CORRECTNESS_OBLIGATIONS.md`. Inode-preserving CAS rename is **not** claimed.

## 13. Implementation

Rust workspace on Linux x86_64. Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`) — tags must not move. Notable product fixes on `main` through Phase F (`84b07c1`): inherited `/dev/null` read identity (`bb29414`); inherited fd>2 preflight; descriptor enumeration fail-closed + `dup2(fd,fd)` + directory-state forget on reuse (PR [#8](https://github.com/Satwik-P28/tracejit/pull/8)); post-`Cache::open` inherited-fd re-scan (PR [#11](https://github.com/Satwik-P28/tracejit/pull/11)); Phase C semantics; Phase F stream-hash CAS staging, single-fd metadata+hash pairs, candidate `LIMIT`, precomputed runtime-identity JSON. Research branches #6/#7/#9/#10 stay **isolated** (Phase A reconciliation: keep #4/#5/#8 on main; reject #6/#7/#9/#10 for main).

## 14. Experimental methodology

| Suite | Method | Evidence |
| --- | --- | --- |
| Official short ETL | 5 warmups + 30 runs; direct / cold / cached | `./scripts/benchmark.sh` → `benchmarks/results/latest.{json,md}` |
| Duration sweep (historical) | same shape on hosted Ubuntu 24.04 | `e9684c1`; `benchmarks/results/break-even.*` |
| Phase D differential | seeds 7/11/17; native vs discover vs reuse | `benchmarks/differential/phase_d.py`; `benchmarks/results/phase_d/differential/` |
| Phase D adversarial | Rust scenarios | `crates/tracejit-cli/tests/phase_d_verification.rs` |
| Phase F profile | phase timers (no `perf`/CPU PMU on host) | `benchmarks/repos/phase_f_profile.py`; `benchmarks/results/phase_f/` |
| Phase G evaluation | 5 warmups + 20 runs; two held-out sessions | `benchmarks/repos/phase_g_evaluation.py`; `benchmarks/results/phase_g/` |

Host for Phases F/G: kernel `6.12.113+`, rustc `1.100.0`, ext4, 4 CPUs. Tools absent and **not claimed**: ninja, ccache, sccache, perf, strace. Allocator tunables `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `MALLOC_ARENA_MAX=1` are experimental environment choices for controlled C workloads, not general compatibility.

## 15. Correctness results

- Linux integration on Phase G tip: **55** passed, `proven-reuse PASS` (PR #16 body; Landlock available on that host).
- Phase D differential: seeds 7/11/17 each **0** `incorrect_hits`, **0** `discover_mismatches` (135 executed / 11 skipped per seed).
- Phase D adversarial: `executed=11 skipped=0 incorrect_hits=0`.
- Concurrency RESULT lines: cold/warm/reused=8; restore contention `errors=0`.
- `proptest` properties: no product defect found (one test-only generator assumption fixed).
- Closed P0s on main: D-A1…D-A5 (defect register). Phase B D-B1 post-open re-scan landed.
- Controlled Python / epoll / two-stage retrieval / metadata hash-cache: **rejected for main** (research #6/#7/#9/#10).

## 16. Performance results

Numbers below cite committed harness outputs only.

### Wins (Phase G session A medians)

| Scenario | Direct / other | TraceJIT | Evidence |
| --- | ---: | ---: | --- |
| CPU `c-transform` | 36.136 ms | **3.116 ms** warm reused | `evaluation-session-a.md` |
| `bzip2 -9` (contract) | 26.485 ms | **5.333 ms** always-warm | same |
| A/B/A third run | — | **4/4** Reused | same |
| Large restore opt (F vs E) | cas_restore 9.116 ms (E tip) | **7.541 ms** (F tip) | Phase G ablation |

### Losses (retained)

| Scenario | Number | Evidence |
| --- | --- | --- |
| Official short ETL | 1.455 → 3.571 ms (**0.407×**) | `latest.md` @ `94c64c7` |
| Phase G short ETL | 1.537 vs 3.421 ms | session A |
| Large ~8 MiB read | 10.786 vs 21.539 ms | session A |
| Build identical rerun vs make | TraceJIT 58.467 ms Executed×3 vs make 1.651 ms | session A |

### Historical (do not merge into same-commit comparisons)

| Workload | Commit | Direct | Hit | Ratio |
| --- | --- | ---: | ---: | ---: |
| Synthetic transform (250M mixes) | `e9684c1` | 312.913 ms | 3.972 ms | 78.780× |
| Short C ETL | `63e3363` | 7.396 ms | 7.957 ms | 0.929× |

Duration sweep hit floor ~4 ms (`break-even.md` @ `e9684c1`).

## 17. Ablation studies

| Lever | Finding | Status | Evidence |
| --- | --- | --- | --- |
| Stream-hash CAS staging | Large-file warm 14.591 → 9.748 ms; cas_restore 9.980 → 5.947 ms | shipped | Phase F `profile-*.md` |
| Drop staging `sync_all` | Small-file cas_restore 1.128 → 0.134 ms | **rejected** (durability) | `profile-ablation-no-fsync.md` |
| Candidate `LIMIT` | Newest-hit ~3 ms across bounds 1–32 | keep | Phase G |
| Lazy `CandidateBytes` | Decode small on newest hit | keep | Phase G |
| Strict vs Fast guards (~1.8 MiB) | Fast warm 7.386 / guard 0.032 vs Strict 8.409 / 1.046 ms | Fast **experimental** opt-in | Phase G |
| Admission `auto` | Skips short ETL; caches transform | keep production | Phase G |
| Bandit default | Tied/worse than `CurrentAuto` | **rejected** | Phase E |
| Metadata fingerprint hash cache | Concurrent same-metadata risk | **rejected** | D-B7 / #10 |

## 18. Negative findings

- Native real-world census remains **0/9** reusable (clocks/randomness/identity/`getrusage`/pipes); fail closed, not “fixed” by weakening ([LITERATURE_REVIEW.md](LITERATURE_REVIEW.md), Phase 3F/3G audits).
- Output-presence guards are **necessary**: bzip2 identical rerun deopts when the destination exists (Phase 3B); treating absence as an optimization would be unsound.
- Phase 3D two-stage retrieval: no general win; **reject** merge (#6).
- Controlled CPython contracts change cold-run semantics; counterexamples recorded; **reject** for main (#9/#10).
- Make/Ninja correctly configured workflows remain faster on identical reruns; TraceJIT’s defensible difference is automatic discovery + correct recovery, not build-graph throughput (Phase G build-edit table).
- Hardware PMU/`perf` unavailable on evaluation host — **blocked**; wall-clock + phase timers only.

## 19. Related work

Prior art is reviewed in [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) and [COMPETITIVE_BENCHMARKS.md](COMPETITIVE_BENCHMARKS.md). Attribution, not novelty claims:

| Area | Systems |
| --- | --- |
| Automatic process/command caching | Firebuild |
| Compiler caches | ccache, sccache |
| Build graphs | Bazel, Buck2, Make, Ninja, Rattle |
| Incremental computation | Salsa, Adapton |
| Record/replay & determinism | rr, Hermit |
| Enforcement | Linux seccomp, Landlock |
| Content-addressed storage | Nix store ideas; TraceJIT uses BLAKE3 CAS |
| CEGAR | classical software-model-checking literature; TraceJIT’s loop is an engineering workflow over effect abstractions |
| Online decisions | TraceJIT’s admission policies are cost models over tracing, not bandits in production |

TraceJIT does **not** claim superiority over Firebuild/ccache/sccache on matched workloads; ninja/ccache/sccache were absent on the Phase G host and were skipped, not invented.

## 20. Limitations

1. Validate→restore TOCTOU remains.
2. Multi-output restore not crash-atomic / not inode-preserving.
3. Observation ≠ full userspace dependency capture.
4. Certificates never claim `FullEquivalenceProof`.
5. Short-command floor; large restore+hash can lose to direct copy.
6. Python/shell/`cc -c` typically refused on native census.
7. Cache not encrypted; single-operator threat model.
8. TLA+ model not machine-checked against the binary.
9. No peer-reviewed publication; no production-adoption claim.

## 21. Future research

Deferred or blocked items only — not promises:

- Durable multi-file restore journal with measured fault injection.
- Privileged mount-namespace tests for bind-mount `/dev/null` (D-B9).
- Broader syscall modeling only with obligation suites (epoll fork/exec/`RLIMIT_NOFILE`/fd transfer before any merge of #7).
- Matched competitive runs once ninja/ccache/sccache/Firebuild are installed.
- Hardware-counter attribution when PMU/`perf` exist.
- Formal connection from TLA+ typestate to Rust hit path (**blocked** as full-system proof).

---

**Evidence index:** [README](../../README.md) · [CLAIMS_LEDGER](CLAIMS_LEDGER.md) · [FOCUS materials](../focus/APPLICATION_MATERIALS.md) · [EXECUTION_EQUIVALENCE](EXECUTION_EQUIVALENCE.md) · [benchmarks/results/](../../benchmarks/results/) · [SAFETY](../../SAFETY.md) · [ARCHITECTURE](../../ARCHITECTURE.md)

**Appendix — superseded narrative:** The 9 November 2026 public-`f90b4db` report and Phase 3A–3G addenda remain in git history; this Part XVIII rewrite supersedes them as the living technical report. Historical numbers above keep their original commits.
