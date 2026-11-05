# Phase 2H: adversarial differential testing

Verdict: 32 differential cases, **0 incorrect hits**. The harness compares TraceJIT's bytes with a
fresh native execution after every mutation, and treats a `Reused` decision with different bytes as
a failure. This is coverage of the listed cases, not a proof.

## Harness

`benchmarks/differential/fuzz.py` (deterministic seed, `--seed 7` for the recorded run):

- six commands (`sed`, `wc -c`, `md5sum`, `gzip -9 -c`, `base64`, `tr` with stdin), each run cold,
  then warm under `--contract allocator-entropy-v1`, and compared with direct execution;
- each mutation is applied between the cold and the changed run, after which both native and
  TraceJIT are run again and compared;
- a corrupt CAS object is truncated and the next attempt must fail closed or reproduce the native
  bytes, never serve different bytes.

| Mutation | What it tests |
| --- | --- |
| content rewrite | input hash and size invalidation |
| symlink repoint (`a` → `b`) | the Phase 2G `..`/symlink class stays closed |
| `chmod 0400` | metadata/permission changes are observed, not ignored |
| executable replacement | runtime identity cannot come from a replaced path |
| environment marker / `TZ` | environment is part of the identity and of clock behaviour |
| inherited stdin offset | a consumed descriptor cannot be replayed at offset zero |
| concurrent writer | a mid-run mutation never yields a silently wrong hit |
| corrupt CAS object | integrity failure fails closed |

## Results

```text
cases: 32    statuses: {"ok": 32}    incorrect_hits: 0    RESULT differential PASS
```

Every post-mutation run either used the new bytes or refused; no case returned the old bytes under
`Reused`. The cold/warm pair also confirmed that first execution and reuse agree with native output
for all six commands.

## What each result supports

- **Content and metadata mutations:** the guard compares content hash and fingerprint, so a changed
  input or permission cannot satisfy a stale record.
- **Symlink/`..`:** the record keeps the requested pathname and the guard replays kernel resolution;
  repointing the link invalidates.
- **Executable replacement and environment:** both are part of the lookup identity, so the mutated
  run cannot find the old record.
- **Inherited offsets and concurrency:** the safe outcome is a miss or deoptimisation; the harness
  accepts either and only fails on a wrong `Reused`.
- **Corrupt object:** the CAS rehashes on read, so a truncated object is detected; the result is a
  refusal or a retrace, not stale bytes.

Repeated byte equality is not used as a semantic proof. The fuzzer's guarantee is narrower: for the
listed commands and mutations, no `Reused` decision returned bytes that differed from native
execution.
