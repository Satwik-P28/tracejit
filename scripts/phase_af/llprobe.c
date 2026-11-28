#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#include <string.h>
#include <linux/landlock.h>

#ifndef __NR_landlock_create_ruleset
#define __NR_landlock_create_ruleset 444
#endif

int main(void) {
    long abi = syscall(__NR_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 0) { printf("landlock_abi=null errno=%d (%s)\n", errno, strerror(errno)); return 2; }
    printf("landlock_abi=%ld\n", abi);
    return 0;
}
