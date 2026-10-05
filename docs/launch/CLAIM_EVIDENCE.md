# Claim evidence

This table is for the 0.1.1 candidate. Quantitative rows are historical. They were not remeasured on this commit. The runtime hit path since `e9684c1` changed only by refusing writable shared file mappings. The synthetic transform does not use that mapping, so the old median is not a silent claim about 0.1.1's speed.

| Claim | Source | Commit | Evidence | Status |
| --- | --- | --- | --- | --- |
| Linux x86_64 only | README, `doctor` | 0.1.1 tree | `cfg` gates and `doctor` on other machines | Code. Linux run is CI, not this Mac. |
| Observed dependency capture | README | 0.1.1 | ptrace loop and `reconstruct_dependencies` | Code. Demo asserts `numbers.txt` on Linux CI. |
| Synchronous guards before replay | SAFETY.md, `run` | 0.1.1 | `validate_all` then `restore_outputs` | Code. Not atomic with other processes. |
| Deoptimization on input change | README, demo | 0.1.1 | `scripts/demo.sh` requires `DEOPT` and forbids `HIT` | Asserted by the script. Not yet run on this commit's Linux CI. |
| ptrace | ARCHITECTURE | 0.1.1 | `tracejit-trace` | CI doctor must print `ptrace yes`. |
| seccomp and Landlock for PROVEN | SAFETY.md | 0.1.1 | `tracejit_sandbox::apply` | CI sets `TRACEJIT_REQUIRE_PROVEN=1` and fails if the sandbox test skips. |
| GUARDED reuse | README | 0.1.1 | classification plus guards | Integration test `RESULT guarded_hit PASS` required in CI. |
| 312.913 ms, 3.972 ms, 78.780x | README, break-even.md | `e9684c1` | harness, 5 warmups, 30 runs, Ubuntu 24.04 x86_64 | Historical. Not a 0.1.1 measurement. |
| 7.396 ms, 7.957 ms, 0.929468x | README, latest.md | `63e3363` | same harness shape | Historical loss. Not a 0.1.1 measurement. |
| Tracing the first run is slower | break-even.md | `e9684c1` | traced-cold column | Historical. |
| Short commands can lose | README | `63e3363` and the sweep at `e9684c1` | both result files | Historical. |
| explain summary | README | 0.1.1 | CLI printer; demo requires `observed inputs` | Not in the v0.1.0 binary. |
| doctor text | README | 0.1.1 | `doctor()` | Checked on macOS for the unsupported path. Linux wording is CI. |
| Python refused | break-even.md | `e9684c1` | `getrandom`, `gettid` | Historical harness output. |
| Shell and `cc -c` refused | break-even.md | `e9684c1` | classification `Unknown` | Historical. |
| UNKNOWN and NONDETERMINISTIC do not reuse | effects `cache_eligible` | 0.1.1 | unit tests and integration | Integration not run here. |
| Writable MAP_SHARED is UNKNOWN | ARCHITECTURE, fixtures | 0.1.1 | `mmap_shared_write`, `mmap_shared_mprotect` | Fixture added. Linux CI must run it. v0.1.0 did not do this. |
| vDSO clock can be invisible | SAFETY.md | 0.1.1 | no tracer hook for userspace vDSO | Open limitation. Not fixed. |
| TOCTOU between guard and restore | SAFETY.md, core `run` | 0.1.1 | validate, then restore, no filesystem freeze | Open limitation. Not claimed atomic. |
