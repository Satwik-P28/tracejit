# Phase 2Q: causal-correctness gaps, benchmark isolation, and the general-workload wall

Base `e382877`. Linux 6.1.102, 8 vCPU, GCC 13.3.0. This phase validated the Phase 2P
output-prestate contract, repaired benchmark contamination, measured 17 unmodified commands, and
implemented metadata-write modeling. It ends with a negative result and one measured architectural
limit, not with a general-purpose preview.

## 1. Output-prestate adversarial audit

The accepted class is "absent or writable regular file". Native GCC replaces the output directory
entry (`as` writes a temporary and renames it) rather than truncating an existing inode, so the
pre-state's bytes, mode, ownership, hard links and xattrs do **not** survive a native run either.
Measured against native, with an existing output carrying stale bytes, `0600`, an extra hard link
and a `user.*` xattr:

| Pre-state property | Native result | TraceJIT reuse | Match |
| --- | --- | --- | --- |
| stale bytes replaced | yes | yes | yes |
| mode `0600` → `0644` | yes (replaced entry) | yes | yes |
| extra hard link left with stale bytes | yes | yes | yes |
| xattr dropped | yes | yes | yes |
| symlink or directory at the path | never replaced | refused/ineligible | yes |
| second hard link at the destination | reuse precondition refuses multi-link outputs | refused | yes |

New regressions: `output_prestate_reuse_matches_native_filesystem_effects` compares post-state
bytes, mode and the extra hard link against a direct GCC run; `output_prestate_refuses_non_file_destinations`
covers symlink and directory destinations and asserts the symlink target is untouched. No false hit
was found. The hard-link case surfaced as a plain cache miss, not a hit, and the miss is covered by
the same test rather than assumed benign.

Remaining limits: concurrent replacement of the output between validation and restoration keeps the
existing TOCTOU window; mount-namespace changes are untested (no privileges); and the contract is a
declared compiler contract, not universal native equivalence.

## 2. General effect model: what changed

The model already distinguished external reads, program intermediates, read-before-write,
write-before-read, negative dependencies, outputs/effects and concurrent/unknown effects. The
adversarial gap was not a new framework: **metadata-mutating syscalls were unmodeled**, which made
every metadata-preserving tool ineligible.

Implemented, minimum scope:

- `fchmod`, `fchown`, `chmod`, `chown`, `fchmodat`, `fchownat`, `ftruncate`, `truncate` succeed as
  `FileWrite` output effects; an unclassifiable descriptor stays an unknown effect.
- `utimensat` with a null times pointer or `UTIME_NOW` is **refused**: a cached timestamp would
  differ from a native rerun. Explicit timestamps are modeled.
- `umask` is a known process-internal call; the resulting output mode is captured in the artifact.
- `OutputArtifact` now carries mode, uid, gid, atime and mtime. Restoration applies ownership,
  then mode (chown clears set-id bits), then timestamps; unrepresentable or pre-epoch timestamps
  fail closed. Older records decode via `serde(default)`.
- Audited-compiler behavior, native behavior and event ordering are unchanged; no new syscall
  handlers beyond the eight metadata calls.

End-to-end regression `metadata_preserving_program_reuses_and_replays_mode_and_times`: a probe that
writes, `utimensat`s to a fixed time and `chmod`s to `0600` records, reuses, and reports mode `0600`
and mtime `1000000`. It reproduced a real refusal before the change (unmodeled syscall 280/91).

## 3. Benchmark isolation

- `compiler_baseline.py` still set the ignored legacy `TRACEJIT_CACHE`; fixed to
  `TRACEJIT_CACHE_DIR`.
- `compiler_hits.py` now strips the legacy variable, requires the per-session cache directory to
  appear, and fails a session whose cold run reports `Reused`. Phase 2P results already used the
  correct variable and are retained; Phase 2O results remain labelled invalid because of the bug.
- New `workload_discovery.py` gives each candidate a fresh cache, strips the legacy variable,
  asserts cache creation and cold non-reuse, records the decision, the complete refusal reasons and
  the failing guard, compares artifact hashes with native, and reports a changed-input decision.
- Discovery normalises two non-input conditions for **both** arms: a regular empty stdin file
  instead of `/dev/null` (which makes some tools seek an inherited character device) and
  `glibc.malloc.tcache_count=0` (allocator seeding, not a tool input). Outputs still match native.

## 4. Seventeen-workload discovery matrix

`benchmarks/results/phase2q/discovery.json`. Times in ms, medians of two native runs.

| Workload | Native | Cold | Warm | Decision | First refusal |
| --- | ---: | ---: | ---: | --- | --- |
| gzip -9 | 70.5 | 112.8 | 87.2 | Ineligible | failed `O_EXCL` open, `EEXIST` |
| xz -6 | 1867.9 | 2053.3 | 1949.8 | Ineligible | getrandom, sysinfo, monotonic clock |
| bzip2 -9 | 527.7 | 672.9 | 618.5 | Ineligible | getrandom |
| tar -cf | 6.1 | 108.2 | 99.7 | Ineligible | getrandom, realtime clock, failed socket |
| zip -r | 9.0 | 153.7 | 157.2 | Ineligible | getrandom, monotonic clock |
| sort -o | 62.8 | 184.5 | 188.4 | Ineligible | getrandom, sched_getaffinity |
| jq transform | 183.7 | 299.7 | 277.1 | Ineligible | getpid, getrandom, getppid |
| objdump -d | 10.3 | 64.7 | 50.6 | Ineligible | getpid, getrandom, prlimit64 |
| nm | 4.8 | 44.9 | 42.3 | Ineligible | getpid, getrandom, prlimit64 |
| readelf -a | 3.8 | 43.3 | 37.3 | Ineligible | getpid, getrandom |
| strip -o | 3.0 | 42.4 | 30.3 | Ineligible | getrandom, prlimit64 |
| objcopy -O binary | 2.3 | 37.4 | 27.8 | Ineligible | getrandom, prlimit64 |
| compileall | 54.2 | 298.7 | 262.7 | Ineligible | getpid, getrandom, clocks |
| python script | 225.4 | 367.6 | 377.8 | Ineligible | getpid, getrandom, clocks |
| gcc -O2 (native mode) | 730.1 | 888.9 | 890.7 | Ineligible | getrusage |
| awk transform | 32.7 | ~150 | ~140 | Ineligible | getpid, getrandom, realtime clock |
| sed transform | 59.7 | ~300 | ~220 | Ineligible | getpid, getrandom |

Each row records the full reason list, not only the first refusal. Twelve of seventeen are stopped
by `getrandom` alone. The two highest-value candidates (xz, 1.9 s; python transform, 225 ms) are
both blocked by it.

## 5. Ranking by expected developer value

1. **gzip/xz/bzip2**: high reuse frequency and real duration; blocked by `EEXIST` policy and
   `getrandom`. gzip is closest: one failed-open policy plus randomness.
2. **python build scripts / compileall**: high frequency; blocked by process identity and clocks in
   addition to randomness.
3. **tar/zip packaging**: frequent but short (6-15 ms native), so a 30-40 ms hit cannot repay
   tracing.
4. **static analysis output (objdump/nm/readelf) and strip/objcopy**: frequent inspection, tiny
   commands, fixed hit cost dominates.
5. **sort/awk/sed**: good duration, blocked by randomness and CPU-affinity reads.

No candidate is safely eligible, so no warm artifact was produced for any real tool.

## 6. The implementation experiment and its result

The metadata model removes a real class of false refusals and is verified by the probe above, but
it does not unlock gzip because the next observation is the tool's own `getrandom`. A sound reuse
policy cannot replay randomness a native rerun would not reproduce without recording and
interposing on the call; the existing controlled-entropy contract is limited to audited binaries
and does not apply to unmodified utilities. Treating the call as harmless would be an unsupported
claim about output dependence, which the rules forbid.

The second gap is failed filesystem effects: `gzip -f` probes `O_EXCL`, observes `EEXIST`, unlinks
and retries. TraceJIT records that as "failed filesystem effect is not guardable". A presence
dependency (and a retry model) is implementable, but alone it still leaves `getrandom`.

## 7. Performance

No positive end-to-end result is claimed. Metadata replay adds one `chown` and one `set_times` per
output (microseconds). On the compiler reference, guard validation still dominates the ~70 ms hit;
the Phase 2P breakdown is unchanged. Discovery cold overhead is 30-80 ms for short tools and
0.2-1.3 s for the long ones, consistent with per-process identity and guard validation.

## 8. Verification and readiness

- `cargo fmt --check`, Clippy `-D warnings`, workspace tests: see the gate output in the commit
  message; the new metadata test and both prestate regressions pass.
- Path 2P regressions retained: false-hit probe, contract isolation, panic and clock-pointer fixes.
- `PROVEN` remains **BLOCKED** (`landlock no`, `seccomp yes`); compiler-runtime-v1 remains
  experimental and opt-in.
- CI is **BLOCKED**, not green: the branch is unpushed; the only run remains
  [42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118).
- **Developer-preview readiness: NO** for general workloads. The engine is ready for continued
  research on a bounded randomness contract, not for users.

## 9. Commands

```bash
cargo build --release --workspace
python3 benchmarks/repos/workload_discovery.py
cargo test -p tracejit-cli --test linux_integration metadata_preserving -- --nocapture
TRACEJIT_PHASE_TIMING=1 TRACEJIT_PHASE_TIMING_PATH=/tmp/p.json TRACEJIT_CACHE_DIR=/tmp/c \
  ./target/release/tracejit run --json -- gzip -9 -k -f in.txt
```
