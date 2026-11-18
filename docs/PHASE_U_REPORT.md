# Phase U technical report — `development/v0.3`

Status: development branch. **Nothing is released, tagged or merged to `main`,
and `v0.2.0-beta.1` is untouched.** Every number below was produced on the host
described in §8 and is committed under `benchmarks/results/phaseu/`.

## 1. Commits

| Point | Commit |
| --- | --- |
| Starting point: published beta (tag `v0.2.0-beta.1`) | `7a594b9` |
| `origin/main` at the start of this phase | `fc82b3a` |
| `development/v0.3` model changes | see `git log v0.2.0-beta.1..development/v0.3` |

`development/v0.3` is cut from the published tag commit, which merges the release
branch into `main`: it is `main` plus the release packaging that the beta shipped.
`main` itself was not advanced, and no published tag was moved.

## 2. What was changed

Four model expansions and two deterministic-failure corrections, each with a
semantic argument and an independent regression:

1. **Null device by identity.** `open("/dev/null")` was refused as an unhashable
   open, which blocked `perl`, `make` and any tool that opens the device for
   buffering control. The descriptor is now classified as the kernel null device
   after confirming character device 1:3 on the *open* descriptor, reads and
   writes on it record nothing, and its pathname is still guarded as metadata.
2. **Create-only epoll instances.** `epoll_create1` returns an `FdState::Epoll`
   that is process-internal until something observes readiness. `epoll_ctl`,
   `epoll_wait`, reads and failed creation still refuse.
3. **`F_SETFL`/`FIONBIO` for the blocking bit only.** Admitted when the sole
   changed flag is `O_NONBLOCK` on a regular file this process opened, and only
   before the process has created a child (a fork shares the open file
   description). Every other flag change, pipe descriptor, inherited descriptor
   and post-fork rewrite still refuses; a failed rewrite records an effect.
4. **`prlimit64` queries of identity-guarded limits** (stack, open files, address
   space, RSS) are no longer effects. Installing a limit still is. This is the
   only change that flipped held-out workloads: `objdump` and `nm`.
5. **Negative-descriptor `EBADF`** from `close`/`dup`/`F_SETFD` is deterministic.
6. **`TCGETS` on an internal pipe** can only fail with `ENOTTY`; the successful
   case still refuses.

New harness: `benchmarks/realworld/census_v03.py`, twenty held-out workloads
importing the original census machinery.

## 3. Eligibility, before and after

Same host, same harness, same environment, same binary build flags.

| Tier | Corpus | `v0.2.0-beta.1` | `development/v0.3` |
| --- | --- | ---: | ---: |
| Native defaults | original 32 | 1 / 31 (3.2 %) | 1 / 31 (3.2 %) |
| `allocator-entropy-v1` contract | original 32 | 7 / 31 (22.6 %) | 7 / 31 (22.6 %) |
| Native defaults | held-out 20 | 0 / 20 | 0 / 20 |
| `allocator-entropy-v1` contract | held-out 20 | 6 / 20 (30.0 %) | **8 / 20 (40.0 %)** |

The only eligibility movement is on the held-out corpus under the audited
contract: `objdump` and `nm` become reusable because their `prlimit64` limit
queries are now recognised as reads of a value the cache key already contains,
and `strip` moves from a refusal to `Guarded` (it then deoptimizes on the atime
defect in §6). Those two are the entire before/after delta; the original census
was already saturated for the contract tier.

**The native rate does not move, and that is the phase's central finding.** Once
the model gaps are closed, the remaining refusals are not gaps: they are (a) the
glibc allocator reading eight bytes of entropy at the first `malloc`, (b) the wall
and monotonic clocks, (c) `fstat` on pipes and short pipe reads, (d) `getrusage`,
(e) process-relative procfs, and (f) `rustc`'s chain of `clone`/`poll`/shared
mappings. Each is a genuine observation of state a rerun can differ on. Admitting
them natively would be a false-HIT risk, not a compatibility win, so they stay
refused; the audited contract tier is where eligibility for them lives, and it is
opt-in, versioned and never mixed with native records.

What did change is *why* workloads are refused. After this branch, `shell-pipeline`
and `gzip-roundtrip-file` refuse only on pipe `fstat` (the negative-descriptor and
`TCGETS` noise is gone), `pil-image-transform` refuses on CPython's clock and
identity rather than on epoll, `perl` on entropy and the clock rather than on
`/dev/null`, and `sort` no longer reports a `prlimit64` observation.

## 4. Performance, measured

Hit latency on the seven workloads the contract admits (5 measured runs, 1 warmup,
medians, census environment):

| Workload | Direct | Cache hit | Ratio |
| --- | ---: | ---: | ---: |
| `bzip2-compress-stdout` | 19.66 ms | 10.84 ms | **1.81× faster** |
| `openssl-sha256` | 6.58 ms | 15.99 ms | 0.41× |
| `gzip-compress-stdout` | 1.41 ms | 7.17 ms | 0.20× |
| `sha256sum-blob` | 3.56 ms | 23.33 ms | 0.15× |
| `sed-rewrite-stdout` | 2.04 ms | 19.20 ms | 0.11× |
| `wc-line-count` | 1.15 ms | 15.42 ms | 0.08× |
| `od-hex-prefix` | 1.42 ms | 20.20 ms | 0.07× |

Only `bzip2` (a genuinely expensive transform) repays a hit. The rest are net
losses, so the breakdown matters more than the table:

| Component | `od -An -tx1 -N 256` |
| --- | ---: |
| Native execution | 2.21 ms |
| `tracejit --version` (process start only) | 1.56 ms |
| Cache hit, `--guard-mode fast` | 12.82 ms |
| Cache hit, `--guard-mode strict` | 19.08 ms |

So ~11 ms of a hit is fixed cache-path work (SQLite open/lookup, candidate
validation, report assembly) and ~6 ms is strict content hashing of ~50
dependencies. Neither is output restoration: these workloads have no outputs. It
follows that for the *large-output* case the Phase S finding still holds (restore
dominates) while for short commands dependency validation dominates, and the two
need different work.

The product response to the short-command case already exists and was verified:
`--admission auto` runs a short command directly instead of tracing it
(`od`: 2.21 ms direct, 6.87 ms under auto — the measurement probe itself costs
~4.7 ms, still less than a 19 ms hit). This branch adds no performance change;
the honest result is that the measured hit cost is fixed-overhead-bound, and the
fix is structural (a hit index that avoids a full cache open, and parallel guard
verification), not a tuning patch. Reflink restoration was not adopted because the
test filesystem is ext4, so no improvement could be demonstrated.

## 5. Correctness and verification

* `cargo fmt --all -- --check`: clean.
* `cargo clippy --workspace --all-targets --all-features -- -D warnings`: clean.
* `cargo test --workspace`: green.
* `cargo test -p tracejit-cli --test linux_integration -- --test-threads=4`:
  **67 passed, 0 failed**, including five new regressions
  (`null_device_open_is_reusable`, `create_only_epoll_is_reusable`,
  `epoll_registration_is_refused`, `regular_file_blocking_bit_is_reusable`,
  `observable_status_flag_rewrites_are_refused`) and the updated
  `fcntl_setfl_is_unknown_and_never_reused`.
* Both censuses compare, for every eligible workload, the cold traced result and
  the cache-hit result against the native run (stdout, stderr, exit status and
  output-file hashes). **Zero output-equivalence failures, zero incorrect hits**
  across 32 + 20 workloads in four configurations.
* At the default test parallelism (8 threads on this 8-vCPU VM) 8 of 67 integration
  tests fail to spawn their fixture; the tagged `v0.2.0-beta.1` suite fails 2 of 62
  the same way on this host. The failure is test-harness process pressure, not a
  product assertion: every one of those tests passes in isolation and the whole
  suite passes at 4 threads. Recorded rather than hidden; CI was not observable
  from this workspace (`gh` is unauthenticated).

## 6. Defect found but not fixed

`strip`, `objcopy` and `unzip` classify `Guarded` under the contract and then
deoptimize on the next run. The failing guard is the *input's* `FileMetadata`, and
the only difference is `accessed_ns`: the traced command read the file, so the
kernel updated its access time after the fingerprint was captured. The entry
invalidates itself on creation. The refusal is sound (a program that printed the
access time would genuinely differ on a rerun), so it is documented with its exact
cause in `docs/COMPATIBILITY_V03.md` §6 and left to the roadmap rather than fixed
by dropping a guarded field.

## 7. Rejected

Native admission of the allocator entropy probe; `fstat` on pipes; `F_SETFL` on
pipes/inherited descriptors; `epoll_ctl`/`epoll_wait`/`poll`; `flock`, `link`,
`renameat2` flags; `statx` (modelable, but rustc's chain still needs four other
unsafe observations, so it buys no eligibility today); `copy_file_range`/reflink
(no measurable gain on ext4); skipping `sync_data` (changes the durability
contract); dropping `atime` from metadata guards (weakens a guarantee). Reasons
and evidence are in `docs/COMPATIBILITY_V03.md` §5.

## 8. Environment

Ubuntu 24.04, Linux 6.1.102, x86_64, 8 vCPU, 16 GiB, ext4, ext4-backed `/tmp`,
rustc 1.100.0. Landlock is **not** enabled on this host
(`/sys/kernel/security/lsm` = `capability,selinux`), so `PROVEN` and the sandbox
integration cases are skipped here exactly as documented for the beta.

## 9. Recommendation

Do not ship this as a behaviour change for native reuse users — it does not change
their eligibility. Ship the *diagnosis*, the held-out corpus, the five new
regressions and the compatibility document, and treat the audited-contract tier as
the supported answer for developer workloads until the following are done:

1. a hit path that avoids a full cache open and verifies guards concurrently
   (the measured 11 ms fixed + 6 ms hashing);
2. field-precision metadata guards, which unblock `strip`/`objcopy`/`unzip`
   without weakening a guarantee;
3. the Rust toolchain chain (`statx`, `prctl`, create-only `eventfd2`, and an
   explicit decision on `/proc/self/maps`);
4. a documented decision on a clock contract for the two identified runtime call
   sites, or an explicit refusal to have one.

No v0.3 release should be cut until at least (1) and (2) produce measured gains on
the held-out corpus.
