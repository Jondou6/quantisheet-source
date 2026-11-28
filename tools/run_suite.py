"""The whole test suite on several cores at once (Nov 25 optimization list:
"Faster full test run" - 60 minutes one chunk after another).

    python tools/run_suite.py [workers] [--only tests/test_a.py ...]
    python tools/run_suite.py start [workers]   in the background (the
                                   PC runner stops a request at 15 min)
    python tools/run_suite.py status            its result when done

The test files (tests\\, quantisheet_backoffice\\tests and
quantisheet_claims\\tests) are shared out among `workers` pytest
processes (default: cores - 1, at most 6), the slowest files first, by
the times the last run took (.run\\suite_times.json). Each process has
its own temporary folder and QuantiSheet settings, as every test already
does. Prints one summary, the failures, and the slowest files; exit 1 if
anything failed."""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMES = os.path.join(ROOT, ".run", "suite_times.json")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
GROUPS = [("tests", "tests/test_*.py"),
          ("quantisheet_backoffice", "quantisheet_backoffice/tests/test_*.py"),
          ("quantisheet_claims", "quantisheet_claims/tests/test_*.py")]
SUMMARY = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")


def files():
    out = []
    for _g, pat in GROUPS:
        out += sorted(p.replace("\\", "/") for p in
                      glob.glob(os.path.join(ROOT, pat)))
    return [os.path.relpath(p, ROOT).replace("\\", "/") for p in out]


def load_times():
    try:
        with open(TIMES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def share(names, workers, times):
    """Longest first onto the least-loaded worker. Files in one package
    stay in that package's processes (their conftest differs)."""
    guess = sorted(times.values())[len(times) // 2] if times else 5.0
    buckets = [[] for _ in range(workers)]
    load = [0.0] * workers
    for n in sorted(names, key=lambda n: -times.get(n, guess)):
        i = load.index(min(load))
        buckets[i].append(n)
        load[i] += times.get(n, guess)
    return [b for b in buckets if b], load


def _pkg(name):
    for g, _pat in GROUPS:
        if name.startswith(g + "/"):
            return g
    return "tests"


DONE = re.compile(r"^(=+ )?.*\b(passed|failed|errors?|no tests ran)\b.* in "
                  r"[\d.]+s", re.M)
LIMIT_S = 40 * 60


def _wait_all(procs):
    """Wait for every pytest. One that has printed its last line but
    doesn't exit (a thread a test left running) is stopped after 30 s;
    one that says nothing for LIMIT_S is stopped too."""
    done_at = {}
    t0 = time.time()
    tried = set()

    def waiting(p):
        # finished, or it printed its result 45 s ago (the result is in
        # its output either way - don't wait on a kill that may not work)
        return p.poll() is None and not (
            p.pid in done_at and time.time() - done_at[p.pid] > 45)
    while any(waiting(p) for p, *_ in procs):
        time.sleep(2)
        for p, _log, tmp, _batch, _st in procs:
            if p.poll() is not None:
                continue
            out = os.path.join(tmp, "out.txt")
            try:
                with open(out, "rb") as f:
                    f.seek(max(0, os.path.getsize(out) - 400))
                    tail = f.read().decode("utf-8", "replace")
            except OSError:
                tail = ""
            # anywhere in the tail: a process that won't exit may print
            # more after its result line
            if DONE.search(tail):
                done_at.setdefault(p.pid, time.time())
            if p.pid in tried:
                continue
            if (p.pid in done_at and time.time() - done_at[p.pid] > 30) or \
                    time.time() - t0 > LIMIT_S:
                tried.add(p.pid)
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               capture_output=True,
                               creationflags=getattr(
                                   subprocess, "CREATE_NO_WINDOW", 0)) \
                    if sys.platform.startswith("win") else p.kill()
                if p.pid in done_at:
                    p.returncode_override = True


def run(names, workers):
    times = load_times()
    jobs = []
    for g in {_pkg(n) for n in names}:
        mine = [n for n in names if _pkg(n) == g]
        w = max(1, round(workers * len(mine) / len(names)))
        for b in share(mine, w, times)[0]:
            jobs.append(b)
    procs = []
    t0 = time.time()
    for k, batch in enumerate(jobs):
        tmp = tempfile.mkdtemp(prefix=f"qs_suite{k}_")
        report = os.path.join(tmp, "durations.txt")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   TMP=tmp, TEMP=tmp, QS_SUITE_REPORT=report)
        cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--durations=0", "--durations-min=0.5", "-rfE",
               f"--basetemp={os.path.join(tmp, 'pt')}"] + batch
        log = open(os.path.join(tmp, "out.txt"), "w", encoding="utf-8",
                   errors="replace")
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log,
                             stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
        procs.append((p, log, tmp, batch, time.time()))
    total = {}
    fails = []
    new_times = dict(times)
    _wait_all(procs)
    for p, log, tmp, batch, started in procs:
        log.close()
        with open(os.path.join(tmp, "out.txt"), encoding="utf-8",
                  errors="replace") as f:
            text = f.read()
        done = [ln for ln in text.splitlines() if DONE.search(ln)]
        tail = done[-1:] or text.strip().splitlines()[-1:] or [""]
        for n, kind in SUMMARY.findall(tail[0]):
            kind = "errors" if kind.startswith("error") else kind
            total[kind] = total.get(kind, 0) + int(n)
        fails += [ln for ln in text.splitlines()
                  if ln.startswith(("FAILED ", "ERROR "))]
        if p.returncode not in (0, 1, 5) and \
                not getattr(p, "returncode_override", False):
            fails.append(f"pytest exit {p.returncode} for {batch[0]} ...: "
                         + tail[0])
        # per-file time: the test durations pytest printed, summed
        per = {}
        for m in re.finditer(r"^\s*([\d.]+)s (?:call|setup|teardown)\s+"
                             r"(\S+?)::", text, re.M):
            per[m.group(2)] = per.get(m.group(2), 0.0) + float(m.group(1))
        for n in batch:
            new_times[n] = round(per.get(n, 0.2), 1)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    wall = time.time() - t0
    try:
        with open(TIMES, "w") as f:
            json.dump(new_times, f, indent=0, sort_keys=True)
    except OSError:
        pass
    print(f"{len(names)} test files in {len(jobs)} processes: "
          + ", ".join(f"{v} {k}" for k, v in sorted(total.items()))
          + f" in {wall / 60:.1f} min")
    for ln in fails:
        print(ln)
    slow = sorted(((v, k) for k, v in new_times.items() if k in names),
                  reverse=True)[:8]
    print("slowest files:", "; ".join(f"{k} {v:.0f}s" for v, k in slow))
    return 1 if fails or total.get("failed") or total.get("errors") else 0


OUT = os.path.join(ROOT, ".run", "run_suite.out")


STARTED = OUT + ".started"


def start(argv):
    with open(OUT, "w") as f:
        f.write("running since " + time.strftime("%H:%M:%S") + "\n")
    with open(STARTED, "w") as f:
        f.write(str(time.time()))
    flags = 0
    for f_ in ("CREATE_NO_WINDOW", "DETACHED_PROCESS",
               "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, f_, 0)
    log = open(OUT + ".tmp", "w")
    subprocess.Popen([sys.executable, os.path.abspath(__file__)] + argv,
                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, creationflags=flags,
                     close_fds=True, env=dict(os.environ,
                                              QS_SUITE_OUT=OUT))
    print("started; check with: tool run_suite status")
    return 0


def workers_now(since, tmp=None):
    """What each pytest process of the run started at `since` has said so
    far: [(folder name, its result line or None, FAILED/ERROR lines)].
    For when the run's own summary never arrives (Nov 25: a finished
    worker that doesn't exit left run_suite waiting)."""
    tmp = tmp or tempfile.gettempdir()
    out = []
    for d in sorted(glob.glob(os.path.join(tmp, "qs_suite*_*"))):
        log = os.path.join(d, "out.txt")
        try:
            if os.path.getctime(d) < since - 5:
                continue
            with open(log, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        done = [ln for ln in text.splitlines() if DONE.search(ln)]
        fails = [ln for ln in text.splitlines()
                 if ln.startswith(("FAILED ", "ERROR "))]
        out.append((os.path.basename(d), done[-1] if done else None, fails))
    return out


def status():
    try:
        with open(OUT, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        print("not started")
        return 0
    print(text)
    if "[done, exit" in text:
        return 0
    try:
        with open(STARTED) as f:
            since = float(f.read())
    except (OSError, ValueError):
        return 0
    rows = workers_now(since)
    total = {}
    for name, done, fails in rows:
        print(f"{name}: {done.strip('= ') if done else 'still running'}")
        for ln in fails:
            print("   ", ln)
        for n, kind in SUMMARY.findall(done or ""):
            kind = "errors" if kind.startswith("error") else kind
            total[kind] = total.get(kind, 0) + int(n)
    left = sum(1 for _n, done, _f in rows if not done)
    print(f"so far, after {(time.time() - since) / 60:.0f} min:",
          ", ".join(f"{v} {k}" for k, v in sorted(total.items())) or "-",
          f"| {left} of {len(rows)} processes still running"
          if left else "| every process has finished")
    return 0


def main(argv):
    if argv[:1] == ["start"]:
        return start(argv[1:])
    if argv[:1] == ["status"]:
        return status()
    workers = int(argv[0]) if argv and argv[0].isdigit() else \
        max(1, min(6, (os.cpu_count() or 2) - 1))
    names = files()
    if "--only" in argv:
        names = argv[argv.index("--only") + 1:]
    return run(names, workers)


if __name__ == "__main__":
    code = main(sys.argv[1:])
    if os.environ.get("QS_SUITE_OUT"):       # started in the background
        sys.stdout.flush()
        try:
            shutil_ = __import__("shutil")
            shutil_.copyfile(os.environ["QS_SUITE_OUT"] + ".tmp",
                             os.environ["QS_SUITE_OUT"])
            with open(os.environ["QS_SUITE_OUT"], "a") as f:
                f.write(f"[done, exit {code}]\n")
        except OSError:
            pass
    sys.exit(code)
