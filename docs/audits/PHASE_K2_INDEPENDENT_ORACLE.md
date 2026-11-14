# Phase K2 — Independent execution oracle

Date: 2026-11-14  
Tip at authoring: `94d714d` (post K1 merge)  
Harness: `benchmarks/oracle/independent_obs.py`

## Independence claim

The oracle:

- does **not** import `tracejit-effects`, `tracejit-guards`, `tracejit-core`, or any other product crate;
- does **not** call `classify`, `validate_all`, or reconstruct dependencies;
- talks to TraceJIT only through the `tracejit` CLI (`run --json`) and to the OS through native `exec`.

Judgment rule: if `cache_decision` / `kind` is `Reused` and Obs differs from a twin-workspace native Exec, that is an **incorrect_hit**.

Obs = exit status + stdout/stderr digests + named output file digests (BLAKE3 unavailable → SHA-256).

## Cases

| Case | Intent |
| --- | --- |
| `copy_stable` | Warm reuse Obs must equal native twin |
| `copy_content_change` | After input rewrite, Reused+stale Obs = incorrect |
| `rename_exchange` | K1 counterexample must stay non-eligible / never wrong HIT |
| `getrandom_never_hit` | NONDETERMINISTIC must never Reuse |

## Results (this host)

Seeds 7 / 11 / 17 on tip lineage including K1 (`94d714d`):

| Seed | incorrect_hits | regress_eligible | Artifact |
| --- | --- | --- | --- |
| 7 | 0 | 0 | `benchmarks/results/phase_k2/oracle-seed-7.json` |
| 11 | 0 | 0 | `benchmarks/results/phase_k2/oracle-seed-11.json` |
| 17 | 0 | 0 | `benchmarks/results/phase_k2/oracle-seed-17.json` |

```text
RESULT phase-k2-oracle incorrect_hits=0 regress_eligible=0 cases=4
```

## Relation to Phase D

`benchmarks/differential/phase_d.py` is also CLI-based. K2 adds an explicit independence document, twin-workspace Obs comparison, and the post-K1 exchange regression as a first-class oracle case.
