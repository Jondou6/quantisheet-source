"""Read-only check (Nov 5): does a second PDF open in the running
QuantiSheet, or start a second copy? Starts the INSTALLED QuantiSheet
with practice file A, waits, starts it again with file B, counts the
QuantiSheet processes, then closes only the processes it started.

    python tools/check_single_instance.py [seconds-between]
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                   "QuantiSheet", "QuantiSheet.exe")


def procs():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq QuantiSheet.exe",
                          "/FO", "CSV", "/NH"], capture_output=True,
                         text=True).stdout
    return [ln.split('","')[1] for ln in out.splitlines()
            if ln.startswith('"QuantiSheet.exe"')]


def sample(path, text):
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), text)
    d.save(path)
    d.close()
    return path


def main(argv):
    gap = float(argv[0]) if argv else 15
    if not os.path.isfile(EXE):
        print("no installed QuantiSheet at", EXE)
        return
    before = set(procs())
    print("QuantiSheet processes before:", len(before))
    tmp = os.path.join(os.environ.get("TEMP", ROOT), "qs-single-check")
    os.makedirs(tmp, exist_ok=True)
    a = sample(os.path.join(tmp, "check A.pdf"), "check A")
    b = sample(os.path.join(tmp, "check B.pdf"), "check B")
    p1 = subprocess.Popen([EXE, a])
    time.sleep(gap)
    mid = set(procs()) - before
    print("after opening A:", len(mid), "new process(es)")
    t = time.monotonic()
    p2 = subprocess.Popen([EXE, b])
    try:
        rc = p2.wait(timeout=60)
        print(f"second start exited with {rc} after "
              f"{time.monotonic() - t:.1f}s (0 = handed over)")
    except subprocess.TimeoutExpired:
        print("second start is STILL RUNNING after 60s: a second copy")
    time.sleep(3)
    after = set(procs()) - before
    print("after opening B:", len(after), "new process(es)")
    log = os.path.join(os.path.expanduser("~"), ".quantisheet",
                       "quantisheet.log")
    try:
        lines = open(log, encoding="utf-8", errors="replace").read() \
            .splitlines()[-40:]
        for ln in lines:
            if any(k in ln for k in ("starting", "handed", "single",
                                     "listen", "Error", "Traceback")):
                print("  log:", ln[:220])
    except OSError:
        pass
    for pid in after:                 # only what this check started
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       capture_output=True)
    print("closed", len(after), "process(es) this check started")


if __name__ == "__main__":
    main(sys.argv[1:])
