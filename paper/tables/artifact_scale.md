**Table: Cost across authentic artifact sizes. Cold is the first traced execution, warm is a verified HIT of the same command.**

| Artifact | Workload | Native (ms) | Cold trace (ms) | Warm HIT (ms) | Native/HIT | Break-even n |
| --- | --- | --- | --- | --- | --- | --- |
| 1MiB | gzip-stdout | 38.1 | 56.3 | 3.1 | 12.1× | 2 |
| 1MiB | gzip-stdout-incompressible | 27.0 | 48.2 | 4.8 | 5.6× | 2 |
| 1MiB | sha256sum | 1.4 | 33.5 | 11.3 | 0.1× | never |
| 1MiB | bzip2-stdout | 64.5 | 86.3 | 4.3 | 15.1× | 2 |
| 1MiB | gzip-file | 42.3 | 63.3 | 8.2 | 5.1× | 2 |
| 10MiB | gzip-stdout | 486.2 | 601.9 | 11.4 | 42.7× | 2 |
| 10MiB | gzip-stdout-incompressible | 266.1 | 304.2 | 20.0 | 13.3× | 2 |
| 10MiB | sha256sum | 8.2 | 45.4 | 11.0 | 0.7× | never |
| 10MiB | bzip2-stdout | 555.8 | 733.1 | 11.9 | 46.6× | 2 |
| 10MiB | gzip-file | 478.4 | 602.6 | 16.2 | 29.4× | 2 |

*Source: benchmarks/results/phaseaf/artifact_scale.json, produced by benchmarks/phase_ad/artifact_scale.py on a pinned release archive*
