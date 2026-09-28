# Safety model

TraceJIT is conservative. It does not claim that arbitrary programs are safe to
memoize.

## Observable and hidden dependencies

ptrace observes kernel crossings, not arbitrary userspace memory reads. V1
therefore preserves the entire inherited environment in the pre-execution identity
instead of pretending to know which getenv calls occurred. It adds executable,
runtime, cwd, file-content, and file-metadata guards from observed behavior.

Userspace mechanisms such as vDSO can serve clock data without a syscall. Programs
that can observe hidden state outside the modeled surface must not be assumed safe.
The adversarial suite targets known effect paths, but it is not a proof over every
Linux program.

## Nondeterminism and irreversible effects

Observed clocks, random devices, getrandom, process identifiers, mutable system
information, network reads or writes, signals, and unresolved IPC produce
NONDETERMINISTIC. Effect attempts that have no safe model, including failed
attempts that can influence control flow, produce UNKNOWN. Both disable reuse.
Missing-path filesystem results use explicit absence guards.

Filesystem writes are reusable only when the final regular file or deletion is
captured. Network mutation, device access, privilege changes, external databases,
and unknown kernel interfaces are not replayed.

## Guards and time-of-check/time-of-use

Guards check metadata before hashing. Strict mode always validates file contents
with BLAKE3. Fast mode is experimental and may accept an unchanged fingerprint
without hashing. Fingerprints contain device and inode identity, size and block
information, access/change/modification times, mode, link count, ownership, and
special-device identity. When ordinary identity metadata changes but mode and
ownership do not, a matching content hash can validate the file. Permission or
ownership changes still fail. Metadata is not equivalent to content, so strict
remains the default.

There is an unavoidable TOCTOU interval between guard validation and output
restoration. GUARDED does not prevent another process from mutating an input in
that interval. PROVEN narrows the executing process's effect surface, but current
Landlock policy does not freeze external processes or the filesystem. Use TraceJIT
only where concurrent mutation is controlled.

## Sandbox limitations

PROVEN requires Linux x86_64, successful seccomp-BPF installation, and Landlock ABI
3 or newer so file truncation is enforceable. seccomp denies V1 networking and
dangerous syscall classes. Landlock restricts path access. seccomp alone is not
path confinement, and Landlock alone does not classify all syscalls.

The first enforcement request is a discovery run unless a guarded profile already
exists. It is never labeled PROVEN. A compiled policy that cannot be installed
returns an error or a non-proven discovery result. A denied unexpected effect is
recorded and prevents promotion.

Landlock availability depends on kernel configuration and ABI. Capability-dependent
tests print an explicit skip reason when seccomp or the required Landlock ABI is
unavailable, or when policy installation is blocked by the execution environment.

## Cache and output security

The cache contains command stdout, stderr, exit codes, input metadata, inherited
environment values, and copies of output files. It can therefore contain secrets.
The default location inherits the user's filesystem permissions; V1 does not add
encryption or multi-user isolation. Do not share ~/.cache/tracejit across trust
boundaries.

Objects are rehashed on every read. Corruption stops reuse. Guard failure prevents
restoration. Before mutation, restoration validates every object and the output
open preconditions captured during tracing. Symlink substitutions, hard-linked
outputs, missing files that the original open could not create, and non-writable
existing outputs fail closed. Restoration failure also stops reuse rather than
continuing with a partially trusted result.

## Classification rules

- UNKNOWN means no reuse.
- Guard failure means no reuse.
- Irreversible external effects mean no reuse.
- Observation alone never produces PROVEN.
- No cached stdout, stderr, exit code, or output file is exposed before every guard
  succeeds.
- Unsupported enforcement never produces PROVEN.
