"""Diagnostic (read-only): read every schedule printout PDF in a folder
with the Master Schedule PDF reader and print what it found. Opens the
PDFs read-only; writes nothing.
    python tools/diag_pdfsched.py "C:\\...\\Schedulke Examples" """
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.pm.master.formats import pdfsched  # noqa: E402

folder = " ".join(sys.argv[1:])
for f in sorted(glob.glob(os.path.join(folder, "**", "*.pdf"),
                          recursive=True)):
    try:
        p = pdfsched.read_pages(pdfsched._words(f))
    except Exception as e:                                # noqa: BLE001
        print("==", os.path.basename(f), "ERROR", e)
        continue
    a = pdfsched.activities(p)
    print("==", os.path.basename(f)[:70], p["layout"], p["data_date"],
          "activities", len(a), "started", sum(r["start_a"] for r in a),
          "finished", sum(r["finish_a"] for r in a))
    for r in a[:3] + a[-2:]:
        print("   ", r["id"], "|", r["name"][:55], "|", r["orig"], r["rem"],
              r["start"], "A" if r["start_a"] else "", r["finish"],
              "A" if r["finish_a"] else "")
