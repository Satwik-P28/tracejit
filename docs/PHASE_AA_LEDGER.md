# Phase AA hypothesis ledger

Accepted and rejected hypotheses, with the measurement that decided them and
where the evidence lives. Exact medians, intervals and raw samples are in
`benchmarks/results/phaseaa/results.json`; this file records the *decisions*, so
a later phase does not have to re-litigate them.

Protocol version: `tracejit.realworld.results/v1`. Corpus: 59 workloads, 177
(tier, policy) rows. Host: 2-vCPU shared Linux VM, Ubuntu 24.04, glibc
`2.39-0ubuntu8.12`, ext4.

## Accepted

| # | Hypothesis | Deciding evidence | Where |
| --- | --- | --- | --- |
| A1 | Native and contract eligibility must not be reported as one number | On the identical 49 attempted tier-A workloads: native 1 eligible, `allocator-entropy-v1` 9, `compiler-runtime-v1` 15. A single "eligibility" figure would have been off by 15× depending on which policy the reader assumed. | `aggregate.eligibility_by_tier_and_policy` |
| A2 | `compiler-runtime-v1` makes real compiler workloads reusable | `gcc-cc-heavy-tu` (zlib 1.3.1 `deflate.c`, `-O2`) is refused natively and reused under the contract with a large, low-variance win. | `raw/gcc-cc-heavy-tu__compiler-runtime-v1.json` |
| A3 | Compute-bound commands whose output is smaller than their cost are the honest win | `c-numeric-integration` (60 M-step reduction, no file inputs) repays its cold trace on the **first** repeat. | `raw/c-numeric-integration__*.json` |
| A4 | A fixed hit cost dominates short commands | Every timed workload with a direct median below ~15 ms lost. The cheapest warm hit measured was 11.4 ms and a small command's floor is 13–17 ms, before any output work. | `results.md` |
| A5 | Guard validation, not restoration, dominates compiler hits | `guard_validation_ns` was 52–72 ms of a 72–90 ms instrumented hit for every gcc workload; `cas_restore_ns` was 3–18 ms. | `timing.cost_model.stages_ns` |
| A6 | Persisting the decision record on a hit is a material cost | `decision_persist_ns` reached 8–23 ms on hits whose total was 70–90 ms. Not previously measured; a Phase AB candidate. | `timing.cost_model.stages_ns` |
| A7 | `make` is ineligible, and attempting to trace it costs real time | `make-build` refused under all three policies; the wrapper added ~50 ms per invocation versus native `make`. | `competitive.json` → `ineligible_command_overhead` |
| A8 | Moving the cache directory invalidates every record | `TRACEJIT_CACHE_DIR` is part of the inherited environment and the environment is hashed into the identity; a copied cache produced `Executed`/no eligible record. Reproduced twice. | `competitive.json` → `cache_relocation` |
| A9 | A missing output CAS object aborted the user's command | Removing an output blob made `tracejit run` exit 1 with `cache I/O failed` and **no execution**; the stream path already retraced. Fixed on this branch with a regression. | commit `c3f77d8`, `crates/tracejit-cache/src/lib.rs` |
| A10 | Returning to an earlier input state still deoptimises | After mutating and then restoring the input, `gzip` and `gcc` deoptimised although the original record existed. The barrier is the compiler/tool's own metadata observation, matching the Phase W finding. | `decisions[step=input_restored]` |
| A11 | A command that rewrites its own input can never be warmed | `fs-identical-rewrite` is classified `Guarded` and every first warm attempt deoptimises, because the recorded pre-state no longer holds after the command ran. | `raw/fs-identical-rewrite__native.json` |
| A12 | One candidate still reports "eligible" and then never hits | `nm-symbols` is `Guarded`, obtains no hit, and reproduces the documented metadata-guard (`atime`) limitation. | `raw/nm-symbols__*.json` |

## Rejected

| # | Hypothesis | Why it was rejected |
| --- | --- | --- |
| R1 | "The contract tier makes most real workloads reusable" | Tier-C workloads: 0/5 eligible under every policy (CPython/NumPy/Pillow all refuse on clock, identity or entropy). Tier A reaches only 15/49 even under the compiler contract. The dominant blockers stay: randomness 23, `getrusage` 10, `clock_gettime` 8, `getcwd`-class syscalls 16. |
| R2 | "Text tools are a good target" | `sed-substitute-file` is 5–6× slower warm; `sort-lines`, `awk-reduce` and `jq-sum` are refused. The direct commands are too cheap to repay hashing. |
| R3 | "Compression is a good target" | `gzip-6-stdout` is ~2× slower warm; `gzip-9-file` is slower still once the output is materialised. Compression output is as large as the work saved. |
| R4 | "Toolchain inspection commands are a good target" | `objdump`, `readelf` and `nm` are 4–7× slower warm: the direct command costs 2–4 ms and the hit costs 15–17 ms. |
| R5 | "Incremental `make` sessions benefit" | `make-build` and `make-incremental-noop` are refused; the competitive run shows the wrapper only adds overhead. |
| R6 | "Scientific Python / Parquet benefits" | `pyarrow` is unavailable; NumPy and Pillow workloads are refused on interpreter-level nondeterminism. |
| R7 | "The same-size/same-timestamp rewrite hazard is reachable on this host" | The attempt could not reproduce a ctime collision: `os.utime` restores mtime, but ctime moved by a measurable delta, so the guard saw the change and deoptimised. The hazard remains a documented theoretical window, not a reproduced failure here. |
| R8 | "The validate-to-restore race produces stale output often enough to measure" | 0 stale observations in 12 race trials. This is **not** evidence that the window is closed; it is evidence that a 12-trial probe at this timing granularity cannot find it. |

## Unsupported, kept as negative results

| Workload | Outcome |
| --- | --- |
| `cppcheck-project`, `shellcheck-script`, `ruff-check`, `zstd-19-file`, `parquet-convert` | `tool_unavailable` on this image; excluded from denominators |
| `make-build`, `make-clean`, `make-incremental-noop`, `make-header-change` | refused (`Unknown`) |
| `python-csv-json`, `py-compile`, `py-compileall`, `numpy-matmul`, `pil-image-transform` | refused (clock / process identity / entropy) |
| `node-compute`, `node-script-file`, `perl-reduce` | refused |
| `shell-pipeline`-shaped workloads | refused (pipe packetisation, `fstat` on a pipe) |

## Discipline notes

- No product optimization was implemented in Phase AA. The single product change
  (A9) is a robustness fix found by the harness, not a performance change, and it
  was not selected by looking at the held-out split.
- The held-out split (16 workloads) was declared before the run and executed
  once. Its rows are reported separately in `results.json`.
- Every adaptation is listed in `manifest.json` under `adaptations`; nothing
  adapted is described as unmodified.
