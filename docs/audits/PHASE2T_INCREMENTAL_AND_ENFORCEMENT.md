# Phase 2T: incremental-workflow value and enforced reuse

Base commit: `a11ae4be21b59b20dd74651908dda548ac19e0d4`. Work is local; nothing was pushed or
released. Measurements use the release binary at `cf0c8bef3995bc53a242e3f0e69ada47f8f76107d0594fbc9a6dc6def8409099`
on Linux 6.1.102, 8 vCPU, 15.6 GiB RAM, GNU Make 4.3 and Ninja 1.13.2.

## 1. CI and enforcement state

GitHub Actions run [42724119434](https://github.com/Satwik-P28/tracejit/actions/runs/42724119434)
tested exactly `a11ae4b` and the job `validate` (`129525232436`) completed successfully. The job
record shows every step succeeded, including Formatting, Clippy, Tests, Release build, Doctor and
kernel capabilities, Linux integration, census, and Demo. The run page is public but its raw logs
are not anonymously retrievable, so the reported `Landlock ABI 8`, `proven yes`,
`RESULT seccomp PASS`, `RESULT proven PASS`, `RESULT sandbox PASS` and `RESULT integration PASS`
values are treated as CI evidence supplied by the runner, not as locally reproduced output.

The three states are now distinct:

1. **This local host:** `landlock no`, `seccomp yes`, `proven no`. The new test skips, and the
   existing sandbox unit test skips its Landlock probes.
2. **CI host:** Landlock ABI 8 and a successful PROVEN probe according to the runner.
3. **End-to-end PROVEN reuse:** the CI probe is not the same thing as a command receiving a policy
   and a cache record being reused. This needed a separate test.

That gap was real. `TraceOutcome.sandbox_enforced` used to mean only that a policy was requested;
`trace_command` only returns an outcome after `pre_exec` succeeds, so a failed installation falls
back to an unsandboxed retrace, but no test asserted the end-to-end sequence. Two changes address
it:

- `tracejit_sandbox::apply` now calls `verify_seccomp_installed` after installation. It requires
  `PR_GET_SECCOMP == SECCOMP_MODE_FILTER` and `PR_GET_NO_NEW_PRIVS == 1` in the confined caller.
  A capability probe alone can no longer classify an execution.
- `enforced_execution_is_proven_reused_and_invalidated` requires: first discovery `Guarded`;
  second run `Executed` and `Proven`; third run `Reused` and still `Proven`; then an input edit
  must reject the record and produce the new bytes. CI now greps for `RESULT proven-reuse PASS`.

**Verification status:** the new test compiles and runs locally as SKIP for the correct local
reason. It has not executed on the new tree because this phase forbids pushing. End-to-end PROVEN
reuse is therefore **unverified**, not proven and not known to be architecturally impossible. The
likely failure point, if CI rejects it, is the policy constructed from recorded dependencies
(loader/runtime paths and write destinations), not the capability probe. The test will distinguish
those cases by reporting a Guarded fallback rather than a Proven pass.

## 2. Comparative workflow

`benchmarks/repos/phase2t_incremental.py` compares five arms on three 2.8 MB JavaScript assets
compressed with `bzip2 -9 -k -f`. All five write the real `.bz2` output inside the timed build.
Make uses a normal file-target rule and `touch $@` after `bzip2`; without `touch`, bzip2's
whole-second output timestamp is older than the input's nanosecond timestamp and both Make and
Ninja rebuild every time. The content arm is an independent 25-line cache keyed by relative path
plus input bytes; it always materialises its stored object. Arm order is randomized per session;
each session has isolated workspaces and caches. Three sessions are retained in
`benchmarks/results/phase2t/incremental.json`.

Medians of three sessions, complete workflow wall time in milliseconds:

| Scenario | Native | TraceJIT | Make | Ninja | Hash cache | Correct artifacts |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| First build, no outputs | 430.00 | 669.07 | 425.66 | 436.50 | 495.54 | all |
| Identical rerun | 433.68 | 678.59 | **2.63** | **2.82** | **60.22** | all |
| Outputs deleted | 425.56 | 625.69 | 422.87 | 444.69 | 64.07 | all |
| One input modified | 421.75 | 658.84 | 147.26 | 153.67 | 219.56 | all |
| Unrelated file modified | 420.27 | 248.23 | **2.70** | **3.05** | **60.57** | all |
| Input changed, mtime preserved | 423.57 | 240.50 | 2.87 | 2.89 | 197.59 | Make/Ninja **stale** |
| Output corrupted, no input change | 428.88 | 437.08 | 2.65 | 2.91 | 51.62 | Make/Ninja **stale** |
| Build directory relocated | 437.39 | 625.42 | 2.63 | 2.85 | 60.71 | Make/Ninja **stale from prior scenarios** |
| Three parallel transformations | 423.74 | 231.50 | 164.51 | 158.17 | 62.98 | all |
| Five development sessions | 2142.60 | 2445.11 | **800.41** | **835.88** | **1071.34** | all |

The first-build cost includes TraceJIT's three cold traces. Make and Ninja are a little slower than
native because of driver startup. The content cache is slower on a cold build because it copies and
stores the object.

**Workflow result: valid negative.** On an identical rerun Make is 258x faster than TraceJIT
(2.63 ms versus 678.59 ms), Ninja 241x, and the independent content cache 11.3x. Across five
development sessions TraceJIT is 0.876x native, 0.327x Make, 0.342x Ninja, and 0.438x the content
cache. The content cache is the strongest fair opponent: it has no build graph and still eliminates
the repeated transformation.

**Execution result, kept separate.** Individual cached commands do accelerate: in the real-project
evaluation below, jQuery is 28.68 ms normally and 10.63 ms warm (2.70x), Socat 15.15 to 8.41 ms
(1.80x), and Expat 8.45 to 7.29 ms (1.16x). This does not make the complete build competitive when
an incremental tool starts no commands at all.

### Where automatic observation differs

The mtime-preserved edit and the corrupted output are the meaningful differences. Make and Ninja
both consider the target current and leave the wrong bytes in place. TraceJIT hashes the observed
input and restores its recorded output, so it returns the correct artifact. The content cache also
returns the correct artifact, but only because the harness told it exactly which input maps to
which output; TraceJIT observed that edge itself. That is a dependency-discovery and
missing/corrupt-output advantage, not a speed advantage.

Make, Ninja and the content cache also do not reproduce native output metadata: `touch` and
`write_bytes` change the mtime, while TraceJIT's artifacts preserve the native mode and timestamps.
The content cache could be extended to preserve them; that is additional configuration and side
effect code, not an inherent impossibility.

Configuration effort is deliberately recorded separately:

| Arm | Build/config lines | Declared input→output edges |
| --- | ---: | ---: |
| Native | 0 | 0 |
| TraceJIT | 0 build file; the wrapper enumerates the three commands | 0 |
| Make | 15 | 3 |
| Ninja | 9 | 3 |
| Content cache | 25 | 3 |

TraceJIT's advantage here is that the three edges and their hidden file reads are discovered. Its
disadvantage is a 6–20 ms hit floor plus a cold trace and a presence-change retrace; for a 140 ms
compression, Make's 2–3 ms no-op wins decisively.

## 3. Output-effect audit

Raw sequence: `benchmarks/results/phase2t/effect-sequence.txt`, reproduced from
`benchmarks/repos/phase2t_effect_probe.c` with:

```bash
cc -O2 -Wall -Wextra benchmarks/repos/phase2t_effect_probe.c -o /tmp/effect_probe
strace -f -qq -e trace=openat,write,pwrite64,ftruncate,truncate,rename,renameat,renameat2,unlink,unlinkat,link,linkat,chmod,fchmod,chown,fchown,utimensat /tmp/effect_probe
```

The observed families are:

| Operation | Sequence | Current model | Pathname-visible replay |
| --- | --- | --- | --- |
| New file | `openat(O_CREAT|O_EXCL)` then `write` | `CreateOrModify`, create allowed | yes, by staged rename |
| Existing inode truncated | `openat(O_TRUNC)` then `write` | `CreateOrModify` | yes for path content/metadata; **inode is replaced** |
| Random/positioned write | `pwrite64`, `write`, `ftruncate`, `truncate` | content write / metadata mutation | same inode caveat |
| Atomic replacement | `rename`, `renameat`, `renameat2` | `Delete` source + `RenameDestination` | yes |
| Deletion | `unlink`, `unlinkat` | `Delete` | yes |
| Hard-link creation | `link`, `linkat` | not modelled; successful unknown/refused | **no** |
| Metadata-only | `chmod`, `chown`, `fchmod`, `fchown`, `utimensat` | metadata captured on artifact | yes for mode/uid/gid/atime/mtime |
| Duplicated descriptor | `dup` then `write` | descriptor provenance retained | path-visible yes; inode caveat |
| Inherited descriptor | inherited fd written directly | unclassified write | **no**, ineligible |
| External open descriptor | descriptor opened before restoration | not observed | **no**, old inode remains |

The smallest sufficient classification is therefore **new creation, existing-inode mutation,
pathname replacement, deletion, metadata-only, and unsupported aliasing**. The implementation
does not need a new restoration engine this phase: the declared contract is pathname-visible, and
CAS-and-rename already reproduces that result for a single-link regular destination. Inode identity,
ctime, xattrs and pre-existing open descriptors are outside the contract. The current choice is to
keep reuse for the pathname-visible cases, refuse hard-linked/symlinked/directory destinations, and
refuse unclassified inherited descriptors. That is conservative for the declared contract and
avoids claiming inode equivalence.

No new effect-model code was justified. A test that "preserved" the inode by writing in place would
require a copy-based backup and a crash-recovery journal to retain rollback guarantees; it would
change the restore engine for a property the contract explicitly does not promise. The existing
metadata, hard-link, partial-failure, corruption and concurrency regressions were rerun as part of
the 126-test workspace run.

## 4. Existing-project recurrence

`benchmarks/repos/phase2t_real_workflows.py` copies three installed project artifacts into isolated
workspaces. The normal invocation is recorded before TraceJIT runs. Each result is compared to a
fresh native artifact for the current input. Raw data: `benchmarks/results/phase2t/real_workflows.json`.

| Project | Artifact | Normal invocation | Native | TraceJIT warm | Result |
| --- | ---: | --- | ---: | ---: | --- |
| jQuery | 289,812 B `jquery.js` | `bzip2 -9 -k -f jquery.js` | 28.68 ms | 10.63 ms | 2.70x, 3 Reused |
| Expat | 109,050 B `reference.html` | `gzip -9 -c reference.html > reference.html.gz` | 8.45 ms | 7.29 ms | 1.16x, 3 Reused |
| Socat | 281,660 B `socat.html` | `gzip -9 -c socat.html > socat.html.gz` | 15.15 ms | 8.41 ms | 1.80x, 3 Reused |

All nine TraceJIT executions produced the native-reference bytes, including the edited and
fresh-workspace runs. Output deletion reuses the gzip streams (the output is a captured stream, not
a traced write); jQuery deoptimises because bzip2's existing-output state changed. A source edit
deoptimises all three. A fresh workspace with the same cache executes rather than reuses, because
cwd is part of the identity. Changing `TZ` also executes, because the environment is part of the
identity. There is no cross-workspace cache and none was added.

The limits are clear: these are single-artifact deployment/documentation jobs, not whole builds.
The normal build system may already skip a repeated compression; that baseline wins when it does.
The advantage is limited to cases where the tool has no declared graph, loses or corrupts an output,
or must prove that an input's timestamp is not trustworthy.

## 5. Security and gates

- `cargo fmt --all -- --check`: pass.
- Clippy `--workspace --all-targets --all-features -- -D warnings`: pass.
- `cargo test --workspace`: **126 passed, 0 failed**.
- Differential fuzz: 120 cases, 120 ok, **0 incorrect hits** (`benchmarks/results/phase2t/differential`).
- Allocation contract remains opt-in; no new entropy, clock, PID or syscall coverage was added.
- The local kernel has no Landlock, so all Landlock enforcement tests remain skipped locally.
- The new enforcement test is wired into CI but has not run on this tree.

Finite adversarial coverage is evidence, not proof of noninterference. The restoration window and
external open-descriptor observation remain documented limits.

## 6. Readiness

**Developer preview: still limited, now with a sharper niche.** Do not claim TraceJIT beats Make or
Ninja on a correctly declared, mtime-clean incremental build; the three-session comparison shows
the opposite. The defensible use is an explicit, expensive command whose dependency graph is not
declared and whose outputs are missing or suspect, especially when the caller needs native output
metadata restored. The strongest independent baseline is a content-addressed cache, not Make, and
it is faster on the measured pipeline.

The next product experiment should target a workflow where the content cache would need manual
input→output configuration and where cold traces are rare relative to many executions. It should
not add syscall coverage or a distributed cache to manufacture a win.

## 7. Reproduction

```bash
cargo build --release --workspace
python3 benchmarks/repos/phase2t_incremental.py --sessions 3
python3 benchmarks/repos/phase2t_real_workflows.py
python3 benchmarks/differential/fuzz.py --seed 20261110 --output benchmarks/results/phase2t/differential
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Ninja was installed from the Python `ninja` 1.13.2 package for this local run; CI should install the
same version before the comparative harness. No benchmark command is part of the CI job yet because
it requires that tool and several minutes.
