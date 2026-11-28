"""Replace the running test runner with a fresh copy of tools/runner.py
(for a runner started before it could restart itself). Run through the
runner: `tool runner_restart`. The new runner waits a few seconds, so
this request finishes and leaves the old runner's process tree first,
then its _stop_old ends the old runner."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(w):
        exe = w
    flags = 0
    for f in ("CREATE_NO_WINDOW", "DETACHED_PROCESS",
              "CREATE_NEW_PROCESS_GROUP", "CREATE_BREAKAWAY_FROM_JOB"):
        flags |= getattr(subprocess, f, 0)
    try:
        p = subprocess.Popen([exe, os.path.join(ROOT, "tools", "runner.py"),
                              "--after", "20"], cwd=ROOT,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags,
                             close_fds=True)
    except OSError:                      # a job that forbids breakaway
        flags &= ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        p = subprocess.Popen([exe, os.path.join(ROOT, "tools", "runner.py"),
                              "--after", "20"], cwd=ROOT,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags,
                             close_fds=True)
    print("new runner started, pid", p.pid, "- it takes over in 20 s")
