"""Screenshot of the Scheduler with a sample site-utilities schedule:
python tools/shot_scheduler.py OUT.png"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication                    # noqa: E402

from app import settings, theme                               # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-sched-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = None

PLAN = [("Mobilization & site prep", None, [
            ("Mobilize", 3, ""), ("Erosion control (SWPPP)", 4, "2"),
            ("Clear and grub", 5, "3")]),
        ("Utilities", None, [
            ("8\" sanitary sewer", 12, "4"), ("Manholes", 6, "6SS+3"),
            ("Water line", 10, "4"), ("Storm drain", 8, "6")]),
        ("Paving", None, [
            ("Fine grade", 4, "7,8,9"), ("Curb and gutter", 6, "11"),
            ("Asphalt", 3, "12")]),
        ("Substantial completion", 0, "13")]


def main(argv):
    out = argv[0]
    app = QApplication.instance() or QApplication([])
    theme.apply(m="light")
    from app.pm import scheduler as sch
    st = sch.create_schedule("Shelter Cove - Site Utilities",
                             folder=os.path.join(TMP, "job"),
                             start=dt.date(2026, 11, 2))
    w = sch.Scheduler(st)
    w.resize(1600, 820)
    w.show()
    t = w.table
    for name, dur, kids in PLAN:
        if isinstance(kids, str):                  # a milestone
            t.item(t.rowCount() - 1, sch.C_NAME).setText(name)
            r = t.rowCount() - 2
            t.item(r, sch.C_DUR).setText(str(dur))
            t.item(r, sch.C_PRED).setText(kids)
            continue
        t.item(t.rowCount() - 1, sch.C_NAME).setText(name)
        first = t.rowCount() - 1
        t.clearSelection()
        t.selectRow(first - 1)
        while w.levels.get(w.order[-1]["_id"], 0) > 0 and w.outdent():
            t.selectRow(first - 1)
        for kname, kdur, preds in kids:
            t.item(t.rowCount() - 1, sch.C_NAME).setText(kname)
            r = t.rowCount() - 2
            t.item(r, sch.C_DUR).setText(str(kdur))
            if preds:
                t.item(r, sch.C_PRED).setText(preds)
                rec = st.get("activity", t.item(r, 0).data(
                    __import__("PySide6.QtCore").QtCore.Qt.UserRole))
                print(f"typed {preds!r} on row {r + 1} {kname}: stored "
                      f"{[x['id'] for x in rec.get('preds') or []]}; order "
                      f"{[(a['_no'], a['name'][:8]) for a in w.order]}")
        t.clearSelection()
        from PySide6.QtCore import QItemSelectionModel as M
        for r in range(first, t.rowCount() - 1):
            t.selectionModel().select(t.model().index(r, 0),
                                      M.Select | M.Rows)
        w.indent()
    t.item(5, sch.C_PCT).setText("40")
    w.go_today()
    w.scroll.horizontalScrollBar().setValue(0)
    for _ in range(5):
        app.processEvents()
    w.grab().save(out)
    print(out, len(w.order), "rows;", w.summary.text())
    print("problems:", w.cpm["problems"])


if __name__ == "__main__":
    main(sys.argv[1:])
