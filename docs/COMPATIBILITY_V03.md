# Real-world compatibility, v0.3 development line (Phase U)

This document analyses *why* TraceJIT refuses real developer commands, what was
changed on `development/v0.3`, and what cannot be changed without weakening
correctness. Numbers come from the two corpora in `benchmarks/realworld/` and are
reproduced in `benchmarks/results/phaseu/`.

## 1. Method

* Baseline: the published `v0.2.0-beta.1` binary (`7a594b9`), built from its tag.
* Candidate: `development/v0.3`, built from this branch.
* Both use the same harness (`benchmarks/realworld/census.py`), which runs the
  command natively, then under TraceJIT with a fresh cache, records the
  classification, every refusal reason and the dependency/effect counts, and — when
  the workload is eligible — takes a real cache hit and compares stdout, stderr,
  exit status and output-file hashes against the native run.
* Held-out corpus: twenty further workloads (`census_v03.py`) written *after* the
  blocker analysis, so no optimisation was chosen by looking at them. They import
  the original harness rather than reimplementing it.
* Determinism of the harness: every workload's fixtures are generated, the direct
  and traced runs use the same environment (`GLIBC_TUNABLES=glibc.malloc.tcache_count=0`,
  `MALLOC_ARENA_MAX=1`), and no workload touches the network or the repository.

## 2. Eligibility, measured

| Tier | Corpus | Attempted | Reused, beta | Reused, v0.3 |
| --- | --- | ---: | ---: | ---: |
| Native defaults | original 32 | 31 | 1 (3.2 %) | 1 (3.2 %) |
| `allocator-entropy-v1` contract | original 32 | 31 | 7 (22.6 %) | 7 (22.6 %) |
| Native defaults | held-out 20 | 20 | 0 (0 %) | 0 (0 %) |
| `allocator-entropy-v1` contract | held-out 20 | 20 | 6 (30.0 %) | **8 (40.0 %)** |

The candidate does not raise *native* eligibility, and this document is explicit
about why: after the model gaps below were closed, every remaining native refusal
in both corpora is either nondeterminism the contract tier exists to make
reproducible, or an observation that genuinely depends on scheduling.

The one measured eligibility gain is on the held-out corpus under the audited
contract: `objdump` and `nm` move from refused to reused because their
`prlimit64` queries now read a value `RuntimeIdentity` already guards, and
`strip` moves from refused to `Guarded` (then deoptimizing on §6).

## 3. What blocks native reuse

Counted over the original census after the v0.3 changes (one workload can name
more than one blocker):

| Blocker | Workloads | Nature |
| --- | ---: | --- |
| `randomness` (glibc allocator probe at first `malloc`) | 18 | Genuine nondeterminism. The returned bytes are a runtime input no guard can reproduce, so a cached result could not be proven equal to a rerun's. |
| `clock` (`clock_gettime`, `time`) | 9 | Genuine nondeterminism. gawk seeds its RNG from the wall clock; CPython reads monotonic and realtime clocks. |
| `unmodeled syscall 5` (`fstat` on a pipe) | 3 | `fstat` on a pipe reports bytes currently buffered, which depends on the reader's schedule. |
| `unmodeled syscall 98` (`getrusage`) | 4 (gcc driver) | Process CPU time is not reproducible and gcc can print it. |
| `procfs_process_relative` (`/proc/self/maps`, `/proc/self/cgroup`) | 4 | Address-space layout and cgroup placement are process-relative and not replayable. |
| short pipe reads / multiple writers | 3 | Packetisation, not content, is the observation. |
| `fcntl(F_SETFL)` on stdio pipes | 3 | Toggling `O_NONBLOCK` on a shared pipe changes whether a write returns `EAGAIN`. |
| `clone` with descriptor sharing, writable `MAP_SHARED`, `poll`, `flock`, `epoll_ctl` | 1 (rustc) | Cross-process or readiness-sensitive state. |

The dominant term is the first row: **nearly every glibc program that touches the
heap reads eight bytes of entropy at first allocation** (the allocator's
double-free key). That is why `wc`, `sed`, `sha256sum`, `objcopy`, `unzip`, `nm`
and `readelf` are refused today, and why nine of the twenty held-out workloads are
refused by nothing else.

Admitting those bytes natively is not a modelling choice, it is an unsoundness: the
value differs between runs, no guard can compare it, and the library that stores it
may in principle use it to produce program-visible output. TraceJIT already has the
right mechanism — an audited call site plus a fixed value — in the
`allocator-entropy-v1` controlled-execution contract, and the table above measures
what it buys. That tier is deliberately separate: its records are never mixed with
native ones, and its results are labelled reproducible-under-contract, not
equivalent to native execution.

## 4. Accepted model expansions

Each was written with its semantic argument, a fixture case, and an independent
differential check through the harness.

### 4.1 `/dev/null` by device identity, not pathname

`open("/dev/null")` was refused as "opened dependency cannot be guarded" because a
character device has no content hash. Reads from the null device always reach EOF
and writes are discarded, so the descriptor contributes no observable. The new
`FdState::NullDevice` is assigned only after `fstat` through `/proc/<pid>/fd/<fd>`
confirms character device 1:3, so a bind mount or substituted node that makes
`/dev/null` a regular file takes the ordinary, refusing path. The pathname is still
guarded as metadata, which catches replacement of the node itself.

Consequences: `perl` no longer blocks on `/dev/null`; its remaining refusal is
entropy and the clock.

### 4.2 Create-only epoll instances

`epoll_create1` now yields `FdState::Epoll`. Creation, `dup`, `close` and `fstat`
are process-internal; the instance holds no state a caller can observe until a
descriptor is registered or readiness is waited for. `epoll_ctl`, `epoll_wait`,
`epoll_pwait`, reads from the descriptor and a *failed* creation all still refuse.
Regression: `create_only_epoll_is_reusable`, `epoll_registration_is_refused`.

Consequences: the Pillow image workload no longer blocks on epoll; its remaining
refusals are CPython's clock and identity reads.

### 4.3 `F_SETFL` / `FIONBIO` restricted to the blocking bit on a private regular file

Admission requires all three of:

1. the descriptor is `FdState::File` — opened by this process, not inherited;
2. the process has created no child (`descriptor_sharing`), because a fork copies
   the descriptor table and both processes then reach the same open file
   description;
3. the open object is a regular file (checked on the descriptor, not the pathname),
   and for `F_SETFL` every changed bit other than `O_NONBLOCK` is zero.

`O_NONBLOCK` has no effect on regular-file I/O, and the one path that could still
observe it — a blocking lock request turning into `EAGAIN` — is itself an
unmodelled `fcntl` command. `O_APPEND`, `O_DIRECT` and `O_NOATIME` changes, pipe
descriptors, inherited descriptors and post-fork processes keep refusing, and a
*failed* rewrite records an effect instead of being treated as a silent no-op.
Regressions: `regular_file_blocking_bit_is_reusable`,
`observable_status_flag_rewrites_are_refused`, and the updated
`fcntl_setfl_is_unknown_and_never_reused`.

**Result: neutral for this census.** xz and make rewrite flags on *stdio pipes*,
which remain refused. The rule is still a strictly narrower refusal (it admits what
it can prove and names the rejected flag otherwise) but it is documented as a
neutral result, not a win.

### 4.4 Resource-limit queries the identity already guards — the one measured win

`prlimit64(0, resource, NULL, &old)` was `None` only for `RLIMIT_STACK`. It is now
admitted for the four limits `RuntimeIdentity` records (stack, open files, address
space, RSS), because reading back a value that is already part of the cache key
cannot change what a hit reproduces. Installing a limit (`new != NULL`), querying a
limit the identity does not carry, and every other resource stay effects.

This is the only expansion in this phase that changed an eligibility decision on
real workloads: `objdump` and `nm` (held out) were refused solely on
`process read system information via prlimit64` and are now reused with verified
output equivalence. `strip` also stops refusing, and is then caught by the atime
defect in §6 instead.

### 4.5 Deterministic failures

`close`, `dup` and `F_SETFD` on a negative descriptor can only return `EBADF`; the
observation is fixed by the argument, not by state. `TCGETS` on an internal pipe
can only return `ENOTTY`. Both were recorded as unmodelled failures, which refused
`sh` pipelines and `gzip | gunzip` for no semantic reason. They now record nothing,
and a *successful* `TCGETS` still refuses.

## 5. Rejected and deferred, with reasons

| Candidate | Decision | Reason |
| --- | --- | --- |
| Admit the glibc allocator entropy probe natively | **Rejected** | The bytes differ per run and no guard can compare them; a cached hit could expose output a rerun would not produce. Only the audited contract may fix the value, and it must stay a separate tier. |
| `fstat` on a pipe (3 workloads) | **Rejected** | `st_size` is the current pipe occupancy. Replaying a stored value would answer a question the kernel answers differently under a different schedule. |
| `F_SETFL(O_NONBLOCK)` on pipes / inherited descriptors | **Rejected** | The description is shared, and a would-block write becomes `EAGAIN`, which the program can observe and branch on. |
| `epoll_ctl` / `epoll_wait` / `poll` | **Rejected** | Readiness is scheduling state. Modelling it would need a replay scheduler, which is a different product. |
| `flock` / `link` / renameat2 with flags | **Rejected** | Cross-process or inode-aliasing effects that pathname restoration does not reproduce. |
| `statx` | **Deferred** | Modelable (requested mask + result bytes), but it would not change eligibility: rustc's chain also needs `/proc/self/maps`, `poll`, `clone` sharing and a writable `MAP_SHARED`. Recorded as roadmap work for Rust tooling, not as a Phase U win. |
| Drop `atime` from metadata guards for paths the command read | **Rejected** | This is the deopt cause in §6, but a program may legitimately print a file's access time. Removing the field would weaken a guarantee to buy a benchmark. |
| `copy_file_range` / reflink for output restoration | **Not adopted** | Reflink is unavailable on the ext4 test filesystem, so no improvement could be *measured* here; `copy_file_range` still requires reading the object to verify its hash, so it trades one userspace copy for a second kernel read. Deferred with the measurement gap stated rather than claimed. |
| Skipping `sync_data` on restored outputs | **Rejected** | Native execution does not fsync its outputs, so removing it would be faster — but it changes the durability contract that crash recovery is built on. That is a contract decision, not an optimisation. |

## 6. Defect found: metadata guards include an atime the command itself changes

`strip`, `objcopy` and `unzip` classify as `Guarded` under the contract yet
deoptimize on the very next run. The failing guard is the input's `FileMetadata`:

```text
expected: ... size: 1216, accessed_ns: 1794971759320677689, modified_ns: 1794971759320677689
actual:   ... size: 1216, accessed_ns: 1794971759364677689, modified_ns: 1794971759320677689
reason:   metadata changed; no content hash was recorded
```

Only `atime` moved, and it moved because the traced command read the file. The
guard is therefore self-invalidating for any command that `stat`s an input before
reading it: the first run poisons the entry it just created. This is pre-existing
behaviour, not a regression from this branch, and the refusal is *sound* — a
program that printed the atime would indeed produce different output on a rerun.
It is recorded here as a compatibility cost with a precise cause, and the
field-precision fix is deliberately left for the roadmap because it needs
provenance information TraceJIT does not yet record.

## 7. Roadmap for v0.3

1. **Rust toolchain chain**: model `statx`, `prctl(PR_SET_NAME)`, create-only
   `eventfd2`, and decide whether `/proc/self/maps` can ever be guarded (it cannot
   today; ASLR makes it a genuine nondeterministic read).
2. **Second content-free device class**: extend the null-device model to
   `/dev/full`, `/dev/zero` only if their write/read semantics are proven per
   device (`/dev/zero` yields deterministic zeroes but the *size* of the read is
   the caller's, so it is already content-free; `/dev/full` always `ENOSPC`).
3. **Field-precision metadata guards** using recorded provenance, so `strip`
   stops deoptimizing without dropping a guarantee.
4. **Contract tier**: evaluate a documented clock contract for the two confirmed
   runtime call sites (gawk `srand`, CPython monotonic/realtime) under the same
   audit discipline as the allocator contract, or explicitly decide not to.
