"""Is matchTemplate faster in threads on this PC? (made-up picture)"""
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np


def main():
    rng = np.random.default_rng(1)
    g = (rng.random((3456, 5184)) * 255).astype(np.uint8)
    ts = [(rng.random((44, 44)) * 255).astype(np.uint8) for _ in range(8)]
    print("cv2 threads", cv2.getNumThreads(), "cpus", cv2.getNumberOfCPUs())
    t = time.perf_counter()
    for tp in ts:
        cv2.matchTemplate(g, tp, cv2.TM_CCOEFF_NORMED)
    a = time.perf_counter() - t
    t = time.perf_counter()
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda tp: cv2.matchTemplate(g, tp,
                                                 cv2.TM_CCOEFF_NORMED), ts))
    b = time.perf_counter() - t
    print(f"8 matches: one after another {a:.2f} s, 4 threads {b:.2f} s")


if __name__ == "__main__":
    main()
