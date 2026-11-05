"""Install Modulor into QuantiSheet's .venv from the reviewed source zip
(vendor/modulor-40f6c2a.zip - kept in the project - checked by SHA-256
first). The first run copies it there from .run/modulor_spike.

    python tools/install_modulor.py
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "vendor", "modulor-40f6c2a.zip")
SPIKE = os.path.join(ROOT, ".run", "modulor_spike", "modulor-40f6c2a.zip")
SHA = "c234db9221c6037eda35699e3aa52ad1fbaaf862a7a159d630ad68c27effb0c5"
if not os.path.isfile(ZIP) and os.path.isfile(SPIKE):
    import shutil
    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    shutil.copy2(SPIKE, ZIP)
    print("copied the reviewed zip to", ZIP)
h = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
if h != SHA:
    raise SystemExit("STOP: Modulor source is not the reviewed one")
r = subprocess.run([sys.executable, "-m", "pip", "install",
                    "--disable-pip-version-check", ZIP],
                   capture_output=True, text=True)
print(r.stdout[-1500:], r.stderr[-1500:])
r = subprocess.run([sys.executable, "-c",
                    "import modulor, manifold3d, numpy, cv2, fitz; "
                    "print('modulor', modulor.__version__, 'numpy', "
                    "numpy.__version__, 'cv2', cv2.__version__)"],
                   capture_output=True, text=True)
print(r.stdout, r.stderr[-800:])
