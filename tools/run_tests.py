"""Run the whole test suite and write test-results.txt (like run-tests.bat):
python tools/run_tests.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
out = os.path.join(ROOT, "test-results.txt")
with open(out, "w", encoding="utf-8") as f:
    code = subprocess.call([sys.executable, "-m", "pytest", "-q", "-p",
                            "no:cacheprovider"], cwd=ROOT, env=env,
                           stdout=f, stderr=subprocess.STDOUT)
with open(out, encoding="utf-8", errors="replace") as f:
    print(f.read()[-3000:])
sys.exit(code)
