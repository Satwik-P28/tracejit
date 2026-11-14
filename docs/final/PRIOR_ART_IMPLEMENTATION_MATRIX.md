# Prior-art implementation matrix (§14)

Date: 2026-11-14  
TraceJIT tip context: `bb4302fccaf780d53287dde557f984adc2615870`  
Method: read public docs + listed source paths at the cited commits (GitHub). **No code copied** from incompatible licenses. Prefer independent reimplementation of well-known interfaces.

| Project | Ref commit | File / function | Technique | Target problem | Applicability to TraceJIT | License | Risk | Experiment | Measured / decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strace | `3a4f0c7c3969` | `doc/INTERNALS.md`; `src/filter_seccomp.c`; `src/strace.c` (`next_event` / `dispatch_event`) | ptrace event loop; optional `--seccomp-bpf` selective stops (`SECCOMP_RET_TRACE` / `ALLOW`) | Low-overhead filtered syscall tracing | Observation pedagogy; selective tracing **deferred** until complete-event proof (§6) | LGPL-2.1-or-later (program); tests GPL-2 | License OK to study; do not vendor | Study only | **Rejected** as production selective backend for now |
| rr | `a8089421921a` | `src/AddressSpace.*`; `src/AutoRemoteSyscalls.*`; record/replay session code under `src/` | Full record/replay + syscall buffering ideas | Deterministic replay | Different product (replay ≠ whole-command reuse) | MIT (LICENSE) | Semantic mismatch if ported naively | Study only | **Rejected** as TraceJIT architecture |
| ccache | `ff29a9daf9cc` | `src/ccache/ccache.cpp`; `hash.cpp` / `hashutil.cpp`; `storage/`; direct-mode docs | Compiler-aware multi-result cache; manifest of includes | Compiler build caching | Not a compiler wrapper; native `cc` census refuses | GPL-3.0-or-later | **Incompatible** for code import into Apache/MIT-style crates without careful isolation | Study manifests | **Rejected** code reuse; idea of multi-candidate retention already independently implemented |
| sccache | `ca81ec2a2566` | `src/compiler/`; `src/cache/`; `src/server.rs` | Distributed/local compiler wrapper cache | Toolchain-keyed compilation | Same non-overlap as ccache for transparent cmds | Apache-2.0 | Low copy risk if ever needed; still wrong abstraction | Not installed on census host | **Not ported**; skipped competitor arm when absent |
| Firebuild | `4b6e21d83afc` | `src/interceptor/`; `src/firebuild/` | LD_PRELOAD intercept + command cache/replay | Transparent acceleration | Closest *goal* overlap; different observation stack | Proprietary / commercial trial (`LICENSE.md`) | **Do not copy**; redistribution restrictions | Not installed here | **Rejected** code reuse; no superiority claim (K8/K10) |
| Buck2 DICE | `560c92af07b3` | `app/buck2_common/src/dice.rs` + `dice/`; docs `rule_authors/incremental_actions.md` | Versioned incremental computation / value equality | Owned build graph invalidation | Needs trustworthy change channel TraceJIT lacks for arbitrary processes | Apache-2.0 (Buck2) | Wrong ownership model if forced | Design only (§7) | **Deferred**; typed DAG design boundary only |
| Linux seccomp | kernel docs (stable) | `userspace-api/seccomp_filter.html` | BPF syscall filter; `SECCOMP_RET_TRACE` | Confinement / selective trap | Used for `PROVEN` install via `tracejit-sandbox` | Kernel license (study API) | Incomplete isolation if overclaimed | Installed path required for PROVEN | **Accepted** as enforcement dependency, not novelty |
| Linux Landlock | kernel docs (stable) | `userspace-api/landlock.html` | Unprivileged path access control | Path confinement | Required with seccomp for PROVEN | Kernel license (study API) | Same | ABI 3+ required | **Accepted** as enforcement dependency, not novelty |
| Nix store | docs | Content-addressed store manual | CAS identity | Hermetic artifacts | Informs BLAKE3 CAS engineering only | NixOS license (docs) | Overclaim hermeticity | Independent CAS | **Idea only**; no Nix code |
| Kernel ptrace | man/kernel | `PTRACE_O_TRACE*` / syscall-stop | Process observation | TraceJIT tracer basis | Core V1 mechanism | Kernel | Incomplete without event coverage discipline | Production | **Accepted** baseline |

## Licensing discipline

- **No Firebuild code** (commercial/restricted `LICENSE.md`).
- **No ccache code** (GPL-3) into the TraceJIT tree.
- strace/rr studied for algorithms and failure modes; TraceJIT keeps its own Rust tracer.
- Attribution retained in this matrix and in `docs/research/NOVELTY_MATRIX.md`.

## Upstream bug classes reviewed (discipline borrow)

| Class | Upstream lesson | TraceJIT response |
| --- | --- | --- |
| Filesystem races / replace-via-rename | Caches must not trust path strings alone | Symlink_metadata checks; content guards; residual TOCTOU documented |
| Output materialization partial apply | Crash mid-write | Soft rollback + restore-intent refuse HIT |
| Invalidation too weak (mtime) | Classic ccache/make footgun | Strict content hashing default; mtime-only **rejected** |
| Incomplete child tracing | strace/rr fork attach races | PTRACE fork/vfork/clone registration before child work |

## Non-claims

- This matrix is **not** a claim of peer-reviewed novelty.
- Absence of a competitor binary ⇒ “not tested”, not “worse”.
- Reading a file at a commit is not a full security audit of that project.
