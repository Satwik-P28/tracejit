**Table: Enforcement capability and the lifecycle outcome it produces. A host without Landlock ABI 3+ can never produce PROVEN; that is the documented fallback, not a defect.**

| Environment | Landlock ABI | seccomp | Discovery class | Enforced run | Enforced reuse | Producer under --enforce |
| --- | --- | --- | --- | --- | --- | --- |
| Ubuntu 24.04.5 LTS / 7.0.0-38-generic | 8 | yes | GUARDED | PROVEN | Reused | UNKNOWN |
| Ubuntu 24.04.5 / 6.1.102 | absent | yes | GUARDED | GUARDED | not demonstrated | not measured |
| ubuntu-25.10 / 6.1.102 | absent | unknown | refused | not PROVEN | not demonstrated | not measured |
| ubuntu-25.10-glibc2.42 / 6.1.102 | absent | unknown | refused | not PROVEN | not demonstrated | not measured |

*Source: benchmarks/results/phaseaf/enforcement_lifecycle.json (this phase, capable host), benchmarks/results/phaseae/environment-local.json, benchmarks/results/phaseae/multi_environment.json*
