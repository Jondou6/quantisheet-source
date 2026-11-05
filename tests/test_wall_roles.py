"""Walls by role: the walls Auto Walls finds, sorted into Exterior /
Corridor / Restroom / Shaft / Demising / Interior from the sheet's room
names, each role its own takeoff group."""
import os

import fitz

from app import wall_roles as wr

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from test_gui import win, qapp                     # noqa: F401
except Exception:                  # no Qt here: the geometry tests still run
    win = qapp = None

P = 10.0                                   # points per foot (synthetic)


def W(x0, y0, x1, y1, th):
    return {"p0": (x0 * P, y0 * P), "p1": (x1 * P, y1 * P),
            "thickness": th, "length": ((x1 - x0) ** 2 +
                                        (y1 - y0) ** 2) ** 0.5}


def L(text, x, y):
    kind, tenant = wr.classify_label(text)
    return {"text": text, "pt": (x * P, y * P), "kind": kind,
            "tenant": tenant}


# a 60' x 40' floor: two suites over a corridor, a restroom and storage
# under it; 3' doors; a 4' exterior door at the corridor's end
PLAN = [W(0, 0, 60, 0, 8), W(0, 40, 60, 40, 8), W(0, 0, 0, 40, 8),
        W(60, 0, 60, 19, 8), W(60, 23, 60, 40, 8),               # 0-4
        W(0, 18, 10, 18, 5), W(13, 18, 45, 18, 5), W(48, 18, 60, 18, 5),
        W(0, 24, 5, 24, 5), W(8, 24, 30, 24, 5), W(33, 24, 60, 24, 5),
        W(30, 0, 30, 18, 6),                                     # 11
        W(15, 24, 15, 40, 5)]                                    # 12
PLAN_LABELS = [L("SUITE 101", 15, 9), L("SUITE 102", 45, 9),
               L("CORRIDOR", 20, 21), L("RESTROOM", 7, 32)]


def _roles_by_wall(pieces):
    out = {}
    for p in pieces:
        out.setdefault(p["wall"], []).append((p["role"], p["length"]))
    return out


def test_labels():
    assert wr.classify_label("MEN'S TOILET") == ("restroom", None)
    assert wr.classify_label("WOMEN 112")[0] == "restroom"
    assert wr.classify_label("CORR. 100")[0] == "corridor"
    assert wr.classify_label("HALL")[0] == "corridor"
    assert wr.classify_label("ELEV 2")[0] == "shaft"
    assert wr.classify_label("STAIR 1")[0] == "shaft"
    assert wr.classify_label("MECH SHAFT")[0] == "shaft"
    assert wr.classify_label("ELEV. LOBBY") == (None, None)
    assert wr.classify_label("TENANT A") == ("tenant", "TENANT A")
    assert wr.classify_label("Suite 200") == ("tenant", "SUITE 200")
    assert wr.classify_label("UNIT HEATER") == (None, None)
    assert wr.classify_label("OFFICE 101") == (None, None)
    words = [(140, 85, 160, 95, "SUITE", 0, 0, 0),
             (161, 85, 175, 95, "101", 0, 0, 1),
             (300, 300, 340, 310, "OFFICE", 1, 0, 0),
             (50, 315, 90, 325, "TOILET", 2, 0, 0)]
    labs = wr.labels_from_words(words)
    assert [(lb["kind"], lb["tenant"]) for lb in labs] == \
        [("tenant", "SUITE 101"), ("restroom", None)]
    assert labs[0]["pt"] == (157.5, 90.0)


def test_roles_on_a_small_plan():
    pieces = wr.classify(PLAN, PLAN_LABELS, P, "ft")
    by = _roles_by_wall(pieces)
    for i in range(5):
        assert [r for r, _ in by[i]] == ["Exterior"], (i, by[i])
    for i in (5, 6, 7, 10):
        assert [r for r, _ in by[i]] == ["Corridor"], (i, by[i])
    assert [r for r, _ in by[8]] == ["Restroom"]
    assert [r for r, _ in by[12]] == ["Restroom"]
    assert [r for r, _ in by[11]] == ["Demising"]
    # the corridor wall over the restroom changes role where the
    # restroom ends (x = 15'), to within about a wall's thickness
    assert [r for r, _ in by[9]] == ["Restroom", "Corridor"]
    assert abs(by[9][0][1] - 7.0) < 1.0
    sm = wr.summary(pieces)
    assert list(sm) == ["Exterior", "Restroom", "Corridor", "Demising"]
    assert abs(sm["Exterior"] - 196) < 0.01
    assert abs(sm["Demising"] - 18) < 0.01
    assert abs(sum(sm.values()) - sum(w["length"] for w in PLAN)) < 0.01


def test_shaft_beats_corridor_and_one_tenant_is_not_demising():
    walls = [W(0, 0, 30, 0, 8), W(0, 20, 30, 20, 8), W(0, 0, 0, 20, 8),
             W(30, 0, 30, 20, 8), W(10, 0, 10, 20, 5), W(20, 0, 20, 8, 5),
             W(20, 12, 20, 20, 5)]
    labs = [L("ELEV 1", 5, 10), L("HALL", 15, 10), L("TENANT A", 25, 4)]
    by = _roles_by_wall(wr.classify(walls, labs, P))
    assert [r for r, _ in by[4]] == ["Shaft"]
    # the wall at x=20 (with a 4' door) has the hall on one side
    assert {r for i in (5, 6) for r, _ in by[i]} == {"Corridor"}


def test_demising_spreads_through_doors_within_a_suite():
    """Tenant names sit in one room; the wall between that tenant's back
    office and the next tenant is still demising."""
    walls = [W(0, 0, 40, 0, 8), W(0, 30, 40, 30, 8), W(0, 0, 0, 30, 8),
             W(40, 0, 40, 30, 8),
             W(20, 0, 20, 30, 6),                      # 4: the demising
             W(0, 15, 8, 15, 5), W(11, 15, 20, 15, 5)]  # suite A: 2 rooms
    labs = [L("SUITE 101", 10, 25), L("SUITE 102", 30, 15)]
    by = _roles_by_wall(wr.classify(walls, labs, P))
    assert [r for r, _ in by[4]] == ["Demising"]
    assert [r for r, _ in by[5]] == ["Interior"]


def test_corridor_branch_closed_off_by_a_bridge_is_still_corridor():
    walls = [W(0, 0, 60, 0, 8), W(0, 40, 60, 40, 8), W(0, 0, 0, 40, 8),
             W(60, 0, 60, 40, 8),
             W(0, 18, 60, 18, 5), W(0, 24, 27, 24, 5), W(33, 24, 60, 24, 5),
             W(27, 24, 27, 40, 5), W(33, 24, 33, 40, 5)]
    by = _roles_by_wall(wr.classify(walls, [L("CORRIDOR", 10, 21)], P))
    assert [r for r, _ in by[7]] == ["Corridor"]
    assert [r for r, _ in by[8]] == ["Corridor"]


def test_storefront_opening_does_not_make_rooms_exterior():
    """A 12' storefront (wider than a door bridge) lets the outside into
    suite 101: its partition is still not an exterior wall."""
    walls = [W(0, 0, 4, 0, 8), W(16, 0, 40, 0, 8), W(0, 20, 40, 20, 8),
             W(0, 0, 0, 20, 8), W(40, 0, 40, 20, 8), W(20, 0, 20, 20, 5)]
    by = _roles_by_wall(wr.classify(
        walls, [L("SUITE 101", 10, 10), L("SUITE 102", 30, 10)], P))
    for i in range(5):
        assert [r for r, _ in by[i]] == ["Exterior"]
    assert [r for r, _ in by[5]] == ["Interior"]


def test_sheet_border_is_left_out_and_marks():
    border = [W(0.5, 0.5, 78.7, 0.5, 12), W(0.5, 60.7, 78.7, 60.7, 12)]
    walls = [W(10, 10, 30, 10, 8), W(10, 30, 30, 30, 8),
             W(10, 10, 10, 30, 8), W(30, 10, 30, 30, 8)] + border
    pieces = wr.classify(walls, [], P, page_rect=(0, 0, 792, 612))
    assert {p["wall"] for p in pieces} == {0, 1, 2, 3}
    assert {p["role"] for p in pieces} == {"Exterior"}
    ms = wr.marks(0, pieces, {"ppu": P, "unit": "ft"})
    assert len(ms) == 4 and ms[0][1] == "add_line"
    m = ms[0][2]["measure"]
    assert m["group"] == "Exterior Walls" and m["type"] == "length"
    assert wr.role_of_group("Exterior Walls") == "Exterior"
    assert wr.role_of_group("Wall 8in") is None


# ---- on a real PDF ------------------------------------------------------------------------
PPU = 9.0                                   # 1/8" = 1'-0"
OX, OY = 72.0, 72.0


def _plan_pdf():
    """PLAN drawn the CAD way: each wall a thin filled rectangle (its two
    faces), run on through the walls it meets; room names as text."""
    d = fitz.open()
    page = d.new_page(width=792, height=612)
    sh = page.new_shape()
    for w in PLAN:
        (x0, y0), (x1, y1) = [(v / P) for v in w["p0"]], \
            [(v / P) for v in w["p1"]]
        t = w["thickness"] / 12.0
        if y0 == y1:                     # horizontal
            r = fitz.Rect(OX + (x0 - t / 2) * PPU, OY + (y0 - t / 2) * PPU,
                          OX + (x1 + t / 2) * PPU, OY + (y0 + t / 2) * PPU)
        else:
            r = fitz.Rect(OX + (x0 - t / 2) * PPU, OY + (y0 - t / 2) * PPU,
                          OX + (x0 + t / 2) * PPU, OY + (y1 + t / 2) * PPU)
        sh.draw_rect(r)
    sh.finish(color=(0, 0, 0), fill=(0.6, 0.6, 0.6), width=0.5)
    sh.commit()
    for lab in PLAN_LABELS:
        x, y = lab["pt"][0] / P, lab["pt"][1] / P
        page.insert_text((OX + (x - 3) * PPU, OY + y * PPU), lab["text"],
                         fontsize=7)
    from app import annotate
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft",
                                         name='1/8" = 1\'-0"'))
    return d


def test_walls_by_role_from_a_pdf():
    d = _plan_pdf()
    pieces, labels = wr.find(d[0], PPU, "ft")
    assert {lb["kind"] for lb in labels} == {"tenant", "corridor",
                                             "restroom"}
    sm = wr.summary(pieces)
    assert {"Exterior", "Corridor", "Restroom", "Demising"} <= set(sm), sm
    assert abs(sm["Demising"] - 18) < 1.5, sm
    assert abs(sm["Exterior"] - 196) < 8, sm
    assert 85 < sm["Corridor"] < 105, sm


def test_walls_by_role_in_the_app(qapp, win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from app import annotate, takeoff_assist_ui as tau, wall_roles
    path = str(tmp_path / "roles.pdf")
    _plan_pdf().save(path)
    win.open_path(path)
    v = win._view
    # the review table: change one wall's role before adding
    seen = {}

    def fake_exec(dlg):
        seen["n"] = len(dlg.pieces)
        i = next(k for k, p in enumerate(dlg.pieces)
                 if p["role"] == "Demising")
        dlg.combos[i].setCurrentText("Shaft")
        assert dlg.pieces[i]["role"] == "Shaft"
        assert "Shaft Walls" in dlg.info.text()
        return QDialog.Accepted
    monkeypatch.setattr(tau.WallRolesDialog, "exec", fake_exec)
    sm = tau.walls_by_role(win)
    assert sm and seen["n"] >= 10
    assert "Shaft" in sm and "Demising" not in sm
    items = annotate.takeoff_items(v.doc)
    groups = {it["group"] for it in items}
    assert {"Exterior Walls", "Corridor Walls", "Restroom Walls",
            "Shaft Walls"} <= groups
    # move one wall to another role after the fact
    a = next(a for a in annotate.iter_annots(v.pg)
             if ":Corridor Walls" in ((a.info or {}).get("subject") or ""))
    v.select(a)
    assert tau.change_wall_role(win, "Interior") == 1
    groups = [it["group"] for it in annotate.takeoff_items(v.doc)]
    assert "Interior Walls" in groups
    # one undo step per change
    win.undo()
    assert "Interior Walls" not in {it["group"] for it in
                                    annotate.takeoff_items(v.doc)}
    win.undo()
    assert not [it for it in annotate.takeoff_items(v.doc)
                if wall_roles.role_of_group(it["group"])]
    # nothing selected: nothing happens, no dialog
    v.select(None)
    assert tau.change_wall_role(win, "Shaft") == 0


# ---- no footprint, no "freestanding" (Aiken A-102, 0.13.6 review #11) -----

def test_open_outline_keeps_exterior_walls_exterior():
    """Walls Auto Walls found only in part (the outline doesn't close):
    walls with outside on a face stay Exterior; nothing becomes
    Freestanding without a building footprint."""
    walls = [W(0, 0, 60, 0, 8), W(0, 0, 0, 40, 8), W(60, 0, 60, 15, 8),
             W(0, 18, 25, 18, 5)]
    pieces = wr.classify(walls, [L("OFFICE", 10, 9)], P, "ft")
    roles = {p["role"] for p in pieces}
    assert "Freestanding" not in roles
    ext = sum(p["length"] for p in pieces if p["role"] == "Exterior")
    assert ext > 60


def test_outline_around_part_of_the_walls_is_not_the_exterior():
    """A loop that closes around one small room while most walls are
    outside it is not taken as the building's exterior wall."""
    walls = [W(0, 0, 12, 0, 8), W(0, 10, 12, 10, 8), W(0, 0, 0, 10, 8),
             W(12, 0, 12, 10, 8),                     # a closed 12x10 box
             W(30, 0, 120, 0, 8), W(30, 0, 30, 60, 8), W(120, 0, 120, 60, 8),
             W(30, 60, 70, 60, 8)]                    # the rest, open
    ext = wr.exterior_outline(walls, P, "ft")
    assert ext["outer_face_lf"] is None
    assert any("part of the walls" in f for f in ext["flags"])


def test_outline_inside_another_drawing_on_the_sheet_is_left_out():
    """The floor plan and a mezzanine plan drawn beside it on one sheet:
    the mezzanine's outline is not a second building."""
    def box(x, y, w, h):
        return [W(x, y, x + w, y, 8), W(x, y + h, x + w, y + h, 8),
                W(x, y, x, y + h, 8), W(x + w, y, x + w, y + h, 8)]
    walls = box(0, 0, 60, 40) + box(100, 0, 25, 25)
    both = wr.exterior_outline(walls, P, "ft")
    assert both["loops"] == 2
    view = ((95 * P, -5 * P, 130 * P, 30 * P), "MEZZANINE FLOOR PLAN")
    one = wr.exterior_outline(walls, P, "ft", other_views=[view])
    assert one["loops"] == 1
    assert abs(one["outer_face_lf"] - both["outer_face_lf"] + 100) < 6
    assert any("MEZZANINE" in f for f in one["flags"])
