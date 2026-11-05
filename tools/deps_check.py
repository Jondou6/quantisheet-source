"""Report which programs QuantiSheet uses are installed (changes nothing)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ps1 = os.path.join(ROOT, "tools", "install_deps.ps1")
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", ps1, "-DetectOnly"] + sys.argv[1:],
                   capture_output=True, text=True)
print(r.stdout)
print(r.stderr)
print("exit", r.returncode)
