"""Run the tests one file at a time, each with a time limit, so a test that
hangs is named (with where it hung) instead of stalling the whole run.

    python tools/testfiles.py [PATTERN] [--limit SECONDS]
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    limit = 240
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    skip = {argv.index("--limit") + 1} if "--limit" in argv else set()
    pats = [a for i, a in enumerate(argv)
            if not a.startswith("--") and i not in skip]
    files = sorted(glob.glob(os.path.join(ROOT, "tests",
                                          (pats[0] if pats else "test_*")
                                          + ("" if pats and pats[0]
                                             .endswith(".py") else ".py"))))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    total_fail = 0
    for f in files:
        name = os.path.basename(f)
        t = time.time()
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "-o", f"faulthandler_timeout={max(30, limit - 20)}", f]
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        try:
            out, _ = p.communicate(timeout=limit)
            last = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
            ok = p.returncode == 0
            print(f"{'ok  ' if ok else 'FAIL'} {name:32} {time.time() - t:6.1f}s"
                  f"  {last[0] if last else ''}")
            if not ok:
                total_fail += 1
                print(out[-6000:])
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
            total_fail += 1
            print(f"HANG {name:32} > {limit}s")
            print(out[-8000:])
        sys.stdout.flush()
    print(f"\n{len(files)} files, {total_fail} with problems")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
