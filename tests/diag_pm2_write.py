"""Diagnostic only (run explicitly with -s): step through MainWindow._write
for the takeoff-items save on the installed PyMuPDF; made-up data."""
import os
import traceback

import fitz
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_gui import win, qapp                     # noqa: E402,F401
from app import embfiles                            # noqa: E402


def _state(doc, tag):
    try:
        print(f"[{tag}] xref_length={doc.xref_length()} dirty={doc.is_dirty}"
              f" can_incr={doc.can_save_incrementally()} names={embfiles.names(doc)}")
        for x in range(max(1, doc.xref_length() - 4), doc.xref_length()):
            try:
                print(f"   xref {x} stream={doc.xref_is_stream(x)} "
                      f"{doc.xref_object(x, compressed=True)[:90]}")
            except Exception as e:                # noqa: BLE001
                print(f"   xref {x} !! {e!r}")
    except Exception as e:                        # noqa: BLE001
        print(f"[{tag}] !! {e!r}")


def _disk(path, tag):
    d = fitz.open(path)
    try:
        _state(d, tag + " disk")
    finally:
        d.close()


def test_diag(win, tmp_path):
    print("\nPyMuPDF", fitz.VersionBind)
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    path = win._path
    print("path", path, "doc.name", v.doc.name)
    _state(v.doc, "open")
    t.new_item("Doors", "count", activate=False)
    _state(v.doc, "after item 1")
    t.new_item("Carpet", "area", activate=False)
    _state(v.doc, "after item 2")
    doc = v.doc
    snap = embfiles.snapshot(doc)
    print("snapshot", {k: len(b) for k, b in snap.items()})
    for label, kw in (("incr+KEEP", dict(incremental=True,
                                         encryption=fitz.PDF_ENCRYPT_KEEP)),):
        try:
            doc.save(path, **kw)
            print(label, "saved")
        except Exception:
            traceback.print_exc()
        _state(doc, label + " live")
        _disk(path, label)
        print(label, "mismatches", embfiles.saved_mismatches(path, snap))
    try:
        tmp = path + ".diag-tmp"
        doc.save(tmp, garbage=1, deflate=True)
        print("full save to tmp ok")
        _disk(tmp, "full tmp")
        print("tmp mismatches", embfiles.saved_mismatches(tmp, snap))
        os.remove(tmp)
    except Exception:
        traceback.print_exc()
    try:
        page = v.page
        doc.close()
        tmp = path + ".diag-tmp2"
        print("closed; trying a fresh open + full save copy")
        d = fitz.open(path)
        _state(d, "fresh open")
        d.close()
    except Exception:
        traceback.print_exc()
    v.doc = fitz.open(path)
    try:
        win._write(path)
        print("_write ok")
    except Exception:
        traceback.print_exc()
