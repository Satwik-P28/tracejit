/* Deterministic ETL used for guarded-reuse timings.
   Reads the committed CSV inputs, performs a fixed integer mix, and writes one
   JSON file. It does not call the clock, getrandom, or process-id syscalls.
   CPython calls gettid while binding its main thread, so it is not this workload. */
#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CUSTOMERS "benchmarks/workloads/python-etl/inputs/customers.csv"
#define SALES "benchmarks/workloads/python-etl/inputs/sales.csv"
#define OUTPUT_PATH "benchmarks/workloads/c-etl/output/report.json"
enum { WORK_PER_SALE = 1000000 };

static char *read_file(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        return NULL;
    }
    size_t capacity = 4096;
    size_t used = 0;
    char *buffer = malloc(capacity);
    if (buffer == NULL) {
        close(fd);
        return NULL;
    }
    while (1) {
        if (used + 1 >= capacity) {
            capacity *= 2;
            char *grown = realloc(buffer, capacity);
            if (grown == NULL) {
                free(buffer);
                close(fd);
                return NULL;
            }
            buffer = grown;
        }
        ssize_t count = read(fd, buffer + used, capacity - used - 1);
        if (count < 0) {
            free(buffer);
            close(fd);
            return NULL;
        }
        if (count == 0) {
            break;
        }
        used += (size_t)count;
    }
    close(fd);
    buffer[used] = '\0';
    return buffer;
}

static const char *region_for(const char *customers, const char *customer_id) {
    const char *line = strchr(customers, '\n');
    if (line == NULL) {
        return NULL;
    }
    for (line += 1; *line != '\0';) {
        const char *end = strchr(line, '\n');
        const char *comma = strchr(line, ',');
        size_t length = end == NULL ? strlen(line) : (size_t)(end - line);
        if (comma != NULL && (end == NULL || comma < end)) {
            size_t id_length = (size_t)(comma - line);
            if (strlen(customer_id) == id_length && memcmp(line, customer_id, id_length) == 0) {
                return comma + 1;
            }
        }
        if (end == NULL) {
            break;
        }
        line = end + 1;
        (void)length;
    }
    return NULL;
}

static void add_total(long *north, long *south, long *east, long *west, const char *region, long amount) {
    if (strncmp(region, "north", 5) == 0) {
        *north += amount;
    } else if (strncmp(region, "south", 5) == 0) {
        *south += amount;
    } else if (strncmp(region, "east", 4) == 0) {
        *east += amount;
    } else if (strncmp(region, "west", 4) == 0) {
        *west += amount;
    }
}

int main(void) {
    const char *wanted = getenv("TRACEJIT_REPORT_REGION");
    if (wanted == NULL || wanted[0] == '\0') {
        wanted = "all";
    }
    char cwd[4096];
    if (getcwd(cwd, sizeof(cwd)) == NULL) {
        return 1;
    }
    char *customers = read_file(CUSTOMERS);
    char *sales = read_file(SALES);
    if (customers == NULL || sales == NULL) {
        free(customers);
        free(sales);
        return 1;
    }

    long north = 0;
    long south = 0;
    long east = 0;
    long west = 0;
    uint64_t digest = 0;
    char *line = strchr(sales, '\n');
    if (line != NULL) {
        line += 1;
    }
    while (line != NULL && *line != '\0') {
        char *next = strchr(line, '\n');
        if (next != NULL) {
            *next = '\0';
        }
        char *first = strchr(line, ',');
        char *second = first == NULL ? NULL : strchr(first + 1, ',');
        if (first != NULL && second != NULL) {
            *first = '\0';
            *second = '\0';
            const char *customer_id = first + 1;
            long amount = strtol(second + 1, NULL, 10);
            const char *region = region_for(customers, customer_id);
            int selected = region != NULL && (strcmp(wanted, "all") == 0 || strncmp(region, wanted, strlen(wanted)) == 0);
            if (selected) {
                add_total(&north, &south, &east, &west, region, amount);
                digest ^= (uint64_t)amount;
                for (int iteration = 0; iteration < WORK_PER_SALE; iteration++) {
                    digest = digest * 1315423911ull + (uint64_t)iteration;
                }
            }
        }
        line = next == NULL ? NULL : next + 1;
    }

    char body[1024];
    int body_length = snprintf(
        body,
        sizeof(body),
        "{\n  \"cwd\": \"%s\",\n  \"region\": \"%s\",\n  \"totals_cents\": {\n    \"east\": %ld,\n    \"north\": %ld,\n    \"south\": %ld,\n    \"west\": %ld\n  },\n  \"work_digest\": \"%016llx\"\n}\n",
        cwd,
        wanted,
        east,
        north,
        south,
        west,
        (unsigned long long)digest);
    if (body_length < 0 || (size_t)body_length >= sizeof(body)) {
        free(customers);
        free(sales);
        return 1;
    }
    int output = open(OUTPUT_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (output < 0) {
        free(customers);
        free(sales);
        return 1;
    }
    size_t pending = (size_t)body_length;
    const char *cursor = body;
    int write_failed = 0;
    while (pending > 0) {
        ssize_t wrote = write(output, cursor, pending);
        if (wrote < 0) {
            write_failed = 1;
            break;
        }
        cursor += wrote;
        pending -= (size_t)wrote;
    }
    close(output);
    free(customers);
    free(sales);
    if (write_failed) {
        return 1;
    }
    fputs(OUTPUT_PATH, stdout);
    fputc('\n', stdout);
    return 0;
}
