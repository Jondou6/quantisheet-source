"""Diagnostic only (run explicitly with -s): MainWindow._write fallback for
the takeoff-items save on the installed PyMuPDF; made-up data."""
import os
import traceback

import fitz
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_gui import win, qapp                     # noqa: E402,F401
from app import embfiles                            # noqa: E402


def test_diag(win, tmp_path):
    print("\nPyMuPDF", fitz.VersionBind)
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    path = win._path
    raw = fitz.open(path)
    print("raw: dirty before", raw.is_dirty)
    raw.embfile_add("x.json", b"{}", filename="x.json")
    print("raw: dirty after embfile_add", raw.is_dirty)
    raw.close()
    t.new_item("Doors", "count", activate=False)
    print("app: dirty after new_item", v.doc.is_dirty)
    import app.autosave as a
    print("autosave mode", a.mode())
    try:
        win._write(path)
        print("_write ok")
    except Exception:
        traceback.print_exc()
    d = fitz.open(path)
    print("disk names", embfiles.names(d))
    try:
        print("disk data", embfiles.get(d, "pdfstudio_takeoffitems.json")[:60])
    except Exception as e:
        print("disk get !!", repr(e))
    d.close()
