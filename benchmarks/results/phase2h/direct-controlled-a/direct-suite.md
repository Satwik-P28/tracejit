# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 7/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 28.99 ms, cached 8.97 ms, cold 72.12 ms, 3.23x, 2.15 hits to repay

## bzip2
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 19.58 ms, cached 12.15 ms, cold 53.19 ms, 1.61x, 4.52 hits to repay

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
- timing: direct 4.92 ms, cached 13.79 ms, cold 39.3 ms, 0.36x, None hits to repay

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
- timing: direct 1.75 ms, cached 12.92 ms, cold 35.19 ms, 0.14x, None hits to repay

## base64
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.84 ms, cached 14.62 ms, cold 32.37 ms, 0.13x, None hits to repay

## md5sum
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 2.61 ms, cached 15.05 ms, cold 31.15 ms, 0.17x, None hits to repay

## wc
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- timing: direct 1.2 ms, cached 11.42 ms, cold 26.62 ms, 0.11x, None hits to repay

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
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd8627eee0, 0x7ffd8627f468, 0x7ffd8627f030, 0x0, 0x7f2984516380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd08ef8d90, 0x7ffd08ef9310, 0x7ffd08ef8ee0, 0x0, 0x7f95bf209380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read system information via prlimit64; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

