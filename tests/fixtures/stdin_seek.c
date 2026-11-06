// Inherited-descriptor fixtures for the stdin offset model.
//
// Each mode returns a distinct exit code on a setup failure so a test failure points at the exact
// operation instead of a generic non-zero status.
#define _GNU_SOURCE
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
  char buffer[64];
  if (argc != 2) return 2;

  if (!strcmp(argv[1], "read-seek-read")) {
    // Read a prefix, rewind, then read again: the final position is 10, not 14.
    ssize_t first = read(0, buffer, 4);
    if (first < 0) return 3;
    if (lseek(0, 0, SEEK_SET) != 0) return 4;
    ssize_t second = read(0, buffer + 4, 10);
    if (second < 0) return 5;
    if (write(1, buffer, (size_t)(first + second)) != first + second) return 6;
    return 0;
  }

  if (!strcmp(argv[1], "probe")) {
    // zlib's seekability probe: a pure offset query that must not move the description.
    off_t current = lseek(0, 0, SEEK_CUR);
    if (current < 0) return 3;
    ssize_t read_bytes = read(0, buffer, 6);
    if (read_bytes < 0) return 4;
    if (write(1, &current, sizeof current) != (ssize_t)sizeof current) return 5;
    if (write(1, buffer, (size_t)read_bytes) != read_bytes) return 6;
    return 0;
  }

  if (!strcmp(argv[1], "end-relative")) {
    // A negative end-relative seek exercises SEEK_END without reading to EOF.
    if (lseek(0, -4, SEEK_END) < 0) return 3;
    ssize_t read_bytes = read(0, buffer, 4);
    if (read_bytes < 0) return 4;
    if (write(1, buffer, (size_t)read_bytes) != read_bytes) return 5;
    return 0;
  }

  if (!strcmp(argv[1], "pread")) {
    // pread observes bytes at an explicit offset and must not advance the description; the
    // following read consumes from the start.
    ssize_t pread_bytes = pread(0, buffer, 4, 8);
    if (pread_bytes < 0) return 3;
    ssize_t read_bytes = read(0, buffer + 4, 4);
    if (read_bytes < 0) return 4;
    if (write(1, buffer, (size_t)(pread_bytes + read_bytes)) !=
        pread_bytes + read_bytes) {
      return 5;
    }
    return 0;
  }

  if (!strcmp(argv[1], "alias")) {
    // A duplicate refers to the same open file description; the model refuses the seek rather
    // than tracking a second position for one description.
    int alias = dup(0);
    if (alias < 0) return 3;
    if (lseek(alias, 0, SEEK_SET) != 0) return 4;
    ssize_t read_bytes = read(0, buffer, 4);
    if (read_bytes < 0) return 5;
    if (write(1, buffer, (size_t)read_bytes) != read_bytes) return 6;
    return 0;
  }

  if (!strcmp(argv[1], "data")) {
    // Allocation-layout advice is not implied by a content hash.
    off_t data = lseek(0, 0, SEEK_DATA);
    if (data < 0) return 3;
    return write(1, &data, sizeof data) == (ssize_t)sizeof data ? 0 : 4;
  }

  if (!strcmp(argv[1], "failed-seek")) {
    // A failed seek leaves the description untouched, so the command stays eligible.
    if (lseek(0, -1, SEEK_SET) != -1) return 3;
    ssize_t read_bytes = read(0, buffer, 4);
    if (read_bytes < 0) return 4;
    if (write(1, buffer, (size_t)read_bytes) != read_bytes) return 5;
    return 0;
  }

  return 7;
}
