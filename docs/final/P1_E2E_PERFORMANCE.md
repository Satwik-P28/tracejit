# P1 §9 — End-to-end performance (four objectives)

Date: 2026-11-14  
Commit in artifact: `026e660f6722ee7dddbf8ec00caaf52a817c36cf`  
Harness: `scripts/final_p1_measure.py`  
Raw: `benchmarks/results/final_p1/{e2e.json,e2e.md,tracing_completeness.json}`  
Protocol: release binary, 5 warmups + 30 runs, bootstrap 95% CI on median (400 resamples), inherited fds >2 closed.

## Aggregate counts (this package)

| Counter | Value |
| --- | ---: |
| `kind` Executed | 113 |
| `kind` Reused (HIT) | 140 |
| `kind` Deoptimized | **0** |
| `cache_decision` Executed | 74 |
| `cache_decision` Reused | 134 |
| `cache_decision` Skipped (admission) | 37 |

## Objective 1 — Hit latency floor (`plain_file_read`)

| Arm | Median (95% CI), n=30 |
| --- | --- |
| DIRECT | 0.384 ms (0.352–0.455) |
| cold trace | 8.315 ms (7.608–10.740) |
| warm HIT | 5.725 ms (4.842–6.330) |
| AUTO | 3.656 ms (3.316–3.838) |

**Verdict:** DIRECT wins the floor. Warm HIT loses on sub-ms native work. AUTO reduces loss by skipping some traces (`Skipped` decisions).

## Objective 2 — Throughput (real `c-transform`)

| Arm | Median (95% CI), n=30 |
| --- | --- |
| DIRECT | 32.662 ms (32.598–32.715) |
| cold trace | 43.414 ms (42.468–44.516) |
| warm HIT | 4.403 ms (4.078–4.826) |
| AUTO | 5.188 ms (4.751–5.747) |

**Verdict:** Warm HIT ≈ **7.4×** vs DIRECT on this CPU-heavy transform (not synthetic-only). Cold trace pays overhead.

## Objective 3 — Developer-session cumulative (`c-etl` stream)

| Arm | Cumulative wall |
| --- | ---: |
| TraceJIT (1 cold + 30 warm) | 166.111 ms |
| DIRECT (same length) | 40.984 ms |
| kinds | Executed 1, Reused 30 |

**Verdict:** Session loses on short ETL despite HITs — admission/session planning matters; spectacular single HIT ≠ session win.

## Objective 4 — Concurrency (8 workers, shared cache)

- wall 13.254 ms, `all_success=True`
- kinds: Executed 2, Reused 6 (no false Obs failure; some workers traced rather than HIT under contention)

## Competitors

Make/Ninja/ccache/Firebuild arms were **not re-scored as losses** here. Prior measured competitive eval remains at `benchmarks/results/phase_k8/` (tip `364331b`). Missing tools stay “not tested”.

## Non-claims

- No invented numbers; see JSON samples.
- No claim that short-command warm HIT beats DIRECT.
- Flagship throughput uses real `c-transform`, not a busy-loop micro only.
