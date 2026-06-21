import threading

counter = 0

def worker():
    global counter
    for _ in range(1_000_000):
        counter += 1   # NOT atomic: load, add, store -> race window

threads = [threading.Thread(target=worker) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()

expected = 8 * 1_000_000
print(f"expected: {expected}")
print(f"actual:   {counter}")
print("RESULT:", "CORRECT" if counter == expected else "WRONG (race condition)")
