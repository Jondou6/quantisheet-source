"""Time real launches of QuantiSheet: the installed program (or the
source with --source) starts, shows its window, writes its step times and
quits. Run twice: the first launch after a reboot or an update is the slow
one (Windows checks every file), the second is the everyday one.

    python tools/time_launch.py [--source] [runs]
"""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    runs = next((int(a) for a in argv if a.isdigit()), 2)
    if "--source" in argv:
        cmd = [sys.executable, os.path.join(ROOT, "quantisheet.py")]
        cwd = ROOT
    else:
        sys.path.insert(0, ROOT)
        from app import branding
        exe = branding.installed_exe()
        if not os.path.isfile(exe):
            raise SystemExit(f"not installed: {exe}")
        cmd, cwd = [exe], os.path.dirname(exe)
    for i in range(runs):
        out = os.path.join(tempfile.mkdtemp(), "timing.json")
        env = dict(os.environ, QUANTISHEET_TIMING=out)
        t = time.perf_counter()
        p = subprocess.run(cmd, cwd=cwd, env=env, timeout=300)
        wall = time.perf_counter() - t
        marks = []
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as f:
                marks = json.load(f)
        shown = next((s for n, s in marks if n == "window shown"), None)
        print(f"launch {i + 1}: exit {p.returncode}, {wall:.1f}s until it "
              f"quit; inside the program: " +
              ", ".join(f"{n} {s}s" for n, s in marks), flush=True)
        if shown is not None:
            print(f"   before Python started (unpacking, virus scan): "
                  f"~{max(0.0, wall - shown - 0.3):.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
