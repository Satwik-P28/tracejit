import ctypes
import time


class Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


libc = ctypes.CDLL(None, use_errno=True)
value = Timeval()
result = libc.gettimeofday(ctypes.byref(value), None)
print(result, value.tv_sec, value.tv_usec, time.time())
