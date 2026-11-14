# TraceJIT novelty matrix (Phase K10)

Attribution matrix. **Do not manufacture novelty.** Each row states what already exists, what TraceJIT implements, and what is claimed vs not claimed.

| Area | Prior art (examples) | TraceJIT mechanism | Claim strength |
| --- | --- | --- | --- |
| Transparent command caching | Firebuild (LD_PRELOAD intercept + replay) | ptrace whole-command trace → classify → guard → CAS restore | Engineering overlap in *goal*; different observation/enforcement stack. **No superiority claim** vs Firebuild (not installed here). |
| Compiler caches | ccache, sccache | Not a compiler wrapper; refuses typical `cc -c` as nondeterministic on native census | **Not competing** on matched compiler-wrapper workloads. |
| Build graphs | Make, Ninja, Bazel, Buck2, Rattle | No owned graph; discovers deps from one execution | Loses identical-rerun wall time; wins content correctness when mtime/graph is stale (K8/G). |
| Incremental computation | Salsa, Adapton | Multi-candidate retention for one command identity only | **No** red-green graph / change propagation claim. |
| Record/replay & determinism | rr, Hermit | Cache reuse under guards, not deterministic replay | Different problem. |
| Syscall sandboxing | seccomp, Landlock | Required for `PROVEN` promotion only | Uses prior art correctly; not a new sandbox design. |
| Content-addressed storage | Nix store ideas; generic CAS | BLAKE3 whole-object CAS + SQLite index | Standard pattern; stream-hash staging is engineering. |
| CEGAR | Classical software model checking | Input-driven effect-hole classifier (`tracejit refine`); never auto-deploys | Workflow analogy only; **no** academic CEGAR novelty claim (K5). |
| Online decision-making | Bandits / contextual bandits | Analytical expected-benefit admission; production `auto` | Bandit-as-default **rejected** (E/K9). |
| Obs equivalence / fail-closed reuse | Build systems assume declared deps; caches assume toolchain contracts | Explicit Obs contract + adversarial disproof of false HIT (`renameat2` exchange) + independent oracle + typestate modelcheck + crash fault injection | **Flagship engineering contribution** (see K11): soundness-first transparent reuse with demonstrated attack→fix, not a new mathematical theory. |
| Reuse certificates | Attestation / provenance literature | Structural + optional StrictCas verifier; ceiling `CheckedByVerifier` | **No** full-proof / `FullEquivalenceProof` claim (K6). |
| Crash-atomic multi-file restore | Journals, rename-over, transactional FS | Soft rollback+retrace; hard-kill recovery without journal | Limitation retained (K4); **not** claimed solved. |

## Summary rule

Ship **correctness-preserving engineering** with measured negatives. Do not claim peer-reviewed novelty, production adoption, or matched wins against absent tools.
