"""Try QuantiSheet on PyMuPDF 2.x without touching the real environment.

    python tools/pymupdf2_trial.py setup          # make .venv-pm2 (once)
    python tools/pymupdf2_trial.py test [ARGS]    # pytest in .venv-pm2
    python tools/pymupdf2_trial.py run SCRIPT [ARGS]  # a script in .venv-pm2

`setup` copies the packages of the main .venv into a separate .venv-pm2
(pip download of everything else is avoided: only PyMuPDF 2.x is fetched)
and upgrades PyMuPDF there. `test` runs pytest with that interpreter; the
main .venv and the installed program are never changed. Delete the
.venv-pm2 folder to undo.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, ".venv")
VENV = os.path.join(ROOT, ".venv-pm2")
WIN = sys.platform.startswith("win")


def _py(venv):
    return os.path.join(venv, "Scripts" if WIN else "bin",
                        "python.exe" if WIN else "python")


def _run(cmd, timeout=840):
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    print((p.stdout or "")[-6000:])
    print((p.stderr or "")[-3000:])
    return p.returncode


def setup():
    base = _py(MAIN)
    if not os.path.exists(base):
        base = sys.executable
    if not os.path.exists(_py(VENV)):
        # --system-site-packages would mix the two; instead make a plain
        # venv and give it the main venv's site-packages via a .pth file,
        # after PyMuPDF 2 is installed into the new venv (found first)
        code = _run([base, "-m", "venv", VENV])
        if code:
            return code
    # PyMuPDF 2 first, into the bare venv, so pip never sees (or touches)
    # the main venv's packages
    code = _run([_py(VENV), "-m", "pip", "install", "--upgrade",
                 "pymupdf>=2,<3"])
    if code:
        return code
    site = subprocess.run(
        [base, "-c", "import sysconfig;print(sysconfig.get_paths()"
         "['purelib'])"], capture_output=True, text=True).stdout.strip()
    new_site = subprocess.run(
        [_py(VENV), "-c", "import sysconfig;print(sysconfig.get_paths()"
         "['purelib'])"], capture_output=True, text=True).stdout.strip()
    with open(os.path.join(new_site, "zz_main_venv.pth"), "w",
              encoding="utf-8") as f:
        f.write(site + "\n")
    _run([_py(VENV), "-c", "import fitz,sys;print('PyMuPDF',"
          "fitz.VersionBind, fitz.__file__)"])
    return code


def test(args):
    if not os.path.exists(_py(VENV)):
        print("run setup first")
        return 2
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    cmd = [_py(VENV), "-m", "pytest", "-q", "-p", "no:cacheprovider"] + \
        (args or ["-x"])
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=840)
    print((p.stdout or "")[-20000:])
    print((p.stderr or "")[-3000:])
    return p.returncode


def run(args):
    if not os.path.exists(_py(VENV)):
        print("run setup first")
        return 2
    if not args:
        print(__doc__)
        return 2
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    cmd = [_py(VENV)] + args
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=840)
    print((p.stdout or "")[-60000:])
    print((p.stderr or "")[-5000:])
    return p.returncode


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("setup", "test", "run"):
        print(__doc__)
        sys.exit(2)
    sys.exit({"setup": lambda r: setup(), "test": test, "run": run}[a[0]](
        a[1:]))
