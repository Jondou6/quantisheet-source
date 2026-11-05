"""Try a change on a COPY of this folder, never the live one.

    python tools/trial_copy.py prepare NAME   copy to ~/quantisheet-NAME and lay
                                              .run/trial_overlay/NAME/* over it
    python tools/trial_copy.py full NAME      the whole suite in the copy:
                                              summary line, exit code, and any
                                              new "Application Error" (1000)
                                              for python.exe since it started
"""
import datetime
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dst(name):
    return os.path.join(os.path.expanduser("~"), "quantisheet-" + name)


def prepare(name):
    d = dst(name)
    if os.path.isdir(d):
        shutil.rmtree(d)                    # only ever the trial copy
    r = subprocess.run(["robocopy", ROOT, d, "/E", "/NFL", "/NDL", "/NJH",
                        "/NJS", "/R:1", "/W:1", "/XD", ".venv", ".run",
                        "release", "build", "dist", "__pycache__",
                        ".pytest_cache", "trial_output",
                        "sample.pdf.versions"], capture_output=True,
                       text=True)
    if r.returncode >= 8:
        raise SystemExit("copy failed: " + r.stdout[-500:])
    ov = os.path.join(ROOT, ".run", "trial_overlay", name)
    n = 0
    for base, _dirs, files in os.walk(ov):
        for f in files:
            src = os.path.join(base, f)
            rel = os.path.relpath(src, ov)
            out = os.path.join(d, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copyfile(src, out)
            print("overlay:", rel)
            n += 1
    print("trial copy:", d, "-", n, "file(s) changed")


def app_errors(since):
    ps = ("Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; "
          f"StartTime=[datetime]'{since:%Y-%m-%dT%H:%M:%S}'}} "
          "-ErrorAction SilentlyContinue | Where-Object { $_.Message -match "
          "'python' } | ForEach-Object { $_.TimeCreated.ToString('s') + ' ' "
          "+ ($_.Message -split \"`n\")[0] + ' | ' + (($_.Message -split "
          "\"`n\") | Select-String 'Exception code|Faulting module name' | "
          "ForEach-Object { $_.Line.Trim() }) -join '; ' }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=120)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def full(name):
    d = dst(name)
    start = datetime.datetime.now()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUNBUFFERED="1")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p",
                        "no:cacheprovider", "-o", "faulthandler_timeout=60"],
                       cwd=d, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=870)
    lines = p.stdout.splitlines()
    for ln in [x for x in lines if x.startswith(("FAILED", "ERROR"))][:40]:
        print(ln)
    summary = [ln for ln in lines if re.search(r"\d+ (passed|failed)", ln)]
    print(summary[-1] if summary else "no pytest summary line")
    rc = p.returncode & 0xFFFFFFFF
    print(f"pytest exit code {rc} (0x{rc:08X})")
    errs = app_errors(start)
    print(f"Application Error 1000 for python since {start:%H:%M:%S}:",
          len(errs))
    for e in errs:
        print("  ", e)
    with open(os.path.join(d, f"trial-full-{start:%H%M%S}.txt"), "w",
              encoding="utf-8") as f:
        f.write(p.stdout + "\n----- stderr -----\n" + p.stderr)
    return 0 if rc == 0 and not errs else 1


if __name__ == "__main__":
    what, name = sys.argv[1], sys.argv[2]
    sys.exit(prepare(name) if what == "prepare" else full(name))
