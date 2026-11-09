# Phase 2R: randomness attribution and the unlocked workload

Base `0aae8c5`. The Phase 2Q conclusion that `getrandom` blocks the discovery set was correct for
native mode but incomplete: an audited allocator-entropy contract already existed and had never
been applied to these workloads. On this host its exact profile matches, and it unlocks a real
compressor. This report attributes every call, compares the three compatibility routes, and
measures the result.

## Part A: why the contract is admissible here

Host: glibc 2.39, GNU build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`, exactly the profile in
`tracejit-effects`. The contract answers only a `getrandom(8, GRND_NONBLOCK)` whose return address
is `libc+0xa9e89`, whose instruction bytes match the audited signature, and whose destination is
`libc+0x20b178` (the `tcache_key` in the library's private writable data). Anything else stays
`Random`. The fixed value is opt-in, part of the cache identity, and is not native equivalence.

## Part B: complete randomness-origin matrix

Method: native execution of every discovery command under `strace -f -i -k -e trace=getrandom`,
with an empty regular stdin and `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`. Each call recorded
PID, RIP, length, flags, return value and stack; the RIP was mapped against the known site. Raw
data: `benchmarks/results/phase2r/getrandom.json`.

| Workload | Calls / PIDs | Length | Site / classification |
| --- | --- | --- | --- |
| gzip, xz, bzip2, tar, zip, sort, strip, objcopy | 1 / 1 | 8 | libc+0xa9e89, allocator-init |
| jq, objdump, nm, readelf, awk, sed | 2 / 2 (shell + tool) | 8 | libc+0xa9e89, allocator-init |
| python compileall | 3 / 1 | 8, 24 | tcache + CPython hash seed (security-sensitive) |
| python script | 3 / 1 | 8, 24 | tcache + CPython hash seed (security-sensitive) |
| gcc reference | 4 / 3 | 8 | tcache in main/cc1/as, one non-libc site |

Every 8-byte call is `GRND_NONBLOCK` and returns 8; the stack is `malloc` → `__libc_start_main`.
Calls in child processes are separate PIDs and are admitted independently by the same site check.
`sh -c` wrappers add one call in the shell process even when the utility itself is admitted.

Two calls are **not** the allocator probe: CPython's 24-byte call is an application hash seed and
is correctly refused; jq makes an additional 8-byte call at the libc address but fails the
contract's destination check, so jq remains ineligible even when invoked directly. A call is not
classified as harmless merely because it is 8 bytes or originates near libc.

Static glibc is not an escape: a `gcc -static` program that only calls `malloc` still issues the
8-byte tcache `getrandom`. musl is not installed (no `musl-gcc`, `musl-clang`, or loader), so the
musl arm is **BLOCKED**, not inferred.

## Discovery under the contract

`benchmarks/results/phase2r/discovery.json`, pre-state present, `--admission always`,
`--contract allocator-entropy-v1`:

| Workload | Native | Cold | Warm | Decision | Remaining refusal |
| --- | ---: | ---: | ---: | --- | --- |
| bzip2 -9 | 576.9 | 629.4 | 20.6 | **Reused** | none |
| gzip -9 -f | 63.8 | 166.6 | 98.3 | Ineligible | failed `O_EXCL` EEXIST |
| xz -6 | 1941.0 | 2174.2 | 2016.0 | Ineligible | sysinfo, monotonic clock |
| tar | 5.3 | 113.6 | 111.5 | Ineligible | realtime clock, failed socket |
| zip | 8.6 | 164.5 | 154.7 | Ineligible | monotonic clock |
| sort | 81.3 | 249.0 | 190.0 | Ineligible | sched_getaffinity |
| jq | 189.8 | 307.2 | 291.2 | Ineligible | getpid/getppid, getrandom |
| objdump / nm | 12.8 / 10.3 | 75.9 / 61.5 | 55.3 / 48.2 | Ineligible | getpid/getppid, prlimit64 |
| readelf | 4.7 | 51.0 | 46.7 | Ineligible | getpid/getppid |
| strip / objcopy | 4.0 / 5.3 | 46.2 / 43.9 | 36.3 / 36.6 | Ineligible | prlimit64 |
| compileall | 55.7 | 572.9 | 304.1 | Ineligible | pid, clocks, 24-byte getrandom |
| python script | 222.8 | 399.6 | 406.2 | Ineligible | pid, clocks, 24-byte getrandom |
| gcc -O2 | 757.1 | 971.5 | 948.6 | Ineligible | getrusage (syscall 98) |
| awk / sed | 26.4 / 58.0 | 193.9 / 298.5 | 174.2 / 251.3 | Ineligible | getpid/getppid, clock |

**1 of 17** is genuinely reusable; the rest now fail for identifiable, independent observations.
The allocator contract removes the entropy refusal from 12 workloads but does not make clocks,
process identity, `sysinfo`, `prlimit64` or `sched_getaffinity` observable.

## Part C: the three routes

**A. Audited profile expansion — chosen.** The host build matches the single existing profile;
the contract admits bzip2 immediately. There is no second glibc build on this host to extend to.
Expansion requires a new build ID, exact instruction bytes, site offset and destination audit;
recognising a call because it is 8 bytes would be the forbidden global whitelist.

**B. Static or alternative libc — negative / blocked.** A static glibc `malloc` program still calls
the tcache probe, so static linking does not remove entropy. musl tooling is absent; no static
bzip2 exists here. Static is not assumed deterministic.

**C. General controlled environment — studied, not built.** Hermit intercepts syscalls and
virtualises time, randomness, PIDs and scheduling so a guest is reproducible under a seed
([Hermit](https://github.com/facebookexperimental/hermit),
[design](https://developers.facebook.com/blog/post/2022/11/22/hermit-deterministic-linux-testing)).
It requires a container/namespace, changes the program's observed clocks/IDs, is explicitly not a
security boundary, and its ptrace/Reverie interception cost is large. That is a different product
from transparent reuse: it would make every execution deterministic rather than proving one
recorded execution can be replayed. Not implemented in this phase.

## Part D: failed exclusive open (`EEXIST`)

gzip `-f` probes `open(O_CREAT|O_EXCL)`; when the output exists the kernel answers `EEXIST`, gzip
unlinks and retries, and the tracer refuses the failed effect. With the output absent gzip is
eligible and **does** reuse on a warm run (`gzip` cold `Executed`, warm `Reused`, byte-identical).

A presence predicate is representable in principle, but the guard would have to preserve the exact
kernel question and its consequences: regular file vs symlink vs directory at the path, parent
write/sticky permissions, unlink success, and concurrent creation between validation and restore.
Today's output pre-state guard already refuses a non-regular or multiply linked destination, but it
does not encode unlink semantics or an atomic presence check. Implementing only "EEXIST means the
path exists" would turn one failed open into a cacheable event without those guarantees. It is
therefore **not implemented**; gzip remains ineligible when the output exists, and bzip2 was chosen
because it does not need this model.

## Part E: unlocked workload

Target: `bzip2 -9 -k -f big.txt` (6.0 MB text, 201,556-byte output), under
`tracejit.allocator-entropy.v1`, output present before the cold trace (the pre-state a repeated
invocation sees). Cold `Executed`, every warm run `Reused`; output SHA-256, size, mode, uid, gid and
mtime equal the cold artifact, and bytes/mode equal native. Ten repeated warm runs cost 140.31 ms
against 5,279.60 ms native.

Adversarial results (`benchmarks/results/phase2r/bzip2.json`):

- changed input: `Deoptimized`, new bytes (SHA differs), correct output, 631.78 ms;
- changed arguments (`-1`): identity miss, `Executed`, 472.11 ms;
- changed environment: identity miss, `Executed`, 612.80 ms;
- corrupt CAS object: `Deoptimized`, retraced, output matches native;
- 8 concurrent warm runs: all `Reused`, one SHA, exit 0, no lock error;
- output absent at cold: first warm deoptimizes because the recorded negative metadata observation
  no longer holds (correct), the second retrace then hits; this is the expected cost of a changed
  pre-state, not a false hit.

## Part F: economics

`TRACEJIT_PHASE_TIMING` for a warm hit: startup 11.58 ms, guard validation 7.83 ms, CAS restore
2.72 ms, SQLite query 0.23 ms, record decode 0.43 ms, lookup key 0.01 ms. Warm median 14.75 ms.
Session 1: native 524.56 ms, cold 627.10 ms, warm 14.75 ms, cache 336000 bytes, ten-run 37.63x. Session 2: native 566.43 ms, cold 697.06 ms, warm 17.21 ms, cache 335549 bytes, ten-run 20.43x. Both sessions used a fresh isolated cache and the same fixture; neither was discarded. Cold premium is about 103-131 ms, so the first repeated hit repays tracing.

This is a real end-to-end win for a substantial noncompiler command, but it is one command under an
opt-in contract, not a general accelerator. gzip's absent-output path also reuses, but its common
existing-output invocation does not.

## Decision and limits

- Keep `allocator-entropy-v1` experimental and opt-in; do not generalise it to 8-byte calls.
- bzip2 is the first substantial unlocked workload with positive savings.
- gzip, xz, Python, jq and the rest stay refused for the reasons above; adding handlers for each is
  out of scope and would not address clocks/identity/randomness.
- `PROVEN` remains **BLOCKED** (`landlock no`, `seccomp yes`); the contract is not a sandbox.
- Local gate: fmt, Clippy `-D warnings`, **123 tests** pass. GitHub Actions is **BLOCKED** (branch
  unpushed); the only run remains
  [42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118). No push, merge or
  release was performed.
