/* Deterministic large-output workload: writes a fixed 64 MiB file.
   No clock, randomness, or malloc, so TraceJIT can classify it GUARDED. */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <stdint.h>
#include <unistd.h>

#define OUTPUT_PATH "benchmarks/releases/fixtures/output/large.bin"
#define OUTPUT_BYTES (64u * 1024u * 1024u)
#define CHUNK 65536u

int main(void) {
    static char buffer[CHUNK];
    uint32_t state = 0x9e3779b9u;
    for (unsigned i = 0; i < CHUNK; i++) {
        state = state * 1664525u + 1013904223u;
        buffer[i] = (char)(state >> 24);
    }
    int fd = open(OUTPUT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        return 1;
    }
    for (unsigned written = 0; written < OUTPUT_BYTES; written += CHUNK) {
        unsigned left = CHUNK;
        const char *cursor = buffer;
        while (left > 0) {
            ssize_t count = write(fd, cursor, left);
            if (count < 0) {
                close(fd);
                return 1;
            }
            cursor += count;
            left -= (size_t)count;
        }
    }
    return close(fd) == 0 ? 0 : 1;
}
