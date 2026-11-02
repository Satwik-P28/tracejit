# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 1/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs
- timing: direct 28.84 ms, cached 4.03 ms, cold 46.26 ms, 7.16x, 0.7 hits to repay

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
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7fbfb28561f7, 0x7fff373ff1a0, 0x0, 0x7fff373fef40, 0x0, 0x7fbfb28a6440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7fbfb28561f7, 0x7fff373ff090, 0x0, 0x7fff373fef40, 0x0, 0x7fbfb28a6440]; unmodeled successful syscall 85: unmodeled syscall 85 args [0x7fff37400e80, 0x1b6, 0x563438706310, 0x1, 0x7fbfb2804b20, 0x0]; unmodeled successful syscall 5: fstat on unclassified fd 3

## sed
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f26016871f7, 0x7fff924fc4f0, 0x0, 0x7fff924fc290, 0x0, 0x7f26016d7440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f26016871f7, 0x7fff924fc3e0, 0x0, 0x7fff924fc290, 0x0, 0x7f26016d7440]

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
- reasons: read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-sh4vjov_/work-tr/input.txt

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
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffa409b370, 0x7fffa409b8f8, 0x7fffa409b4c0, 0x0, 0x7fabbc988380]

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcff19cb60, 0x7ffcff19d0e0, 0x7ffcff19ccb0, 0x0, 0x7f0d26c78380]

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via prlimit64

