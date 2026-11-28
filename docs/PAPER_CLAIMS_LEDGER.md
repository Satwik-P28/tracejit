# Paper claims ledger (Phase AE)

Every sentence the paper, the README, the release notes or a talk may use about TraceJIT's
contribution, its competitive position or its performance, with the status of the evidence
behind it. Statuses: **supported** (measured, reproducible in this repository), **qualified**
(true only with the stated restriction), **retracted** (evidence contradicts it).

## 1. Prior art, and what may not be claimed

| system | mechanism | claims TraceJIT may not make |
| --- | --- | --- |
| Firebuild (0.8.2 … 0.8.6.2) | `LD_PRELOAD` interception, per-process fingerprint, recorded inputs validated against the filesystem at reuse, blob replay, disableable quirks | "first automatic command cache"; "deoptimises where Firebuild silently replays" (it validates content hashes too); "the only system that can cache artifact producers" (0.8.6.2 caches `gzip -k`) |
| ccache / sccache | compiler-driven output caching | any compiler-cache speed claim, any "compiler caching is unsolved" |
| Bazel remote execution, Vesta, Nix | content-addressed actions, hermetic inputs | "content-addressed caching is new"; "hermetic execution is new" |
| Rattle | trace-based record/replay of commands | "first to derive cache keys from traces" |
| Make/Ninja | timestamp and graph-based rebuild avoidance | "avoiding rebuilds is new" |
| deterministic replay / record-replay debuggers | syscall logs, deterministic re-execution | "replaying an execution is new" |
| memoisation libraries (`ccache`, `memoize`, function caches) | pure-function caching | "command memoisation is new" |

## 2. TraceJIT's actual contribution, separated

**Mechanism (defensible, narrow).** A whole-command cache whose reuse decision is a set of
*constructed guards* over an explicitly enumerated observable contract, where the contract
classifies each kernel observation as deterministic, contract-controlled or refused, and where
every guard must pass before any cached byte is exposed. Three companion mechanisms carry weight:
a first-class `DEOPT` outcome that re-executes instead of failing, transactional restoration with
a durable restore intent, and a refusal policy that is the default rather than the exception.

**Empirical (new).** A same-host, randomized, per-invocation-verified comparison against two
Firebuild versions showing (a) where the two engines' *applicability* differs, (b) that default
Firebuild replays stale clock output while its strict configuration does not cache it, (c) that
Firebuild exposes corrupted cached bytes while TraceJIT refuses them, and (d) that the
performance order between the engines flips with the workload class.

**Negative results (valuable).** The validation-to-restore race survives every economical
userspace mitigation; descriptor-query modelling yields 0/48 new eligible cells; metadata guard
relaxation is unjustifiable; `auto` admission costs ~4 % against `always` while protecting
one-shots; Firebuild 0.8.6.2 still refuses `bzip2 -k`.

**Methodology (a contribution in itself).** A benchmark accounting discipline that rejects a
labelled HIT without that invocation's own decision, restoration evidence and an independent
output oracle, plus a frozen corpus and adversarial suites that must retain their
counterexamples.

**Not a contribution.** ptrace tracing, BLAKE3 hashing, SQLite storage, the crate layout, the
`allocator-entropy-v1` audit itself (it is a per-libc-build engineering artefact).

## 3. Which paper is the strongest

| option | verdict |
| --- | --- |
| A. a new guarded-reuse mechanism | **Too thin on its own.** Every ingredient exists elsewhere; the novelty is the composition and the contract discipline. A mechanism paper invites "this is engineering" and loses the strongest evidence. |
| B. a systematic study of conservative whole-command reuse | **Viable, but the study is narrow**: one non-compiler workload family, two environments on one kernel, one competitor. As a study it over-claims generality. |
| C. correctness/performance trade-offs in execution caching | **Strongest available framing.** The paper can show, with measurements on both systems, exactly what each contract buys and what it costs: content validation versus assumption, refusal versus replay, applicability versus speed, and the price of verified replay (≈80 ms per 100 MiB). |
| D. an empirical and negative-results study | **A component, not the paper.** The residual TOCTOU race and the 0/48 descriptor result are excellent negative results; they do not carry a paper alone. |

**Recommended: C, with D as the evaluation's spine.** Title shape: *what a fail-closed contract
costs and buys for automatic command reuse*, evaluated against Firebuild 0.8.2/0.8.6.2, with a
section on verified-replay lower bounds and a section on the residual race.

## 4. Performance claims, with status

| claim | value | status |
| --- | --- | --- |
| "TraceJIT makes repeated bzip2 -9 -k ~5.6× faster than native and Firebuild cannot cache it" | n=25 cold session: native 2846.7 ms, TraceJIT 545.3 ms, Firebuild 0.8.6.2 3119.4 ms | **supported** (one host, one size, one file) |
| "TraceJIT is faster than Firebuild at replay" | gzip -k: Firebuild 254.7 ms vs TraceJIT 425.0 ms → **TraceJIT slower**; gzip -stdout 1.2 MiB: TraceJIT 6.56 vs Firebuild 7.47 ms/invocation; 100 MiB text stdout: 79.8 vs 288.2 ms (different harnesses) | **retracted as a general claim; qualified per workload** |
| "TraceJIT wins the artifact-producing niche outright" | false once Firebuild 0.8.6.2 is included | **retracted** |
| "TraceJIT replays a 100 MiB text artifact in ~80 ms, of which ~39 ms is input hashing" | phase profile, one host | **supported** |
| "TraceJIT is within ~1.5× of the verified-replay floor" | floor derivation in `VALIDATED_REPLAY_PERFORMANCE.md` | **qualified** (floor is an estimate from measured components) |
| "hash-only commands never pay below ~10 MiB and pay from ~9 invocations at 100 MiB" | Phase AD artifact table, integer `n*`; AE reconfirms the reversal at 1 MiB (12.9 ms hit vs 3.3 ms native) | **supported** |
| "every compression workload breaks even at the second invocation" | 1 MiB incompressible gzip needs 3 by the model and 10 by the measured cold session | **retracted** |
| "`auto` admission costs 4 % against `always`" | one 24-step session, two repeats | **qualified** (single session, not re-measured in AE) |

## 5. Correctness claims, with status

| claim | status |
| --- | --- |
| "Every guard must pass before cached bytes are exposed, and unverified cache objects are never exposed" | **supported** for the tested paths; corrupted-object experiment: no hit, correct output; the guarantee is structural (typestate gate + re-hash of the object). |
| "TraceJIT refuses clock- and entropy-dependent programs that Firebuild replays" | **supported with the configuration named**: default Firebuild replays; Firebuild with `ignore-time-queries` removed refuses to cache. |
| "TraceJIT deoptimises when an input changes" | **supported** for changes before the surviving validation pass (measured at three injection points). |
| "TraceJIT is safe against a concurrent writer" | **retracted / not claimed**: a mutation after validation yields stale output (measured). |
| "`PROVEN` proves the reuse is equivalent to native execution" | **false**: `PROVEN` means seccomp + Landlock ≥ ABI 3 were installed for that execution; it is not an equivalence proof and must not be described as one. |
| "TraceJIT never produces an incorrect HIT" | **qualified**: zero incorrect HITs inside the declared contract across the AE measurements (798 matrix rows, all correct; policy probes; integrity probes), with the residual race excluded from the contract and documented. |

## 6. Wording that must appear in the abstract

1. The measured niche: repeated generation of **stable-input artifacts** (compression and
   archive producers) where replay is worth 3–5× and refused commands are the common case.
2. The loss cases: cheap filters, hash-only commands below ~10 MiB, one-shot commands, and
   mutation-heavy workloads.
3. One host (two userspaces) and one competitor family, both stated.
4. The residual validation-to-restore race, stated as an assumption, not a footnote.
5. `PROVEN` described as "policy installed", never as "formally equivalent".

## 7. Wording that must not appear anywhere

* "first", "only", "novel" without the prior-art table above and the specific restriction.
* "unvalidated reuse" about Firebuild.
* "atomic", "race-free", "snapshot-isolated" about TraceJIT's reuse.
* any performance number whose arm, session mode (`cold`/`steady`), version and host are not
  named next to it.
* any Firebuild number without its version and configuration (`default`/`tuned`/`strict`).
