"""Where the time goes in slow UI actions (cProfile, top functions).

    python tools/profile_ui.py [SHEETS] [ACTION ...]

ACTIONs: open next rotate rotateback drag theme draw zoom (default all).
"""
import cProfile
import io
import os
import pstats
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")


def prof(label, fn, app, top=22):
    pr = cProfile.Profile()
    pr.enable()
    fn()
    app.processEvents()
    pr.disable()
    s = io.StringIO()
    st = pstats.Stats(pr, stream=s)
    total = sum(v[3] for v in st.stats.values() if True) if False else None
    st.sort_stats("cumulative").print_stats(top)
    text = s.getvalue()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = next((ln for ln in lines if "function calls" in ln), "")
    print(f"\n=== {label}: {head.strip()}")
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().startswith("ncalls")), 0)
    for ln in lines[start:start + top + 1]:
        print("  " + ln.strip()[:150])
    sys.stdout.flush()


def main(argv):
    n = int(argv[0]) if argv and argv[0].isdigit() else 120
    acts = [a for a in argv if not a.isdigit()] or [
        "open", "next", "rotate", "rotateback", "click", "drag", "draw",
        "zoom", "theme"]
    tmp = tempfile.mkdtemp(prefix="quantisheet-prof-")
    from app import settings
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    import perf
    path = os.path.join(tmp, "p.pdf")
    perf.make(path, n)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    app = QApplication(sys.argv[:1])
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Wall", True))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    for name in ("information", "warning"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    from app import theme
    theme.apply(app, "dark")
    from app.main_window import MainWindow
    win = MainWindow()
    win.resize(1600, 960)
    win.show()
    app.processEvents()
    if "open" in acts:
        prof("open the set", lambda: win.open_path(path), app)
    else:
        win.open_path(path)
    v = win._view
    win.fit_page()
    app.processEvents()
    if "next" in acts:
        prof("next page", v.next_page, app)
        v.go_to(0)
    if "rotate" in acts:
        prof("rotate page right", lambda: win._rotate_pages([0], 90), app)
    if "rotateback" in acts:
        prof("rotate page back", lambda: win._rotate_pages([0], -90), app)
    z = v.zoom
    if "click" in acts:
        win.set_tool(None, ask=False)
        prof("click to select a markup", lambda: QTest.mouseClick(
            v, Qt.LeftButton, Qt.NoModifier,
            QPoint(int(240 * z), int(230 * z))), app)
        prof("click empty paper", lambda: QTest.mouseClick(
            v, Qt.LeftButton, Qt.NoModifier,
            QPoint(int(1900 * z), int(1500 * z))), app)
    if "drag" in acts:
        def drag():
            pa = QPoint(int(240 * z), int(230 * z))
            QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pa)
            QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pa)
            for k in range(1, 21):
                QTest.mouseMove(v, pa + QPoint(k * 3, k * 2))
                app.processEvents()
            QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier,
                               pa + QPoint(60, 40))
        prof("select + drag a markup", drag, app)
    if "draw" in acts:
        def draw():
            win.set_tool("add_rect", ask=False)
            pa, pb = QPoint(int(300 * z), int(1300 * z)), \
                QPoint(int(420 * z), int(1380 * z))
            QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pa)
            QTest.mouseMove(v, pb)
            QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pb)
        prof("draw a rectangle", draw, app)
    if "undo" in acts:
        win.set_tool(None, ask=False)
        QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(240 * z), int(230 * z)))
        v.move_selected(20, 10)
        app.processEvents()
        prof("undo a move", win.undo, app, top=30)
    if "panels" in acts:
        prof("refresh the panels", win._refresh_panels, app, top=30)
    if "zoom" in acts:
        prof("zoom in", lambda: win._zoom(1.25), app)
    if "theme" in acts:
        prof("switch theme", lambda: win.set_theme("light"), app)
    v.dirty = False
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
