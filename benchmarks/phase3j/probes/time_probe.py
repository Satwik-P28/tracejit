import time

m0 = time.monotonic_ns()
t0 = time.time_ns()
count = 0
while count < 1000:
    if time.monotonic_ns() >= m0 + 1_000_000:
        break
    count += 1
print(m0, t0, count, time.monotonic_ns() - m0)
