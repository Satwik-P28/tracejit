#define _GNU_SOURCE
#include <fcntl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Exercises the output-mutating syscall families audited in Phase 2T. The result is inspected
 * with strace; this file intentionally ignores short-write results because it is a syscall trace
 * probe, not a correctness fixture. */
int main(void) {
  int fd;
  fd = open("new.bin", O_CREAT | O_EXCL | O_WRONLY, 0600);
  if (fd < 0) return 1;
  if (write(fd, "new", 3) != 3) return 2;
  close(fd);

  fd = open("existing.bin", O_CREAT | O_WRONLY | O_TRUNC, 0600);
  if (fd < 0) return 3;
  if (write(fd, "trunc", 5) != 5) return 4;
  close(fd);

  fd = open("existing.bin", O_WRONLY);
  if (fd < 0) return 5;
  if (pwrite(fd, "P", 1, 0) != 1) return 6;
  if (ftruncate(fd, 4) != 0) return 7;
  close(fd);
  if (truncate("existing.bin", 3) != 0) return 8;

  if (rename("new.bin", "renamed.bin") != 0) return 9;
  if (link("renamed.bin", "hard.bin") != 0) return 10;
  if (chmod("renamed.bin", 0640) != 0) return 11;
  struct timespec times[2] = {{1000000, 0}, {1000000, 0}};
  if (utimensat(AT_FDCWD, "renamed.bin", times, 0) != 0) return 12;

  fd = open("dup.bin", O_CREAT | O_WRONLY | O_TRUNC, 0600);
  if (fd < 0) return 13;
  int copy = dup(fd);
  if (copy < 0 || write(copy, "dup", 3) != 3) return 14;
  close(copy);
  close(fd);

  if (unlink("hard.bin") != 0) return 15;
  if (unlink("dup.bin") != 0) return 16;
  if (unlink("renamed.bin") != 0) return 17;
  if (unlink("existing.bin") != 0) return 18;
  return 0;
}
