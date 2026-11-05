"""Try the Venice AI patch modules in a throw-away copy of QuantiSheet
(nothing in the real app folder changes)."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "trial_output", "venice")
tmp = tempfile.mkdtemp(prefix="venice-")
try:
    shutil.copytree(os.path.join(ROOT, "app"), os.path.join(tmp, "app"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(tmp, "tests"))
    for f in os.listdir(os.path.join(SRC, "app")):
        shutil.copy(os.path.join(SRC, "app", f), os.path.join(tmp, "app", f))
    for f in os.listdir(os.path.join(SRC, "tests")):
        shutil.copy(os.path.join(SRC, "tests", f),
                    os.path.join(tmp, "tests", f))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p",
                        "no:cacheprovider", "tests", "--tb=line"]
                       + sys.argv[1:], cwd=tmp, env=env,
                       capture_output=True, text=True)
    print(r.stdout[-20000:])
    print(r.stderr[-3000:])
    # import every module too (catches errors in ones without tests)
    code = ("import importlib,sys;sys.path.insert(0,'.');"
            "mods=" + repr([f[:-3] for f in os.listdir(os.path.join(SRC, 'app'))
                             if f.endswith('.py')]) +
            "\nfor m in mods:\n try:\n  importlib.import_module('app.'+m)"
            "\n except Exception as e: print('IMPORT FAIL',m,repr(e))")
    r2 = subprocess.run([sys.executable, "-c", code], cwd=tmp, env=env,
                        capture_output=True, text=True)
    print(r2.stdout, r2.stderr[-2000:])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
