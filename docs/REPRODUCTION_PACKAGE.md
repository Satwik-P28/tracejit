# Reproduction package

Two paths: a **small** one a fresh Linux user can finish in minutes, and a **full** one that
reproduces the evaluation. Both are command lines with expected output, not descriptions.

Requirements common to both: Linux x86_64, `ptrace` permitted (no `kernel.yama.ptrace_scope`
restriction that blocks a child tracing its own child), glibc 2.39 or the pinned toolchain, and a
Rust toolchain for source builds.

## 0. Environment diagnostics (run first, keep the output)

```sh
uname -srm; ldd --version | head -1; nproc; free -g | head -2
tracejit doctor --json
```

`doctor` is the capability gate. `"proven": true` means this host can install the enforcement
policy; on a host where it is false, the enforcement-dependent steps below are expected to refuse
or skip, and that is a capability result, not a failure of the package. Do not substitute
`/sys/kernel/security/lsm` for this check: it is absent on hosts that do enforce Landlock.

Expected shape (values vary by host):

```json
{"os":"linux","arch":"x86_64","supported":true,"ptrace":true,"seccomp":true,
 "landlock":8,"proven":true,"runtime":"allocator-entropy-v1 audited (…)"}
```

## Small reproduction — about 5 minutes, no network beyond the toolchain

```sh
# 1. Build (or install the packaged archive; see docs/INSTALL.md)
cargo build --release -p tracejit-cli
export PATH="$PWD/target/release:$PATH"

# 2. The shipped demo: cold trace, guarded hit, explain, input mutation -> DEOPT
bash scripts/demo.sh

# 3. A genuine compression workload on a 4 MiB incompressible file
mkdir -p /tmp/rp && cd /tmp/rp
head -c 4194304 /dev/urandom > in.bin
tracejit run -- gzip -6 -c in.bin > first.gz     # discovery
tracejit run -- gzip -6 -c in.bin > second.gz    # guarded reuse
gzip -6 -c in.bin > native.gz
cmp first.gz native.gz && cmp second.gz native.gz && echo "gnu-gzip-identical"

# 4. Damaged CAS object must never be served
obj=$(ls "$TRACEJIT_CACHE_DIR"/objects/* | head -1)
: > "$obj"                                       # truncate one stored object
tracejit run --json -- gzip -6 -c in.bin > after.json 2>/dev/null; gzip -6 -c in.bin > after.gz
python3 -c 'import json;d=json.load(open("after.json"));print("kind",d["kind"])'   # Executed, not Reused
cmp after.gz native.gz && echo "still-correct-after-corruption"

# 5. Short correctness suite
cargo test -p tracejit-core --lib
```

Expected: `scripts/demo.sh` prints `RESULT direct PASS`, `RESULT miss PASS`, `RESULT hit PASS`,
`RESULT explain PASS`, `RESULT mutation DEOPT`; step 3 prints `gnu-gzip-identical`; step 4 prints
`still-correct-after-corruption` — a truncated object is not served, the command runs instead, and
the output still matches native gzip. Step 5 passes.

`scripts/demo.sh` exports `TRACEJIT_CACHE_DIR`, `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and
`MALLOC_ARENA_MAX=1` itself; steps 3–4 need those exported too, because an inherited descriptor or
an unaudited allocator environment is refused rather than cached.

Fresh-user install from the archive instead of a source build:

```sh
tar xzf tracejit-v0.3.0-alpha.1-x86_64-unknown-linux-gnu.tar.gz
cd tracejit-v0.3.0-alpha.1-x86_64-unknown-linux-gnu && sha256sum -c ../SHA256SUMS
./scripts/install-dev.sh     # or scripts/install-release.sh from a checkout
tracejit doctor
```

## Full evaluation — hours, needs Firebuild 0.8.6.2 and ccache

Pinned inputs. Fetch and verify before measuring; every table records the commit it came from.

| input | version / hash | used by |
| --- | --- | --- |
| TraceJIT | `b81242d65e8a02bfe4459506a44b2eca566c5d89` | everything |
| Linux source archive | `linux-6.6.50.tar.xz` (pinned in `benchmarks/phase_af/artifact_scale` setup) | artifact scale |
| Firebuild | `0.8.6.2` (built from source; record the build id) | competitive matrix |
| ccache | any 4.x; record `ccache --version` | compiler workloads |
| gzip, bzip2, sed | distribution versions; record them | workload matrix |

```sh
# 1. Frozen compatibility census (native vs controlled contract)
python3 benchmarks/phase_ae/census.py            # ~40 min, 4 vCPU, <2 GiB
python3 benchmarks/phase_ae/test_accounting.py   # 17 tests

# 2. Competitive matrix (needs Firebuild + ccache on PATH)
bash benchmarks/realworld/run_v2.sh              # see its README for the pinned config

# 3. Artifact-scale study (needs the pinned archive; ~15 min, ~2 GiB disk)
python3 benchmarks/phase_af/build_tables.py --check --emit paper/tables
python3 benchmarks/phase_af/test_tables.py

# 4. Adversarial and correctness evidence
python3 benchmarks/phase_ae/toctou_race.py       # reproduces the residual race
python3 benchmarks/phase_af/enforcement_lifecycle.py --assert-capability
bash scripts/phase_k4_restore_fault.sh
cargo test --workspace

# 5. Environment qualification
tracejit doctor --json > env.json
```

Storage: about 2 GiB for the archive study, 4 GiB for a full competitive run with warm caches.
Capability-dependent skips: `enforcement_lifecycle.py` without `--assert-capability` records an
incapable host as a result rather than a pass; `phase_k4_restore_fault.sh` prints
`RESULT … SKIP` when its pause hook does not fire, and the property it targets is covered by
`linux_integration::interrupted_restore_intent_refuses_hit`.

## Publication tables

```sh
python3 benchmarks/phase_af/build_tables.py --check    # fails on missing or inconsistent evidence
python3 benchmarks/phase_af/build_tables.py --emit paper/tables
python3 benchmarks/phase_af/test_tables.py             # 10 tests
```

The paper includes `paper/tables/*.tex` directly. No benchmark value in the paper tables is typed
by hand: each is generated from a file under `benchmarks/results/`, and `--check` fails when a
source is missing or two sources disagree.

## Clean-checkout verification

```sh
git clone <repo> && cd tracejit && git checkout b81242d
cargo build --release -p tracejit-cli
bash scripts/clean-install-verify.sh /tmp/dist    # needs a packaged dist dir
```

Expected: every line `RESULT … PASS`, ending `RESULT clean-install PASS`.

## What an independent operator cannot get from this package

* A second hardware platform. All numbers here come from one 4-vCPU host plus one CI runner.
* Independent Firebuild builds with identical optimisation settings.
* Any claim of binary reproducibility: two builds of this tree were not shown to produce equal
  digests, and the packaged artifact was built from a dirty tree.
