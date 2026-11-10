# TraceJIT Literature and Implementation Review

This is the initial Phase 3A review. It records mechanisms that are relevant to the next cycles. It does
not claim that every listed project was source-audited. Entries marked **docs** were checked against
official documentation; entries marked **source pending** need a source-level read before reuse.

## Execution and build caches

| System | Mechanism relevant to TraceJIT | Evidence | Status |
| --- | --- | --- | --- |
| ccache | Direct mode stores a manifest keyed by source, options and compiler identity; the manifest holds result references and include paths/hashes. This is compiler-aware multi-result caching. | <https://ccache.dev/manual/latest.html> | docs |
| Firebuild | Automatic command accelerator that caches outputs and replays them for equivalent commands; documented interception uses a preloaded library for dynamically linked processes. | <https://github.com/firebuild/firebuild>, <https://firebuild.com/> | docs; source pending |
| sccache | Compiler-wrapper cache spanning C/C++/Rust. Its advantage is language/toolchain knowledge, not transparent process tracing. | <https://github.com/mozilla/sccache> | source pending |
| Bazel / Buck2 | Build-graph ownership permits action keys, declared inputs, and selective scheduling. TraceJIT does not own the graph, so these are workflow-level baselines rather than drop-in components. | <https://bazel.build/remote/caching>, <https://github.com/facebook/buck2> | source pending |
| Rattle | Build-system experiment in dependency tracking and incremental execution. Relevant to future workflow-level ownership. | <https://github.com/ndmitchell/rattle> | source pending |
| Nix | Content-addressed store and hermetic derivation identities. Relevant to artifact identity, not to observing an arbitrary unmodified process. | <https://nixos.org/manual/nix/stable/store/> | source pending |

The Phase 2T measurement is the relevant competitive result: correctly configured Make and Ninja skip an
unchanged build far more cheaply than TraceJIT, and a content-addressed cache also beats TraceJIT on the
measured incremental pipeline. TraceJIT's current defensible difference is automatic dependency
discovery plus recovery when an output is missing or suspect, not whole-build throughput. Raw result:
`benchmarks/results/phase2t/incremental.json`.

## Incremental computation

| System | Mechanism | Relevance | Status |
| --- | --- | --- | --- |
| Salsa | Revisioned database and red-green validation. A changed input marks dependents; a re-executed dependency that produces an equal value can stop propagation. | Candidate model for a future workflow graph. Not applicable to an arbitrary process without an explicit graph. | docs: <https://salsa-rs.github.io/salsa/reference/algorithm.html> |
| Adapton | Demand-driven incremental computation with dirtying and change propagation. | Same conceptual direction; needs a source-level comparison before any claim of novelty. | source pending |

The Phase 3A candidate index is deliberately smaller than these systems: it retains alternate execution
records for one already-computed command identity. It does not build a dependency graph, propagate
changes, or schedule speculative work.

## Deterministic and controlled execution

| System | Mechanism | Relevance | Status |
| --- | --- | --- | --- |
| Hermit | Deterministic execution and replay for Linux processes. | Long-term comparison for controlled contracts and syscall virtualization. | source pending: <https://github.com/facebookincubator/hermit> |
| rr | Recording and deterministic replay. | Replay fidelity and observation boundaries; not a cache. | source pending |
| Landlock | Unprivileged filesystem access control. | Current `PROVEN` enforcement requires it in addition to seccomp. | docs: <https://docs.kernel.org/userspace-api/landlock.html> |
| seccomp | Syscall filtering. | Current enforcement layer; child-side filter mode is verified after installation. | docs: <https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html> |

TraceJIT's controlled contracts are explicitly not native-equivalent. A contract identifier is part of
the lookup key and is checked before reuse. Any future `PROVEN` claim must require installed enforcement,
not merely a capability report.

## Storage and validation

| Mechanism | Potential value | Risk | Status |
| --- | --- | --- | --- |
| BLAKE3 whole-object CAS | Current artifact identity and corruption detection. | Every hit re-reads and rehashes objects. | implemented |
| fs-verity | Kernel-authenticated immutable file digests could reduce repeated hashing. | Writable inputs and changing verification policies need a sound invalidation model. | unverified: <https://docs.kernel.org/filesystems/fsverity.html> |
| FastCDC | Content-defined chunking for large, shifting artifacts. | Changes artifact schema, restore semantics, and the current whole-object contract. | unverified: <https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf> |
| Merkle indexes | Share unchanged regions across large artifacts. | More complexity than the measured workloads justify so far. | unverified |
| Zstandard | Compression of cache objects. | Retrieval cost and deterministic decompression must be measured. | unverified |

No chunking, fs-verity, compression, or inode-preserving storage was added in Phase 3A.

## What was actually changed

The implementation was informed by the general multi-result idea in ccache and the red-green separation
of validation from recomputation in Salsa, but it is not a port of either. The concrete change is a
bounded SQLite candidate index plus per-candidate guard validation. The A/B/A experiment is the evidence
for that change, not an analogy to prior systems.

## Claims that are not supported

- TraceJIT is not shown to be faster than Make, Ninja, ccache, sccache, Firebuild, Bazel, or Buck2.
- TraceJIT does not provide atomic multi-file restoration or inode-preserving rollback.
- TraceJIT does not yet provide workflow-level incremental recomputation.
- A successful local guard test is not a `PROVEN` enforcement result.
- No academic novelty claim is made for retaining multiple cached candidates; similar multi-result
  structures are established in compiler caches.
