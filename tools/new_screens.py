"""Screenshots of the newest features for review:
in-place Edit Text, Auto Walls & Doors, Gantt chart, lookahead PDF.

    python tools/new_screens.py [OUT_DIR]
"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox       # noqa: E402

from app import settings, theme                               # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-new-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Pat Morgan"}
# nothing may wait for a click: this runs unattended
from PySide6.QtWidgets import QDialog                          # noqa: E402
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QMessageBox.warning = staticmethod(lambda *a, **k: 0)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
QMessageBox.exec = lambda self, *a: QMessageBox.Discard
QDialog.exec = lambda self, *a: 0

SPEC = ("The contractor shall furnish all labor, materials, equipment and "
        "services required to complete the cast-in-place concrete work "
        "shown on the drawings and specified herein, including formwork, "
        "reinforcement, embedded items and curing.")


def spec_pdf(path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE",
                  fontsize=13, fontname="hebo")
    p.insert_text((72, 110), "PART 1 - GENERAL", fontsize=11,
                  fontname="hebo")
    p.insert_textbox(fitz.Rect(72, 124, 540, 220), "1.1 SUMMARY\n" + SPEC,
                     fontsize=10.5, fontname="tiro")
    p.insert_textbox(fitz.Rect(72, 230, 540, 330),
                     "1.2 SUBMITTALS\nProduct data for each type of "
                     "product. Design mixtures for each concrete mixture. "
                     "Steel reinforcement shop drawings.", fontsize=10.5,
                     fontname="tiro")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80), False)
    pix.set_rect(pix.irect, (210, 225, 240))
    p.insert_image(fitz.Rect(400, 360, 520, 440), stream=pix.tobytes("png"))
    d.save(path)
    return path


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "newshots")
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv[:1])
    from app.main_window import MainWindow
    from app import annotate
    import test_autowalls
    shots = []

    def save(w, name):
        app.processEvents()
        p = os.path.join(out, name + ".png")
        w.grab().save(p)
        shots.append(p)
    theme.apply(app, "light")
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    app.processEvents()
    # 1. in-place editing
    win.open_path(spec_pdf(os.path.join(TMP, "03 30 00.pdf")))
    v = win._view
    v.set_zoom(1.5)
    app.processEvents()
    v.set_tool("edit_text")
    ctl = v.editctl
    ctl.refresh()
    save(win, "edit-outlines")
    w = [w for w in v.pg.get_text("words") if w[4] == "furnish"][0]
    ctl.open(annotate.from_page(v.pg, fitz.Rect(w[:4])).tl + (2, 2))
    ed = ctl.editor
    cur = ed.textCursor()
    cur.setPosition(ed.toPlainText().index("furnish"))
    ed.setTextCursor(cur)
    ed.insertPlainText("promptly ")
    save(win, "edit-typing")
    ctl.commit()
    save(win, "edit-done")
    v.set_tool(None)
    # 2. auto walls & doors
    path = os.path.join(TMP, "plan.pdf")
    test_autowalls._plan().save(path)
    win.open_path(path)
    app.processEvents()
    win.fit_page()
    print("auto walls:", win.auto_walls(quiet=True))
    save(win, "auto-walls")
    for i in range(win.tabs.count()):
        t = win.tabs.widget(i)
        if hasattr(t, "view"):
            t.view.dirty = False
    win.hide()
    # 3. schedule
    from app.pm import center, schedule
    from app.pm.store import ProjectStore
    s = ProjectStore(os.path.join(TMP, "Clinic"))
    s.data["name"] = "Aiken County Spay-Neuter Clinic"
    t0 = dt.date.today() - dt.timedelta(days=20)
    acts = [("Mobilize", 3, [], "Morgan GC"),
            ("Clearing & erosion control", 4, ["A0001"], "Site Pro"),
            ("Excavation", 6, ["A0002"], "Site Pro"),
            ("Underground plumbing", 5, ["A0003"], "ABC Plumbing"),
            ("Footings", 5, ["A0003"], "Carolina Concrete"),
            ("Slab on grade", 4, ["A0004", "A0005"], "Carolina Concrete"),
            ("Steel erection", 8, ["A0006"], "Steel Co"),
            ("Roofing", 7, ["A0007"], "Top Roof"),
            ("Exterior framing", 9, ["A0007"], "Morgan GC"),
            ("Dry-in", 0, ["A0008", "A0009"], ""),
            ("MEP rough-in", 12, ["A0010"], "ABC Plumbing"),
            ("Drywall", 10, ["A0011"], "Interiors Inc"),
            ("Kennel coatings", 6, ["A0012"], "Coatings LLC"),
            ("Substantial completion", 0, ["A0013"], "")]
    for i, (n, dur, preds, who) in enumerate(acts):
        rec = {"name": n, "duration": dur, "responsible": who,
               "preds": [{"id": p} for p in preds],
               "area": "Sitework" if i < 3 else "Building"}
        if i == 0:
            rec["start"] = t0.isoformat()
            rec["actual_start"] = t0.isoformat()
            rec["actual_finish"] = (t0 + dt.timedelta(days=2)).isoformat()
            rec["percent"] = 100
        if i in (1, 2):
            rec["percent"] = 100 if i == 1 else 60
        s.save_record("activity", rec)
    schedule.update_dates(s)
    schedule.set_baseline(s)
    a = s.find("activity", name="Footings")[0]
    a["duration"] = 8                         # slipped 3 days
    s.save_record("activity", a)
    codes = ["31 00 00", "31 00 00", "31 00 00", "22 00 00", "03 30 00",
             "03 30 00", "05 12 00", "07 50 00", "06 10 00", "",
             "26 00 00", "09 21 16", "09 96 00", ""]
    for a, code in zip(sorted(s.list("activity"), key=lambda r: r["_n"]),
                       codes):
        if code:
            a["cost_code"] = code
            s.save_record("activity", a)
    for code, desc, amt in (("31 00 00", "Earthwork", 85000),
                            ("22 00 00", "Plumbing", 120000),
                            ("03 30 00", "Concrete", 140000),
                            ("05 12 00", "Structural steel", 160000),
                            ("07 50 00", "Roofing", 70000),
                            ("06 10 00", "Framing", 90000),
                            ("26 00 00", "Electrical", 130000),
                            ("09 21 16", "Drywall", 60000),
                            ("09 96 00", "Coatings", 45000),
                            ("01 50 00", "General conditions", 75000)):
        s.save_record("budget", {"cost_code": code, "description": desc,
                                 "original": amt})
    s.save_record("cost", {"date": (t0 + dt.timedelta(days=5)).isoformat(),
                           "vendor": "Site Pro", "cost_code": "31 00 00",
                           "amount": 52000, "status": "Paid",
                           "paid": (t0 + dt.timedelta(days=15)).isoformat()})
    for mode in ("light", "dark"):
        theme.apply(app, mode)
        w = center.ProjectCenter(s)
        w.resize(1500, 900)
        w.show()
        w.show_tool("gantt")
        app.processEvents()
        save(w, f"{mode}-gantt")
        w.show_tool("cashflow")
        app.processEvents()
        save(w, f"{mode}-cashflow")
        w.close()
    theme.apply(app, "light")
    from app.organize import OrganizeDialog
    od = fitz.open()
    for i in range(9):
        pg = od.new_page(width=792, height=612)
        pg.draw_rect(fitz.Rect(30, 30, 762, 582))
        pg.insert_text((60, 300), f"A-10{i + 1}", fontsize=60)
    dlg = OrganizeDialog(od)
    dlg.show()
    for _ in range(20):
        app.processEvents()
        dlg._load_some()
    dlg.list.item(2).setSelected(True)
    dlg.rotate(90)
    dlg.move(5, 1)
    save(dlg, "organize")
    dlg.close()
    for name, fn in (("gantt.pdf", lambda p: schedule.gantt_pdf(
            s, p, title="Project Schedule")),
            ("lookahead.pdf", lambda p: schedule.lookahead_pdf(s, p))):
        p = os.path.join(out, name)
        fn(p)
        pix = fitz.open(p)[0].get_pixmap(dpi=110)
        pix.save(p[:-4] + ".png")
        shots += [p, p[:-4] + ".png"]
    print("\n".join(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
