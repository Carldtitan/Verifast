import threading, time

counter = 0

def worker():
    global counter
    for _ in range(1000):
        tmp = counter        # read
        time.sleep(0)        # yield -> lets another thread run in the gap
        counter = tmp + 1    # write back (stale)

threads = [threading.Thread(target=worker) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()

expected = 8 * 1000
print(f"expected: {expected}")
print(f"actual:   {counter}")
print("RESULT:", "CORRECT" if counter == expected else "WRONG (race condition)")
