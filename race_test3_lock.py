import threading, time

counter = 0
lock = threading.Lock()

def worker():
    global counter
    for _ in range(1000):
        with lock:               # only one thread in here at a time
            tmp = counter
            time.sleep(0)
            counter = tmp + 1

threads = [threading.Thread(target=worker) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()

expected = 8 * 1000
print(f"expected: {expected}")
print(f"actual:   {counter}")
print("RESULT:", "CORRECT" if counter == expected else "WRONG (race condition)")
