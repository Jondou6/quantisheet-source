"""Performance targets, checked (0.12.24).

    python tools/perf_gate.py            measure and compare with the budgets
    python tools/perf_gate.py --record   measure and write new budgets
    python tools/perf_gate.py start [--record]   the same in the background
                                     (output: .run/perf_gate.log)

Runs, each in its own fresh process:
  * tools/bigset.py 500   - a 500-sheet vector set: open, previews, deep
                            zoom, search, sheet numbers, the app opening it,
                            page flips, zoom and pan;
  * tools/perf.py 120     - the window driven like an estimator: markups,
                            takeoff, ribbons, save;
  * tools/scanset.py 40   - a 40-sheet set of 200 dpi scans.
All synthetic; never anyone's real drawings.

Budgets live in tools/perf_budgets.json: each is the time a step may take
on this kind of PC. --record sets each budget to twice the measured time
(at least +50 ms) so normal noise passes and a real slow-down fails. The
measured numbers go to .run/perf_last.json. Exit 1 when a step is over.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGETS = os.path.join(ROOT, "tools", "perf_budgets.json")
LAST = os.path.join(ROOT, ".run", "perf_last.json")
RUNS = [("bigset", ["500"]), ("perf", ["120"]), ("scanset", ["40"])]
# one-off set-up steps, not something a user waits for in the app
SKIP = ("build ",)


def measure():
    out = {}
    for tool, args in RUNS:
        fd, js = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        t = time.time()
        p = subprocess.run([sys.executable,
                            os.path.join(ROOT, "tools", tool + ".py"),
                            *args, "--json", js], cwd=ROOT,
                           capture_output=True, text=True, timeout=3000,
                           env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        if p.returncode != 0:
            raise RuntimeError(f"{tool} failed:\n{(p.stdout + p.stderr)[-3000:]}")
        with open(js, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not k.startswith(SKIP):
                    out[f"{tool}: {k}"] = v
        os.remove(js)
        print(f"{tool} done in {time.time() - t:.0f}s", flush=True)
    return out


def compare(measured, budgets):
    """[(step, seconds, budget, over?)]; steps without a budget are
    listed, never failed."""
    rows = []
    for k, v in sorted(measured.items()):
        b = budgets.get(k)
        rows.append((k, v, b, b is not None and v > b))
    return rows


def record(measured):
    return {k: round(max(v * 2.0, v + 0.05), 3) for k, v in measured.items()}


def start(argv):
    log = os.path.join(ROOT, ".run", "perf_gate.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(log, "w", encoding="utf-8") as f:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), *argv],
                         cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags)
    print("started; output in", log)
    return 0


def main(argv):
    if argv[:1] == ["start"]:
        return start(argv[1:])
    measured = measure()
    os.makedirs(os.path.dirname(LAST), exist_ok=True)
    with open(LAST, "w", encoding="utf-8") as f:
        json.dump(measured, f, indent=1)
    if "--record" in argv:
        with open(BUDGETS, "w", encoding="utf-8") as f:
            json.dump(record(measured), f, indent=1, sort_keys=True)
        print(f"budgets written: {BUDGETS}")
    try:
        with open(BUDGETS, encoding="utf-8") as f:
            budgets = json.load(f)
    except OSError:
        budgets = {}
    rows = compare(measured, budgets)
    over = [r for r in rows if r[3]]
    for k, v, b, bad in rows:
        print(f"{'OVER ' if bad else '     '}{k:<64} {v * 1000:8.0f} ms"
              + (f"  (budget {b * 1000:.0f})" if b else "  (no budget)"))
    print(f"\n{len(rows)} steps, {len(over)} over budget")
    print("PERF GATE", "FAILED" if over else "PASSED", flush=True)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
