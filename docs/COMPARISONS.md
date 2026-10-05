# Why not just use something else?

TraceJIT does not replace these tools. Each one already solves a problem TraceJIT does not solve. The niche is narrower: take an existing Linux command, infer the dependencies that show up as modeled syscalls, and reuse the whole command only while synchronous guards still hold.

Anything below that describes another project is only as much as this repository needs for the contrast. Check that project's current documentation before repeating the comparison in a talk or a post.

| System | Dependencies declared? | Automatically observed? | Runtime effects? | Guarded reuse of an arbitrary command? | Primary use |
| --- | --- | --- | --- | --- | --- |
| Make | Yes, in the makefile | No | No | No | Rebuild files when declared inputs are newer |
| Ninja | Yes, plus compiler depfiles | Depfiles come from the compiler, not from a general trace | No | No | Fast rebuilds of a declared graph |
| Bazel | Yes, in rules | The action graph is declared. Sandboxing restricts actions; it does not discover a graph for an unknown binary | Declared inputs and outputs | No | Hermetic, cacheable build actions |
| ccache / sccache | Implicit in the compiler invocation | Preprocessed source, compiler, and related flags | Compiler-specific | No | Reuse compiler output |
| Nix | Yes, in the derivation | No | The store records declared outputs | No | Reproducible package builds |
| A function memoization library | The programmer picks the arguments | No | Only what the language runtime passes | No | Reuse a pure function |
| Filesystem snapshots | No | The snapshot is a filesystem, not a dependency set | No | No | Roll back or copy a tree |
| strace | No | Yes, syscalls | It prints them | No | Inspect one run |
| Containers | No | No | They confine the process | No | Isolate execution |
| TraceJIT V1 | The whole inherited environment is part of the key even without `getenv` | Modeled syscalls and path metadata | Clock, randomness, network, and unknown syscalls become refusals | Whole command, Linux x86_64, when the class is `GUARDED` or `PROVEN` | Skip a rerun that is still safe to skip |

## Make, Ninja, Bazel

These systems are faster and more precise when the build author listed the inputs. They also reuse pieces of a graph. TraceJIT does not. Shell pipelines and `cc -c` are `UNKNOWN` in the published runs, so TraceJIT is not a build cache today. A build tool that already has a correct action graph should keep using it.

## ccache and sccache

They know what a compiler invocation means. TraceJIT tries not to special-case the program. That is why a compiler's `access` checks and unmodeled syscalls currently disable reuse instead of being papered over.

## Nix

Nix hashes a declared recipe and its inputs. TraceJIT hashes an executable it was pointed at and the files that executable touched through modeled syscalls. Nix can rebuild from a definition. TraceJIT can only replay a command it has already seen, and only the outputs it captured.

## Memoization

Memoizing a function requires the function's arguments to be the real inputs. A process can read files, the clock, or another process without those showing up as function arguments. TraceJIT is an attempt to see those effects from the outside, and to stop when it cannot.

## Snapshots and containers

A snapshot copies bytes. It does not know which bytes the process needed. A container limits what a process may touch. TraceJIT's `--enforce` path uses seccomp and Landlock for the `PROVEN` label. That is a confinement check on a later run, not a container platform.

## strace

strace is an observation tool. A cache in front of an strace log still has to decide which lines are inputs, which writes can be replayed, which syscalls make the result unsafe, and what to do when the log contains a syscall the cache does not understand. TraceJIT is that decision. The tracing mechanism is not the novel part. The fail-closed classification and the guards are.

## Firebuild, Rattle, and rr

The README already names these as prior art. Firebuild caches build commands by intercepting execution. Rattle explored traced dependencies and speculative execution. rr records a run so it can be replayed for debugging. TraceJIT V1 does not speculate, does not claim those systems are obsolete, and does not claim automatic effect discovery is new. Its V1 claim is the combination in this repository: explicit classes, synchronous guards, `PROVEN` only after seccomp and Landlock are installed, and no reuse for `UNKNOWN` or `NONDETERMINISTIC`.

Confirm the current behavior of Firebuild, Rattle, and rr before describing them more specifically than that.
