"""Trade Takeoff dialog and Check Takeoff, end to end in the window."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401
import test_tradetakeoff as T                                # noqa: E402


def _open(win, tmp_path, doc, name):
    annotate.apply_op(doc, annotate.new_op("set_scale", 0, ppu=T.PPU,
                                           unit="ft", name="1/4"))
    path = str(tmp_path / name)
    doc.save(path)
    win.open_path(path)
    return win._view


def test_pipe_and_review(qapp, win, tmp_path):
    v = _open(win, tmp_path, T.plumbing(), "plumb.pdf")
    dlg = win.trade_takeoff(show=False)
    found = dlg.pipe.find()
    assert any(g["name"] == '2" CW' for g in found)
    # rename the CW system in the table, keep only the ticked ones
    for i, g in enumerate(dlg.pipe.data):
        if g["name"] == '2" CW':
            dlg.pipe.table.item(i, 1).setText('2" Domestic CW')
    assert dlg.pipe.add() >= 2
    groups = {it["group"] for it in annotate.takeoff_items(v.doc)}
    assert '2" Domestic CW' in groups and '1" HW' in groups
    # check takeoff: accept one, delete one, accept the rest of a group
    chk = win.check_takeoff(show=False)
    total = len(chk.queue)
    assert total >= 3
    chk.accept_one()
    chk.delete_one()
    chk.accept_group()
    done, tot = chk.counts()
    assert done >= 2 and tot == total - 1
    from app import audit
    st = [r["status"] for r in audit.trail(v.doc)]
    assert st.count("Accepted") == done
    dlg.close()
    chk.close()


def test_legend_roof_rebar_earth(qapp, win, tmp_path, monkeypatch):
    d = fitz.open()
    p = d.new_page(width=1224, height=1100)
    T.test_legend_counts.__globals__  # same helpers
    p.insert_text((900, 80), "LEGEND", fontsize=10)
    sh = p.new_shape()
    c = fitz.Point(910, 104)
    sh.draw_circle(c, 5)
    sh.draw_line(c + (-7, -2), c + (-5, -2))
    sh.draw_line(c + (-7, 2), c + (-5, 2))
    sh.finish(color=(0, 0, 0), width=0.8)
    sh.commit()
    p.insert_text((930, 107), "DUPLEX RECEPTACLE", fontsize=7)
    for x, y in ((3, 3), (10, 5), (18, 3)):
        T._receptacle(p, x, y)
    T._text(p, (12, 30), "6:12")
    v = _open(win, tmp_path, d, "mix.pdf")
    dlg = win.trade_takeoff(show=False)
    assert [f["name"] for f in dlg.legend.find()] == ["DUPLEX RECEPTACLE"]
    assert dlg.legend.add() == 3
    # roof: a 40 x 20 ft roof area, pitch printed inside
    pts = [T.P(0, 25), T.P(40, 25), T.P(40, 45), T.P(0, 45)]
    v.apply_marks([(0, "add_polygon", {
        "pts": [list(q) for q in pts],
        "measure": {"type": "area", "value": 800, "unit": "ft",
                    "group": "Roof"}})])
    rows = dlg.roof.find()
    assert len(rows) == 1 and rows[0]["pitch"] == 6
    assert dlg.roof.add() == 2
    roofs = [it for it in annotate.takeoff_items(v.doc)
             if it["group"].startswith("Roof")]
    assert len(roofs) == 1 and abs(roofs[0]["value"] - 894.4) < 1
    # rebar from a footing length
    v.apply_marks([(0, "add_line", {
        "pts": [list(T.P(0, 50)), list(T.P(50, 50))],
        "measure": {"type": "length", "value": 50, "unit": "ft",
                    "group": "Strip footing"}})])
    dlg.rebar.refresh_groups()
    i = [dlg.rebar.group.itemData(k)[0]
         for k in range(dlg.rebar.group.count())].index("Strip footing")
    dlg.rebar.group.setCurrentIndex(i)
    tot = dlg.rebar.find()
    assert tot and tot[0]["bar"] == 4 and tot[0]["lb"] > 100
    assert dlg.rebar.export(str(tmp_path / "rebar.xlsx"))
    dlg.close()


def test_earthwork_in_dialog(qapp, win, tmp_path):
    d = fitz.open()
    p = d.new_page(width=1224, height=1100)
    b = 10
    for k in range(5):
        y = b + k * 10
        T._line(p, (0, y), (40, y), dashes="[3 3] 0", width=0.5)
        T._text(p, (0.5, y - 0.3), f"{100 + k}")
    for k in range(6):
        y = b + k * 10 - 5
        T._line(p, (0, y), (40, y), width=1.0)
        T._text(p, (35, y - 0.3), f"{100 + k}")
    v = _open(win, tmp_path, d, "grade.pdf")
    v.apply_marks([(0, "add_polygon", {
        "pts": [list(T.P(0, b)), list(T.P(40, b)), list(T.P(40, b + 40)),
                list(T.P(0, b + 40))],
        "measure": {"type": "area", "value": 1600, "unit": "ft",
                    "group": "Site"}})])
    dlg = win.trade_takeoff(show=False)
    assert len(dlg.earth.find()) == 2
    res = dlg.earth.calculate()
    assert abs(res["fill"] - 29.6) < 1.5 and res["cut"] < 0.5
    assert dlg.earth.add() == 2
    vols = {it["group"]: it["value"] for it in annotate.takeoff_items(v.doc)
            if it["type"] == "volume"}
    assert abs(vols["Earthwork fill"] - res["fill"]) < 0.1
    dlg.close()


def test_finish_from_walls(qapp, win, tmp_path):
    v = _open(win, tmp_path, T.plumbing(), "walls2.pdf")
    v.apply_marks([(0, "add_line", {
        "pts": [list(T.P(0, 40)), list(T.P(50, 40))],
        "measure": {"type": "length", "value": 50, "unit": "ft",
                    "group": "Wall 5in"}})])
    dlg = win.trade_takeoff(show=False)
    dlg.finish.height.setValue(10)
    rows = dlg.finish.find()
    assert rows[0]["sf"] == 1000 and rows[0]["boards"] == 35
    assert dlg.finish.export(str(tmp_path / "fin.xlsx"))
    dlg.close()
