# Phase S — dependency identity and restoration acceleration

Baseline commit `fc82b3a` (current `main`), branch `phase-s/verity`.
Kernel 6.1.102, x86_64, 2 vCPU, ext4 on `/dev/root` (8 GiB used, 6.8 GiB free), rustc release build.

## 1. Where the warm hit actually goes

`TRACEJIT_PHASE_TIMING=1`, guarded C fixture, 15 warm runs per size, isolated cache:

| input | warm hit | direct | guard validation | CAS restore | SQLite open+schema+query+decode |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 KiB | 10.89 ms | 0.89 | 1.11 | 4.63 | 0.98 |
| 64 KiB | 10.86 | 1.05 | 0.98 | 4.92 | 0.93 |
| 1 MiB | 14.86 | 3.44 | 1.33 | 8.34 | 0.90 |
| 4 MiB | 28.59 | 11.37 | 2.61 | **17.47** | 1.44 |
| 64 MiB | 298.31 | 167.15 | 25.45 | **205.60** | 1.66 (+15.1 lookup, 11.2 decode) |

Why the 4 MiB fixture is slower than small workloads: **restoration materialises and
durably writes the output**. A standalone measurement of the same 4 MiB write gives
6.17 ms write + 6.73 ms `fsync` = 12.9 ms floor; the cache adds streaming BLAKE3 while
copying, the restore-intent journal and a rename. Hashing is *not* the bottleneck:
guard validation is 2.6 ms (9.1 %) at 4 MiB and 25 ms (8.5 %) at 64 MiB. SQLite is
1–2 ms. `process_startup_ns` is quantised by the 10 ms `/proc/<pid>/stat` starttime
tick and is not used.

## 2. Kernel-backed identity prototype (isolated, off by default)

`crates/tracejit-guards/src/verity.rs` implements `FS_IOC_MEASURE_VERITY`
(SHA-256 Merkle root, `0xc0046686`) and stores the root on `Guard::FileHash` as
`#[serde(default)] verity: Option<Hash>`. Validation re-measures the root and accepts
without reading when it matches; a *measured mismatch fails closed* (no hash
fallback, because the file is verity-immutable and changed); unsupported/unenrolled
files (`ENOTTY`, `EOPNOTSUPP`, `EINVAL`, `EPERM`, `ENODATA`) fall back to strict
BLAKE3. Content identity only — path, ownership, permissions and mount identity stay
with the existing metadata guards.

Activation requires `TRACEJIT_VERITY=1`; records without the field deserialize and
behave exactly as before.

## 3. Measurements and verdicts

| candidate | measurement | verdict |
| --- | --- | --- |
| fs-verity content witness | kernel returns `EOPNOTSUPP`; paired probe overhead at 64 KiB / 4 MiB: +0.008 ms `[-0.087,+0.135]`, +0.128 ms `[-0.133,+0.395]` | **not mergeable here** — no supported filesystem, no gain demonstrable; ceiling 8.5–9.1 % of wall |
| reflink (`FICLONE`) CAS → output | `cp --reflink=always`: `Operation not supported` | reject |
| elide restore-intent journal (1 output) | A/B with a temporary hook: −0.033 ms at 4 KiB, −0.091 ms at 4 MiB | reject (no gain; keep the safety record) |
| streaming hash + `sync_data` (existing) | already single-pass; restoring 4 MiB = 17.5 ms vs 12.9 ms raw write+fsync | keep |
| typed cache schema v3 / success statistics (Phase R) | ≥1.9 ms per hit for persisted stats, ≤1.3 ms avoidable validation | reject |

Adversarial content mutations (same inode, two successive rewrites, at 64 KiB,
4 MiB, 64 MiB) produce `Executed`, never `Reused`. The existing suite covers inode
replacement, pathname swap, symlink/hardlink substitution, permission changes,
concurrent replacement, corrupt CAS objects, interrupted multi-output restore and
concurrent cache access.

## 4. Recommendation

Do **not** merge the fs-verity contract yet: it is correct and cheap to probe, but its
benefit is bounded by guard hashing (~9 % of a warm hit) and cannot be validated on
this kernel. If a verity-capable filesystem is available, re-run
`research/phase_s/bench_phases.py` with `TRACEJIT_VERITY=1` and accept only if the
guard phase drops by >50 % with no restore regression. The measured headroom is in
restoration durability, which the current code already implements with the minimum
number of flushes.

## 5. Reproduce

```bash
cargo build --release --workspace
python3 research/phase_s/bench_phases.py            # per-phase attribution
python3 research/phase_s/bench_verity.py --runs 40  # probe cost + adversarial
```
