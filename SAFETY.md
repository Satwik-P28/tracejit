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

## What is proved, what is observed, and what is assumed

Observed: syscall entries and exits that the ptrace loop models, plus metadata
TraceJIT reads itself for paths those syscalls name. That includes file content
hashes taken when an input is acquired, and the process tree events the tracer
follows for fork, vfork, and exec.

Proved, and only for a run labeled `PROVEN`: seccomp-BPF was installed and
Landlock ABI 3 or newer was installed for that process, after the recorded
effects were already `GUARDED`. seccomp is what blocks the syscall classes the
policy denies. Landlock is what confines the declared paths, including truncate.
Both have to succeed. If policy installation fails, the run is not `PROVEN`.
A failed sandbox spawn can fall back to an unenforced discovery trace; that
result is not promoted.

Not proved:

- That every influence on the process was a syscall. vDSO and ordinary memory
  reads are outside the trace.
- That a clock read answered by the vDSO was observed. `clock_gettime` is
  classified only when the syscall instruction is entered. A libc call that
  stays in the vDSO does not. A program whose result depends on that clock can
  still be `GUARDED`. The fixtures call the syscall directly, so they do not
  prove the libc path.
- That no other process changes an input after guards pass and before restore
  finishes.
- That `Guard::NoUnexpectedEffects` checked anything. The variant always
  succeeds. The check that matters already happened at classification.
- That every kernel or libc behavior change is visible. Runtime identity
  guards the kernel release string, hostname, uid, gid, and related fields.
  It does not notice a behavior change that keeps those strings the same.
  Dynamic linker files are guarded only when the trace recorded them as inputs.
- That the cache is confidential. It is a directory of command outputs and
  environment values under the user's permissions.

Assumed: the kernel's ptrace, seccomp, and Landlock behavior matches the
interfaces this code calls; the BLAKE3 implementation and SQLite store do not
silently corrupt a record that later rehashes successfully; and the operator
does not point TraceJIT at a command whose correctness depends on an unmodeled
channel. Those are engineering assumptions, not a verified computing base.
