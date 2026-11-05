"""Use QuantiSheet like an estimator would, start to finish, on a real plan
set, and report what worked and what didn't (with a picture of each step).

    python tools/user_session.py [PDF] [OUT_DIR]

It drives the real main window: the start page, opening the set, paging,
the All Tools panel, scale, Length / Area / Count takeoff by mouse clicks,
markups, undo/redo, Find, layouts, themes, Save As and reopen, Quantities
CSV, Documents panel. Every dialog that would wait for a person is
answered automatically. Your own settings are not touched (a temporary
settings folder is used).
"""
import json
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QPoint, Qt, QtMsgType, qInstallMessageHandler  # noqa
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog,  # noqa
                               QInputDialog, QMessageBox)

from app import settings, theme                                     # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-session-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Session Test"}

# ---- answer every dialog, and remember what it said ----------------------
SAID = []


def _box(kind, ret):
    def f(*a, **k):
        text = a[2] if len(a) > 2 else k.get("text", "")
        SAID.append(f"{kind}: {str(text)[:160]}")
        return ret
    return staticmethod(f)


QMessageBox.information = _box("info", QMessageBox.Ok)
QMessageBox.warning = _box("WARNING", QMessageBox.Ok)
QMessageBox.critical = _box("CRITICAL", QMessageBox.Ok)
QMessageBox.question = _box("question", QMessageBox.Yes)
QMessageBox.exec = lambda self, *a: (SAID.append(
    "box: " + self.text()[:160]), QMessageBox.Ok)[1]
ANSWER = {"text": "Session", "double": 24.0, "item": "ft", "int": 1}
QInputDialog.getText = staticmethod(
    lambda *a, **k: (ANSWER["text"], True))
QInputDialog.getMultiLineText = staticmethod(
    lambda *a, **k: (ANSWER["text"], True))
QInputDialog.getDouble = staticmethod(
    lambda *a, **k: (ANSWER["double"], True))
QInputDialog.getItem = staticmethod(lambda *a, **k: (ANSWER["item"], True))
QInputDialog.getInt = staticmethod(lambda *a, **k: (ANSWER["int"], True))
SAVE = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QDialog.exec = lambda self, *a: (SAID.append(
    "dialog: " + (self.windowTitle() or type(self).__name__)), 0)[1]

ERRORS = []


def _hook(kind, value, tb):
    ERRORS.append("".join(traceback.format_exception(kind, value, tb))[-1500:])


sys.excepthook = _hook


def _qt(mode, ctx, msg):
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg,
                QtMsgType.QtFatalMsg) and "propagateSizeHints" not in msg:
        ERRORS.append(f"Qt: {msg}")


qInstallMessageHandler(_qt)

RESULTS = []


def main(argv):
    pdf = argv[0] if argv else os.path.join(
        os.path.dirname(ROOT), "32410-004-IFC-Plant Drawings.pdf")
    out = argv[1] if len(argv) > 1 else os.path.join(ROOT, ".run",
                                                     "session")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    from PySide6.QtTest import QTest
    from app import annotate
    from app.main_window import MainWindow
    from app.ribbon import clean
    from PySide6.QtCore import QTimer

    def watchdog():
        """A window waiting for a person that this script didn't plan for:
        note it and close it, so the session never stalls."""
        m = app.activeModalWidget() or app.activePopupWidget()
        if m is not None:
            SAID.append(f"UNPLANNED WINDOW closed: {m.windowTitle() or type(m).__name__}")
            try:
                m.reject() if hasattr(m, "reject") else m.close()
            except Exception:
                m.close()
    dog = QTimer()
    dog.timeout.connect(watchdog)
    dog.start(1500)
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    for _ in range(10):
        app.processEvents()

    def pump(n=8, sleep=0.02):
        for _ in range(n):
            app.processEvents()
            time.sleep(sleep)

    def shot(name):
        pump(4)
        p = os.path.join(out, name + ".png")
        w.grab().save(p)
        return p

    def step(name, fn):
        e0, s0 = len(ERRORS), len(SAID)
        t = time.perf_counter()
        try:
            note = fn()
            ok = True
        except Exception:
            note = traceback.format_exc()[-900:]
            ok = False
        pump()
        secs = round(time.perf_counter() - t, 2)
        errs = ERRORS[e0:]
        said = SAID[s0:]
        pic = shot(f"{len(RESULTS) + 1:02d}_{name.split(':')[0][:30]}"
                   .replace(" ", "_").replace("/", "-"))
        RESULTS.append({"step": name, "ok": ok and not errs, "secs": secs,
                        "note": note, "errors": errs, "dialogs": said,
                        "picture": os.path.basename(pic)})
        flag = "OK  " if ok and not errs else "FAIL"
        print(f"{flag} {secs:6.2f}s  {name}  {note if ok else ''}"[:220],
              flush=True)
        for e in errs:
            print("      error:", e.splitlines()[-1][:200], flush=True)
        for s in said:
            print("      said:", s[:200], flush=True)
        if not ok:
            print("      " + note.strip().splitlines()[-1][:200], flush=True)
        return ok

    lay = w.layouts
    def first_look():
        rb = lay.active_bar()
        return (f"layout={lay.name} ribbon shown="
                f"{bool(rb is not None and rb.isVisible())} rail shown="
                f"{lay.rail.isVisible()} rail buttons={len(lay._rail_entries)} "
                f"all_tools_open={not lay.dock.isHidden()} "
                f"window {w.width()}x{w.height()} min width "
                f"{w.minimumSizeHint().width()}px")
    step("start page (default layout: ribbon + left rail)", first_look)

    if not os.path.isfile(pdf):
        print("no such PDF:", pdf)
        return 1

    def open_set():
        ok = w.open_path(pdf)
        assert ok, "open_path returned False"
        v = w._view
        return f"{v.doc.page_count} pages"
    if not step("open the plan set", open_set):
        return 2
    v = w._view

    step("page down x3, End, Home (keyboard)", lambda: (
        [QTest.keyClick(v, Qt.Key_PageDown) for _ in range(3)],
        pump(), f"after PgDn x3: page {v.page + 1}",
        QTest.keyClick(v, Qt.Key_End), pump(),
        f"End: page {v.page + 1}",
        QTest.keyClick(v, Qt.Key_Home), pump(),
        f"Home: page {v.page + 1}")[2::3])

    # find a piping plan sheet to work on
    def goto_plan():
        target = None
        for i in range(min(v.doc.page_count, 120)):
            t = v.doc[i].get_text()[:4000].upper()
            if "PIPING PLAN" in t or "YARD PIPING" in t:
                target = i
                break
        v.go_to(target if target is not None else min(5, v.doc.page_count - 1))
        w.fit_page()
        return f"page {v.page + 1}"
    step("go to a piping plan sheet", goto_plan)

    step("All Tools: type 'length' in the filter", lambda: (
        lay.panel.search.setText("length"),
        [clean(a.text()) for a in lay.panel.visible_actions()][:6])[1])
    lay.panel.search.clear()

    def auto_scale():
        a = w.command("Auto Scale (Read Sheets)")
        if a is None:
            return "no Auto Scale command"
        a.trigger()
        pump(30, 0.05)
        sc = v.scale()
        return f"scale on this page: {sc}"
    step("Auto Scale (read the sheet scales)", auto_scale)

    def ensure_scale():
        if not v.scale():
            v.calibrate(240.0, real=40, unit="ft", all_pages=False)
        return f"scale: {v.scale()}"
    step("scale set (calibrate if Auto Scale found none)", ensure_scale)

    c = v.rect().center()

    def pt(dx, dy):
        return QPoint(c.x() + dx, c.y() + dy)

    def length():
        before = len(annotate.takeoff_items(v.doc))
        w.set_tool("measure_length")
        pump()
        QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(-200, 50))
        QTest.mouseMove(v, pt(0, 50))
        QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(150, 50))
        pump()
        items = annotate.takeoff_items(v.doc)
        assert len(items) == before + 1, f"items {before} -> {len(items)}"
        it = items[-1]
        strip = lay.strip.isVisible()
        return f"{it['value']:.2f} {it['unit']} ({it['group']}); " \
               f"tool strip shown: {strip}"
    step("Length takeoff by two clicks", length)

    def area():
        before = len(annotate.takeoff_items(v.doc))
        w.set_tool("measure_area")
        pump()
        for dx, dy in ((-150, -150), (100, -150), (100, 0)):
            QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(dx, dy))
        QTest.mouseDClick(v, Qt.LeftButton, Qt.NoModifier, pt(-150, 0))
        pump()
        items = annotate.takeoff_items(v.doc)
        assert len(items) > before, f"items {before} -> {len(items)}"
        it = items[-1]
        return f"{it['value']:.1f} {it['unit']}"
    step("Area takeoff (4 corners, double-click)", area)

    def count():
        before = len(annotate.takeoff_items(v.doc))
        ANSWER["text"] = "Valves"
        w.set_tool("count")
        pump()
        for dx in (-100, -60, -20):
            QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(dx, 120))
        pump()
        items = annotate.takeoff_items(v.doc)
        return f"{len(items) - before} count marks added"
    step("Count 3 valves", count)

    def cloud():
        n = len(list(v.pg.annots() or []))
        w.set_tool("add_cloud")
        pump()
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(200, -200))
        QTest.mouseMove(v, pt(320, -120))
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(320, -120))
        pump()
        n2 = len(list(v.pg.annots() or []))
        assert n2 > n, f"annots {n} -> {n2}"
        return f"strip text: {lay._strip_box is not None}"
    step("Cloud markup by drag", cloud)

    def textbox():
        n = len(list(v.pg.annots() or []))
        ANSWER["text"] = "Verify invert at MH-3"
        w.set_tool("add_textbox")
        pump()
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(200, 60))
        QTest.mouseMove(v, pt(380, 110))
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(380, 110))
        pump()
        n2 = len(list(v.pg.annots() or []))
        return f"annots {n} -> {n2}"
    step("Text box", textbox)

    step("Esc back to Select", lambda: (
        QTest.keyClick(v, Qt.Key_Escape), QTest.keyClick(v, Qt.Key_Escape),
        pump(), f"tool={v.tool} strip shown={lay.strip.isVisible()}")[3])

    def undo_redo():
        n = len(list(v.pg.annots() or []))
        w.command("Undo").trigger()
        pump()
        n1 = len(list(w._view.pg.annots() or []))
        w.command("Redo").trigger()
        pump()
        n2 = len(list(w._view.pg.annots() or []))
        return f"annots {n} -> undo {n1} -> redo {n2}"
    step("Undo, then Redo", undo_redo)

    def quantities():
        w.quantities.refresh()
        s = w.quantities.summary()
        return "; ".join(f"{k[0]} {v_:.1f} {k[2]}" for k, v_ in
                         list(s.items())[:5])
    step("Quantities panel totals", quantities)

    def find():
        w.search.open_bar(v.doc)
        w.search.edit.setText("PDG")
        w.search.run()
        return f"{len(w.search.hits)} hits for PDG"
    step("Find 'PDG'", find)
    w.search.close_bar()

    for name in ("simple", "modern", "ribbon"):
        step(f"layout: {name}", lambda n=name: (lay.set_layout(n),
                                                f"name={lay.name}")[1])
    step("back on ribbon + rail after switching", first_look)
    step("theme: dark", lambda: theme.apply(app, "dark"))
    step("theme: light", lambda: theme.apply(app, "light"))

    def pin():
        a = lay._find("Watermark")
        lay.set_pinned(a, True)
        on = a in lay.rail_actions
        lay.set_pinned(a, False)
        return f"pinned on rail: {on}; window min height " \
               f"{w.minimumSizeHint().height()}px"
    step("pin and unpin a tool", pin)

    step("Ctrl+Shift+T (All Tools)", lambda: (
        lay.all_tools_action.trigger(), pump(),
        f"panel shown={not lay.dock.isHidden()}")[2])

    def save_reopen():
        target = os.path.join(TMP, "session-copy.pdf")
        SAVE["path"] = target
        before = len(annotate.takeoff_items(w._view.doc))
        t = time.perf_counter()
        assert w.save_as(), "Save As failed"
        secs = time.perf_counter() - t
        w._view.dirty = False
        w.close_tab(w.tabs.currentIndex())
        pump()
        assert w.open_path(target), "reopen failed"
        after = len(annotate.takeoff_items(w._view.doc))
        return f"save {secs:.1f}s; takeoff items {before} -> {after} " \
               f"after reopen; size {os.path.getsize(target) / 1e6:.1f} MB"
    step("Save As, close, reopen", save_reopen)

    def export_csv():
        from app import estimate  # noqa: F401
        target = os.path.join(TMP, "quantities.csv")
        q = w.quantities
        q.refresh()
        SAVE["path"] = target
        w.export_quantities()               # the menu command, as a user
        assert os.path.isfile(target), "no file written"
        rows = open(target, encoding="utf-8-sig").read().count("\n")
        return f"{rows} lines written"
    step("Export quantities to CSV", export_csv)

    def documents():
        d = w.documents
        d.set_folder(os.path.dirname(pdf))
        w.docs_dock.show()
        w.docs_dock.raise_()
        pump(20, 0.05)
        d.finish_counting() if len(d._pending) < 40 else None
        return f"{d.tree.topLevelItemCount()} top-level rows; " \
               f"label: {d.label.text()[:80]}"
    step("Documents panel on the Desktop folder", documents)

    def close_all():
        for i in reversed(range(w.tabs.count())):
            v_ = w.tabs.widget(i)
            if hasattr(v_, "view"):
                v_.view.dirty = False
            w.close_tab(i)
        pump()
        w.start_page.refresh() if hasattr(w, "start_page") else None
        return f"tabs left {w.tabs.count()}"
    step("close everything, back to the start page", close_all)

    res = {"pdf": pdf, "steps": RESULTS, "all_errors": ERRORS}
    with open(os.path.join(out, "session.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} steps OK; "
          f"pictures in {out}", flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
