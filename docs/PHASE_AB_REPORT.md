# Phase AB report: runtime determinism, output integrity, and real-world performance

**Start:** `fd6d0041ae731784c5e9453bff8accca96791ca1` (`main`, Phase AA1 merged as
PR #43), branch `research/phase-ab`.
**End:** `research/phase-ab`. Code commits: `6a72b11` (production change),
`e0e3035` (adversarial tests). Evidence, harnesses and this report: the commit
that adds `benchmarks/phase_ab/`, `benchmarks/results/phaseab/` and `docs/PHASE_AB_*`;
the merge base stays `fd6d004`.
**Baseline binary:** `daca8b0dc9fda100abd8801d9f6f619c0e1c3082981f20be2de8f1dd4361dbe4`
(built from `git archive HEAD` into a separate `CARGO_TARGET_DIR`).
**Head binary:** `d2f6173562e940e45287de5f391a71627a738c6af5d8dc77c0443b9a0f7f5452`.

Host: 8 vCPU, Linux, glibc 2.39-0ubuntu8.12, gcc 13.3.0, strace 6.8, ccache 4.10.2.
Every measurement in this phase is paired on this host. Numbers from Phase AA1
were taken on a 2 vCPU host and are quoted, never merged, as such.

## 1. What changed in the product

Exactly one production change, in `crates/tracejit-cache`:

```rust
if outputs.is_empty() {
    return Ok(OutputRestore::Nothing);
}
```

A record with no workspace outputs no longer writes, fsyncs, renames and clears a
restore intent that could never protect anything. Everything else is unchanged:
no admission rule, no classification rule, no guard, no identity, no schema.

Supporting, non-production changes: five benchmark harnesses under
`benchmarks/phase_ab/`, their raw results under `benchmarks/results/phaseab/`, two
new adversarial tests (one cache unit test, one integration test) plus a fixture
case, and four documents.

## 2. Intermittent GCC entropy: root cause, closed

**Cause.** glibc's `mkstemps` → `__gen_tempname` fills its suffix-pattern buffer
with a rejection sample: `getrandom(stack_buf, 8, GRND_NONBLOCK)` mixed with
`clock_gettime(MONOTONIC)` and a word from the caller's uninitialised stack,
re-tried until the value exceeds a fixed bound. Disassembly of the exact build
shows the bound `0xf49998db0aa753ff`, a pass probability of
`1 − 0xf49998db0aa753ff/2⁶⁴ = 4.45 %`. The gcc driver calls it once per
invocation to name its temporary assembly file. TraceJIT refuses the
unabsorbed effect, so the invocation becomes `Nondeterministic` with probability
equal to the draw's.

Provenance was established by `strace -f -k`: the call returns to
`libc+0x66b4e`, immediately after `call mkstemps@plt`, from the gcc driver — not
from a plugin, loader hardening, hash-table seeding or `cc1`. The three
`getrandom` calls present in *every* run are the glibc tcache seeds
(`libc+0xa9e69`, key `0xb178`), which the allocator contract already absorbs.

**Rate, at 1,000 trials** (`gcc-cc-small-tu`):

| Measurement | Value |
| --- | --- |
| Native runs containing the stack-destination draw | 29/1000 = 2.9 % |
| TraceJIT cold traces refused | **57/1000 = 5.7 %** (95 % CI 4.3–7.1 %) |
| Read effect count: accepted / refused | 304 / 305 (55 runs) or 306 (2 runs) |

The two rates differ because the compiler contract *supplies*
`clock_gettime`, so only the stack word varies — and the sampled word is caller
stack, so the rate also moves with the invocation (argv, env, call depth). In the
make-driven build of §3 the same mechanism measured 2.3 % (9 refusals in 384
invocations, 9 of 12 cold builds). Every refusal carries exactly one extra
unabsorbed read per draw — a single mechanism, not a family of intermittent
defects.

**Remedy chosen: preserve strict refusal** (option A). The bytes become a
temp file name that `gcc` passes to `cc1`, `as` and `ld` on the command line —
application-visible output, and a path that a concurrent or hostile process could
predict. No sound admission rule exists for it, so none was added.

Rejected, with measurement:

| Remedy | Result |
| --- | --- |
| `gcc -pipe` (remove the temp file) | object byte-identical, but **100/100 refused**: `fstat` on a pipe is `Unknown`. Worse on every axis. |
| Extend the allocator-entropy contract to compiler randomness | rejected: the contract proves "libc seeded its allocator"; it says nothing about a name that reaches `exec` arguments |
| Preflight prediction | implemented as tooling (`entropy_predict.py`, static ELF dynsym scan). It predicted 0.20 for the gcc driver and 0.00 for `readelf`/`gzip`/`sed`, matching the observed pattern, but it is a *hint* for benchmark authors and never changes eligibility |
| Diagnostics | improved in the existing refusal message path; no new user-facing flag |

Unresolved: none. The residual rate is a property of glibc and the audit policy,
not a defect.

## 3. Output integrity: measured against Make and ccache, and the answer is "not as an increment"

Whole-build experiment: Lua 5.4.6, 32 units in `liblua.a`, its own Makefile, four
arms, twelve mutation schedules, every artifact compared with a clean reference.
Full analysis in `OUTPUT_INTEGRITY_ECONOMICS.md`; the three results that matter:

1. **Timing.** Warm 32-unit rebuild: `make` 7.29 s, ccache **0.19 s**, TraceJIT
   **3.20 s** (16× make, 1/17 of ccache's speed-up). Cold: 8.99 s ccache,
   15.2–16.8 s TraceJIT, 7.37 s make.
2. **Repair needs to be asked.** In every corruption schedule, `make` considered
   the artifact current and issued no compile; none of the three caches repaired
   anything. Integrity is not a property a cache can add to a build system that
   does not consult it. Nine of the twelve cold builds also contained exactly one
   entropy refusal, and every one of them still produced correct artifacts.
3. **Reuse can leave an archive stale.** When TraceJIT *did* restore a corrupted
   object (1 hit, 110 ms), the restored object kept its recorded mtime, older
   than the archive built from the corrupted bytes, so `ar u` left the corrupted
   member in `liblua.a`. ccache's restored object is written fresh and the
   archive was corrected. Verified by comparing archive members with `ar p`.

So the "integrity premium" over ccache is negative: it costs ~3 s per full
rebuild and provides no repair ccache does not provide, and in archive builds it
can do worse than recompiling. The defensible claim is *guarded, verified
whole-command reuse*, not "output integrity repair".

## 4. Warm-hit floor: one change, measured paired

`Cache::restore_outputs` was paying one durable restore intent (write + fsync +
rename + directory fsync) on **every** hit, including pure filters with no
destination. Skipping it when the output list is empty is the only optimization
this phase accepted.

Paired, interleaved, 25 rounds, twin workspaces, both sides verified `HIT` with
byte-identical stdout (`ab_hits.py`):

| Workload | before | after | Δ (95 % CI) | distinguishable |
| --- | ---: | ---: | --- | --- |
| `cut-columns` | 13.77 ms | 11.29 ms | −1.91 (−1.65 … −2.71) | yes |
| `gzip-6-stdout` | 8.17 ms | 5.88 ms | −2.22 (−1.87 … −2.79) | yes |
| `sed-substitute-file` | 16.83 ms | 14.00 ms | −2.45 (−1.12 … −3.90) | yes |
| `gcc-cc-small-tu` (control: has an output) | 63.83 ms | 61.66 ms | −2.63 (−2.35 … +4.29) | **no** |

In the frozen corpus smoke, `gzip -6` moved from a 0.77× loss to
`warm_ratio 0.92, CI [0.86, 1.00]` — indistinguishable from native — and
`gcc-cc-small-tu` now measures 1.22× `[1.06, 1.40]` on this host. A hit on a
6 ms filter is now at parity instead of a loss; that is the difference between
"fixed cost makes short commands unusable" and "short filters are neutral".

## 5. Persistence and startup: corrections to Phase AA1

* **Persistence is paid once per record, not per hit.** Measured per sample on
  `/bin/true`: cold trace stores the record (no phase file — instrumentation gap),
  first hit writes the `Executed → Reused` decision (**4.57 ms**), and steady-state
  hits write nothing (`decision_persist_ns = 0`). Phase AA1's "3.5–20 ms per hit"
  is the first-hit cost.
* **The pre-runtime band is 2–4 ms, not 6.5–16 ms.** `tracejit --version` is
  2.3–2.9 ms; identity + SQLite open + schema + query + decode is 1.6–3.1 ms;
  Phase AA1's residual also contained the harness's fork/exec/wait.
* The compiler hit is guard-dominated: 48.4 ms of a 52.0 ms core, hashing 107 MB
  of which 66 MB is the same compiler image under three guard kinds.

No persistence or startup change was made: there is nothing to remove without
weakening the crash contract. Candidates examined and rejected are listed in
`HIT_OVERHEAD_PROFILE.md` §4.

## 6. Eligibility and incorrect HITs

Eligibility is **unchanged**. No admission, classification, identity or guard
rule was touched, so the per-workload outcomes of Phase AA1 (native 2/49,
allocator 12/49, compiler 19/49) stand. The frozen corpus smoke at this head
reproduced the protocol's accounting: 42 declared cells, 40 attempted, 10 reused,
8 timed rows, schema and accounting valid.

Incorrect HITs: **0** in differential fuzzing (seed 29), the W1 oracle (13/13),
the corpus smoke, the adversarial suite, and the whole-build experiment (every
object compared with a clean reference). The 9 refusals observed in 384
first-compile build invocations are the documented entropy draw, not incorrect
reuse.

## 7. Gates

`cargo fmt --all -- --check` pass · `cargo clippy --workspace --all-targets
--all-features -- -D warnings` pass · `cargo test --workspace --no-fail-fast`
pass · `cargo test -p tracejit-cli --test linux_integration -- --test-threads=4`
85/85 · `cargo audit` pass (110 crates) · state-machine model check PASS with the
`restore_crash` two-state limitation · differential fuzz seed 29 PASS, 0
incorrect hits · restore fault injection PASS (soft-fail retrace, hard-kill
recovery) · W1 adversarial oracle 13/13 · frozen corpus smoke pass. Detail in
`PHASE_AB_CORRECTNESS_AUDIT.md`.

CI on this head: **not verifiable from the authoring environment** — no GitHub
API credentials are available here (`gh` unauthenticated), so the branch was
pushed and the PR carries the workflow run. Every job the workflow runs was
executed locally and passed, but "green on CI" is an unverified claim until
somebody with repository access confirms it.

## 8. Experiment ledger

Accepted:

| # | Experiment | Why accepted |
| --- | --- | --- |
| A1 | Skip restore intent for zero-output records | paired 1.9–2.5 ms on four workloads, unit + integration regression, crash semantics unchanged |
| A2 | Entropy preflight predictor (tooling) | predicts ineligibility from static dynsym without substituting entropy; used for corpus design, never for admission |
| A3 | Whole-build harness (`build_integrity.py`) | the first evidence at build scale; produced the archive-staleness finding |

Rejected:

| # | Experiment | Why rejected |
| --- | --- | --- |
| R1 | `-pipe` compiler guidance to dodge the draw | 100/100 refused (pipe `fstat`), byte-identical objects |
| R2 | Contract extension for compiler temp-name entropy | application-visible name; no proof of unobservability |
| R3 | Exclude `TRACEJIT_CACHE_DIR` from identity | an application may read it; excluding it is unsound |
| R4 | Field-precise metadata guards (drop `atime` for content reads) | sound design, needs a record-format change and a full adversarial matrix; deferred, not rushed |
| R5 | One digest per file per pass | unproven within-pass mutation; Phase X's counterexample applies |
| R6 | Parallel guard validation | Phase W measured 111.7 → 110.6 ms |
| R7 | Daemon / shared-memory cache | not justified for a 2–4 ms band; rejected on complexity grounds |
| R8 | Batch or drop durable writes | would weaken crash consistency for <1 ms |
| R9 | Rewrite restored mtimes to "now" | changes the metadata contract to fix an archive-build symptom; recorded instead |

## 9. Did v0.3 readiness improve?

**No, materially it did not.** One real improvement (short-command hits at
parity, worth 1.9–2.5 ms per filter hit) and one root cause closed with numbers.
Neither moves a release gate: the version label is still `0.2.0-beta.1` for
post-beta code, CI on the exact head is still unverified from here, the
validate→restore TOCTOU window is unchanged, and the archive-staleness
limitation is *new* information a v0.3 note would have to carry. The competitive
picture is now measured at build scale and is worse than the per-command picture
suggested: ccache is 17× faster on warm rebuilds.

## 10. Next three highest-value tasks

1. **Field-precise metadata guards.** The only change identified that increases
   eligibility without touching a correctness rule: keep `atime` for recorded
   metadata observations, drop it for content reads. Unblocks `gzip -9`, `strip`,
   `objcopy`. Needs a versioned record format and an adversarial matrix.
2. **Decide the restored-output timestamp semantics.** The archive-staleness
   finding is a real correctness-adjacent defect in packed builds. Either restore
   outputs with a current mtime (and document the Obs-contract consequence) or
   document and test the "treat as unchanged" rule. Do not leave it implicit.
3. **Position the product where ccache cannot go.** Non-compiler whole commands
   (`sort`, `tar`, `objdump`, `gzip`, custom tooling) have no incumbent; compiler
   invocations do, and it wins by 17×. Either make the non-compiler case the
   documented use and strengthen it, or stop claiming the compiler case.

## 11. Reproducing

```bash
cargo build --workspace --release
python3 benchmarks/phase_ab/entropy_study.py --workload gcc-cc-small-tu --trials 1000 \
  --vendor <vendor-dir> --output <out>.json
python3 benchmarks/phase_ab/ab_hits.py --a <baseline-binary> --b target/release/tracejit \
  --vendor <vendor-dir> --workloads cut-columns,gzip-6-stdout,sed-substitute-file,gcc-cc-small-tu \
  --output <out>.json
python3 benchmarks/phase_ab/build_integrity.py --tracejit target/release/tracejit \
  --ccache <ccache> --source <lua-5.4.6.tar.gz> --output <out>.json
AA_MODE=smoke AA_SKIP_BUILD=1 benchmarks/realworld_v2/run.sh
```

Raw data: `benchmarks/results/phaseab/{entropy_study_1000,entropy_study_small,
entropy_predict,hit_profile_baseline,hit_profile_after,ab_hits,build_integrity}.json`
and `benchmarks/results/phaseab/smoke/`.
