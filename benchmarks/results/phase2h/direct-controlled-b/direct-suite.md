# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 7/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 29.45 ms, cached 9.6 ms, cold 53.47 ms, 3.07x, 1.21 hits to repay

## bzip2
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 21.23 ms, cached 11.5 ms, cold 52.73 ms, 1.85x, 3.24 hits to repay

## xz
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system information via sysinfo; process read system clock: monotonic; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## tar
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system clock: realtime; process wrote network: failed socket control (errno 2); executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## sed
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 4.56 ms, cached 12.93 ms, cold 40.6 ms, 0.35x, None hits to repay

## grep
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process-relative procfs dependency: /proc/self/maps; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## sort
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system information via sched_getaffinity; process read system information via prlimit64; process read system information via sysinfo; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## tr
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.41 ms, cached 10.29 ms, cold 27.13 ms, 0.14x, None hits to repay

## base64
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.28 ms, cached 11.5 ms, cold 27.34 ms, 0.11x, None hits to repay

## md5sum
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 2.2 ms, cached 11.55 ms, cold 26.23 ms, 0.19x, None hits to repay

## wc
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.04 ms, cached 9.83 ms, cold 21.49 ms, 0.11x, None hits to repay

## jq
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## python-json
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read process identity via getpid; process read process identity via getppid; process read system clock: monotonic; process read randomness via getrandom; process read process identity via gettid; process read system clock: realtime

## gcc-compile
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc520d9a60, 0x7ffc520d9fe8, 0x7ffc520d9bb0, 0x0, 0x7f3068eb6380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff1db13e50, 0x7fff1db143d0, 0x7fff1db13fa0, 0x0, 0x7f0db1676380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system information via prlimit64; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

