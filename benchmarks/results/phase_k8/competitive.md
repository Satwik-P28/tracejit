# Phase K8 competitive evaluation

- commit: `364331b904d41de3feb7defae152ec0e50112e0e`
- dirty: `True`
- binary sha256: `164a7c0b0007b187…`
- warmups/runs: 2/5

## Host tools

```
{
  "make": "/usr/bin/make",
  "ninja": "/usr/bin/ninja",
  "ccache": "/usr/bin/ccache",
  "sccache": null,
  "bzip2": "/usr/bin/bzip2",
  "cc": "/usr/bin/cc"
}
```

## Build/edit recovery (medians, content correctness)

| Phase | native | make | ninja | simple_cas | TraceJIT |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1_first_build | 17.733 / ok | 20.897 / ok | 10.441 / ok | 50.368 / ok | 55.525 / ok |
| 2_identical_rerun | 17.987 / ok | 1.317 / ok | 1.385 / ok | 31.548 / ok | 14.006 / ok |
| 3_outputs_deleted | 19.439 / ok | 23.362 / ok | 11.227 / ok | 26.235 / ok | 22.385 / ok |
| 4_one_input_modified | 17.113 / ok | 8.759 / ok | 9.72 / ok | 30.746 / ok | 27.631 / ok |
| 5_mtime_preserved_edit | 17.417 / ok | 1.543 / WRONG | 1.82 / WRONG | 30.56 / ok | 41.887 / ok |
| 6_corrupted_output | 16.988 / ok | 1.603 / WRONG | 1.724 / WRONG | 24.287 / ok | 42.069 / ok |

## Short-command ETL overhead (retained loss)

- direct median: **1.575 ms**
- TraceJIT warm median: **3.146 ms** kinds=['Reused', 'Reused', 'Reused', 'Reused', 'Reused']
- net_loss: `True`

## Non-applicable baselines

- ccache / sccache: compiler wrappers; not timed as transparent bzip2 command caches.

Raw JSON: `benchmarks/results/phase_k8/competitive.json`

