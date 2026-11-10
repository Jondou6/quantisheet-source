"""Run pytest in another copy of the source (Nov 5: was a crash at exit
there in 1.1.1 too?). Unzips ZIP into a temp folder (removed after).

    python tools/run_in.py ZIP pytest-args..."""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    z = sys.argv[1].strip('"')
    tmp = tempfile.mkdtemp(prefix="qs_runin_")
    try:
        zipfile.ZipFile(os.path.join(ROOT, z)).extractall(tmp)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p",
                            "no:cacheprovider"] + sys.argv[2:], cwd=tmp,
                           env=env, capture_output=True, text=True,
                           timeout=800)
        print(r.stdout[-3000:], r.stderr[-1500:])
        print("pytest exit code:", r.returncode)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
