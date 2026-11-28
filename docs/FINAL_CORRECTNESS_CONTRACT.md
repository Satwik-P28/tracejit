# TraceJIT final correctness contract (v0.3.0-alpha.1)

This is the authoritative statement of what TraceJIT does, what it refuses, and what it does not
know. `README.md`, `SAFETY.md`, `SPEC.md`, `SECURITY.md` and `docs/LIMITATIONS.md` defer to this
document for the parts they share. Where an older phase report disagrees with this file, that
report is historical evidence and this file is the contract.

Status: research prerelease. Not peer reviewed, no production adoption, one primary measurement
host plus CI evidence, no independent external operator.

---

## 1. Observable behaviour

A command's **observation** is the tuple

```
(stdout bytes, stderr bytes, exit status, declared output files with content and metadata)
```

TraceJIT calls a reuse **correct** when the observation it exposes is the observation a fresh
execution of the same command, from the same pre-state, would have produced. Nothing else is
compared. In particular TraceJIT does not attempt to reproduce side effects outside the declared
outputs, timing, resource usage, or the process tree.

This is the whole of the claim. It is weaker than "the program did the same thing" and stronger
than "the bytes looked equal last time".

## 2. Execution identity

A record is a candidate only for a command whose identity matches:

* executable path and content hash;
* `argv` (exact bytes and order);
* working directory;
* the **entire inherited environment**, hashed, because `getenv` is not a syscall and an
  environment variable can change any branch a program takes;
* the runtime identity: kernel release, libc build, and the allocator/ASLR-relevant properties
  that make a native record reusable at all;
* the execution contract in force (native, or a named contract such as
  `allocator-entropy-v1`), which is part of the identity so records from different contracts are
  never mixed.

Identity is checked before any guard runs. A mismatch is a miss, not a deoptimisation.

## 3. Supported effect classes

Every recorded kernel observation is classified before reuse is considered:

| Class | Meaning | Reuse |
| --- | --- | --- |
| Read / metadata read / access check | Content, metadata, existence or resolvability of a recorded path | Guardable |
| Directory open / enumeration | A directory's identity and entries | Guardable |
| Statfs, filesystem statistics | Filesystem-level answers | Guardable where the recorded value is stable |
| Write / create / delete / rename | Workspace effects | Captured as outputs, restored |
| Mapping that can be observed through a shared page | Writable `MAP_SHARED`, anonymous shared | `UNKNOWN` |
| Clock, entropy, process identity, network, unmodelled syscall | Values that no userspace guard can re-check | `NONDETERMINISTIC` or `UNKNOWN` |
| Controlled entropy (under a contract) | A read whose value the tracer supplies reproducibly | Guardable under that contract only |

Reuse happens only for classification `GUARDED` or `PROVEN`. `UNKNOWN`, `NONDETERMINISTIC` and
`EMPIRICALLY_STABLE` never reuse.

## 4. Guard semantics

A guard is a re-checkable predicate over one recorded observation. Guards are validated
**synchronously, once, immediately before any workspace mutation**, and every guard must pass.

* A failing guard produces a **deoptimisation**: cached bytes are discarded, the command is
  re-executed, and the new execution is recorded.
* Guards are never combined into a "mostly passed" decision, never sampled, never validated
  asynchronously, and never trusted from a previous run. `--guard-mode fast` changes how content
  is compared, not whether every recorded dependency is checked.
* Path guards replay the pathname the process passed; there is no lexical `..` collapse and no
  symlink resolution beyond what the process itself performed.
* A guard that cannot be evaluated fails closed.

## 5. Native versus controlled execution

Two execution tiers exist and their records are never interchangeable.

**Native** execution traces the command as the user's environment runs it. Most programs read
entropy or the clock indirectly through libc, so native reuse is rare: in the frozen census it is
**2 eligible of 49 attempted (4.1 %), 1 reused (2.0 %)**.

**Controlled** execution (`--contract <name>`, opt-in, explicit) supplies a small set of runtime
values reproducibly. `allocator-entropy-v1` is the only contract with a full audit: it pins the
allocator's entropy source for one audited glibc build
(`8cebda42d140fc2b09639f8b13a5d5f2e617ef09`). Under it, the frozen census reaches **12 of 49
eligible (24.5 %) and 10 reused**. `compiler-runtime-v1` additionally supplies the clock the
compiler driver reads: **19 of 49 eligible (38.8 %), 17 reused**.

What the contract changes, precisely:

* the allocator's guard-page and tcache seeding bytes become a function of a recorded,
  reproducible source instead of `getrandom`;
* consequently, a program whose behaviour depends on allocation addresses becomes reproducible
  **under the same libc build** and not otherwise;
* the unpredictability of the allocator marker is weakened by construction. That is the price of
  the tier and it is stated in `SAFETY.md`; it is not a classification exception and it does not
  make the workload deterministic in the kernel sense.

Which behaviours are excluded: any program that reads the clock, entropy, process identity, or an
unmodelled syscall through another path still refuses. Controlled execution is **not** equivalent
to native execution, and a controlled record is never served to a native invocation.

Unaudited runtimes are refused rather than assumed equivalent: on Ubuntu 25.10 with glibc 2.42,
the same commands were refused under every policy and produced no reuse (Phase AE, reproduced in
`benchmarks/results/phaseae/multi_environment.json`).

## 6. `PROVEN`

`PROVEN` means: the effects were `GUARDED` **and** seccomp-BPF and Landlock ABI ≥ 3 were actually
installed in the re-executed child, with the filter's installation verified by
`PR_GET_SECCOMP`/`PR_GET_NO_NEW_PRIVS` in that child before the command ran.

`PROVEN` does **not** mean:

* formal or machine-checked proof of observational equivalence;
* that other processes cannot modify the inputs (see §11);
* that the policy expresses exactly the recorded dependency set, or that it confines the process
  as a security boundary against a hostile command;
* anything about a *reuse* beyond the fact that the reused record was created by an enforced
  execution. A reused run installs no policy of its own, because it executes nothing.

Every public description must say "the policy was installed", never "proven equivalent". The
machine-readable enum value `Proven` is retained for compatibility; the user-facing explanation
above is the one that ships.

## 7. CAS integrity verification

Cached content is addressed by BLAKE3 over its bytes. Before cached stdout, stderr or an output
file is exposed, the object is re-hashed and compared with its address. A mismatch is a
`CorruptObject`: the candidate is discarded, the command is re-executed, and the correct
observation is produced. Corrupting one object does not surface as a hit — measured in
`benchmarks/results/phaseae/tracejit_integrity.json`.

This verifies the cache's own integrity. It says nothing about whether the *observation* is still
the right one for the current inputs; that is the guards' job.

## 8. Transactional restore

Outputs are staged and verified before any destination is mutated. A single output is renamed
into place. Multiple outputs are staged, a durable restore intent is written, and a soft failure
rolls the set back. A hard kill (`SIGKILL`, power loss) between renames can leave a partially
restored set; the durable intent makes the next attempt refuse a hit and retrace instead of
exposing a mixed result. Crash-atomicity across multiple outputs is **not** claimed.

Metadata restoration is recorded, not fresh: a restored regular file carries the recorded
ownership, mode, atime and mtime. That is observable and is a known correctness boundary (§11).

## 9. Failure and deoptimisation

| Situation | Behaviour |
| --- | --- |
| No candidate matches the identity | Execute, trace, store |
| Candidate matches, a guard fails | `DEOPT`: discard cached bytes, execute, store |
| Candidate matches, cached object corrupt | Discard, execute, store |
| Output destination precondition fails | Refuse the record; retrace where re-execution can succeed; a refused deletion stays fatal |
| Admission policy estimates no repayment | Skip caching, execute directly |
| `--enforce` on a host without seccomp + Landlock ≥ 3 | Never reuse, never label `PROVEN`, still execute the command |
| Policy cannot be assembled from the record | Execute unenforced, stay `GUARDED`, say so in the report |
| Tracer failure, unmodelled effect | Fail closed: no reuse |

A deoptimisation is a correct outcome, not an error: it is the mechanism by which a stale
observation is avoided.

## 10. Security assumptions

The trusted computing base is the kernel's ptrace, seccomp and Landlock behaviour, the tracer and
guard code, BLAKE3, SQLite, and the permissions on the cache directory. None of it is formally
verified.

Additional assumptions the contract relies on:

* the cache directory is not writable by an attacker who wants to forge a record; a forged record
  with valid object hashes would pass integrity verification;
* the running binary is the binary that was built from this source (no attestation is produced);
* the command being cached is not itself adversarial. The sandbox narrows an honest command's
  effect surface; it is not a jail.

## 11. Known correctness boundaries

1. **Validation-to-restore race (residual, reproducible).** Guards are validated once, then outputs
   are restored. A writer that changes an input *after* the guard pass and *before* the restore
   causes stale output to be served. Measured: injecting the mutation at
   `after_validation_before_apply` yields `Reused` with stale bytes. Landlock confines the traced
   process, not unrelated writers; a read-only bind mount does not freeze the inode; descriptor
   pinning misses an in-place rewrite; snapshots redefine the observable state.
   **Operating assumption for the prerelease: no external process mutates the inputs during the
   reuse window.** This is an assumption, not an enforced guarantee.
2. **Timestamp restoration and build systems.** A restored object keeps its recorded mtime, which
   can be older than an archive built from it. A make-driven build then considers the archive up
   to date and keeps a stale member. Reproduced on Lua 5.4.6 and zlib 1.3.1.
3. **Multi-output crash atomicity** is not claimed (§8).
4. **Observation is ptrace-level.** A userspace influence that never crosses a modelled syscall
   boundary is invisible.
5. **Enforced promotion is unavailable for a class of producers.** `--enforce` cannot promote a
   command whose recorded output must exist at candidate time *and* which recreates it with
   `O_CREAT|O_EXCL` over an existing file: the absent-output case cannot build a policy, and the
   present-output case produces a refused `EEXIST` write the classifier does not model. `gzip -k
   -f` is the measured example; the run is refused (fail closed) and stays `UNKNOWN`. Read-only
   commands (`sha256sum`, `wc`) do complete the enforced lifecycle.
6. **`PROVEN` does not narrow the race.** An enforced record is still subject to boundary 1 for
   the reuse window.

## 12. Unsupported environments

* Operating systems other than Linux, and architectures other than x86_64: no build, no reuse.
* Linux without `ptrace` permission (`yama.ptrace_scope` and container policies): `doctor`
  refuses; no workaround is attempted.
* Linux without seccomp-BPF or Landlock ABI ≥ 3: `GUARDED` reuse works; `PROVEN` is unreachable
  and `--enforce` never reuses. This is the documented fallback, not a defect.
* musl, non-glibc libcs, and unaudited glibc builds: native reuse is generally unavailable and no
  contract applies.
* Windows, macOS, AArch64: not supported, not advertised.

## 13. What this contract deliberately does not promise

No universal acceleration, no correctness under concurrent mutation, no equivalence to fresh
execution in general, no compiler-cache competitiveness, no remote or shared cache, no partial
in-process reuse, no security boundary against a hostile cached command, and no reproduction of
the original process's timing or resource usage.
