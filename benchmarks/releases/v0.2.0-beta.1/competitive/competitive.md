# Phase K8 competitive evaluation

- commit: `cdb307be9160b93318603005373a0a9f69b84219`
- dirty: `True`
- binary sha256: `5a1100c5fd92dd7f…`
- warmups/runs: 2/5

## Host tools

```
{
  "make": "/usr/bin/make",
  "ninja": null,
  "ccache": null,
  "sccache": null,
  "bzip2": "/usr/bin/bzip2",
  "cc": "/usr/bin/cc"
}
```

## Build/edit recovery (medians, content correctness)

| Phase | native | make | ninja | simple_cas | TraceJIT |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1_first_build | 24.955 / ok | 34.033 / ok | SKIP | 78.889 / ok | 87.602 / ok |
| 2_identical_rerun | 24.42 / ok | 1.979 / ok | SKIP | 38.796 / ok | 33.985 / ok |
| 3_outputs_deleted | 24.288 / ok | 34.114 / ok | SKIP | 38.399 / ok | 49.07 / ok |
| 4_one_input_modified | 24.545 / ok | 12.323 / ok | SKIP | 46.833 / ok | 54.387 / ok |
| 5_mtime_preserved_edit | 24.131 / ok | 1.959 / WRONG | SKIP | 55.13 / ok | 70.667 / ok |
| 6_corrupted_output | 24.004 / ok | 1.967 / WRONG | SKIP | 39.049 / ok | 73.837 / ok |

## Short-command ETL overhead (retained loss)

- direct median: **8.811 ms**
- TraceJIT warm median: **6.34 ms** kinds=['Reused', 'Reused', 'Reused', 'Reused', 'Reused']
- net_loss: `False`

## Non-applicable baselines

- ccache / sccache: compiler wrappers; not timed as transparent bzip2 command caches.

Raw JSON: `benchmarks/releases/v0.2.0-beta.1/competitive/competitive.json`

