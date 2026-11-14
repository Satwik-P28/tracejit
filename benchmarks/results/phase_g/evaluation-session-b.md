# Phase G evaluation

Commit `44bc118ec46b6faf5776107861313e10c95e0a46` · binary `a00efdaec19ea98b` · 5 warmups + 20 runs (suite defaults).

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
| cpu-heavy-transform | direct 36.267 ms → warm 3.287 ms (reused=True) |
| short-command-overhead-loss | direct 1.583 ms vs warm 3.209 ms (expect loss) |
| compression-bzip2 | direct 26.829 ms → always-warm 4.459 ms (reused=True) |
| c-compile | cold_kind=Executed class=Nondeterministic |
| build-edit-recovery | skips=['ninja', 'ccache', 'sccache']; tracejit phases=6; make skipped=False |
| aba-candidate-reuse | third Reused 4/4 |
| large-input-hashing | direct 11.102 ms → warm 21.331 ms |
| multi-output-restore | hit kind=Reused both_present=True |
| nondeterministic-refuse | cold_kind=Executed warm_reused=False |
| high-candidate-count-lookup | b1 newest=2.89ms; b8 newest=3.046ms; b32 newest=3.412ms |
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
        "/tmp/phase-g-guard-8qsgh_1v/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-guard-8qsgh_1v/work"
      ],
      "cold_ms": 33.658,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 7.098,
        "p95_ms": 8.145,
        "min_ms": 6.438,
        "max_ms": 8.263,
        "pstdev_ms": 0.537,
        "rsd": 0.0756,
        "samples_ms": [
          7.55,
          7.054,
          7.102,
          6.775,
          6.518,
          8.145,
          8.083,
          8.263,
          7.572,
          6.83,
          6.87,
          7.109,
          7.008,
          6.834,
          7.094,
          6.438,
          6.851,
          7.615,
          8.063,
          7.369
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
        "cas_restore_ns": 3.51,
        "cli_parse_ns": 0.086,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 1.184,
        "identity_prepare_ns": 0.103,
        "lookup_key_ns": 0.004,
        "present_ns": 0.024,
        "process_startup_ns": 5.893,
        "record_decode_ns": 0.398,
        "sqlite_open_ns": 0.075,
        "sqlite_query_ns": 0.302,
        "sqlite_schema_ns": 0.099,
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
        "/tmp/phase-g-guard-8qsgh_1v/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-guard-8qsgh_1v/work"
      ],
      "cold_ms": 38.222,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 6.023,
        "p95_ms": 6.547,
        "min_ms": 5.611,
        "max_ms": 7.231,
        "pstdev_ms": 0.349,
        "rsd": 0.0579,
        "samples_ms": [
          6.326,
          5.904,
          6.33,
          5.611,
          7.231,
          5.837,
          6.135,
          5.89,
          5.828,
          6.547,
          5.976,
          5.958,
          5.85,
          5.737,
          6.42,
          6.1,
          6.257,
          6.223,
          6.025,
          6.022
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
        "cas_restore_ns": 3.742,
        "cli_parse_ns": 0.078,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.03,
        "identity_prepare_ns": 0.099,
        "lookup_key_ns": 0.004,
        "present_ns": 0.025,
        "process_startup_ns": 6.091,
        "record_decode_ns": 0.395,
        "sqlite_open_ns": 0.071,
        "sqlite_query_ns": 0.306,
        "sqlite
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
      "cold_ms": 10.333,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 10,
        "median_ms": 3.045,
        "p95_ms": 4.066,
        "min_ms": 2.728,
        "max_ms": 4.066,
        "pstdev_ms": 0.409,
        "rsd": 0.1342,
        "samples_ms": [
          3.807,
          2.958,
          3.205,
          3.147,
          2.728,
          3.01,
          4.066,
          2.805,
          3.08,
          2.939
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
        "cache_prepare_ns": 0.008,
        "cas_restore_ns": 0.648,
        "cli_parse_ns": 0.083,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.508,
        "identity_prepare_ns": 0.104,
        "lookup_key_ns": 0.004,
        "present_ns": 0.025,
        "process_startup_ns": 6.751,
        "record_decode_ns": 0.146,
        "sqlite_open_ns": 0.077,
        "sqlite_query_ns": 0.15,
        "sqlite_schema_ns": 0.101,
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
      "cold_ms": 45.034,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 5,
        "median_ms": 3.16,
        "p95_ms": 4.231,
        "min_ms": 2.747,
        "max_ms": 4.231,
        "pstdev_ms": 0.541,
        "rsd": 0.1713,
        "samples_ms": [
          2.919,
          2.747,
          3.16,
          3.671,
          4.231
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
        "cache_prepare_ns": 0.008,
        "cas_restore_ns": 0.62,
        "cli_parse_ns": 0.082,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 0.572,
        "identity_prepare_ns": 0.103,
        "lookup_key_ns": 0.004,
        "present_ns": 0.024,
        "process_startup_ns": 5.886,
        "record_decode_ns": 0.143,
        "sqlite_open_ns": 0.076,
        "sqlite_query_ns": 0.142,
        "sqlite_schema_ns": 0.094,
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
      "cold_ms": 7.685,
      "cold_kind": "Executed",
      "cold_classification": "Unknown",
      "warm": {
        "runs": 10,
        "median_ms": 3.71,
        "p95_ms": 3.817,
        "min_ms": 3.233,
        "max_ms": 3.817,
        "pstdev_ms": 0.19,
        "rsd": 0.0512,
        "samples_ms": [
          3.233,
          3.786,
          3.606,
          3.798,
          3.725,
          3.369,
          3.698,
          3.817,
          3.471,
          3.723
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
        "Execute
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
        "/tmp/phase-g-pf-55b8jmfx/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-pf-55b8jmfx/work"
      ],
      "cold_ms": 63.437,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 12.031,
        "p95_ms": 12.759,
        "min_ms": 11.331,
        "max_ms": 12.781,
        "pstdev_ms": 0.456,
        "rsd": 0.0379,
        "samples_ms": [
          12.759,
          12.781,
          12.113,
          12.114,
          12.588,
          11.838,
          12.11,
          11.941,
          12.622,
          11.376,
          11.351,
          11.353,
          12.413,
          12.067,
          11.592,
          11.851,
          11.996,
          11.331,
          12.171,
          11.681
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
        "cas_restore_ns": 7.284,
        "cli_parse_ns": 0.082,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 1.958,
        "identity_prepare_ns": 0.098,
        "lookup_key_ns": 0.004,
        "present_ns": 0.035,
        "process_startup_ns": 5.768,
        "record_decode_ns": 0.582,
        "sqlite_open_ns": 0.075,
        "sqlite_query_ns": 0.495,
        "sqlite_schema_ns": 0.098,
        "stdio_replay_ns": 0.01
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
        "/tmp/phase-g-pf-55b8jmfx/fixture-driver",
        "plain_file_read",
        "/tmp/phase-g-pf-55b8jmfx/work"
      ],
      "cold_ms": 69.249,
      "cold_kind": "Executed",
      "cold_classification": "Guarded",
      "warm": {
        "runs": 20,
        "median_ms": 14.641,
        "p95_ms": 16.317,
        "min_ms": 13.682,
        "max_ms": 16.704,
        "pstdev_ms": 0.862,
        "rsd": 0.0589,
        "samples_ms": [
          14.404,
          13.682,
          14.711,
          16.704,
          15.985,
          16.164,
          16.317,
          14.571,
          14.257,
          15.893,
          14.961,
          13.871,
          14.962,
          14.219,
          14.217,
          14.793,
          15.883,
          14.566,
          14.283,
          14.544
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
        "cas_restore_ns": 9.428,
        "cli_parse_ns": 0.084,
        "decision_persist_ns": 0.0,
        "guard_validation_ns": 1.973,
        "identity_prepare_ns": 0.088,
        "lookup_key_ns": 0.014,
        "present_ns": 0.036,

```


## Raw paths

- JSON: `benchmarks/results/phase_g/evaluation-session-b.json`
- Markdown: `/agent/repos/tracejit/benchmarks/results/phase_g/evaluation-session-b.md`

Controlled-runtime claims: **not claimed** (not on main).

