"""Run AI Takeoff on a PDF outside the window, logging time and memory per
step to .run/ai_takeoff_run.log:  python tools/ai_takeoff_run.py FILE.pdf
[--start] (--start runs it in the background)"""
import faulthandler
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LOG = os.path.join(ROOT, ".run", "ai_takeoff_run.log")


def rss_mb():
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c),
            c.cb)
        return c.WorkingSetSize / 1e6, c.PeakWorkingSetSize / 1e6
    except Exception:
        return 0, 0


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        m, pk = rss_mb()
        f.write(f"{time.strftime('%H:%M:%S')} [{m:.0f} MB, peak {pk:.0f}] "
                + " ".join(str(x) for x in a) + "\n")


def main(path):
    open(LOG, "w").close()
    fh = open(LOG + ".fault", "w")
    faulthandler.enable(fh)
    import fitz
    from app import aitakeoff as ait
    doc = fitz.open(path)
    log("opened", path, doc.page_count, "pages, repaired:",
        getattr(doc, "is_repaired", "?"))
    t = time.time()

    def p1(i, n):
        if i % 5 == 0:
            log(f"reading sheet {i + 1}/{n}")
        return True
    rows = ait.plan_set(doc, p1)
    log(f"read the set in {time.time() - t:.1f}s")
    for r in rows:
        log("  ", r["page"] + 1, r["number"], "|", r["title"][:40], "|",
            r["discipline"], r["kind"], r["scale"] and r["scale"][0],
            r["engines"], r["note"])
    t = time.time()
    last = [time.time()]

    def p2(k, n, text):
        now = time.time()
        log(f"step {k}/{n} ({now - last[0]:.1f}s since last): {text}")
        last[0] = now
        return True
    res = ait.run(doc, rows, p2)
    log(f"ran in {time.time() - t:.1f}s: {len(res['marks'])} marks")
    log(ait.summary_text(rows, res))


if __name__ == "__main__":
    if "--start" in sys.argv:
        args = [a.strip("\"") for a in sys.argv[1:] if a != "--start"]
        subprocess.Popen([sys.executable, os.path.abspath(__file__)] + args,
                         cwd=ROOT, creationflags=getattr(
                             subprocess, "CREATE_NO_WINDOW", 0),
                         stdout=subprocess.DEVNULL, stderr=open(
                             LOG + ".err", "w"))
        print("started")
    else:
        try:
            main(sys.argv[1].strip("\""))
        except Exception:
            import traceback
            log("FAILED", traceback.format_exc())
            raise
