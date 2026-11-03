# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 1/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs
- timing: direct 30.4 ms, cached 4.69 ms, cold 49.5 ms, 6.48x, 0.74 hits to repay

## bzip2
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom

## xz
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via sysinfo; process read system clock: monotonic

## tar
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f4b3277d1f7, 0x7ffcd1689510, 0x0, 0x7ffcd16892b0, 0x0, 0x7f4b327cd440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f4b3277d1f7, 0x7ffcd1689400, 0x0, 0x7ffcd16892b0, 0x0, 0x7f4b327cd440]; unmodeled successful syscall 85: unmodeled syscall 85 args [0x7ffcd168aeb5, 0x1b6, 0x563a26061310, 0x1, 0x7f4b32604b20, 0x0]; unmodeled successful syscall 5: fstat on unclassified fd 3

## sed
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7ff2b77201f7, 0x7fffb538b7c0, 0x0, 0x7fffb538b560, 0x0, 0x7ff2b7770440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7ff2b77201f7, 0x7fffb538b6b0, 0x0, 0x7fffb538b560, 0x0, 0x7ff2b7770440]

## grep
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process-relative procfs dependency: /proc/self/maps

## sort
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via sched_getaffinity; process read system information via prlimit64; process read system information via sysinfo

## tr
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-oxgjemzv/work-tr/input.txt

## base64
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom

## md5sum
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom

## wc
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom

## jq
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom

## python-json
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read process identity via getpid; process read randomness via getrandom; process read process identity via getppid; process read system clock: monotonic; process read process identity via gettid; process read system clock: realtime

## gcc-compile
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe082cfec0, 0x7ffe082d0448, 0x7ffe082d0010, 0x0, 0x7f2dea8ed380]

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe7082c7f0, 0x7ffe7082cd70, 0x7ffe7082c940, 0x0, 0x7ffb58468380]

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via prlimit64

