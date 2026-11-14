# TraceJIT — executive summary (1 page)

**What.** Fail-closed memoization of unmodified Linux x86_64 commands: ptrace observation → effect classification → synchronous guards → BLAKE3 CAS replay only for `GUARDED`/`PROVEN`.

**Why hard.** Declared graphs and compiler wrappers already know their inputs. Transparent reuse must infer dependencies from kernel crossings without inventing hits for clocks, entropy, unmodeled syscalls, or races. A false HIT is a critical failure; a refused reuse is acceptable.

**Correctness contract (stops where).** Obs match under the modeled effect taxonomy and installed guards/`PROVEN` enforcement. It does **not** claim full execution equivalence, freeze other processes (validate→restore TOCTOU remains), crash-atomic multi-file restore under hard kill, or peer-reviewed novelty.

**Evidence (final adversarial PRs #26–#30 on main@`827b776`).**

- P0: process refuses (O_TMPFILE/fcntl), pre-restore TOCTOU recheck, restore-intent refuse HIT after hard kill.
- P1: 32-workload census (1/32 HIT); e2e warm transform ~7.4× vs DIRECT with bootstrap CIs; short-command floor loss retained; CurrentAuto admission preferred; CEGAR never auto-deploys; modelcheck+fuzz 0 incorrect hits; prior-art matrix with licenses.

**Release posture.** Verified subset shipped; selective tracing, DAG validator, SQLite advisory bump, and controlled-runtime research remain deferred/rejected as documented. No invented metrics.
