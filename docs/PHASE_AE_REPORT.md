# Phase AE report — competitive evidence audit, cross-environment validation, correctness qualification

Phase AE closed the Phase AD evidence loop. It corrected the measurement and reporting defects
that made Phase AD's competitive claim too strong, established a two-version Firebuild baseline,
executed TraceJIT in a second Linux userspace, re-derived the TOCTOU boundary from the code that
actually ships, re-profiled verified replay against measured lower bounds, and rewrote the
claims that the paper and the release notes may use.

Nothing in this phase changes product behaviour. Every change is a harness, a measurement, a
regression, or a document.

## 1. Commits

| item | commit |
| --- | --- |
| Phase AD head / review baseline | `98cbb84a36b9c55dfee516afb26f61588626aa7d` (branch `research/phase-ad`) |
| main at the start of the phase | `68ba4067afd4391c90af9a64ce0b43397438d504` (merge of PR #44) |
| PR #45 head at the start of the phase | `84b9072` (remote `research/phase-ad`), plus local `4880bd4` in a sibling worktree |
| Phase AE work | this branch (`freebuff/a2fee7edda38fc9e50f9ffdf`), commits listed in the final message and in `git log 84b9072..HEAD` |

PR #44 is **merged** (main is its merge commit). PR #45 is **open and draft**; its head could not
be advanced from this environment and no CI run could be read back (see §2).

## 2. PR and CI status, stated exactly

* PR #44: merged; `main = 68ba406` is `Merge pull request #44 from Satwik-P28/research/phase-ab`.
* PR #45: open, unmerged, draft. `refs/pull/45/head` was `84b9072`; a sibling branch held one
  further commit (`4880bd4`).
* **CI status is unknown, not green.** `gh` is unauthenticated, the GitHub REST API returned
  `403 API rate limit exceeded` for this host, and Actions annotations are not reachable from
  the sandbox. No workflow result is claimed for any head in this report. All gate results
  below were produced locally on the exact tree that was pushed.

## 3. Corrected session measurements

Phase AD's harness populated the cache before the timer. Phase AE measures two experiments
separately (`benchmarks/phase_ae/competitive_matrix.py`):

* **cold** — a brand-new cache per session; the first trace, later reuse, refusals and
  deoptimizations are all charged to the arm. This is what a new user pays.
* **steady** — the cache is populated outside the timer, and only the measured window is
  reported. Every such row is labelled `steady` in `matrix.json` and in `economics.json`.

Sessions of 2, 3, 10, 25 and 100 invocations; 5 randomized paired repeats; every invocation
verified against a native oracle for the input variant actually on disk. Median session wall
clock, milliseconds (cold unless stated):

| workload (n=25) | native | TraceJIT AE | TraceJIT native | FB 0.8.2 | FB 0.8.6.2 | FB 0.8.6.2 tuned | TraceJIT steady |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bzip2 -9 -k, 1 MiB | 2846.7 | **545.3** | 5007.6 | 2976.9 | 3119.4 | 3065.6 | 444.7 |
| gzip -9 -n -k, 1 MiB | 882.7 | 425.0 | 1362.9 | 1154.6 | **254.7** | 243.4 | 373.8 |
| gzip -9 -n -c, 1.2 MiB text | 1856.3 | **276.9** | 261.9 | 299.9 | 268.0 | 260.7 | 167.9 |
| sed, 200k lines | 1824.1 | 885.8 | 6125.0 | 2071.2 | 2113.9 | **561.4** | 606.6 |
| sha256sum, 1 MiB | **94.5** | 377.2 | 916.3 | 282.1 | 247.9 | 217.8 | 363.9 |

The mutation schedule (`gzip-mutating`, input rewritten before every third invocation) removes
the reuse on exactly the mutated invocations for every engine: TraceJIT 2 hits of 5 at n=10,
Firebuild 2 hits of 5. No engine serves a stale result across a mutation **before** validation.

## 4. Verified competitor versions

| arm | version | origin | measured binary sha256 |
| --- | --- | --- | --- |
| `fb082-*` | 0.8.2 | Ubuntu multiverse debs (`e8ed7bfd…`, `64268359…`), user-space extraction | `cffadc1609425775fcacc51f8d5fbd811b229fd0ddf89ab9a0efc7e87000f510` |
| `fb862-*` | 0.8.6.2 | source tarball `v0.8.6.2`, CMake+gcc build, pinned dependency set | `8c895da049adcae026a99ac7d208a5691d0f92047fb932680f820938afc930e3` |

No prebuilt 0.8.6.2 artifact exists; the source build is the only route and is not
bit-reproducible across compilers (an earlier clang build produced `d646a662…`). Details and the
`LD_PRELOAD`/build-tree trap are in `docs/FIREBUILD_CROSS_VERSION_RESULTS.md`.

## 5. Competitive results where both engines genuinely reuse

| workload | TraceJIT per-invocation | Firebuild 0.8.6.2 per-invocation | verdict |
| --- | ---: | ---: | --- |
| gzip -9 -n -c, 1.2 MiB text stdout | 6.56 ms [6.49–6.72] | 7.47 ms [7.36–7.61] | TraceJIT ~12 % faster |
| gzip -9 -n -k, 1 MiB file output | 15.02 ms [14.61–15.65] | 8.28 ms [8.14–8.47] | **Firebuild 1.67× faster** |
| sed, 200k lines (Firebuild tuned) | 25.08 ms [24.40–25.61] | 19.16 ms [18.77–19.42] | **Firebuild faster** |
| sha256sum, 1 MiB | 12.89 ms | 9.30 ms | neither is profitable; Firebuild less bad |

Where only one engine reuses: **bzip2 -9 -k** — TraceJIT only (Firebuild 0.8.2 and 0.8.6.2
refuse: `Changing file timestamps is not supported`). Where neither reuses profitably:
`sha256sum` below ~10 MiB. Where Firebuild reuses only with its tuned configuration: `sed`
(`processes.skip_cache` cleared). Only the "both reuse" rows support a performance comparison;
the others are applicability statements. Phase AD's "wins the artifact-producing niche
outright" is withdrawn.

## 6. Actual correctness-policy distinctions

| property | TraceJIT | Firebuild 0.8.2 / 0.8.6.2 |
| --- | --- | --- |
| input validation at reuse | YES — every guard re-hashed before exposure | YES — `pio_matches_fs` compares type, size, mode and content hash |
| same-size rewrite with restored mtime | detected (content hash) | **also detected** (content hash) — Phase AD's "unvalidated" claim retracted |
| clock-dependent output, default config | refused under every policy | **replayed, stale** (`date +%s`, `time.time_ns()`) |
| clock-dependent output, strict config | refused | refused to *cache* (`ignore-time-queries` removed); no stale replay |
| allocator entropy | refused natively; admitted only under `allocator-entropy-v1` (audited libc) | absorbed/ignored |
| cached-object integrity | object re-hashed before exposure; corruption → `MISS`, re-execute | **no verification**: one flipped byte is replayed |
| unsupported effects | `UNKNOWN`/`NONDETERMINISTIC` → refuse/deoptimise | interposed, ignored or quirked |

## 7. Tested Linux environments

Two, plus one prepared:

1. Ubuntu 24.04.3, glibc 2.39, kernel 6.1.102, ext4, `lsm=capability,selinux` (no Landlock).
2. Ubuntu 25.10, glibc 2.42, **same kernel**, entered through `unshare -Urmpf` + `chroot`; the
   tracer and its workload ran correctly and produced byte-identical output, but the
   `allocator-entropy-v1` contract is unavailable for an unaudited libc, so nothing was
   `GUARDED`: no reuse.
3. GitHub Actions `ubuntu-24.04` — workflow prepared, **no result read back**, and a
   vendor-hosted runner is not independent third-party reproduction.

One kernel only; Landlock could not be exercised anywhere. Details:
`docs/MULTI_ENVIRONMENT_VALIDATION.md`.

## 8. Enforcement results

* Guarded reuse works (E1: second run `Reused`).
* `--enforce` **never reuses** on a host that cannot produce a `PROVEN` candidate
  (`lib.rs:471`), labels no run `PROVEN`, and still executes the command successfully — the
  documented fail-closed fallback.
* `doctor` reports `proven=false`, `landlock_abi=null`, `seccomp=true`.
* The Phase AE probe previously derived "enforcement is consistent" from
  `enforced == doctor.proven`, which is vacuously true when both are false. The probe now
  records guarded and enforce arms separately and asserts two falsifiable properties
  (`label_never_exceeds_capability`, `enforce_refuses_reuse_without_proven_capability`).
* `PROVEN` is **not** an equivalence proof (`SAFETY.md`): it records that seccomp-BPF and
  Landlock ABI ≥ 3 were installed. The label invites misreading; renaming is deferred with a
  migration plan rather than done silently.

## 9. Residual TOCTOU findings

Warm reuse performs **one** surviving validation pass. Measured
(`benchmarks/results/phaseae/toctou_race.json`, regenerated this phase):

| injection point | result |
| --- | --- |
| before validation | deoptimised, re-executed, new-input output |
| before cached streams load | deoptimised, re-executed |
| mutate-then-revert (metadata changes) | deoptimised (mtime guard) |
| **after validation, before apply** | **`Reused`, stale bytes served** |
| concurrent writer during hashing (8/8 trials) | deoptimised, re-executed |

No userspace-only mitigation both works and is economical: descriptor pinning misses in-place
writes, read-only bind mounts do not freeze the inode, Landlock confines the traced tree and not
unrelated writers, snapshots redefine the observable semantics, and cooperative locks are not a
guarantee. The prerelease must therefore state the operating assumption (no external writer
during reuse) rather than claim atomicity. `docs/TOCTOU_CORRECTNESS_BOUNDARY.md`.

## 10. Validated replay performance and lower bounds

100 MiB HIT, disjoint phase timers (median of five):

| case | total | guard validation | stdio replay | present | cas restore |
| --- | ---: | ---: | ---: | ---: | ---: |
| gzip text → stdout (19.9 MB out) | 79.8 ms | 39.4 | 19.2 | 12.8 | 0 |
| gzip incompressible → stdout (100 MiB out) | 257.8 ms | 38.8 | 86.1 | 57.5 | 0 |
| gzip text 10 MiB → file | 22.5 ms | 8.0 | 0 | 0 | 10.0 |
| sha256sum 100 MiB | 52.0 ms | 46.5 | 0 | 0 | 0 |

Measured bounds: sequential read 6.25 GiB/s, `memcpy` 4.40 GiB/s, write+`fdatasync`
0.35 GiB/s, 4 KiB `fsync` 0.69 ms, BLAKE3 over the recorded input ≈2.54 GiB/s (derived from the
guard phase). A verified replay of 100 MiB cannot cost less than ≈95 ms; the measured 257.8 ms
is dominated by post-verification buffering and a 57.5 ms pipe write. No optimisation is
promoted: the only remaining candidate (a faster BLAKE3 build) is unmeasured, and every other
candidate would expose unverified bytes or weaken a guard.
`docs/VALIDATED_REPLAY_PERFORMANCE.md`.

## 11. Incorrect HITs, by contract

* **Inside TraceJIT's declared contract: zero.** All 798 matrix rows are `all_correct`; every
  invocation was compared to an independent native oracle. Policy probes: no incorrect output.
  Integrity probe: corruption → `MISS` + correct output.
* **Inside Firebuild's own stated contract: zero observed.** Same-mtime rewrites are detected;
  mutations are detected. The corrupted-blob replay is a cache-integrity failure, not a
  contract violation of its stated reuse rule, and is reported as such.
* **Outside every contract, by design:** the post-validation mutation makes TraceJIT serve stale
  bytes. It is documented, reproducible, and excluded from the guarantee.

## 12. Full correctness gates (local, exact pushed tree)

| gate | result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace` | pass — 283 passed, 1 ignored (includes 85 `linux_integration`, 40 cache tests) |
| `benchmarks/phase_ae/test_accounting.py` | pass — 17 tests |
| `benchmarks/realworld_v2/test_harness.py` | pass (exit 0) |
| `scripts/modelcheck/check_state_machines.py` | PASS (`RESULT phase-k3-modelcheck PASS`) |
| `scripts/phase_k4_restore_fault.sh` | PASS both scenarios (soft-fail retrace, hard-kill recovery) |
| `scripts/check-version-consistency.sh` | PASS (0.2.0-beta.1) |
| fresh-checkout build + reuse smoke (`git archive` → `cargo build --release` → HIT) | pass |
| `cargo audit --deny warnings` (cargo-audit 0.23.0, 1567 advisories) | pass — 0 vulnerabilities in 110 dependencies |
| Phase AE probes (matrix, policy, integrity, TOCTOU, environment, multi-environment) | pass / documented results |
| release packaging and install (`package-release.sh`, `clean-install-verify.sh`) | **not run** |
| GitHub Actions on the final head | **not observable** (see §2) |

## 13. Accepted and rejected optimisations

Accepted: none in product code.

Rejected with evidence: fused hash-and-write and streaming cached bytes (expose unverified
bytes), mmap replay (`memcpy` is not the bottleneck; new failure mode), metadata-only revalidation
fast path (reintroduces the same-timestamp defect), cached guard results between runs (weaker
contract), removal of the `present` copy (that copy is the exposure step), cooperative locking
and snapshot semantics (not guarantees; change observable behaviour), and a faster BLAKE3 build
(not yet measured; the single justified future candidate).

## 14. Defensible paper contribution

**C: correctness/performance trade-offs in execution caching**, with negative results as the
evaluation's spine. The mechanism alone is a composition of known parts; the defensible claims
are the contract discipline, the measured price of verified replay, the measured competitor
distinctions, and the preserved negative results. Prior art and forbidden wording:
`docs/PAPER_CLAIMS_LEDGER.md`.

## 15. v0.3 release-readiness verdict

**Qualified as a research prerelease, not as a stable beta.** The evidence now supports honest
statements about a narrow niche, and the false competitive claims are withdrawn. The remaining
blockers are engineering or capability items, not marketing language:

1. `PROVEN` has never been exercised: no Landlock-capable host in the matrix, so the
   enforcement path is unqualified end-to-end. This blocks any claim that enforcement works.
2. The residual validation-to-restore race is open; it must be disclosed as an operating
   assumption in the release notes.
3. Reuse outside audited glibc builds is unavailable for ordinary programs (`allocator-entropy-v1`
   is libc-build specific). The release must say so.
4. One kernel, two userspaces, one competitor family, one operator: no independent reproduction.
5. The release packaging and clean-install gates were not run in this environment.

## 16. Remaining release blockers, ordered

1. **Landlock/namespace-enforced host** — run `--enforce`, install seccomp+Landlock, exercise a
   `PROVEN` reuse, a policy-installation refusal, and an unexpected-syscall denial. Owner:
   infrastructure.
2. **TOCTOU disclosure and, if possible, an isolated-workspace mode** — documentation first;
   engineering only if a real workflow needs live-workspace reuse under concurrent writers.
3. **Second kernel and second operator** — the only way to make the environment matrix mean
   something. Owner: infrastructure.
4. **Audited libc coverage** — decide whether to audit a second glibc build or to describe
   `allocator-entropy-v1` as a 24.04-only entitlement.
5. **Release packaging gate** — run `package-release.sh` and `clean-install-verify.sh` on the
   final tree before tagging.

No new development roadmap is proposed: the research artefact is defensible at its current
scope once items 2 and 5 are executed and items 1, 3 and 4 are stated as limitations.
