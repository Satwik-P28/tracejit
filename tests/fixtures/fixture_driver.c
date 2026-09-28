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
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysinfo.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
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
  if (argc != 3) {
    return 89;
  }
  const char *name = argv[1];
  const char *root = argv[2];
  char input[4096], output[4096], second[4096];
  join_path(input, sizeof(input), root, "input.txt");
  join_path(output, sizeof(output), root, "output.txt");
  join_path(second, sizeof(second), root, "second.txt");

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
  if (!strcmp(name, "unknown_ioctl")) {
    int pair[2], available = 0;
    if (pipe(pair) != 0) return 1;
    int result = ioctl(pair[0], FIONREAD, &available);
    close(pair[0]);
    close(pair[1]);
    return result < 0;
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
      FILE *file = fopen(input, "rb");
      if (file) fclose(file);
      _exit(file ? 0 : 1);
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
    execl("/bin/cat", "cat", input, (char *)NULL);
    return 93;
  }
  if (!strcmp(name, "interpreter_dependency")) {
    execl("/bin/sh", "sh", "-c", "cat \"$1\"", "tracejit", input,
          (char *)NULL);
    return 94;
  }
  if (!strcmp(name, "script_dependency")) {
    char script[4096];
    join_path(script, sizeof(script), root, "fixture-script.sh");
    execl("/bin/sh", "sh", script, root, (char *)NULL);
    return 95;
  }
  if (!strcmp(name, "shared_file_write")) {
    FILE *file = fopen(output, "ab");
    if (!file) return 1;
    fwrite("x", 1, 1, file);
    fclose(file);
    return 0;
  }
  if (!strcmp(name, "write_then_read")) {
    FILE *file = fopen(output, "wb+");
    if (!file) return 1;
    fwrite("x", 1, 1, file);
    rewind(file);
    (void)fgetc(file);
    fclose(file);
    return 0;
  }
  if (!strcmp(name, "rename_output")) {
    FILE *file = fopen(output, "wb");
    if (!file) return 1;
    fclose(file);
    return rename(output, second);
  }
  if (!strcmp(name, "delete_output")) {
    FILE *file = fopen(output, "wb");
    if (!file) return 1;
    fclose(file);
    return unlink(output);
  }
  if (!strcmp(name, "nonzero_exit")) return 7;
  if (!strcmp(name, "stdout_only")) return fputs("stdout fixture\n", stdout) < 0;
  if (!strcmp(name, "stderr_only")) return fputs("stderr fixture\n", stderr) < 0;
  if (!strcmp(name, "file_mtime_changed")) {
    struct stat metadata;
    return stat(input, &metadata);
  }
  if (!strcmp(name, "symlink_target_changed")) {
    join_path(input, sizeof(input), root, "input-link");
  }
  copy_file(input, output);
  return 0;
}
