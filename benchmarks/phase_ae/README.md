# Phase AE benchmark package

Versioned harnesses, pinned inputs and raw results for the Phase AE claims
(`docs/PHASE_AE_REPORT.md`). Everything here regenerates the tables in the documents; nothing
in the documents is hand-edited from a different run.

## Contents

| file | what it measures |
| --- | --- |
| `reproduce.sh` | entry point: `quick` (no competitor) and `full` (competitive matrix) |
| `competitive_matrix.py` | per-invocation decisions, outputs, cache size; cold and steady sessions |
| `economics.py` | session totals, per-invocation medians with bootstrap CIs, integer break-even, reuse classification |
| `firebuild_policy_probe.py` | Firebuild contract behaviour per version/configuration, including cache corruption |
| `tracejit_integrity_probe.py` | TraceJIT refuses a corrupted cached object (paired with the above) |
| `toctou_race.py` | deterministic and probabilistic validate→restore interleavings |
| `replay_profile.py` | disjoint phase timings for large-artifact HITs plus read/copy/write/fsync bounds |
| `environment_probe.py` | one environment's fingerprint, `doctor` view, guarded and enforce arms |
| `multi_environment.py` | the same probes inside a second unpacked userspace (user+pid+mount namespace) |
| `ci_annotations.py` | publishes a fingerprint as public GitHub Actions annotations |
| `test_accounting.py` | permanent regressions for HIT accounting, output verification and break-even |

Raw results (`benchmarks/results/phaseae/`): `matrix.json`, `economics.json`,
`policy_probe.json`, `tracejit_integrity.json`, `toctou_race.json`, `replay_profile.json`,
`environment-local.json`, `environment-local-earlier.json` (superseded probe, kept for history),
`multi_environment.json`.

## Pinned inputs

* Workload payloads are generated deterministically in the harnesses (xorshift blob; fixed text
  line format), so no large binary blob is required for the matrix.
* The replay profile uses 100 MiB/10 MiB prefixes of the Linux 6.6.50 release archive:
  `https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.50.tar.xz`,
  sha256 `c065e36daf28210060c91a37ef3e92ac5814784e634577e04e406297ead2e86e`.
  Materialise them as `/tmp/artifacts/text-100MiB.bin`, `text-10MiB.bin`, `xz-100MiB.bin`
  (`xz -dc` prefix for text, the tarball prefix for the incompressible case).
* Competitors: Firebuild 0.8.2 debs and the `v0.8.6.2` source tarball, with the hashes and the
  build recipe in `docs/FIREBUILD_CROSS_VERSION_RESULTS.md`.
* TraceJIT revision and binary digest: every results file records the binary path and, for the
  probes, the binary sha256. `git rev-parse HEAD` at the time of a run belongs next to it.

## Running

```bash
# quick: no competitor, ~2 minutes on 8 CPUs
./benchmarks/phase_ae/reproduce.sh quick

# full: one Firebuild arm set; repeat per version/configuration
FIREBUILD=/tmp/fb-build/src/firebuild/firebuild \
FIREBUILD_CONF=/tmp/fb-build/etc/firebuild.conf \
FIREBUILD_VERSION=0.8.6.2 FIREBUILD_LABEL=fb862 \
ARTIFACTS=/tmp/artifacts \
./benchmarks/phase_ae/reproduce.sh full

# second userspace (unpacked Ubuntu 25.10 base root)
python3 benchmarks/phase_ae/multi_environment.py --root .phaseae-rootfs/root \
  --label ubuntu-25.10-glibc2.42 --tracejit target/release/tracejit
```

Run from a clean checkout: the only prerequisite is a Rust toolchain, `gzip`, `bzip2`, `sed`,
`sha256sum`, `python3` and (for the competitive suite) a built Firebuild. No root, no network
access during a run.

## Expected skips and known capability limits

* **Landlock is absent** here (`/sys/kernel/security/lsm = capability,selinux`), so `--enforce`
  never reuses and no run is labelled `PROVEN`. That is the documented fail-closed behaviour,
  not a skip to work around.
* **`allocator-entropy-v1` is libc-build specific.** On an unaudited glibc the contract is
  unavailable and malloc-using programs are `NONDETERMINISTIC`. The second-userspace probe
  therefore shows correct output and zero reuse.
* **Firebuild refuses `$TMPDIR` paths.** All harnesses keep workspaces outside it; a run inside
  `/tmp` manufactures a false "no reuse".
* **Firebuild ≥ 0.8.6 must be run from its build tree.** The installed binary resolves its
  interceptor by bare name; without the library path the child silently fails `LD_PRELOAD`.
* **Replay profile** skips cases whose artifact files are missing, printing the reason.

## Known negative results (do not "fix" them)

* A mutation after guard validation produces stale output; the harness records
  `undetected_stale_bytes: true`. It is the documented boundary.
* Firebuild replays a corrupted cached blob (`served_corrupted_bytes: true` in
  `policy_probe.json`); it is a competitor measurement, not a bug in this repository.
* `sha256sum` below ~10 MiB never pays for either engine.
* The 1 MiB incompressible gzip case breaks even at 3 invocations by the integer model, and at
  10 by the measured cold session. Both numbers stay.
