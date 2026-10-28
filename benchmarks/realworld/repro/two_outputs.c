/* Two-output workspace used by partial_restore.sh.
   Writes <root>/a.txt and <root>/sub/b.txt from <root>/input.txt.
   Uses only open/read/write so the trace classifies as GUARDED. */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

static int copy(const char *input, const char *output) {
    char buffer[4096];
    int source = open(input, O_RDONLY);
    if (source < 0) {
        return 1;
    }
    int destination = open(output, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (destination < 0) {
        close(source);
        return 1;
    }
    ssize_t count;
    while ((count = read(source, buffer, sizeof buffer)) > 0) {
        if (write(destination, buffer, (size_t)count) != count) {
            close(source);
            close(destination);
            return 1;
        }
    }
    close(source);
    close(destination);
    return count < 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 2;
    }
    char input[4096];
    char first[4096];
    char second[4096];
    if (snprintf(input, sizeof input, "%s/input.txt", argv[1]) >= (int)sizeof input ||
        snprintf(first, sizeof first, "%s/a.txt", argv[1]) >= (int)sizeof first ||
        snprintf(second, sizeof second, "%s/sub/b.txt", argv[1]) >= (int)sizeof second) {
        return 2;
    }
    if (copy(input, first) != 0) {
        return 1;
    }
    return copy(input, second);
}
