"""Smoke test: run every command in the app (every menu and ribbon item)
on a marked-up drawing, with dialogs answered automatically, and report
any command that raises an error.

    python tools/click_everything.py [--part I/N] [WATCH]

--part 2/4 runs the second quarter of the commands (the PC runner stops a
request after 900 s). Progress goes to .run/click_progress.txt as it
runs; a command stuck for 120 s writes its stack there and stops the run.
"""
import logging
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

SKIP = {"Exit", "Close Tab", "Print", "Start Relay (host on this computer)",
        "Live Collaboration", "Make Searchable (OCR)", "Sign",
        "AI: Summarize", "AI: Redline", "AI: Spec-Check",
        "AI: Translate Markups", "AI: Find RFIs & Questions",
        "Escalation (BLS)", "Open Recent",
        # start other programs or the browser (left open, they held the
        # runner's output pipe overnight Oct 21-22)
        "ClaimIT (Insurance Claim Estimate)", "Read the Energy Code Online",
        "Open Project Folder", "Terms of Service", "Privacy",
        "Third-Party Licenses", "Support Bundle for IT",
        "Add the QuantiSheet Printer",
        # pops a menu at the mouse and waits for a click (Nov 10)
        "Convert Selected To"}

ERRORS = []
EXIT_CHECK = False      # --exit-check: exit normally, dump threads if stuck


class Catch(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            ERRORS.append(self.format(record))


def _args():
    part, watch, a = (1, 1), "", sys.argv[1:]
    while a:
        x = a.pop(0)
        if x == "--exit-check":
            global EXIT_CHECK
            EXIT_CHECK = True
        elif x == "--part" and a:
            i, n = a.pop(0).split("/")
            part = (int(i), int(n))
        else:
            watch = x
    return part, watch


def main():
    import faulthandler
    (pi, pn), watch = _args()
    prog_path = os.path.join(ROOT, ".run", f"click_progress_{pi}of{pn}.txt")
    os.makedirs(os.path.dirname(prog_path), exist_ok=True)
    prog = open(prog_path, "w", encoding="utf-8", buffering=1)
    prog.write("START\n")
    # start-up itself stuck (a prompt at launch?): dump and stop at 180 s
    faulthandler.dump_traceback_later(180, exit=True, file=prog)
    tmp = tempfile.mkdtemp(prefix="quantisheet-click-")
    from app import settings
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog,
                                   QFileDialog, QInputDialog, QMenu,
                                   QMessageBox, QProgressDialog)
    from PySide6.QtGui import QColor
    app = QApplication(sys.argv[:1])
    QDialog.exec = lambda self, *a: 0
    QMenu.exec = lambda self, *a, **k: None
    QProgressDialog.exec = lambda self, *a: 0
    # PySide binds exec() per class: patch the subclasses too, or a
    # QMessageBox(...).exec() would wait for a click forever
    for cls in (QMessageBox, QFileDialog, QInputDialog, QColorDialog):
        cls.exec = lambda self, *a: 0
    try:
        from PySide6.QtWidgets import QFontDialog, QErrorMessage
        for cls in (QFontDialog, QErrorMessage):
            cls.exec = lambda self, *a: 0
    except ImportError:
        pass
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    for n in ("information", "warning", "critical", "about"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    for n in ("getText", "getMultiLineText", "getItem", "getInt",
              "getDouble"):
        setattr(QInputDialog, n, staticmethod(lambda *a, **k: (None, False)))
    QColorDialog.getColor = staticmethod(lambda *a, **k: QColor())
    h = Catch()
    h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(h)
    import perf
    path = os.path.join(tmp, "job.pdf")
    perf.make(path, 3)
    from app.main_window import MainWindow
    from app.ribbon import all_actions, clean
    win = MainWindow()
    win.resize(1500, 900)
    win.show()
    win.open_path(path)
    app.processEvents()
    prog.write("WINDOW READY\n")
    acts = all_actions(win.menuBar())
    total = len(acts)
    k = -(-total // pn)
    acts = acts[(pi - 1) * k: pi * k]
    print(f"{total} commands; part {pi}/{pn}: {len(acts)}\n")
    bad, slow = [], []
    for path_, a in acts:
        name = clean(a.text())
        if name in SKIP or path_.endswith("Open Recent"):
            continue
        if not a.isEnabled():
            continue
        ERRORS.clear()
        old_hook = sys.excepthook
        caught = []
        sys.excepthook = lambda *e: caught.append(e)
        t = time.perf_counter()
        prog.write(f"RUN {path_} > {name}\n")
        # a command stuck for 120 s: write where, then stop the run
        faulthandler.dump_traceback_later(120, exit=True, file=prog)
        if watch and watch.lower() in name.lower():
            faulthandler.dump_traceback_later(4, repeat=True,
                                              file=sys.stdout)
        try:
            a.trigger()
            app.processEvents()
        except Exception:
            caught.append(sys.exc_info())
        faulthandler.cancel_dump_traceback_later()
        dt = time.perf_counter() - t
        sys.excepthook = old_hook
        # close any windows the command opened
        for w in app.topLevelWidgets():
            if w is not win and w.isVisible() and isinstance(w, QDialog):
                w.close()
        if win._view is None:
            win.open_path(path)
        if caught or ERRORS:
            msg = ""
            if caught:
                msg = "".join(traceback.format_exception(*caught[0]))[-900:]
            elif ERRORS:
                msg = ERRORS[0][-900:]
            bad.append((path_, name, msg))
            print(f"ERROR  {path_} > {name}\n{msg}\n")
        elif dt > 1.0:
            slow.append((path_, name, dt))
        if a.isCheckable() and a.isChecked() and a.data() is not None:
            win.set_tool(None, ask=False)
    faulthandler.cancel_dump_traceback_later()
    prog.write("DONE\n")
    print(f"\n{len(bad)} command(s) with errors, {len(slow)} slower than 1 s")
    for p_, n, dt in slow:
        print(f"  slow  {p_} > {n}  ({dt:.1f} s)")
    try:
        win._view.dirty = False
    except Exception:
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    code = main()
    import faulthandler
    import threading
    if EXIT_CHECK:
        print("threads at exit:", [t.name for t in threading.enumerate()])
    sys.stdout.flush()
    # a normal exit (os._exit crashed Qt on Windows, 0xC0000005); if Qt's
    # teardown ever hangs, dump every thread and stop after 30 s
    faulthandler.dump_traceback_later(30, exit=True)
    sys.exit(code)
