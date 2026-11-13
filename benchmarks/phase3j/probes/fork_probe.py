import os
import sys

pid = os.fork()
if pid == 0:
    os._exit(0)
_, status = os.waitpid(pid, 0)
print("fork", status)
sys.exit(0)
