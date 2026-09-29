/* File transform: fold committed integers, then a fixed extra mix. No malloc. */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define INPUT_PATH "benchmarks/workloads/c-transform/numbers.txt"
#define OUTPUT_PATH "benchmarks/workloads/c-transform/output/report.txt"
enum { EXTRA_ROUNDS = 250000000 };

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

int main(void) {
    int input = open(INPUT_PATH, O_RDONLY);
    if (input < 0) {
        return 1;
    }
    uint64_t digest = 0;
    char buffer[4096];
    char pending[32];
    size_t pending_length = 0;
    while (1) {
        ssize_t count = read(input, buffer, sizeof(buffer));
        if (count < 0) {
            close(input);
            return 1;
        }
        if (count == 0) {
            break;
        }
        size_t index = 0;
        while (index < (size_t)count) {
            char byte = buffer[index++];
            if (byte == '\n') {
                pending[pending_length] = '\0';
                if (pending_length > 0) {
                    digest = digest * 1315423911ull + (uint64_t)strtoull(pending, NULL, 10);
                }
                pending_length = 0;
            } else if (pending_length + 1 < sizeof(pending)) {
                pending[pending_length++] = byte;
            }
        }
    }
    close(input);
    for (int round = 0; round < EXTRA_ROUNDS; round++) {
        digest = digest * 1315423911ull + (uint64_t)round;
    }
    char body[32];
    int length = snprintf(body, sizeof(body), "%016llx\n", (unsigned long long)digest);
    if (length < 0 || (size_t)length >= sizeof(body)) {
        return 1;
    }
    int output = open(OUTPUT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (output < 0 || write_all(output, body, (size_t)length) != 0) {
        if (output >= 0) {
            close(output);
        }
        return 1;
    }
    close(output);
    return write_all(STDOUT_FILENO, body, (size_t)length) == 0 ? 0 : 1;
}
