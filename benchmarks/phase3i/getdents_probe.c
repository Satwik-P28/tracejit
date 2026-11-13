#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

/*
 * Read one getdents64 buffer with a caller-chosen fill byte, then print every
 * record's semantic fields separately from the bytes after the name NUL.
 *
 * The fill is the experiment: if getdents64 left the padding alone, the same
 * fields will be surrounded by 0xaa in one run and 0x55 in the next.
 */
int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <directory> <fill-byte-hex>\n", argv[0]);
        return 2;
    }
    char *end = NULL;
    unsigned long fill = strtoul(argv[2], &end, 16);
    if (end == argv[2] || *end != '\0' || fill > 0xff) {
        fprintf(stderr, "invalid fill byte: %s\n", argv[2]);
        return 2;
    }
    int fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    unsigned char buffer[32768];
    memset(buffer, (int)fill, sizeof(buffer));
    long count = syscall(SYS_getdents64, fd, buffer, sizeof(buffer));
    if (count < 0) {
        perror("getdents64");
        close(fd);
        return 1;
    }
    printf("path=%s fill=%02lx returned=%ld\n", argv[1], fill, count);
    long offset = 0;
    while (offset < count) {
        if (count - offset < 19) {
            fprintf(stderr, "truncated record at %ld\n", offset);
            close(fd);
            return 1;
        }
        unsigned char *record = buffer + offset;
        uint64_t ino;
        int64_t off;
        uint16_t reclen;
        memcpy(&ino, record, sizeof(ino));
        memcpy(&off, record + 8, sizeof(off));
        memcpy(&reclen, record + 16, sizeof(reclen));
        if (reclen < 20 || offset + reclen > count) {
            fprintf(stderr, "invalid reclen %u at %ld\n", reclen, offset);
            close(fd);
            return 1;
        }
        unsigned char type = record[18];
        unsigned char *name = record + 19;
        size_t name_capacity = (size_t)reclen - 19;
        size_t name_len = strnlen((char *)name, name_capacity);
        if (name_len == name_capacity) {
            fprintf(stderr, "unterminated name at %ld\n", offset);
            close(fd);
            return 1;
        }
        printf("record ino=%llu off=%lld reclen=%u type=%u name=",
               (unsigned long long)ino, (long long)off, reclen, type);
        for (size_t i = 0; i < name_len; i++) {
            printf("%02x", name[i]);
        }
        printf(" padding=");
        for (size_t i = 19 + name_len + 1; i < reclen; i++) {
            printf("%02x", record[i]);
        }
        printf("\n");
        offset += reclen;
    }
    close(fd);
    return 0;
}
