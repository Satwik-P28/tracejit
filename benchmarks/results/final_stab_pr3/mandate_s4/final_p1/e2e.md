# Final P1 e2e measurements

Commit: `4ffde9aa82ba91b4f71a587d5c8acb3136ad96a7`

## Aggregate kind / decision counts

- kind_counts: `{"Executed": 114, "Reused": 139}`
- cache_decision_counts: `{"Executed": 74, "Reused": 134, "Skipped": 37}`

## Hit floor (`plain_file_read`)

- DIRECT: 0.337 ms (95% CI 0.331–0.351, n=30)
- cold: 7.783 ms (95% CI 7.517–8.578, n=30)
- warm: 4.332 ms (95% CI 3.894–4.610, n=30)
- auto: 3.252 ms (95% CI 3.072–3.391, n=30)

## Throughput

- binary: `/agent/repos/tracejit-final-adv/benchmarks/workloads/c-transform/transform`
- DIRECT: 32.524 ms (95% CI 32.481–32.569, n=30)
- cold: 43.676 ms (95% CI 42.387–44.312, n=30)
- warm: 5.303 ms (95% CI 4.881–5.797, n=30)
- auto: 7.061 ms (95% CI 5.179–7.560, n=30)

## Session cumulative

- TraceJIT cumulative: 177.046 ms
- DIRECT cumulative: 35.452 ms
- kinds: `{"Executed": 1, "Reused": 30}`

## Concurrency

- workers=8 wall=23.440 ms all_success=True kinds=`{"Executed": 3, "Reused": 5}`

## Admission

- policy            Never total_ns=866000000 oracle_ns=575000000 regret_ns=291000000 traces=0 hits=0 directs=34
- policy           Always total_ns=1086000000 oracle_ns=575000000 regret_ns=511000000 traces=18 hits=16 directs=0
- policy      CurrentAuto total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
- policy        Threshold total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
- policy             Ewma total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
- policy  ConfidenceBound total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
- RESULT phase-e-admission preferred=CurrentAuto regret_ns=49000000
