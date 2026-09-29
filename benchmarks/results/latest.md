# TraceJIT benchmark result

Measured commit: `63e33638709aacfaed896ab587435e64c0ecea62`

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
| Baseline | 7.396036 ms | 10.619713 ms | 7.344846 ms | 11.731960 ms | 1.036400 ms | 30 |
| Traced cold | 21.024211 ms | 168.417168 ms | 19.017278 ms | 178.756103 ms | 52.009012 ms | 30 |
| Guard check | 1.113292 ms | 1.251817 ms | 1.028313 ms | 19.630951 ms | 3.324015 ms | 30 |
| Cached end-to-end | 7.957282 ms | 18.618426 ms | 7.539442 ms | 25.213143 ms | 3.581329 ms | 30 |

Tracing overhead: `184.263232%`

Cache-hit speedup: `0.929468x`

Median time saved: `-0.561246 ms`

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
- process read process identity via gettid

The equivalence check compares workload exit status, captured stdout, captured stderr, output bytes, and output SHA-256 across baseline, traced, and cache-hit execution.

## Environment

### `uname -a`

```text
Linux runnervmtr4k5 6.17.0-1022-azure #22-Ubuntu SMP Mon Jul 27 17:24:03 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
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
Address sizes:                           48 bits physical, 48 bits virtual
Byte Order:                              Little Endian
CPU(s):                                  4
On-line CPU(s) list:                     0-3
Vendor ID:                               AuthenticAMD
Model name:                              AMD EPYC 9V74 80-Core Processor
CPU family:                              25
Model:                                   17
Thread(s) per core:                      2
Core(s) per socket:                      2
Socket(s):                               1
Stepping:                                1
BogoMIPS:                                5192.29
Flags:                                   fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm constant_tsc rep_good nopl xtopology tsc_reliable nonstop_tsc cpuid extd_apicid aperfmperf tsc_known_freq pni pclmulqdq ssse3 fma cx16 pcid sse4_1 sse4_2 movbe popcnt aes xsave avx f16c rdrand hypervisor lahf_lm cmp_legacy svm cr8_legacy abm sse4a misalignsse 3dnowprefetch osvw topoext vmmcall fsgsbase bmi1 avx2 smep bmi2 erms invpcid avx512f avx512dq rdseed adx smap avx512ifma clflushopt clwb avx512cd sha_ni avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves user_shstk avx512_bf16 clzero xsaveerptr rdpru arat npt nrip_save tsc_scale vmcb_clean flushbyasid decodeassists pausefilter pfthreshold v_vmsave_vmload avx512vbmi umip avx512_vbmi2 gfni vaes vpclmulqdq avx512_vnni avx512_bitalg avx512_vpopcntdq rdpid fsrm
Virtualization:                          AMD-V
Hypervisor vendor:                       Microsoft
Virtualization type:                     full
L1d cache:                               64 KiB (2 instances)
L1i cache:                               64 KiB (2 instances)
L2 cache:                                2 MiB (2 instances)
L3 cache:                                32 MiB (1 instance)
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-3
Vulnerability Gather data sampling:      Not affected
Vulnerability Ghostwrite:                Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Old microcode:             Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Vulnerable: Safe RET, no microcode
Vulnerability Spec store bypass:         Vulnerable
Vulnerability Spectre v1:                Mitigation; usercopy/swapgs barriers and __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; Retpolines; STIBP disabled; RSB filling; PBRSB-eIBRS Not affected; BHI Not affected
Vulnerability Srbds:                     Not affected
Vulnerability Tsa:                       Vulnerable: No microcode
Vulnerability Tsx async abort:           Not affected
Vulnerability Vmscape:                   Not affected
```

### `free -h`

```text
total        used        free      shared  buff/cache   available
Mem:            15Gi       1.1Gi        11Gi        48Mi       3.8Gi        14Gi
Swap:          3.0Gi          0B       3.0Gi
```

### `df -T .`

```text
Filesystem     Type 1K-blocks     Used Available Use% Mounted on
/dev/root      ext4 151263856 61981764  89265708  41% /
```

### `python3 --version`

```text
Python 3.12.3
```

### `rustc --version`

```text
rustc 1.98.1 (48a229cea 2026-09-01)
```

### `cargo --version`

```text
cargo 1.98.1 (797e8a9bc 2026-08-05)
```

### `git rev-parse HEAD`

```text
63e33638709aacfaed896ab587435e64c0ecea62
```

## Limitations

These measurements cover one small deterministic C ETL workload on one ephemeral GitHub-hosted runner. CPython is reported as a refusal, not as a speedup. They are not evidence of universal speedups, production readiness, or performance on other workloads or machines.
