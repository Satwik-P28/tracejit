**Table: Break-even, four ways. Columns 2 and 3 are invocation counts: the first at which cumulative cost equals native, and the first at which savings are strictly positive. Columns 4 and 5 are the measured cumulative change at sampled session lengths, which is not the same quantity.**

| Workload | Equal cost at n | Positive at n | Measured n=10 | Measured n=25 |
| --- | --- | --- | --- | --- |
| bzip2 -9 -k (1 MiB incompressible, file output) | 3 | 3 | +72.5 % | +86.9 % |
| gzip -9 -n -k (1 MiB, file output) | 9 | 17 | -- | -- |
| gzip-mutating | 3 | 5 | +30.7 % | +87.5 % |
| gzip -9 -n -c (1.2 MiB text, stdout) | 8 | 9 | -- | -- |
| sed (200k lines) | 20 | 30 | -- | -- |
| sha256sum (1 MiB) | never | never | -- | -- |

*Source: benchmarks/results/phaseae/economics.json, mode=cold; counts derived from one cold trace plus steady hits*
