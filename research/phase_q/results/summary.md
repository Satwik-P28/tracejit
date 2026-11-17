# Phase Q raw summary

- guards=33 blocks=28 candidate_cap=8
- DP transitions over blocks: 7.516e+09

## E1 greedy ratio optimality
- n=4: suboptimal=0/150 max_gap=0.00e+00
- n=6: suboptimal=0/150 max_gap=0.00e+00
- n=8: suboptimal=0/150 max_gap=0.00e+00
- n=10: suboptimal=0/150 max_gap=0.00e+00
- n=12: suboptimal=0/150 max_gap=0.00e+00
- n=14: suboptimal=0/60 max_gap=0.00e+00
- n=16: suboptimal=0/60 max_gap=0.00e+00

## E2 measured 33-guard workload
- current=3.2477 ms ratio=0.0275 ms saved=3.2203 ms (1.31% of measured deopt wall)

## E3 correlated
- current: mean_gap=31.873% max_gap=67.928% extra_vs_ratio=+0.4868 ms runtime=0.00 ms break_even_speedup=n/a
- ratio-greedy: mean_gap=2.337% max_gap=7.274% extra_vs_ratio=+0.0000 ms runtime=0.10 ms break_even_speedup=n/a
- local-search: mean_gap=0.002% max_gap=0.019% extra_vs_ratio=-0.0362 ms runtime=11.34 ms break_even_speedup=313.0x
- simulated-annealing: mean_gap=0.005% max_gap=0.010% extra_vs_ratio=-0.0362 ms runtime=235.88 ms break_even_speedup=6524.2x
- tabu: mean_gap=0.000% max_gap=0.000% extra_vs_ratio=-0.0363 ms runtime=202.86 ms break_even_speedup=5594.7x
- parallel-tempering: mean_gap=0.009% max_gap=0.019% extra_vs_ratio=-0.0361 ms runtime=402.77 ms break_even_speedup=11163.0x
- branch-and-bound: mean_gap=1.300% max_gap=3.762% extra_vs_ratio=-0.0166 ms runtime=819.42 ms break_even_speedup=49336.8x

## E4 candidates
- m=1: newest=1.133 ms optimal=1.133 ms model_saving=0.000 ms measured_gap=-5.185 ms
- m=2: newest=1.649 ms optimal=1.649 ms model_saving=0.000 ms measured_gap=-0.377 ms
- m=4: newest=2.749 ms optimal=2.322 ms model_saving=0.427 ms measured_gap=3.278 ms
- m=8: newest=4.368 ms optimal=3.945 ms model_saving=0.423 ms measured_gap=8.784 ms
- m=16: newest=8.325 ms optimal=7.929 ms model_saving=0.396 ms measured_gap=12.768 ms
- m=32: newest=17.730 ms optimal=17.398 ms model_saving=0.332 ms measured_gap=28.816 ms
- m=64: newest=38.767 ms optimal=38.526 ms model_saving=0.241 ms measured_gap=67.690 ms
- exact enumeration m=8: 40320 orders, exact=3.9446 ms ratio=3.9446 ms runtime=81.0 ms
- learner (m=8): newest=2.84 validations, learned=2.14, saving=0.795 ms, model newest/learned/optimal=4.368/3.945/3.945 ms, decision=0.002662 ms

## E5 knapsack QUBO
- exact-dp: value=4102.08 gap=0.00% feasible=True runtime=0.00 ms
- greedy-ratio: value=4102.08 gap=-0.00% feasible=True runtime=0.00 ms
- qubo-sa: value=4102.08 gap=0.00% feasible=True runtime=71.79 ms
- qubo-tabu: value=4102.08 gap=0.00% feasible=True runtime=4200.63 ms
- qubo-sqa: value=4102.08 gap=0.00% feasible=True runtime=1687.09 ms
- penalty x1 sa: feasible=True value=4102.08 max_coeff=65 runtime=71.8 ms
- penalty x1 sqa: feasible=True value=4102.08 max_coeff=65 runtime=1689.5 ms
- penalty x10 sa: feasible=False value=3894.43 max_coeff=650 runtime=72.2 ms
- penalty x10 sqa: feasible=False value=3894.43 max_coeff=650 runtime=1687.9 ms
- penalty x100 sa: feasible=True value=4102.08 max_coeff=6.5e+03 runtime=73.0 ms
- penalty x100 sqa: feasible=True value=3669.15 max_coeff=6.5e+03 runtime=1677.3 ms

## E6 partition QUBO
- lpt: makespan=2.041 ms feasible=True runtime=0.00 ms
- qubo-sa: makespan=2.092 ms feasible=True runtime=34.63 ms
- qubo-tabu: makespan=2.041 ms feasible=True runtime=843.36 ms
- qubo-sqa: makespan=2.113 ms feasible=True runtime=2929.08 ms
- serial=5.945 ms, ideal/4=1.486 ms

## E7 CEGAR
- epoch 0: static=0.9954 cumulative=0.9954 ewma=0.9954 oracle=0.9250 ms
- epoch 1: static=0.8706 cumulative=0.8740 ewma=1.0081 oracle=0.7989 ms
- epoch 2: static=0.8618 cumulative=0.8828 ewma=0.9248 oracle=0.7783 ms
- epoch 3: static=0.9100 cumulative=0.9241 ewma=0.9045 oracle=0.8253 ms
- epoch 4: static=0.9320 cumulative=0.9450 ewma=0.9300 oracle=0.8496 ms
- epoch 5: static=0.8936 cumulative=0.9185 ewma=0.8856 oracle=0.8214 ms

## E9 session accounting
- deopt_rate=0%: gross=0.0 ms/1000 runs (0.000% of wall), net_after_sort=-77.0 ms
- deopt_rate=1%: gross=57.2 ms/1000 runs (0.170% of wall), net_after_sort=-19.8 ms
- deopt_rate=5%: gross=286.0 ms/1000 runs (0.676% of wall), net_after_sort=+209.0 ms
- deopt_rate=20%: gross=1144.0 ms/1000 runs (1.538% of wall), net_after_sort=+1067.0 ms

## E8 admission (recorded)
- CurrentAuto regret 49.0 ms over 34 steps = 1.441 ms/step bound
