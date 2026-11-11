#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <locale.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/random.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/syscall.h>
#include <sys/sysinfo.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

static void join_path(char *destination, size_t capacity, const char *root,
                      const char *name) {
  if (snprintf(destination, capacity, "%s/%s", root, name) >= (int)capacity) {
    exit(90);
  }
}

static void copy_file(const char *input, const char *output) {
  char buffer[4096];
  int source = open(input, O_RDONLY);
  if (source < 0) exit(91);
  int destination = open(output, O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (destination < 0) {
    close(source);
    exit(91);
  }
  ssize_t count;
  while ((count = read(source, buffer, sizeof(buffer))) > 0) {
    ssize_t offset = 0;
    while (offset < count) {
      ssize_t written = write(destination, buffer + offset, count - offset);
      if (written <= 0) {
        close(source);
        close(destination);
        exit(92);
      }
      offset += written;
    }
  }
  close(source);
  close(destination);
  if (count < 0) exit(92);
}

static void network_write(void) {
  int fd = socket(AF_INET, SOCK_DGRAM, 0);
  struct sockaddr_in address = {.sin_family = AF_INET,
                                .sin_port = htons(9),
                                .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
  if (fd >= 0) {
    connect(fd, (struct sockaddr *)&address, sizeof(address));
    send(fd, "x", 1, 0);
    close(fd);
  }
}

static void *thread_noop(void *unused) {
  (void)unused;
  return NULL;
}

int main(int argc, char **argv) {
  const char *name;
  const char *root;
  if (argc == 4 && !strcmp(argv[1], "script_interpreter")) {
    name = "plain_file_read";
    root = argv[3];
  } else if (argc == 3) {
    name = argv[1];
    root = argv[2];
  } else {
    return 89;
  }
  char input[4096], output[4096], second[4096];
  join_path(input, sizeof(input), root, "input.txt");
  join_path(output, sizeof(output), root, "output.txt");
  join_path(second, sizeof(second), root, "second.txt");

  if (!strcmp(name, "vdso_clock")) {
    struct timespec spec;
    struct timeval wall;
    if (clock_gettime(CLOCK_REALTIME, &spec) != 0) return 1;
    if (clock_gettime(CLOCK_MONOTONIC, &spec) != 0) return 1;
    if (gettimeofday(&wall, NULL) != 0) return 1;
    if (time(NULL) == (time_t)-1) return 1;
    return 0;
  }
  if (!strcmp(name, "clock_realtime") || !strcmp(name, "clock_monotonic")) {
    struct timespec value;
    int clock = !strcmp(name, "clock_realtime") ? CLOCK_REALTIME : CLOCK_MONOTONIC;
    return syscall(SYS_clock_gettime, clock, &value) < 0;
  }
  if (!strcmp(name, "getrandom")) {
    unsigned char value;
    return syscall(SYS_getrandom, &value, sizeof(value), 0) < 0;
  }
  if (!strcmp(name, "urandom")) {
    int fd = open("/dev/urandom", O_RDONLY);
    unsigned char value;
    int result = read(fd, &value, sizeof(value));
    close(fd);
    return result != 1;
  }
  if (!strcmp(name, "network_connect") || !strcmp(name, "network_send") ||
      !strcmp(name, "dns_lookup")) {
    network_write();
    return 0;
  }
  if (!strcmp(name, "unix_socket")) {
    int pair[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0) {
      send(pair[0], "x", 1, 0);
      close(pair[0]);
      close(pair[1]);
    }
    return 0;
  }
  if (!strcmp(name, "mmap_shared_write") || !strcmp(name, "mmap_shared_mprotect")) {
    int fd = open(input, O_RDWR);
    if (fd < 0) return 1;
    int prot = !strcmp(name, "mmap_shared_write") ? PROT_READ | PROT_WRITE : PROT_READ;
    void *mapping = mmap(NULL, 4096, prot, MAP_SHARED, fd, 0);
    if (mapping == MAP_FAILED) {
      close(fd);
      return 1;
    }
    if (!strcmp(name, "mmap_shared_mprotect") &&
        mprotect(mapping, 4096, PROT_READ | PROT_WRITE) != 0) {
      munmap(mapping, 4096);
      close(fd);
      return 1;
    }
    ((unsigned char *)mapping)[0] = 'Z';
    munmap(mapping, 4096);
    close(fd);
    return 0;
  }
  if (!strcmp(name, "unknown_ioctl")) {
    int pair[2], available = 0;
    if (pipe(pair) != 0) return 1;
    int result = ioctl(pair[0], FIONREAD, &available);
    close(pair[0]);
    close(pair[1]);
    return result < 0;
  }
  if (!strcmp(name, "readlink_non_symlink")) {
    char target[4096];
    errno = 0;
    ssize_t result = readlink(input, target, sizeof(target));
    return result != -1 || errno != EINVAL;
  }
  if (!strcmp(name, "tracked_file_terminal_probe")) {
    int fd = open(input, O_RDONLY);
    if (fd < 0) return 1;
    struct termios terminal;
    errno = 0;
    int result = ioctl(fd, TCGETS, &terminal);
    int saved_errno = errno;
    close(fd);
    return result != -1 || saved_errno != ENOTTY;
  }
  if (!strcmp(name, "fd_cloexec")) {
    int fd = open(input, O_RDONLY);
    if (fd < 0) return 1;
    int result = ioctl(fd, FIOCLEX);
    close(fd);
    return result != 0;
  }
  if (!strcmp(name, "at_empty_path")) {
    int fd = open(input, O_RDONLY);
    if (fd < 0) return 1;
    struct stat metadata;
    int result = syscall(SYS_newfstatat, fd, "", &metadata, AT_EMPTY_PATH);
    close(fd);
    return result != 0;
  }
  if (!strcmp(name, "stdin_metadata")) {
    struct stat metadata;
    return fstat(STDIN_FILENO, &metadata);
  }
  if (!strcmp(name, "proc_self")) {
    copy_file("/proc/self/status", output);
    return 0;
  }
  if (!strcmp(name, "proc_cpuinfo")) {
    copy_file("/proc/cpuinfo", output);
    return 0;
  }
  if (!strcmp(name, "hostname")) {
    struct utsname value;
    return uname(&value);
  }
  if (!strcmp(name, "uid_gid_dependency")) {
    return (getuid() == (uid_t)-1 || getgid() == (gid_t)-1);
  }
  if (!strcmp(name, "process_identity")) {
    return syscall(SYS_getpid) < 0;
  }
  if (!strcmp(name, "system_info")) {
    struct sysinfo value;
    return syscall(SYS_sysinfo, &value) < 0;
  }
  if (!strcmp(name, "cwd_dependency")) {
    char cwd[4096];
    return getcwd(cwd, sizeof(cwd)) == NULL;
  }
  if (!strcmp(name, "environment_dependency") ||
      !strcmp(name, "unset_environment_dependency")) {
    const char *value = getenv("TRACEJIT_FIXTURE_VALUE");
    if (value != NULL) {
      volatile size_t observed_length = strlen(value);
      (void)observed_length;
    }
    return 0;
  }
  if (!strcmp(name, "locale_dependency")) {
    const char *locale = getenv("LC_ALL");
    if (locale == NULL) locale = getenv("LC_CTYPE");
    if (locale == NULL) locale = getenv("LANG");
    if (locale != NULL) {
      volatile size_t observed_length = strlen(locale);
      (void)observed_length;
    }
    return 0;
  }
  if (!strcmp(name, "timezone_dependency")) {
    const char *timezone = getenv("TZ");
    if (timezone != NULL) {
      volatile size_t observed_length = strlen(timezone);
      (void)observed_length;
      return 0;
    }
    int fd = open("/etc/localtime", O_RDONLY);
    if (fd < 0) return 1;
    unsigned char byte;
    ssize_t count = read(fd, &byte, sizeof(byte));
    close(fd);
    return count != 1;
  }
  if (!strcmp(name, "tempfile_creation")) {
    unsigned char random_byte;
    if (syscall(SYS_getrandom, &random_byte, sizeof(random_byte), 0) != 1)
      return 1;
    join_path(output, sizeof(output), root, "temporary-XXXXXX");
    int fd = mkstemp(output);
    if (fd >= 0) {
      ssize_t written = write(fd, "x", 1);
      close(fd);
      unlink(output);
      if (written != 1) return 1;
    }
    return fd < 0;
  }
  if (!strcmp(name, "fork_child") || !strcmp(name, "child_file_dependency")) {
    pid_t child = fork();
    if (child == 0) {
      int fd = open(input, O_RDONLY);
      if (fd >= 0) close(fd);
      _exit(fd >= 0 ? 0 : 1);
    }
    int status;
    waitpid(child, &status, 0);
    return !WIFEXITED(status) || WEXITSTATUS(status);
  }
  if (!strcmp(name, "clone_thread")) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, thread_noop, NULL) != 0) return 1;
    return pthread_join(thread, NULL) != 0;
  }
  if (!strcmp(name, "exec_child")) {
    execl("/proc/self/exe", "fixture-driver", "plain_file_read", root,
          (char *)NULL);
    return 93;
  }
  if (!strcmp(name, "interpreter_dependency")) {
    char interpreter[4096];
    join_path(interpreter, sizeof(interpreter), root, "fixture-interpreter");
    execl(interpreter, interpreter, "plain_file_read", root, (char *)NULL);
    return 94;
  }
  if (!strcmp(name, "script_dependency")) {
    char script[4096];
    join_path(script, sizeof(script), root, "fixture-script");
    execl(script, script, root, (char *)NULL);
    return 95;
  }
  if (!strcmp(name, "shared_file_write")) {
    int fd = open(output, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0) return 1;
    ssize_t written = write(fd, "x", 1);
    close(fd);
    return written != 1;
  }
  if (!strcmp(name, "write_then_read")) {
    int fd = open(output, O_RDWR | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    if (write(fd, "x", 1) != 1 || lseek(fd, 0, SEEK_SET) != 0) {
      close(fd);
      return 1;
    }
    unsigned char byte;
    ssize_t count = read(fd, &byte, sizeof(byte));
    close(fd);
    return count != 1;
  }
  if (!strcmp(name, "rename_output")) {
    int fd = open(output, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    close(fd);
    return rename(output, second);
  }
  if (!strcmp(name, "delete_output")) {
    int fd = open(output, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    close(fd);
    return unlink(output);
  }
  if (!strcmp(name, "access_check")) {
    /* Both probes steer control flow: one reports a file that must be absent, the other a file
       that must be readable. Neither writes, so only the recorded answers can invalidate it. */
    char probe[4096];
    join_path(probe, sizeof(probe), root, "probe-absent.txt");
    if (access(probe, F_OK) == 0) return 2;
    if (access(input, R_OK) != 0) return 3;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "faccessat_check")) {
    char probe[4096];
    join_path(probe, sizeof(probe), root, "probe-absent.txt");
    if (faccessat(AT_FDCWD, probe, F_OK, 0) == 0) return 2;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "pipe_roundtrip")) {
    /* One process writes one complete record into a pipe and reads it back after closing the
       write end. Every read either receives the whole request or reaches end-of-file, so the
       observed transfer does not depend on scheduling and reuse is permitted. */
    int fds[2];
    const char *payload = "tracejit\n";
    char buffer[64] = {0};
    ssize_t received;
    if (pipe(fds) != 0) return 1;
    if (write(fds[1], payload, 9) != 9) return 2;
    if (close(fds[1]) != 0) return 3;
    received = read(fds[0], buffer, sizeof(buffer));
    if (close(fds[0]) != 0) return 4;
    if (received != 9) return 5;
    if (write(STDOUT_FILENO, buffer, (size_t)received) != received) return 6;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "pipe_short_read")) {
    /* A read that is only partially satisfied while the writer still has data pending makes the
       reader's observations schedule dependent, so the classification must refuse it. The second
       pipe only orders the two events, which keeps the fixture itself deterministic: the child's
       read of 64 bytes cannot block, because one byte is already buffered. */
    int fds[2];
    int sync[2];
    pid_t child;
    char buffer[64] = {0};
    char token = 's';
    if (pipe(fds) != 0) return 1;
    if (pipe(sync) != 0) return 2;
    child = fork();
    if (child < 0) return 3;
    if (child == 0) {
      if (close(fds[1]) != 0) _exit(4);
      if (close(sync[0]) != 0) _exit(5);
      if (read(fds[0], buffer, sizeof(buffer)) != 1) _exit(6);
      if (write(sync[1], &token, 1) != 1) _exit(7);
      _exit(0);
    }
    if (close(fds[0]) != 0) return 8;
    if (close(sync[1]) != 0) return 9;
    if (write(fds[1], "a", 1) != 1) return 10;
    if (read(sync[0], &token, 1) != 1) return 11;
    if (write(fds[1], "b", 1) != 1) return 12;
    if (close(fds[1]) != 0) return 13;
    if (waitpid(child, NULL, 0) != child) return 14;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "nonzero_exit")) return 7;
  if (!strcmp(name, "stdout_only"))
    return write(STDOUT_FILENO, "stdout fixture\n", 15) != 15;
  if (!strcmp(name, "stderr_only"))
    return write(STDERR_FILENO, "stderr fixture\n", 15) != 15;
  if (!strcmp(name, "epoll_create_only")) {
    int fd = epoll_create1(EPOLL_CLOEXEC);
    if (fd < 0) return 1;
    if (close(fd) != 0) return 2;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "epoll_dup_close")) {
    int fd = epoll_create1(EPOLL_CLOEXEC);
    if (fd < 0) return 1;
    int duplicate = dup(fd);
    if (duplicate < 0) return 2;
    if (close(fd) != 0) return 3;
    if (close(duplicate) != 0) return 4;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "epoll_ctl_use")) {
    int fd = epoll_create1(EPOLL_CLOEXEC);
    if (fd < 0) return 1;
    int pipe_fds[2];
    if (pipe(pipe_fds) != 0) return 2;
    struct epoll_event event = {.events = EPOLLIN, .data.fd = pipe_fds[0]};
    int control = epoll_ctl(fd, EPOLL_CTL_ADD, pipe_fds[0], &event);
    if (close(pipe_fds[0]) != 0) return 3;
    if (close(pipe_fds[1]) != 0) return 4;
    if (close(fd) != 0) return 5;
    if (control != 0) return 6;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "dev_null_lseek")) {
    if (lseek(STDIN_FILENO, 0, SEEK_CUR) != 0) return 1;
    if (lseek(STDIN_FILENO, 7, SEEK_SET) != 0) return 2;
    if (lseek(STDIN_FILENO, 0, SEEK_END) != 0) return 3;
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "inherited_seek_probe")) {
    lseek(STDIN_FILENO, 0, SEEK_CUR);
    lseek(STDIN_FILENO, 7, SEEK_SET);
    lseek(STDIN_FILENO, 0, SEEK_END);
    copy_file(input, output);
    return 0;
  }
  if (!strcmp(name, "output_presence_stdout") ||
      !strcmp(name, "output_presence_stderr")) {
    /* The output's pre-state steers the bytes this program writes. A cache hit with a
       different pre-state is therefore a false hit, and a corrupted stream must be rejected
       before the recorded output is restored. */
    struct stat metadata;
    int present = stat(output, &metadata) == 0;
    int fd = open(output, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    const char *payload = present ? "PRESENT\n" : "ABSENT\n";
    size_t length = strlen(payload);
    if (write(fd, payload, length) != (ssize_t)length) {
      close(fd);
      return 2;
    }
    close(fd);
    if (!strcmp(name, "output_presence_stdout"))
      return write(STDOUT_FILENO, "stream fixture\n", 15) != 15;
    return write(STDERR_FILENO, "stream fixture\n", 15) != 15;
  }
  if (!strcmp(name, "file_mtime_changed")) {
    struct stat metadata;
    return stat(input, &metadata);
  }
  if (!strcmp(name, "symlink_target_changed")) {
    join_path(input, sizeof(input), root, "input-link");
  }
  if (!strcmp(name, "read_to_stdout")) {
    int fd = open(input, O_RDONLY);
    if (fd < 0) return 91;
    char buffer[4096];
    ssize_t count = read(fd, buffer, sizeof(buffer));
    close(fd);
    if (count < 0) return 92;
    return write(STDOUT_FILENO, buffer, (size_t)count) != count;
  }
  copy_file(input, output);
  return 0;
}
