"""Install/upgrade QuantiSheet's Python packages (requirements.txt) into
the environment running this script: python tools/pip_install.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
req = os.path.join(ROOT, "requirements.txt")
cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
       "-r", req] + sys.argv[1:]
print(" ".join(cmd), flush=True)
sys.exit(subprocess.call(cmd))
