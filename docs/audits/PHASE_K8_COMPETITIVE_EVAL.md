# Phase K8 — Competitive evaluation (independent re-measure)

Date: 2026-11-14  
Tip: `364331b904d41de3feb7defae152ec0e50112e0e` (post-K7)  
Harness: `benchmarks/repos/phase_k8_competitive.py`  
Raw: `benchmarks/results/phase_k8/competitive.{json,md}`

## Claim boundary

TraceJIT is a transparent command cache. Correctly configured Make/Ninja own the build graph and win identical-rerun wall time. The defensible difference is **automatic dependency discovery + content-correct recovery** when mtime/graph tools retain stale bytes. No invented baselines.

## Host tooling

| Tool | Status |
| --- | --- |
| make | `/usr/bin/make` — measured |
| ninja | `/usr/bin/ninja` — measured (was skipped on Phase G host) |
| bzip2 / cc | installed |
| ccache | installed but **not applicable** as a transparent bzip2 command-cache arm |
| sccache | **not installed** — skipped |
| Firebuild | **not installed** — skipped |

## Build/edit recovery (this host)

Single-invocation phases for correctness-critical transitions; steady-state warm samples only for identical rerun.

| Phase | make | ninja | TraceJIT | Verdict |
| --- | ---: | ---: | ---: | --- |
| identical rerun | **1.317** ms ok | **1.385** ms ok | 14.006 ms ok | **loss** vs graph tools |
| outputs deleted | 23.362 ok | 11.227 ok | 22.385 ok (Reused×3) | recovery works |
| mtime-preserved edit | 1.543 **WRONG** | 1.820 **WRONG** | 41.887 **ok** | **correctness win** |
| corrupted output | 1.603 **WRONG** | 1.724 **WRONG** | 42.069 **ok** | **correctness win** |

simple_cas (input-byte hashcache) stayed content-correct and was slower than TraceJIT warm identical rerun on this fixture (31.5 vs 14.0 ms).

## Retained short-command loss

| Arm | Median wall |
| --- | ---: |
| direct `c-etl` | 1.575 ms |
| TraceJIT warm reuse | 3.146 ms (all `Reused`) |

Net loss retained. Safety not weakened for this floor.

## Relation to Phase G / 2T

Phase G sessions A/B and Phase 2T remain archival evidence. K8 confirms the same qualitative story on tip `364331b` with **ninja now installed and measured**, and continues to skip inventing Firebuild/sccache numbers.
