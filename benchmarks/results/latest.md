# TraceJIT benchmark result

Measured commit: `94c64c709dfb0bec433dacf83cc967aeee6a1f1b`

## Methodology

The committed C ETL workload was measured with 5 warmups and 30 recorded runs per stable condition. Baseline runs execute that binary directly. Every traced-cold sample uses a fresh TraceJIT cache. Cached samples use an unchanged guarded entry and must report a cache hit. All timings are wall-clock process times except guard-check timings, which are TraceJIT's internal guard validation, output restoration, and cached-stream loading duration.

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
| Baseline | 1.455152 ms | 1.644641 ms | 1.234551 ms | 1.824625 ms | 0.137484 ms | 30 |
| Traced cold | 8.968401 ms | 12.919426 ms | 7.820731 ms | 14.036943 ms | 1.462091 ms | 30 |
| Guard check | 1.390462 ms | 1.974330 ms | 1.109110 ms | 2.348442 ms | 0.269321 ms | 30 |
| Cached end-to-end | 3.571171 ms | 5.655776 ms | 3.017916 ms | 5.782441 ms | 0.616765 ms | 30 |

Tracing overhead: `516.320563%`

Cache-hit speedup: `0.407472x`

Median time saved: `-2.116019 ms`

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

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

The equivalence check compares workload exit status, captured stdout, captured stderr, output bytes, and output SHA-256 across baseline, traced, and cache-hit execution.

## Environment

### `uname -a`

```text
Linux cursor 6.12.113+ #1 SMP PREEMPT_DYNAMIC Fri Nov 13 20:22:28 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
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
Architecture:                            x86_64
CPU op-mode(s):                          32-bit, 64-bit
Address sizes:                           46 bits physical, 57 bits virtual
Byte Order:                              Little Endian
CPU(s):                                  4
On-line CPU(s) list:                     0-3
Vendor ID:                               GenuineIntel
Model name:                              Intel(R) Xeon(R) Processor
CPU family:                              6
Model:                                   207
Thread(s) per core:                      1
Core(s) per socket:                      4
Socket(s):                               1
Stepping:                                2
BogoMIPS:                                4800.00
Flags:                                   fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush dts mmx fxsr sse sse2 ss ht syscall nx pdpe1gb rdtscp lm constant_tsc pebs bts rep_good nopl xtopology nonstop_tsc cpuid tsc_known_freq pni pclmulqdq dtes64 vmx ssse3 fma cx16 pcid sse4_1 sse4_2 x2apic movbe popcnt tsc_deadline_timer aes xsave avx f16c rdrand hypervisor lahf_lm abm 3dnowprefetch cpuid_fault ssbd ibrs ibpb stibp ibrs_enhanced tpr_shadow flexpriority ept vpid ept_ad fsgsbase tsc_adjust bmi1 avx2 smep bmi2 erms invpcid avx512f avx512dq rdseed adx smap avx512ifma clflushopt clwb avx512cd sha_ni avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves avx_vnni avx512_bf16 wbnoinvd arat vnmi avx512vbmi umip pku ospke avx512_vbmi2 gfni vaes vpclmulqdq avx512_vnni avx512_bitalg avx512_vpopcntdq rdpid bus_lock_detect cldemote movdiri movdir64b fsrm md_clear serialize tsxldtrk amx_bf16 avx512_fp16 amx_tile amx_int8 flush_l1d arch_capabilities
Virtualization:                          VT-x
Hypervisor vendor:                       KVM
Virtualization type:                     full
L1d cache:                               192 KiB (4 instances)
L1i cache:                               128 KiB (4 instances)
L2 cache:                                8 MiB (4 instances)
L3 cache:                                320 MiB (1 instance)
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-3
Vulnerability Gather data sampling:      Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Not affected
Vulnerability Spec store bypass:         Mitigation; Speculative Store Bypass disabled via prctl
Vulnerability Spectre v1:                Mitigation; usercopy/swapgs barriers and __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; Enhanced / Automatic IBRS; IBPB conditional; PBRSB-eIBRS SW sequence; BHI BHI_DIS_S
Vulnerability Srbds:                     Not affected
Vulnerability Tsa:                       Not affected
Vulnerability Tsx async abort:           Mitigation; TSX disabled
Vulnerability Vmscape:                   Not affected
```

### `free -h`

```text
total        used        free      shared  buff/cache   available
Mem:            15Gi        10Gi       1.6Gi        17Mi       3.5Gi       4.8Gi
Swap:             0B          0B          0B
```

### `df -T .`

```text
Filesystem     Type 1K-blocks    Used Available Use% Mounted on
/dev/vdc       ext4 265591976 9979468 255596124   4% /
```

### `python3 --version`

```text
Python 3.12.3
```

### `rustc --version`

```text
rustc 1.100.0 (0ef1bc386 2026-11-09)
```

### `cargo --version`

```text
cargo 1.100.0 (3acc79c0c 2026-11-05)
```

### `git rev-parse HEAD`

```text
94c64c709dfb0bec433dacf83cc967aeee6a1f1b
```


Every condition reports `relative_standard_deviation`, so run-to-run noise is visible next to each median rather than hidden behind it.

## Repository mutation

Tracked or untracked paths that appeared during the run: `['benchmarks/results/explain-cache-hit.txt', 'benchmarks/results/explain-deopt.txt', 'benchmarks/workloads/python-etl/inputs/sales.csv']`. The workload writes only into its own `output/` directory and the compiled binary, both of which are ignored by Git, and the harness restores the input and output files it touched.

## Limitations

These measurements cover one small deterministic C ETL workload on one Linux x86_64 host. CPython is reported as a refusal, not as a speedup. They are not evidence of universal speedups, production readiness, or performance on other workloads or machines.
