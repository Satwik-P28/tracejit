# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 1/16
Traced output matched a direct run: 16/16

## gzip
- classification Guarded, eligible True, reused True, second decision Reused
- direct exit 0, traced exit 0, stdout matches True
- reasons: all observed dependencies are guardable or captured outputs
- timing: direct 28.78 ms, cached 4.18 ms, cold 47.1 ms, 6.89x, 0.74 hits to repay

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
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7fc6d421a1f7, 0x7ffe7bb9f730, 0x0, 0x7ffe7bb9f4d0, 0x0, 0x7fc6d426a440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7fc6d421a1f7, 0x7ffe7bb9f620, 0x0, 0x7ffe7bb9f4d0, 0x0, 0x7fc6d426a440]; unmodeled successful syscall 85: unmodeled syscall 85 args [0x7ffe7bb9fe80, 0x1b6, 0x55b44ca39310, 0x1, 0x7fc6d4004b20, 0x0]; unmodeled successful syscall 5: fstat on unclassified fd 3

## sed
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f34881831f7, 0x7fff37cd8260, 0x0, 0x7fff37cd8000, 0x0, 0x7f34881d3440]; unmodeled successful syscall 137: unmodeled syscall 137 args [0x7f34881831f7, 0x7fff37cd8150, 0x0, 0x7fff37cd8000, 0x0, 0x7f34881d3440]

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
- reasons: read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt; read from inherited descriptor 0 is not replayable: /tmp/tracejit-direct-231rxjgk/work-tr/input.txt

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
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffdd25a0af0, 0x7ffdd25a1078, 0x7ffdd25a0c40, 0x0, 0x7f8b6fecc380]

## assemble
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffff4780270, 0x7ffff47807f0, 0x7ffff47803c0, 0x0, 0x7fb19e69d380]

## strip
- classification Nondeterministic, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: process read randomness via getrandom; process read system information via prlimit64

