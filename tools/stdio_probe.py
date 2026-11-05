"""Which feature leaks open files? Repeat the stress test's steps in one
session and, after each, count the free C runtime file slots (what MuPDF
runs out of). A step whose count keeps dropping is the leak.

    python tools/stdio_probe.py PLANS.pdf
"""
import ctypes
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                      # noqa: E402

crt = ctypes.cdll.ucrtbase
crt.fopen.restype = ctypes.c_void_p
crt.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
crt.fclose.argtypes = [ctypes.c_void_p]
crt._setmaxstdio(512)              # the old limit, so a leak shows quickly


def free_slots():
    held = []
    while len(held) < 9000:
        f = crt.fopen(b"NUL", b"r")
        if not f:
            break
        held.append(f)
    for f in held:
        crt.fclose(f)
    return len(held)


TMP = tempfile.mkdtemp(prefix="quantisheet-stdio-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Probe"}
os.makedirs(settings.DIR, exist_ok=True)


def main(argv):
    src = argv[0].strip('"')
    path = os.path.join(TMP, "set.pdf")
    shutil.copy(src, path)
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    last = [free_slots()]
    print(f"start: {last[0]} free file slots (limit 512)", flush=True)

    def mark(label):
        n = free_slots()
        print(f"{label:44} {n:5} free  ({n - last[0]:+d})", flush=True)
        last[0] = n

    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    app.processEvents()
    mark("window")
    w.open_path(path)
    for _ in range(20):
        app.processEvents()
    mark("open the set")
    v = w._view
    for p in range(min(40, v.doc.page_count)):
        v.go_to(p)
        app.processEvents()
    mark("flip 40 sheets")
    for p in range(min(40, v.doc.page_count)):
        v.go_to(p)
        app.processEvents()
    mark("flip 40 sheets again")
    w.set_tool("edit_text")
    app.processEvents()
    v.editctl.finish()
    mark("edit text in/out")
    for _ in range(5):
        w.simple_menu.set_on(True)
        app.processEvents()
        w.simple_menu.set_on(False)
        app.processEvents()
    mark("simple menus x5")
    w.toggle_field_mode()
    app.processEvents()
    w.toggle_field_mode()
    mark("field mode on/off")
    from app import acrobat2
    for i in range(3):
        try:
            acrobat2.external_issue(v.doc, os.path.join(TMP, f"e{i}.pdf"))
            mark(f"external issue #{i + 1}")
        except Exception as e:
            mark(f"external issue #{i + 1} FAILED {e}")
    v.dirty = False
    w.close()
    app.processEvents()
    mark("close")
    shutil.rmtree(TMP, ignore_errors=True)
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
