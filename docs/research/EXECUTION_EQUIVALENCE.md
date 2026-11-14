# Execution-equivalence contract (Phase C)

This document formalizes what TraceJIT V1 means by safe reuse. It describes the
**implemented** contract, not a machine-checked proof of the full system.

## Terms

| Term | Meaning |
| --- | --- |
| **Exec(E)** | Native execution of command identity `E` (argv, cwd, environment, runtime identity, contract id) under the host kernel. |
| **Trace(E)** | ptrace observation of one Exec(E), producing effects, classification, guards, and captured artifacts. |
| **Reuse(E, R)** | Serving cached stdout, stderr, exit status, and output artifacts from record `R` without re-executing. |
| **Obs(E)** | The observable result of Exec(E): exit status, stdout, stderr, and the pathname-visible filesystem effects TraceJIT captures as outputs. |

Lookup key material is the command identity above. Input file *contents* are
guards, not key bits.

## Obs(E): inclusions and exclusions

**Included (must match for a correct hit):**

- Process exit status.
- Bytes written to the traced stdout and stderr pipes TraceJIT captures.
- Regular-file output artifacts TraceJIT recorded (content + version-2 metadata when present).
- Recorded deletions restored as absences under the documented preconditions.

**Excluded from Obs(E) (not promised equivalent):**

- Inode numbers, directory entry identity across rename/CAS restore, and open file
  description identity after restore (restoration is pathname-visible).
- Concurrent mutations by other processes during the validate→restore window.
- Effects TraceJIT never modeled (those runs are not reusable).
- Performance, scheduling, cgroup pressure, and wall-clock duration.

## Classification eligibility (implemented)

| Class | Reuse in V1? | Meaning under this contract |
| --- | --- | --- |
| `PROVEN` | Yes, when seccomp **and** Landlock ABI 3+ were **installed** for that record | Obs matches provided sandbox policy still covers recorded reads/writes; enforcement is not full equivalence by itself. |
| `GUARDED` | Yes | Every compiled guard passed; artifacts verified; no unmodeled/nondeterministic class effects. |
| `EMPIRICALLY_STABLE` | **No** | Observed stable in samples; not admitted for reuse. |
| `UNKNOWN` | **No** | Unmodeled or unsafe effect (including writable shared mappings). |
| `NONDETERMINISTIC` | **No** | Entropy, clocks, process identity, or similar. |

`cache_eligible()` is only `PROVEN | GUARDED`. Uncertainty fails closed.

## Descriptor and filesystem identity (implemented)

- Descriptor state is tracked primarily by **numeric fd** inside a process, with
  **pipe identity** separate from the number so `dup`/fork/exec keep provenance.
- **Open file description (OFD)** sharing is modeled only for inherited stdin
  offset reuse. Aliases of stdin (same device/inode/position when `kcmp` is
  unavailable) are refused rather than guessed.
- Path dependencies keep the **pathname the process passed**; only `.` is
  stripped. `..` is not collapsed lexically — the guard re-asks the kernel.
- Negative lookups (`ENOENT` / `ENOTDIR`) become absent fingerprints and must
  stay absent.
- Hard-link *creation* (`link`/`linkat`) is `UNKNOWN` (not pathname-equivalent
  to CAS restore). Hard-linked *destinations* for restore are refused.
- `/proc/<pid>/fd/n` paths ending in ` (deleted)` are not treated as live
  pathnames.

## Shared memory

- File-backed writable `MAP_SHARED` (or `mprotect` making a shared mapping
  writable) → `UNKNOWN`.
- Anonymous `MAP_SHARED` → `UNKNOWN` (untracked cross-fork shared memory).
- Anonymous private mappings remain process-internal.

## Hit-path obligation

Reuse may expose cached stdout/stderr/exit/files only after:

1. classification eligibility,
2. all guards pass,
3. stdout/stderr CAS objects verify,
4. inherited-stream seek probes succeed,
5. output artifacts stage and restore without precondition failure,
6. inherited-stream offsets are applied.

Core encodes this order as a small typestate (`GuardsPassed` →
`ArtifactsVerified` → `ExposableHit`).

## Hidden assumptions

- The executable is not replaced in the final window between identity hash and
  `execve`.
- The cache root is not replaced by a hostile symlink after open validation.
- A malicious local cache owner is outside the threat model.
- Filesystem rename/link semantics match ordinary Linux VFS expectations.
- **seccomp + Landlock ≠ full execution equivalence.** They constrain the
  enforced child; they do not make multi-output restore crash-atomic, close the
  validate→restore TOCTOU window, or model every OFD/alias edge.
- Multi-output restore remains pathname-visible under hard kill (no journal).

## Non-claims

This contract is **not** a formal verification of TraceJIT. It does not claim
observational equivalence for unmodeled syscalls, research controlled-Python
contracts, or inode-preserving restore.
