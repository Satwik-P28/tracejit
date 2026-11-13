import threading

values = []
def worker():
    values.append(threading.get_native_id())

thread = threading.Thread(target=worker)
thread.start()
thread.join()
print("thread", len(values), values[0] if values else 0)
