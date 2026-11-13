import ctypes
import os
import sys

libc = ctypes.CDLL(None, use_errno=True)
SYS_getdents64 = 217
path = sys.argv[1]
fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
buffer = (ctypes.c_ubyte * 4096)()
buffer[:] = b"\xaa" * 4096
count = libc.syscall(SYS_getdents64, fd, ctypes.byref(buffer), 4096)
os.close(fd)
if count < 0:
    raise OSError(ctypes.get_errno(), "getdents64")
raw = bytes(buffer[:count])
offset = 0
paddings = []
while offset < len(raw):
    reclen = int.from_bytes(raw[offset + 16:offset + 18], "little")
    record = raw[offset:offset + reclen]
    name = record[19:].split(b"\0", 1)[0]
    padding = record[19 + len(name) + 1:]
    paddings.append(padding.hex())
    offset += reclen
print("padding", len(paddings), ",".join(paddings))
