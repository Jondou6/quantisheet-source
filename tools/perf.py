"""Responsiveness test: drives the real window like an estimator would and
times each action.

    python tools/perf.py [SHEETS] [--pdf FILE]

Anything over 150 ms is flagged SLOW (the point where a click feels
sluggish); over 1 s, VERY SLOW.
"""
import os
import random
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402

RESULTS = []


def make(path, n):
    import bigset
    rnd = random.Random(3)
    doc = fitz.open()
    for i in range(n):
        bigset.sheet(doc, i, rnd)
    from app import annotate
    op = annotate.new_op
    annotate.apply_op(doc, op("set_scale", 0, ppu=18, unit="ft",
                              pages=list(range(n))))
    for k in range(150):                         # a marked-up sheet
        x, y = 200 + (k % 15) * 120, 200 + (k // 15) * 110
        if k % 3 == 0:
            annotate.apply_op(doc, op("add_rect", 0, rect=[x, y, x + 80,
                                                           y + 60]))
        elif k % 3 == 1:
            annotate.apply_op(doc, op(
                "add_polyline", 0, pts=[[x, y], [x + 90, y], [x + 90, y + 50]],
                measure={"type": "length", "value": 7.8, "unit": "ft",
                         "group": "Interior Wall"}))
        else:
            annotate.apply_op(doc, op("add_cloud", 0, rect=[x, y, x + 70,
                                                            y + 50]))
    doc.save(path, garbage=3, deflate=True)
    doc.close()


def t(label, fn, n=1, budget=0.15):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.processEvents()
    start = time.perf_counter()
    out = None
    for _ in range(n):
        out = fn()
        app.processEvents()
    dt = (time.perf_counter() - start) / n
    flag = "VERY SLOW" if dt > 1.0 else "SLOW" if dt > budget else ""
    RESULTS.append((label, dt, flag))
    print(f"  {label:<48} {dt * 1000:9.0f} ms  {flag}")
    sys.stdout.flush()
    return out


def main(argv):
    n = int(argv[0]) if argv and argv[0].isdigit() else 120
    tmp = tempfile.mkdtemp(prefix="quantisheet-perf-")
    from app import settings
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    path = argv[argv.index("--pdf") + 1].strip('"') if "--pdf" in argv else \
        os.path.join(tmp, f"perf-{n}.pdf")
    if "--pdf" not in argv:
        print(f"Building a {n}-sheet set with a marked-up first sheet...")
        make(path, n)
    print(f"{os.path.basename(path)}: {os.path.getsize(path) / 1e6:.0f} MB\n")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    # nobody to answer dialogs: give the usual answers
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Wall", True))
    QInputDialog.getItem = staticmethod(
        lambda *a, **k: ((a[3] if len(a) > 3 and a[3] else ["ft"])[0], True))
    QInputDialog.getDouble = staticmethod(lambda *a, **k: (10.0, True))
    QInputDialog.getInt = staticmethod(lambda *a, **k: (1, True))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    # a real set may have no scale on the sheet: the first length then asks
    # for one (a modal dialog nobody is there to answer) - give it 10 ft
    from app import calibrate_dialog
    calibrate_dialog.ask_calibration = lambda *a, **k: (10.0, "ft", False)
    for name in ("information", "warning", "about", "critical"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    from app import theme
    theme.apply(app, "dark")
    from app.main_window import MainWindow
    win = t("start the app (window ready)", lambda: MainWindow(), budget=1.5)
    win.resize(1600, 960)
    win.show()
    t("open the set", lambda: win.open_path(path), budget=1.5)
    v = win._view
    t("fit width", win.fit_width)
    t("next page (average of 10)", v.next_page, 10)
    t("previous page (average of 10)", v.prev_page, 10)
    v.go_to(0)
    t("zoom in (average of 4)", lambda: win._zoom(1.25), 4)
    t("zoom out (average of 4)", lambda: win._zoom(0.8), 4)
    t("fit page", win.fit_page)

    def pan():
        sc = win._scroll
        sc.verticalScrollBar().setValue(sc.verticalScrollBar().value() + 120)
        v.repaint()
    v.set_zoom(4.0)
    t("pan at 400 % (average of 10)", pan, 10)
    win.fit_page()
    t("rotate this page right", lambda: win._rotate_pages([v.page], 90))
    t("undo the rotate", win.undo)
    t("redo the rotate", win.redo)
    t("rotate this page back", lambda: win._rotate_pages([v.page], -90))
    t(f"rotate all {v.doc.page_count} pages right",
      lambda: win._rotate_pages(list(range(v.doc.page_count)), 90),
      budget=1.0)
    t("undo rotate all", win.undo, budget=1.0)
    t("rotate via the menu command (Ctrl+Shift+=)",
      lambda: win.command("Rotate Right").trigger())
    win.undo()

    z = v.zoom

    def drag(tool, a, b):
        win.set_tool(tool, ask=False)
        pa = QPoint(int(a[0] * z), int(a[1] * z))
        pb = QPoint(int(b[0] * z), int(b[1] * z))
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pa)
        for k in range(1, 11):
            QTest.mouseMove(v, pa + (pb - pa) * (k / 10))
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pb)

    before = len(list(v.pg.annots()))
    t("draw a rectangle markup", lambda: drag("add_rect", (300, 1300),
                                              (420, 1380)))
    print(f"     markups on the sheet: {before} -> {len(list(v.pg.annots()))}")
    win.set_tool(None, ask=False)
    t("select a markup (click)", lambda: (
        QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(240 * z), int(230 * z)))))

    def move():
        pa = QPoint(int(240 * z), int(230 * z))
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pa)
        for k in range(1, 21):
            QTest.mouseMove(v, pa + QPoint(k * 3, k * 2))
            app.processEvents()
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier,
                           pa + QPoint(60, 40))
    t("drag a markup (20 mouse moves + drop)", move, budget=0.4)

    def moves_only():
        pa = QPoint(int(600 * z), int(600 * z))
        for k in range(30):
            QTest.mouseMove(v, pa + QPoint(k, k))
            app.processEvents()
    t("mouse moves over the sheet (30)", moves_only, budget=0.3)
    t("undo the move", win.undo)
    t("redo the move", win.redo)
    t("delete the selected markup", lambda: win.command(
        "Delete Selected Markup").trigger())
    t("undo the delete", win.undo)

    def measure():
        win.set_tool("measure_length", ask=False)
        for x, y in ((500, 1500), (800, 1500)):
            QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier,
                             QPoint(int(x * z), int(y * z)))
        QTest.mouseDClick(v, Qt.LeftButton, Qt.NoModifier,
                          QPoint(int(800 * z), int(1500 * z)))
    t("take off a length (2 clicks + finish)", measure, budget=0.4)
    win.set_tool(None, ask=False)
    t("open command search", lambda: win.command_search(show=False))
    t("switch to dark theme", lambda: win.set_theme("dark"), budget=0.5)
    t("switch to light theme", lambda: win.set_theme("light"), budget=0.5)
    t("show Takeoff ribbon tab", lambda: win.ribbon.show_page("Takeoff"))
    out = os.path.join(tmp, "saved.pdf")
    t("save as", lambda: win._write(out), budget=2.0)
    v.dirty = False
    win.close()
    if "--json" in argv:                 # for tools/perf_gate.py
        import json as _json
        with open(argv[argv.index("--json") + 1].strip('"'), "w",
                  encoding="utf-8") as _f:
            _json.dump({r[0]: r[1] for r in RESULTS}, _f, indent=1)
    slow = [r for r in RESULTS if r[2]]
    print(f"\n{len(RESULTS)} actions timed, {len(slow)} slow:")
    for label, dt, flag in slow:
        print(f"  {flag:<9} {label} ({dt * 1000:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
