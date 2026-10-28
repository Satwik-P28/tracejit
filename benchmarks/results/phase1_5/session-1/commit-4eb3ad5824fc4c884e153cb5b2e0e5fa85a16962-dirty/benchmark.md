# TraceJIT benchmark result

Measured commit: `4eb3ad5824fc4c884e153cb5b2e0e5fa85a16962`

## Methodology

The committed C ETL workload was measured with 10 warmups and 50 recorded runs per stable condition. Baseline runs execute that binary directly. Every traced-cold sample uses a fresh TraceJIT cache. Cached samples use an unchanged guarded entry and must report a cache hit. All timings are wall-clock process times except guard-check timings, which are TraceJIT's internal guard validation, output restoration, and cached-stream loading duration.

The process ran with `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `MALLOC_ARENA_MAX=1` so glibc does not draw allocator entropy or query CPU count. The Python ETL is analyzed separately with `PYTHONHASHSEED=0` and `PYTHONDONTWRITEBYTECODE=1`. CPU frequency, neighboring runner activity, and warm operating-system filesystem caches were not controlled.

## Commands

```text
cargo build --workspace --release
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
python3 benchmarks/harness/benchmark.py --runs 30 --warmups 5
```

## Results

| Condition | Median | p95 | Minimum | Maximum | Standard deviation | Runs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 8.341420 ms | 8.430869 ms | 8.285366 ms | 8.462468 ms | 0.040564 ms | 50 |
| Traced cold | 19.023566 ms | 19.850000 ms | 18.349036 ms | 21.470368 ms | 0.533140 ms | 50 |
| Guard check | 1.594950 ms | 1.730466 ms | 1.488791 ms | 2.411140 ms | 0.124911 ms | 50 |
| Cached end-to-end | 3.971501 ms | 4.187832 ms | 3.876498 ms | 4.603512 ms | 0.114342 ms | 50 |

Tracing overhead: `128.061481%`

Cache-hit speedup: `2.100319x`

Median time saved: `4.369919 ms`

## Correctness

Output equivalence: `PASS`

Mutation/deopt: `PASS`

Changed dependency: `benchmarks/workloads/python-etl/inputs/sales.csv`

Explanation identified dependency: `yes`

## Python ETL

This command is not part of the timed reuse result. CPython binds its main thread with `gettid`, which TraceJIT classifies as process identity and refuses.

Command: `python3 benchmarks/workloads/python-etl/main.py`

Classification: `Nondeterministic`

Eligible for reuse: `no`

Reasons:

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

The equivalence check compares workload exit status, captured stdout, captured stderr, output bytes, and output SHA-256 across baseline, traced, and cache-hit execution.

## Environment

### `uname -a`

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

### `uname -m`

```text
x86_64
```

### `cat /etc/os-release`

```text
PRETTY_NAME="Ubuntu 24.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.5 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo
```

### `lscpu`

```text
Architecture:                         x86_64
CPU op-mode(s):                       32-bit, 64-bit
Address sizes:                        48 bits physical, 48 bits virtual
Byte Order:                           Little Endian
CPU(s):                               2
On-line CPU(s) list:                  0,1
Vendor ID:                            AuthenticAMD
Model name:                           19/01
CPU family:                           25
Model:                                1
Thread(s) per core:                   1
Core(s) per socket:                   2
Socket(s):                            1
Stepping:                             1
BogoMIPS:                             4890.81
Flags:                                fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm constant_tsc rep_good nopl nonstop_tsc cpuid extd_apicid tsc_known_freq pni pclmulqdq ssse3 fma cx16 pcid sse4_1 sse4_2 x2apic movbe popcnt aes xsave avx f16c rdrand hypervisor lahf_lm cmp_legacy svm cr8_legacy abm sse4a misalignsse 3dnowprefetch osvw topoext perfctr_core invpcid_single ssbd ibrs ibpb stibp vmmcall fsgsbase tsc_adjust bmi1 avx2 smep bmi2 erms invpcid rdseed adx smap clflushopt clwb sha_ni xsaveopt xsavec xgetbv1 xsaves clzero xsaveerptr wbnoinvd arat npt lbrv nrip_save tsc_scale vmcb_clean flushbyasid pausefilter pfthreshold v_vmsave_vmload vgif umip pku ospke vaes vpclmulqdq rdpid fsrm arch_capabilities
Virtualization:                       AMD-V
Hypervisor vendor:                    KVM
Virtualization type:                  full
L1d cache:                            32 KiB (1 instance)
L1i cache:                            32 KiB (1 instance)
L2 cache:                             512 KiB (1 instance)
L3 cache:                             32 MiB (1 instance)
NUMA node(s):                         1
NUMA node0 CPU(s):                    0,1
Vulnerability Gather data sampling:   Not affected
Vulnerability Itlb multihit:          Not affected
Vulnerability L1tf:                   Not affected
Vulnerability Mds:                    Not affected
Vulnerability Meltdown:               Not affected
Vulnerability Mmio stale data:        Not affected
Vulnerability Reg file data sampling: Not affected
Vulnerability Retbleed:               Not affected
Vulnerability Spec rstack overflow:   Mitigation; safe RET, no microcode
Vulnerability Spec store bypass:      Mitigation; Speculative Store Bypass disabled via prctl
Vulnerability Spectre v1:             Mitigation; usercopy/swapgs barriers and __user pointer sanitization
Vulnerability Spectre v2:             Mitigation; Retpolines; IBPB conditional; IBRS_FW; STIBP disabled; RSB filling; PBRSB-eIBRS Not affected; BHI Not affected
Vulnerability Srbds:                  Not affected
Vulnerability Tsx async abort:        Not affected
```

### `free -h`

```text
total        used        free      shared  buff/cache   available
Mem:           3.8Gi       407Mi       2.0Gi       1.1Mi       1.7Gi       3.4Gi
Swap:             0B          0B          0B
```

### `df -T .`

```text
Filesystem     Type 1K-blocks    Used Available Use% Mounted on
/dev/root      ext4  16337788 7156108   8326436  47% /
```

### `python3 --version`

```text
Python 3.12.3
```

### `rustc --version`

```text
rustc 1.99.1 (58cf8f9c3 2026-10-13)
```

### `cargo --version`

```text
cargo 1.99.1 (5f94df478 2026-08-27)
```

### `git rev-parse HEAD`

```text
4eb3ad5824fc4c884e153cb5b2e0e5fa85a16962
```


Every condition reports `relative_standard_deviation`, so run-to-run noise is visible next to each median rather than hidden behind it.

## Repository mutation

Tracked or untracked paths that appeared during the run: `['benchmarks/workloads/python-etl/inputs/sales.csv']`. The workload writes only into its own `output/` directory and the compiled binary, both of which are ignored by Git, and the harness restores the input and output files it touched.

## Limitations

These measurements cover one small deterministic C ETL workload on one Linux x86_64 host. CPython is reported as a refusal, not as a speedup. They are not evidence of universal speedups, production readiness, or performance on other workloads or machines.
