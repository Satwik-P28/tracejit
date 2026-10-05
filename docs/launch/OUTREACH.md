# Outreach

Send these only to people who have published work in the area, and only after you have read something they wrote. Do not ask for a star. Do not send the same paragraph to a list. One specific question is enough. If you do not have a public reason to write to someone, do not write.

No names or addresses are listed here. Find people from their public project pages, papers, and commit history. Do not scrape private data.

## Categories

### Bazel engineers

Why they might care: they already refuse actions whose inputs are incomplete. TraceJIT is the undeclared-command version of that problem, and it currently loses to Bazel anywhere a rule exists.

Mention: fail-closed classes, and that `cc` was `UNKNOWN` in the published run.

Ask: "Where would a syscall trace be the wrong way to discover an action input that a rule should have declared?"

### Nix contributors

Why: content-addressed outputs and explicit inputs. TraceJIT hashes outputs it captured, not a derivation.

Mention: the cache is a replay of one command, not a store that can rebuild from a definition.

Ask: "Which inputs do you treat as undeclarable, and would you rather refuse those builds than observe them?"

### Buck2 contributors

Why: Buck2 is explicit about action keys and incremental builds. The overlap is the key, not the implementation.

Mention: TraceJIT's lookup key is executable, argv, cwd, the entire environment, and runtime identity. Files are guards, not key fields.

Ask: "Is putting the whole environment in the key a reasonable conservative choice, or does it hide missing dependency precision?"

### Ninja and other build-system maintainers

Why: depfiles are compiler-generated declarations. TraceJIT is what you do when you do not have a depfile.

Mention: TraceJIT does not parse depfiles and does not claim to speed up Ninja.

Ask: "Which depfile edges are hard to recover from syscalls alone?"

### Compiler and runtime engineers

Why: startup effects (`getrandom`, `gettid`, allocator entropy) are why Python is refused and why the C fixtures disable glibc tcache.

Mention: there is no whitelist. A runtime that calls `getrandom` during startup is `NONDETERMINISTIC` even if the user program is pure.

Ask: "Which startup syscalls are semantically pure, and which would be dishonest to ignore?"

### Systems researchers

Why: the research question is observable dependency inference versus declared incremental computation. Rattle and rr are prior art, not things this replaces.

Mention: no speculation in V1. Whole-command only.

Ask: "What would you need to see in the safety argument before you believed a guarded hit?"

### Rust performance engineers

Why: the hit path is SQLite, BLAKE3, and process startup, measured in `benchmarks/results/break-even.md`. A daemon was considered and not added.

Mention: the published decision-persist cost dropped because a steady-state hit no longer rewrites the record. Guard checks stayed.

Ask: "Which of those phase medians look like the wrong thing to optimize?"

### Linux sandboxing engineers

Why: `PROVEN` is seccomp plus Landlock ABI 3+, and the policy is only as good as the paths recorded on the previous run.

Mention: the first enforced run without a profile is discovery and is not `PROVEN`. Landlock does not stop a concurrent writer.

Ask: "Where does this Landlock ruleset fail to match the ptrace model?"

### CI infrastructure engineers

Why: they feel the pain of rerunning commands, and they will notice that shell and compilers are unsupported.

Mention: do not propose TraceJIT as a CI cache. The interesting question is which jobs are long, deterministic, and free of network.

Ask: "Which jobs in your system are rerun with no declared inputs, and which of those read the network or the clock?"

### Incremental computation researchers

Why: self-adjusting computation and build systems assume a language or a rule that names dependencies. TraceJIT starts from a binary.

Mention: `EMPIRICALLY_STABLE` exists as a class and is not allowed to reuse.

Ask: "Where is an observed syscall trace fundamentally unable to reconstruct the dependency a language-level system would have?"

### Developer-tool authors

Why: the product question is whether `tracejit run --` is a credible interface or whether the refusal rate makes it a benchmark toy.

Mention: `tracejit doctor`, the demo script, and the published loss.

Ask: "What would you need on the first ten minutes, other than more syscall coverage, before you would try it on a real command?"

## Shape of a note

> I've been working on automatic dependency inference for whole Linux commands, with reuse only when the guards still hold. I would particularly value criticism of the safety model, especially [one concrete question from the category above]. The short-command result got slower, and that table is in the repo. No need to star anything.

Stop there.
