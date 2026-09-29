/* CPU sweep workload. argv: <rounds> <output-path>. No malloc, clock, or process-id calls. */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static int write_all(int fd, const char *bytes, size_t length) {
    while (length > 0) {
        ssize_t wrote = write(fd, bytes, length);
        if (wrote < 0) {
            return -1;
        }
        bytes += wrote;
        length -= (size_t)wrote;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        return 2;
    }
    char *end = NULL;
    unsigned long long rounds = strtoull(argv[1], &end, 10);
    if (end == argv[1] || *end != '\0') {
        return 2;
    }
    uint64_t digest = 0;
    for (unsigned long long round = 0; round < rounds; round++) {
        digest = digest * 1315423911ull + round;
    }
    char body[32];
    int length = snprintf(body, sizeof(body), "%016llx\n", (unsigned long long)digest);
    if (length < 0 || (size_t)length >= sizeof(body)) {
        return 1;
    }
    int output = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (output < 0 || write_all(output, body, (size_t)length) != 0) {
        if (output >= 0) {
            close(output);
        }
        return 1;
    }
    close(output);
    return write_all(STDOUT_FILENO, body, (size_t)length) == 0 ? 0 : 1;
}
