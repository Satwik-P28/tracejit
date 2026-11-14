# Final P1 e2e measurements

Commit: `026e660f6722ee7dddbf8ec00caaf52a817c36cf`

## Aggregate kind / decision counts

- kind_counts: `{"Executed": 113, "Reused": 140}`
- cache_decision_counts: `{"Executed": 74, "Reused": 134, "Skipped": 37}`

## Hit floor (`plain_file_read`)

- DIRECT: 0.384 ms (95% CI 0.352–0.455, n=30)
- cold: 8.315 ms (95% CI 7.608–10.740, n=30)
- warm: 5.725 ms (95% CI 4.842–6.330, n=30)
- auto: 3.656 ms (95% CI 3.316–3.838, n=30)

## Throughput

- binary: `/agent/repos/tracejit-final-adv/benchmarks/workloads/c-transform/transform`
- DIRECT: 32.662 ms (95% CI 32.598–32.715, n=30)
- cold: 43.414 ms (95% CI 42.468–44.516, n=30)
- warm: 4.403 ms (95% CI 4.078–4.826, n=30)
- auto: 5.188 ms (95% CI 4.751–5.747, n=30)

## Session cumulative

- TraceJIT cumulative: 166.111 ms
- DIRECT cumulative: 40.984 ms
- kinds: `{"Executed": 1, "Reused": 30}`

## Concurrency

- workers=8 wall=13.254 ms all_success=True kinds=`{"Executed": 2, "Reused": 6}`

## Admission

- policy            Never total_ns=866000000 oracle_ns=575000000 regret_ns=291000000 traces=0 hits=0 directs=34
- policy           Always total_ns=1086000000 oracle_ns=575000000 regret_ns=511000000 traces=18 hits=16 directs=0
- policy      CurrentAuto total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
- policy        Threshold total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
- policy             Ewma total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
- policy  ConfidenceBound total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
- RESULT phase-e-admission preferred=CurrentAuto regret_ns=49000000
