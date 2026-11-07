/* Parallel vfork/exec storm. The kernel may report a vfork child's first stop before the parent's
 * PTRACE_EVENT_VFORK; that ordering becomes common when several processes are forking at once, and
 * is what makes `make -j4` fail if the tracer requires the event to arrive first. */
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

struct worker {
    const char *program;
    long count;
    long index;
};

static void *storm(void *argument) {
    const struct worker *worker = argument;
    // `vfork` makes GCC treat locals as potentially clobbered.
    for (volatile long index = 0; index < worker->count; index++) {
        pid_t pid = vfork();
        if (pid < 0) {
            perror("vfork");
            return (void *)1;
        }
        if (pid == 0) {
            execl(worker->program, worker->program, (char *)NULL);
            _exit(127);
        }
        int status = 0;
        while (waitpid(pid, &status, 0) < 0) {
            if (errno != EINTR) {
                perror("waitpid");
                return (void *)1;
            }
        }
        if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
            fprintf(stderr, "worker %ld child %ld failed\n", worker->index, (long)index);
            return (void *)1;
        }
    }
    return NULL;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s PROGRAM COUNT THREADS\n", argv[0]);
        return 2;
    }
    long count = strtol(argv[2], NULL, 10);
    long threads = strtol(argv[3], NULL, 10);
    if (count < 1 || threads < 1 || threads > 64) {
        fprintf(stderr, "invalid COUNT or THREADS\n");
        return 2;
    }
    pthread_t *handles = calloc((size_t)threads, sizeof *handles);
    struct worker *workers = calloc((size_t)threads, sizeof *workers);
    if (handles == NULL || workers == NULL) {
        return 1;
    }
    for (long index = 0; index < threads; index++) {
        workers[index] = (struct worker){argv[1], count, index};
        if (pthread_create(&handles[index], NULL, storm, &workers[index]) != 0) {
            perror("pthread_create");
            return 1;
        }
    }
    int failed = 0;
    for (long index = 0; index < threads; index++) {
        void *result = NULL;
        pthread_join(handles[index], &result);
        failed |= result != NULL;
    }
    free(handles);
    free(workers);
    if (failed) {
        return 1;
    }
    printf("spawned %ld children across %ld workers\n", count * threads, threads);
    return 0;
}
