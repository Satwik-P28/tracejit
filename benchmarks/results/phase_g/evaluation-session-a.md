# Phase G evaluation

Commit `f50c29785eeed92647b1bf6fbd96a3e6c725afaf` · binary `a00efdaec19ea98b` · 5 warmups + 20 runs (suite defaults).

## Host

- kernel: `6.12.113+`
- rustc: `rustc 1.100.0 (0ef1bc386 2026-11-09)`
- filesystem: `ext4   /      rw,relatime`
- cpus: `4`

### Tooling availability

| Tool | Path |
| --- | --- |
| make | `/usr/bin/make` |
| ninja | `SKIPPED (not installed)` |
| ccache | `SKIPPED (not installed)` |
| sccache | `SKIPPED (not installed)` |
| cc | `/usr/bin/cc` |
| bzip2 | `/usr/bin/bzip2` |
| gzip | `/usr/bin/gzip` |
| perf | `SKIPPED (not installed)` |
| strace | `SKIPPED (not installed)` |

## Suite summary

| Scenario | Verdict / key number |
| --- | --- |
| cpu-heavy-transform | direct 36.136 ms → warm 3.116 ms (reused=True) |
| short-command-overhead-loss | direct 1.537 ms vs warm 3.421 ms (expect loss) |
| compression-bzip2 | direct 26.485 ms → always-warm 5.333 ms (reused=True) |
| c-compile | cold_kind=Executed class=Nondeterministic |
| build-edit-recovery | skips=['ninja', 'ccache', 'sccache']; tracejit phases=6; make skipped=False |
| aba-candidate-reuse | third Reused 4/4 |
| large-input-hashing | direct 10.786 ms → warm 21.539 ms |
| multi-output-restore | hit kind=Reused both_present=True |
| nondeterministic-refuse | cold_kind=Executed warm_reused=False |
| high-candidate-count-lookup | b1 newest=3.051ms; b8 newest=3.774ms; b32 newest=2.933ms |
| mixed-eligible-ineligible-sequence | warm kinds=['Reused', 'Executed', 'Reused', 'Reused', 'Executed'] |

## Ablations

### guard-mode-strict-vs-fast

```
{
  "ablation": "guard-mode-strict-vs-fast",
  "note": "Fast may skip content hash after metadata match; Strict always hashes. Not a reordering toggle \u2014 measures pair validation cost difference.",
  "modes": {
    "strict": {
      "name": "guard-strict",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/tmp/phase-g-guard-3i5y5mh3/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-guard-3i5y5mh3/work"
      ],
      "cold_ms": 37.127,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 8.409,
        "p95_ms": 9.536,
        "min_ms": 6.815,
        "max_ms": 9.837,
        "pstdev_ms": 0.791,
        "rsd": 0.0941,
        "samples_ms": [
          8.564,
          7.43,
          7.502,
          7.48,
          8.33,
          8.542,
          9.536,
          9.837,
          8.943,
          7.743,
          6.991,
          8.67,
          8.411,
          9.487,
          8.533,
          8.376,
          8.113,
          6.815,
          8.675,
          8.408
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.008,
        "cas_restore_ns": 4.878,
        "cli_parse_ns": 0.086,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 1.046,
        "identity_prepare_ns": 0.11,
        "lookup_key_ns": 0.005,
        "present_ns": 0.026,
        "process_startup_ns": 6.222,
        "record_decode_ns": 0.406,
        "sqlite_open_ns": 0.078,
        "sqlite_query_ns": 0.318,
        "sqlite_schema_ns": 0.103,
        "stdio_replay_ns": 0.009
      },
      "invalidation": null
    },
    "fast": {
      "name": "guard-fast",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "fast",
      "contract": null,
      "argv": [
        "/tmp/phase-g-guard-3i5y5mh3/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-guard-3i5y5mh3/work"
      ],
      "cold_ms": 41.404,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 7.386,
        "p95_ms": 7.894,
        "min_ms": 5.897,
        "max_ms": 7.952,
        "pstdev_ms": 0.635,
        "rsd": 0.086,
        "samples_ms": [
          6.352,
          6.341,
          7.428,
          7.562,
          7.617,
          7.578,
          7.753,
          7.874,
          6.622,
          6.901,
          6.679,
          7.858,
          6.639,
          7.343,
          7.894,
          7.952,
          6.198,
          7.114,
          7.612,
          5.897
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.008,
        "cas_restore_ns": 4.916,
        "cli_parse_ns": 0.081,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.032,
        "identity_prepare_ns": 0.102,
        "lookup_key_ns": 0.004,
        "present_ns": 0.024,
        "process_startup_ns": 5.663,
        "record_decode_ns": 0.398,
        "sqlite_open_ns": 0.078,
        "sqlite_query_ns": 0.311,
        "s
```

### adaptive-admission

```
{
  "ablation": "adaptive-admission",
  "note": "auto should avoid tracing short ETL; always pays cold+warm; never never caches",
  "rows": {
    "etl-always": {
      "name": "etl-always",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/agent/repos/tracejit/benchmarks/workloads/c-etl/etl"
      ],
      "cold_ms": 11.963,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 10,
        "median_ms": 3.89,
        "p95_ms": 4.738,
        "min_ms": 3.219,
        "max_ms": 4.738,
        "pstdev_ms": 0.508,
        "rsd": 0.1307,
        "samples_ms": [
          3.945,
          4.1,
          3.353,
          3.333,
          3.219,
          4.738,
          4.684,
          4.115,
          3.597,
          3.835
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.009,
        "cas_restore_ns": 1.387,
        "cli_parse_ns": 0.088,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.573,
        "identity_prepare_ns": 0.113,
        "lookup_key_ns": 0.004,
        "present_ns": 0.027,
        "process_startup_ns": 5.852,
        "record_decode_ns": 0.166,
        "sqlite_open_ns": 0.083,
        "sqlite_query_ns": 0.155,
        "sqlite_schema_ns": 0.102,
        "stdio_replay_ns": 0.011
      },
      "invalidation": null
    },
    "transform-always": {
      "name": "transform-always",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/agent/repos/tracejit/benchmarks/workloads/c-transform/transform"
      ],
      "cold_ms": 45.623,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 5,
        "median_ms": 3.602,
        "p95_ms": 3.933,
        "min_ms": 3.505,
        "max_ms": 3.933,
        "pstdev_ms": 0.154,
        "rsd": 0.0428,
        "samples_ms": [
          3.602,
          3.933,
          3.505,
          3.531,
          3.684
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.009,
        "cas_restore_ns": 1.094,
        "cli_parse_ns": 0.082,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.591,
        "identity_prepare_ns": 0.116,
        "lookup_key_ns": 0.004,
        "present_ns": 0.024,
        "process_startup_ns": 6.996,
        "record_decode_ns": 0.153,
        "sqlite_open_ns": 0.088,
        "sqlite_query_ns": 0.16,
        "sqlite_schema_ns": 0.108,
        "stdio_replay_ns": 0.011
      },
      "invalidation": null
    },
    "etl-auto": {
      "name": "etl-auto",
      "arm": "tracejit-auto",
      "admission": "auto",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/agent/repos/tracejit/benchmarks/workloads/c-etl/etl"
      ],
      "cold_ms": 6.733,
      "cold_kind": "Executed",
      "cold_classification": "Unknown",
      "warm": {
        "runs": 10,
        "median_ms": 3.975,
        "p95_ms": 4.937,
        "min_ms": 3.709,
        "max_ms": 4.937,
        "pstdev_ms": 0.321,
        "rsd": 0.0807,
        "samples_ms": [
          4.024,
          3.831,
          3.99,
          3.973,
          3.883,
          3.709,
          3.845,
          3.989,
          4.937,
          3.977
        ]
      },
      "warm_kinds": [
        "Executed",
        "Executed",
        "Executed",
        "Executed",
        "Executed",
        "Executed",
        "Executed",
        "Executed",
        "Exec
```

### phase-f-opts-vs-phase-e-tip

```
{
  "ablation": "phase-f-opts-vs-phase-e-tip",
  "phase_e_binary": "/tmp/tracejit-phase-e-tip/target/release/tracejit",
  "phase_e_sha256": "d22e0db2fa5611273b9b61beb55ba6acb4a327173265ac171627861f49726de1",
  "tip_sha256": "a00efdaec19ea98bd9ba029a08c1ef3079456de27560b8643227cb5fa989ada8",
  "large_file": {
    "tip": {
      "name": "phase-f-tip-large",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/tmp/phase-g-pf-rwd106wt/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-pf-rwd106wt/work"
      ],
      "cold_ms": 68.132,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 12.641,
        "p95_ms": 14.193,
        "min_ms": 11.295,
        "max_ms": 14.594,
        "pstdev_ms": 0.857,
        "rsd": 0.0678,
        "samples_ms": [
          13.718,
          13.187,
          12.012,
          14.193,
          12.247,
          14.594,
          13.907,
          12.441,
          12.902,
          12.33,
          13.709,
          12.298,
          12.445,
          12.599,
          12.683,
          13.132,
          14.042,
          11.821,
          11.295,
          12.486
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.009,
        "cas_restore_ns": 7.541,
        "cli_parse_ns": 0.092,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 2.042,
        "identity_prepare_ns": 0.11,
        "lookup_key_ns": 0.004,
        "present_ns": 0.036,
        "process_startup_ns": 4.75,
        "record_decode_ns": 0.637,
        "sqlite_open_ns": 0.085,
        "sqlite_query_ns": 0.561,
        "sqlite_schema_ns": 0.107,
        "stdio_replay_ns": 0.011
      },
      "invalidation": null
    },
    "phase_e": {
      "name": "phase-e-tip-large",
      "arm": "tracejit-always",
      "admission": "always",
      "guard_mode": "strict",
      "contract": null,
      "argv": [
        "/tmp/phase-g-pf-rwd106wt/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-pf-rwd106wt/work"
      ],
      "cold_ms": 71.322,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 14.146,
        "p95_ms": 15.603,
        "min_ms": 11.788,
        "max_ms": 15.847,
        "pstdev_ms": 1.072,
        "rsd": 0.0758,
        "samples_ms": [
          14.093,
          13.647,
          14.37,
          15.847,
          14.176,
          14.208,
          14.661,
          15.39,
          13.465,
          15.603,
          14.162,
          14.053,
          14.522,
          14.75,
          14.13,
          12.728,
          12.054,
          13.574,
          11.788,
          12.366
        ]
      },
      "warm_kinds": [
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused",
        "Reused"
      ],
      "all_warm_reused": true,
      "phases_median_ms": {
        "cache_prepare_ns": 0.009,
        "cas_restore_ns": 9.116,
        "cli_parse_ns": 0.084,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 1.856,
        "identity_prepare_ns": 0.09,
        "lookup_key_ns": 0.013,
        "present_ns": 0.034,
      
```


## Raw paths

- JSON: `benchmarks/results/phase_g/evaluation-session-a.json`
- Markdown: `/agent/repos/tracejit/benchmarks/results/phase_g/evaluation-session-a.md`

Controlled-runtime claims: **not claimed** (not on main).

