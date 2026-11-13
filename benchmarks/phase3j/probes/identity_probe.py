import ctypes
import os
import threading

libc = ctypes.CDLL(None)
print(os.getpid(), os.getppid(), threading.get_native_id(), libc.getpid())
