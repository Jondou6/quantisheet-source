"""Where a background run_suite is: the tail of each worker's output.
python tools/diag_suite.py [kill]"""
import glob
import os
import subprocess
import sys
import tempfile
import time

for d in sorted(glob.glob(os.path.join(tempfile.gettempdir(), "qs_suite*"))):
    out = os.path.join(d, "out.txt")
    if not os.path.isfile(out):
        continue
    age = time.time() - os.path.getmtime(out)
    with open(out, encoding="utf-8", errors="replace") as f:
        text = f.read()
    print(f"== {os.path.basename(d)} last output {age:.0f}s ago, "
          f"{len(text)} chars")
    print("   " + text[-300:].replace("\n", "\n   "))
if sys.argv[1:2] == ["kill"]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
         "-match 'qs_suite|run_suite' } | ForEach-Object { Stop-Process "
         "-Id $_.ProcessId -Force; $_.ProcessId }"],
        capture_output=True, text=True)
    print("stopped:", r.stdout.split())
