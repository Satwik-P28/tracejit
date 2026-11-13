/*
 * Research-only Phase 3H prototype. It is not a TraceJIT contract and is not
 * a substitute for syscall-level provenance.
 *
 * Build:
 *   cc -shared -fPIC -O2 -o virtualize.so virtualize.c -ldl
 *
 * Select with PHASE3H_VIRTUALIZE=clocks|identity|both. Clock values advance by
 * one millisecond per read so a fixed value cannot make a polling loop appear
 * to terminate for the wrong reason. `getpid`/`getppid` are symbols and can be
 * replaced here. `threading.get_native_id` is not replaceable this way: CPython
 * invokes syscall(SYS_gettid) directly from libpython, which is why a real
 * contract must be enforced at the syscall boundary.
 */

#define _GNU_SOURCE

#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define VIRTUAL_REALTIME_SEC 1700000000
#define VIRTUAL_MONOTONIC_NS 1000000000ULL
#define VIRTUAL_PID 4242
#define VIRTUAL_PPID 1

static int enabled;
static int initialized;
static unsigned long long tick;
static int mode_clocks;
static int mode_identity;

static void initialize(void) {
    if (initialized) {
        return;
    }
    initialized = 1;
    const char *value = getenv("PHASE3H_VIRTUALIZE");
    if (value == NULL) {
        return;
    }
    mode_clocks = strcmp(value, "clocks") == 0 || strcmp(value, "both") == 0;
    mode_identity = strcmp(value, "identity") == 0 || strcmp(value, "both") == 0;
    enabled = mode_clocks || mode_identity;
}

static void virtual_timespec(clockid_t clock, struct timespec *result) {
    unsigned long long now = tick++;
    if (clock == CLOCK_REALTIME || clock == CLOCK_REALTIME_COARSE) {
        result->tv_sec = VIRTUAL_REALTIME_SEC;
        result->tv_nsec = (long)((now * 1000000ULL) % 1000000000ULL);
        return;
    }
    result->tv_sec = (time_t)(VIRTUAL_MONOTONIC_NS / 1000000000ULL);
    result->tv_nsec = (long)(VIRTUAL_MONOTONIC_NS % 1000000000ULL)
                    + (long)((now * 1000000ULL) % 1000000000ULL);
    if (result->tv_nsec >= 1000000000L) {
        result->tv_sec += result->tv_nsec / 1000000000L;
        result->tv_nsec %= 1000000000L;
    }
}

int clock_gettime(clockid_t clock, struct timespec *result) {
    initialize();
    if (enabled && mode_clocks &&
        (clock == CLOCK_REALTIME || clock == CLOCK_REALTIME_COARSE ||
         clock == CLOCK_MONOTONIC || clock == CLOCK_MONOTONIC_COARSE ||
         clock == CLOCK_BOOTTIME)) {
        virtual_timespec(clock, result);
        return 0;
    }
    static int (*real)(clockid_t, struct timespec *);
    if (real == NULL) {
        real = (int (*)(clockid_t, struct timespec *))dlsym(RTLD_NEXT, "clock_gettime");
    }
    if (real != NULL) {
        return real(clock, result);
    }
    return (int)syscall(SYS_clock_gettime, clock, result);
}

int gettimeofday(struct timeval *result, void *timezone) {
    initialize();
    if (enabled && mode_clocks) {
        struct timespec now;
        virtual_timespec(CLOCK_REALTIME, &now);
        result->tv_sec = now.tv_sec;
        result->tv_usec = now.tv_nsec / 1000;
        return 0;
    }
    static int (*real)(struct timeval *, void *);
    if (real == NULL) {
        real = (int (*)(struct timeval *, void *))dlsym(RTLD_NEXT, "gettimeofday");
    }
    if (real != NULL) {
        return real(result, timezone);
    }
    return (int)syscall(SYS_gettimeofday, result, timezone);
}

time_t time(time_t *result) {
    initialize();
    if (enabled && mode_clocks) {
        time_t value = VIRTUAL_REALTIME_SEC;
        if (result != NULL) {
            *result = value;
        }
        return value;
    }
    static time_t (*real)(time_t *);
    if (real == NULL) {
        real = (time_t (*)(time_t *))dlsym(RTLD_NEXT, "time");
    }
    if (real != NULL) {
        return real(result);
    }
    return (time_t)syscall(SYS_time, result);
}

pid_t getpid(void) {
    initialize();
    if (enabled && mode_identity) {
        return VIRTUAL_PID;
    }
    static pid_t (*real)(void);
    if (real == NULL) {
        real = (pid_t (*)(void))dlsym(RTLD_NEXT, "getpid");
    }
    return real != NULL ? real() : (pid_t)syscall(SYS_getpid);
}

pid_t getppid(void) {
    initialize();
    if (enabled && mode_identity) {
        return VIRTUAL_PPID;
    }
    static pid_t (*real)(void);
    if (real == NULL) {
        real = (pid_t (*)(void))dlsym(RTLD_NEXT, "getppid");
    }
    return real != NULL ? real() : (pid_t)syscall(SYS_getppid);
}
