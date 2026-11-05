# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 7/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 28.61 ms, cached 3.87 ms, cold 47.36 ms, 7.39x, 0.76 hits to repay

## bzip2
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 17.55 ms, cached 4.28 ms, cold 34.4 ms, 4.1x, 1.27 hits to repay

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
- timing: direct 3.59 ms, cached 5.19 ms, cold 22.53 ms, 0.69x, None hits to repay

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
- timing: direct 1.13 ms, cached 4.51 ms, cold 17.13 ms, 0.25x, None hits to repay

## base64
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.52 ms, cached 5.1 ms, cold 18.0 ms, 0.3x, None hits to repay

## md5sum
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.74 ms, cached 5.74 ms, cold 17.86 ms, 0.3x, None hits to repay

## wc
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 0.85 ms, cached 4.08 ms, cold 13.5 ms, 0.21x, None hits to repay

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
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffdae6efab0, 0x7ffdae6f0038, 0x7ffdae6efc00, 0x0, 0x7fa761c9d380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcde85b860, 0x7ffcde85bde0, 0x7ffcde85b9b0, 0x0, 0x7ff3a936c380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system information via prlimit64; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

