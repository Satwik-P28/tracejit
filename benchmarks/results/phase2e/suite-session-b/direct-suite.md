# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 1/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs
- timing: direct 30.32 ms, cached 4.36 ms, cold 53.31 ms, 6.95x, 0.89 hits to repay

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
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f31e0fa61f7, 0x7ffdfebec9a0, 0x0, 0x7ffdfebec740, 0x0, 0x7f31e0ff6440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f31e0fa61f7, 0x7ffdfebec890, 0x0, 0x7ffdfebec740, 0x0, 0x7f31e0ff6440]; unmodeled successful syscall 85: unmodeled syscall 85 args [0x7ffdfebeceb5, 0x1b6, 0x55cc1a092310, 0x1, 0x7f31e0e04b20, 0x0]; unmodeled successful syscall 5: fstat on unclassified fd 3

## sed
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f9eed3551f7, 0x7ffd89417700, 0x0, 0x7ffd894174a0, 0x0, 0x7f9eed3a5440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f9eed3551f7, 0x7ffd894175f0, 0x0, 0x7ffd894174a0, 0x0, 0x7f9eed3a5440]

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
- reasons: read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-y3bk97l4/work-tr/input.txt

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
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffdd4a3a0d0, 0x7ffdd4a3a658, 0x7ffdd4a3a220, 0x0, 0x7fd949976380]

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffeacaea960, 0x7ffeacaeaee0, 0x7ffeacaeaab0, 0x0, 0x7f95af5ba380]

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via prlimit64

