"""Build an MSI from the last program build and check it (no install):

    python tools/msi_trial.py

Uses %LOCALAPPDATA%\\QuantiSheetBuild\\dist\\QuantiSheet (made by
build_installer) and writes .run\\msitrial\\QuantiSheet-trial.msi.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def main():
    import check_msi
    import make_msi
    from app import __version__
    app_dir = os.path.join(os.environ["LOCALAPPDATA"], "QuantiSheetBuild",
                           "dist", "QuantiSheet")
    out = os.path.join(ROOT, ".run", "msitrial", "QuantiSheet-trial.msi")
    t = time.time()
    path, code, n = make_msi.build(app_dir, out, __version__)
    print(f"built {path} ({os.path.getsize(path) / 1e6:.0f} MB, {n} files) "
          f"in {time.time() - t:.0f}s")
    return check_msi.main([path, app_dir])


if __name__ == "__main__":
    sys.exit(main())
