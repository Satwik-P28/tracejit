# `getrusage` investigation — is the compiler blocked by it?

Commit: `bd59a0e`. Host: Linux 6.1.102, gcc 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1), no clang
installed. All measurements below are from this host in this session.

## Answer in one line

`getrusage(RUSAGE_SELF)` is called **once by `as`**, not by `cc1`, not by the gcc driver, and not for
gcc's `-ftime-report`; its value provably did not reach any observable output in these experiments,
but the value is nondeterministic and cannot be guarded, so the classification stays
`NONDETERMINISTIC`. The compiler is nevertheless **not** one model away from reuse: with the shell
wrapper removed, `getrusage` is the *only* blocker for `cc -O2 -c`, which makes it the decisive one.

## Which process calls it

`strace -f -e trace=getrusage,execve /usr/bin/cc -O2 -c input.c -o plain.o` produces exactly one
call:

```text
2678  execve("/usr/bin/cc", [...]) = 0
2679  execve("/usr/libexec/gcc/x86_64-linux-gnu/13/cc1", [...]) = 0
2680  execve("/usr/bin/as", ["as", "--64", "-o", "plain.o", "/tmp/cclbCQvt.s"], ...) = 0
2680  getrusage(RUSAGE_SELF, {ru_utime={0,0}, ru_stime={0,3925}, ...}) = 0
```

- `who` = `RUSAGE_SELF` (0), as the census already reported from the register dump.
- `cc1` alone: **zero** `getrusage` calls (`strace ... cc1 -quiet -O2 -o cc1.s input.c`).
- `as` alone on a pre-generated `.s` file: **one** call, reproduced standalone.
- Call count is **1 with and 1 without `-ftime-report`**, so this is not gcc's timing machinery.

So the caller is the GNU assembler. `nm -D /usr/bin/as` shows `U getrusage@GLIBC_2.2.5`; the
disassembly contains two call sites. Ubuntu ships `as` stripped, so the function names are not
recoverable locally and the surrounding C source was not inspected directly — this is the one part of
the investigation that rests on behaviour rather than source.

## What the value reaches — interventional evidence, not repeated observation

Equality across repeated runs is weak evidence, so the value was **overridden** with an `LD_PRELOAD`
shim that replaces `getrusage` and returns either all zeros or absurd values (12345 s user time,
999999 maxrss, 987654321 context switches). A third variant returns `-1` with `EINVAL`.

| Probe | Result |
| --- | --- |
| `sha256` of the object file, baseline vs zeros vs extreme | identical (`24832fef…`) |
| same, with `getrusage` failing (`EINVAL`/`-1`) | identical, exit status 0, empty stderr |
| `as --statistics` under zeros vs extreme | prints `total time in assembly: 0.000000` **in both** |
| `-ftime-report` output under the shim | unchanged; gcc's report is not fed by `getrusage` |

Two conclusions follow. First, substituting the value by orders of magnitude changed nothing
observable for these inputs, and even total failure of the call is tolerated — the assembler does not
branch on the return code in this path. Second, the `--statistics` report does *not* derive from
these values, which rules out the most obvious consumer.

This is stronger than "the outputs matched last time": it is a controlled intervention on the
variable. It is still **not** a proof of non-interference for all inputs — it samples two values, and
a threshold that neither sample crosses would be missed. That distinction is why the classification
does not change.

## Why it must stay `NONDETERMINISTIC`

`ru_utime`, `ru_stime`, `ru_maxrss`, `ru_minflt` and friends report the process's own consumption.
They differ on every run by construction and cannot be guarded: there is no value to compare against,
and re-asking the kernel at validation time would return the validator's own usage. A program that
prints them (`bash -c times`, `time -v`, a test harness reporting peak RSS) would replay stale text.
No global `getrusage` whitelist is therefore admissible, and none was added.

## Why this matters more than its frequency suggests

With the shell wrapper removed, a direct compile has exactly one refusal reason:

```text
$ target/release/tracejit analyze --json -- cc -O2 -c hello.c -o hello.o
classification: Unknown   eligible: False   dependencies: 301
   - unmodeled successful syscall 98: [...] args [0x0, ...]
```

Nothing else. No clock read, no randomness, no `getrandom`, no unclassified descriptor, no pipe
problem. `cc1` and the driver are, as far as this tracer observes, deterministic. The single
nondeterministic read is a resource-usage probe inside the assembler that we have good evidence does
not affect the artifact.

That is the precise shape of the blocker: not "gcc is nondeterministic", but "one tool in the
compiler pipeline reads usage counters, and the model cannot say they are irrelevant".

## What would change the answer, and what was rejected

- **Rejected:** whitelisting `getrusage` so that `cc` becomes eligible. It is correct for this
  workload and wrong in general, and it would be indistinguishable from tuning for the benchmark.
- **Rejected:** differential testing at cache-fill time (run twice with substituted values and cache
  only if outputs agree). It samples, it does not prove, and it weakens the stated contract without
  making the weakness visible to the user.
- **Not attempted here:** a documented, opt-in profile that declares resource-usage reads
  non-influential for a named toolchain version, enforced by an adversarial test that shows the
  declaration is violated when the program *does* print the values. That is a trust-model change with
  a user-visible contract, not a syscall model, and it should be decided explicitly rather than
  slipped in to move a number.

## Status

| Question | Answer |
| --- | --- |
| Caller | `as` (GNU assembler) **[VERIFIED]** |
| `who` | `RUSAGE_SELF` **[VERIFIED]** |
| Fields that reach output | none observed, by intervention **[VERIFIED for these inputs]** |
| Config that eliminates the call | none found; count is 1 with and without `-ftime-report` **[VERIFIED]** |
| Guardable | no — the value is per-run consumption **[VERIFIED]** |
| Classification retained | `NONDETERMINISTIC`/`UNKNOWN` (never reusable) **[VERIFIED]** |
| Compiler reuse achievable without a policy change | no **[INFERENCE]** from the single-blocker analysis |
