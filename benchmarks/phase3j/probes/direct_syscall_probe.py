import ctypes

libc = ctypes.CDLL(None, use_errno=True)
SYS_getpid = 39
SYS_getppid = 110
SYS_gettid = 186
print(
    libc.syscall(SYS_getpid),
    libc.syscall(SYS_getppid),
    libc.syscall(SYS_gettid),
)
