import os
import signal

seen = []
def handler(signum, frame):
    seen.append(signum)

signal.signal(signal.SIGUSR1, handler)
os.kill(os.getpid(), signal.SIGUSR1)
print("signal", seen)
