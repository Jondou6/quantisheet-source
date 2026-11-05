"""AI Takeoff accuracy, phase 2 part A (Aiken review #6/#7, N7/N9/N10 and
the Colleton County EOC findings C3, C6-C9, C11). Every drawing here is
made up in the test - no real project drawings.

(a) schedules: a door schedule is read (multi-line header, ruled
    columns); door tags on the plan agree with it; a tag repeated in a
    second view, a room number and a notes block are not counted twice;
    hardware sets are counted from the schedule's hardware column
(b) a plumbing fixture schedule: P-1.. counted on the plan (title block
    and keyed notes left out), checked against the QTY column
(c) a table whose cells don't line up is not confident -> review
(d) steel: column tags with leaders are a COUNT (never the leader
    length), height unknown -> no weight; a beam's length is its member
    line; members on two plans counted once; LB when the height is known
(e) ducts: only tagged groups whose width matches; fragments and absurd
    widths dropped; the rest to review
(f) civil: pipe drawn on the grading AND the utility plan counted once,
    from the utility plan, with a message that is true
(g) the split label "110 LF-4\"" with PVC on the next line
(h) a WALL TYPES sheet at 1-1/2" = 1'-0" (and a furniture plan) is not a
    plan for the rooms engine
(i) a raster-only sheet: "raster sheet, measure by hand"
"""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, civiltakeoff, schedules, structural  # noqa: E402,E501
from app import tradetakeoff as tt                                     # noqa: E402

PPU = 18.0                                   # 1/4" = 1'-0"
W, H = 1728, 1152
OX, OY = 120, 120
BLACK = (0, 0, 0)


def P(x, y):
    return (OX + x * PPU, OY + y * PPU)


def sheet(doc, number, title, scale="1/4\" = 1'-0\""):
    """A made-up sheet with a frame and a right-hand title block."""
    page = doc.new_page(width=W, height=H)
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(36, 36, W - 36, H - 36))
    sh.draw_rect(fitz.Rect(W - 300, 36, W - 36, H - 36))
    sh.finish(color=BLACK, width=1.5)
    sh.commit()
    page.insert_text((W - 285, H - 300), "MADE-UP TEST PROJECT", fontsize=9)
    page.insert_text((W - 285, H - 200), "SHEET TITLE:", fontsize=7)
    page.insert_text((W - 285, H - 182), title, fontsize=12)
    page.insert_text((W - 285, H - 110), f"SCALE: {scale}", fontsize=10)
    page.insert_text((W - 285, H - 60), number, fontsize=28)
    return page


def put(page, x, y, s, size=8):
    page.insert_text((x, y), s, fontsize=size)


def line(page, a, b, width=1.0, color=BLACK, dashes=None):
    sh = page.new_shape()
    sh.draw_line(a, b)
    sh.finish(color=color, width=width, dashes=dashes)
    sh.commit()


def table(page, x, y, title, header, rows, widths, ruled=True, size=8):
    """A schedule: title, a header (list of lines, each a list of cell
    texts), rows; ruled with vertical lines between the columns."""
    put(page, x, y, title, 12)
    xs = [x]
    for w in widths:
        xs.append(xs[-1] + w)
    yy = y + 22
    for hl in header:
        for i, t in enumerate(hl):
            if t:
                put(page, xs[i] + 4, yy, t, size)
        yy += 11
    top = y + 10
    yy += 4
    for r in rows:
        for i, t in enumerate(r):
            if t:
                put(page, xs[i] + 4, yy, t, size)
        yy += 13
    if ruled:
        sh = page.new_shape()
        for xx in xs:
            sh.draw_line((xx, top), (xx, yy - 6))
        sh.draw_line((xs[0], top), (xs[-1], top))
        sh.draw_line((xs[0], yy - 6), (xs[-1], yy - 6))
        sh.finish(color=BLACK, width=0.5)
        sh.commit()
    return yy


def view_title(page, x, y, t):
    put(page, x, y, t, 12)
    put(page, x, y + 14, "SCALE: 1/4\" = 1'-0\"", 8)


def rows_for(doc):
    """plan_set-like rows for schedules.takeoff without the whole reader."""
    out = []
    for i in range(doc.page_count):
        txt = doc[i].get_text()
        num = next((n for n in ("A-101", "A-801", "P-101", "P-301", "M-101",
                                "S-101", "S-201") if n in txt), "")
        title = ""
        for t in ("FLOOR PLAN", "DOOR SCHEDULE AND DETAILS",
                  "PLUMBING PLAN", "PLUMBING SCHEDULES"):
            if t in txt:
                title = t
                break
        out.append({"page": i, "number": num, "title": title,
                    "discipline": ait.discipline(num, title, txt),
                    "kind": ait.sheet_kind(title, txt), "raster": False})
    return out


# ---- (a) door schedule and door tags ------------------------------------------------
DOOR_HDR = [["DOOR", "WIDTH", "HEIGHT", "TYPE", "HDW"],
            ["NO.", "", "", "", "SET"]]
DOOR_W = [60, 60, 60, 50, 60]


def door_set(extra_row=False):
    d = fitz.open()
    p = sheet(d, "A-101", "FLOOR PLAN")
    # main view: door tags 101-103
    put(p, 200, 300, "101")
    put(p, 400, 300, "102")
    put(p, 600, 300, "103")
    put(p, 200, 302 + 0.2, "101")              # drawn twice on itself
    # a room tag whose number is a door number too
    put(p, 300, 500, "OFFICE", 10)
    put(p, 304, 512, "101")
    view_title(p, 150, 760, "FLOOR PLAN")
    # a second view repeats door 101
    put(p, 1050, 300, "101")
    view_title(p, 1000, 760, "MEZZANINE PLAN")
    # a notes block naming door 102 on a line of its own
    put(p, 150, 880, "GENERAL NOTES:", 10)
    put(p, 150, 895, "102")
    put(p, 190, 895, "HOLD OPEN DEVICE BY OWNER.")
    s = sheet(d, "A-801", "DOOR SCHEDULE AND DETAILS")
    rows = [["101", "3'-0\"", "7'-0\"", "A", "1.0"],
            ["102", "3'-0\"", "7'-0\"", "A", "2.0"],
            ["103", "3'-0\"", "7'-0\"", "B", "2.0"]]
    if extra_row:
        rows.append(["104", "3'-0\"", "7'-0\"", "B", "3.0"])
    table(s, 100, 100, "DOOR SCHEDULE", DOOR_HDR, rows, DOOR_W)
    return d


def test_a_door_schedule_is_read_with_its_columns():
    d = door_set()
    ts = schedules.read_page(d[1], "architectural")
    doors = [t for t in ts if t["kind"] == "door"]
    assert len(doors) == 1, [t["title"] for t in ts]
    t = doors[0]
    assert t["confident"], t["why"]
    assert t["columns"] == ["DOOR NO.", "WIDTH", "HEIGHT", "TYPE", "HDW SET"]
    assert t["key"] == "DOOR NO." and t["hw"] == "HDW SET"
    assert [r["DOOR NO."] for r in t["rows"]] == ["101", "102", "103"]
    assert t["rows"][2]["HDW SET"] == "2.0"
    assert t["csi"].startswith("08")
    # the sheet title "DOOR SCHEDULE AND DETAILS" in the title block is not
    # a second table
    assert all(x["bbox"][0] < W - 300 for x in ts)


def test_a_doors_agree_with_the_plan_tags_and_hardware_is_counted():
    d = door_set()
    res = schedules.takeoff(d, rows_for(d))
    by = {ln["name"]: ln for ln in res["lines"]}
    doors = by["Doors"]
    assert doors["status"] == "taken off", doors["why"]
    assert doors["qty"] == 3
    # one mark per door, at its tag on the plan (main view only)
    assert sorted(h["page"] for h in doors["hits"]) == [0, 0, 0]
    assert by["Hardware set 1.0"]["qty"] == 1
    assert by["Hardware set 2.0"]["qty"] == 2
    assert by["Hardware set 2.0"]["csi"] == "08 71 00"
    # the tag in the mezzanine view is listed, not counted
    rv = [x for x in res["review"] if x.get("key") == "101"]
    assert rv and "MEZZANINE PLAN" in rv[0]["why"], res["review"]


def test_a_doors_through_ai_takeoff():
    d = door_set()
    rows = ait.plan_set(d)
    by = {r["number"]: r for r in rows}
    assert "schedules" in by["A-801"]["engines"]        # not skipped
    assert by["A-801"]["kind"] == "detail"
    res = ait.run(d, rows, engines=["schedules"])
    tot = ait.totals(res)["schedules"]
    assert tot.get("Doors") == 3, tot
    assert tot.get("Hardware set 2.0") == 2, tot
    counts = [pl for _p, k, pl in res["marks"] if k == "add_count"]
    assert all(pl["measure"]["method"] == "AI takeoff: schedules"
               for pl in counts)
    assert {pl["measure"]["csi"][:2] for pl in counts} == {"08"}
    assert "From the schedules" in ait.summary_text(rows, res)


def test_a_a_door_with_no_tag_sends_the_doors_to_review():
    d = door_set(extra_row=True)
    res = schedules.takeoff(d, rows_for(d))
    by = {ln["name"]: ln for ln in res["lines"]}
    assert by["Doors"]["status"] == "review"
    assert "104" in by["Doors"]["why"]
    assert not by["Doors"]["hits"]
    # hardware counted from a schedule that doesn't agree: review too
    assert by["Hardware set 2.0"]["status"] == "review"
    assert any(x["name"] == "Doors" and x["qty"] == 4
               for x in res["review"])


# ---- (b) plumbing fixture schedule --------------------------------------------------
def plumbing_set():
    d = fitz.open()
    p = sheet(d, "P-101", "PLUMBING PLAN")
    for x, y, k in ((200, 300, "P-1"), (300, 300, "P-1"), (200, 450, "P-2"),
                    (300, 450, "P-2"), (500, 450, "P-3")):
        put(p, x, y, k)
    put(p, 700, 300, "SD-1 120")        # not a plumbing key
    # keyed notes: P-1 on a line of its own - not a fixture
    put(p, 900, 700, "KEYED NOTES:", 10)
    put(p, 900, 715, "P-1")
    put(p, 940, 715, "ROUGH-IN ONLY, FIXTURE BY OWNER.")
    put(p, W - 280, 600, "P-2")          # in the title block
    s = sheet(d, "P-301", "PLUMBING SCHEDULES")
    table(s, 100, 100, "PLUMBING FIXTURE SCHEDULE",
          [["MARK", "FIXTURE", "MANUFACTURER", "QTY"]],
          [["P-1", "WALL HUNG LAVATORY", "KOHLER K-2005", "2"],
           ["P-2", "WATER CLOSET", "KOHLER K-4325", "2"],
           ["P-3", "SINGLE BOWL SINK", "ELKAY LR-1918", "2"]],
          [50, 140, 120, 40])
    return d


def test_b_plumbing_fixtures_counted_on_the_plan():
    d = plumbing_set()
    res = schedules.takeoff(d, rows_for(d))
    by = {ln["key"]: ln for ln in res["lines"]}
    assert by["P-1"]["status"] == "taken off" and by["P-1"]["qty"] == 2
    assert by["P-1"]["name"] == "P-1 WALL HUNG LAVATORY"
    assert by["P-1"]["csi"] == "22 40 00"
    assert by["P-2"]["qty"] == 2 and by["P-2"]["status"] == "taken off"
    # schedule QTY 2, one tag on the plan: not guessed
    assert by["P-3"]["status"] == "review"
    assert "QTY says 2" in by["P-3"]["why"]
    assert any(x["key"] == "P-3" for x in res["review"])


def test_b_plan_area_leaves_out_title_block_and_notes():
    d = plumbing_set()
    info = schedules.sheet_info(d[0])
    ex = schedules.plan_exclusions(info)
    keys = {"P-1": "P-1", "P-2": "P-2", "P-3": "P-3"}
    c = schedules.count_tags(info, keys, "plumbing fixtures", ex)
    assert {k: len(v) for k, v in c["main"].items()} == \
        {"P-1": 2, "P-2": 2, "P-3": 1}


# ---- (c) columns that don't line up ------------------------------------------------
def test_c_misaligned_table_is_not_confident():
    d = fitz.open()
    s = sheet(d, "P-301", "PLUMBING SCHEDULES")
    put(s, 100, 100, "PLUMBING FIXTURE SCHEDULE", 12)
    for x, t in ((104, "MARK"), (200, "FIXTURE"), (330, "QTY")):
        put(s, x, 122, t)
    # every description runs across the QTY column
    for i, (k, desc) in enumerate((("P-1", "WALL HUNG LAVATORY WITH CARRIER"),
                                   ("P-2", "WATER CLOSET FLOOR MOUNTED TANK"),
                                   ("P-3", "SINK SINGLE BOWL STAINLESS"))):
        put(s, 104, 140 + 13 * i, k)
        put(s, 200, 140 + 13 * i, desc)
    ts = schedules.read_page(s, "plumbing")
    t = next(t for t in ts if t["kind"] == "plumbing fixtures")
    assert not t["confident"]
    assert "line up" in t["why"]


def test_c_schedule_titles_and_kinds():
    k = schedules.kind_of
    assert k("DOOR SCHEDULE") == "door"
    assert k("DOOR AND FRAME SCHEDULE") == "door"
    assert k("HARDWARE SETS") == "hardware"
    assert k("PLUMBING FIXTURE SCHEDULE") == "plumbing fixtures"
    assert k("FIXTURE SCHEDULE", "plumbing") == "plumbing fixtures"
    assert k("LIGHT FIXTURE SCHEDULE") == "light fixtures"
    assert k("DIFFUSER, REGISTER & GRILLE SCHEDULE") == "air devices"
    assert k("PLANT SCHEDULE") == "plants"
    assert k("TOILET ACCESSORY SCHEDULE") == "toilet accessories"
    assert k("EQUIPMENT SCHEDULE") == "equipment"
    assert k("FOOTING SCHEDULE") == "footing"
    assert k("FLOOR PLAN") is None
    assert schedules.CSI["plants"] == "32 93 00"
    assert schedules.CSI["air devices"] == "23 37 00"
    assert schedules.CSI["light fixtures"] == "26 51 00"
    assert schedules.CSI["equipment"] == "11 00 00"
    assert schedules.CSI["toilet accessories"] == "10 28 00"
    cells = schedules.make_cells([(10, 10, 80, 18, "SEE", 1, 0, 0),
                                  (84, 10, 110, 18, "DOOR", 1, 0, 1),
                                  (114, 10, 170, 18, "SCHEDULE", 1, 0, 2)])
    assert schedules.titles(cells) == []        # a reference, not a title
    assert schedules.hw_value("SET 1.0") == "1.0"
    assert schedules.hw_value("#3") == "3"


# ---- (d) steel: columns are counts, beams are their member lines ------------------
def steel_sheet(d, number, title, note=None):
    p = sheet(d, number, title)
    # grid bubbles: A B C across the top, 1 2 down the left
    for lab, gx in (("A", 0), ("B", 20), ("C", 40)):
        cx, cy = P(gx, -4)
        sh = p.new_shape()
        sh.draw_circle((cx, cy), 16)
        sh.finish(color=BLACK, width=0.6)
        sh.commit()
        p.insert_text((cx - 3.5, cy + 3.5), lab, fontsize=10)
    for lab, gy in (("1", 0), ("2", 20)):
        cx, cy = P(-4, gy)
        sh = p.new_shape()
        sh.draw_circle((cx, cy), 16)
        sh.finish(color=BLACK, width=0.6)
        sh.commit()
        p.insert_text((cx - 3, cy + 3.5), lab, fontsize=10)
    # three HSS columns (6" squares) at A2, B2, C2, each tagged off to the
    # side with a 6 ft diagonal leader
    for gx in (0, 20, 40):
        cx, cy = P(gx, 20)
        sh = p.new_shape()
        sh.draw_rect(fitz.Rect(cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5))
        sh.finish(color=BLACK, width=1.0)
        sh.commit()
        tx, ty = P(gx + 4.5, 24.5)
        line(p, (tx, ty - 8), (cx + 4.5, cy + 4.5), 0.5)
        put(p, tx, ty, "HSS4X4X1/4")
    # a W8X21 beam on grid 1 from A to B, tagged along it
    line(p, P(0, 0), P(20, 0), 1.4)
    put(p, P(8, -0.4)[0], P(8, -0.4)[1], "W8X21")
    if note:
        put(p, 150, 980, "STRUCTURAL NOTES:", 10)
        put(p, 150, 995, note)
    return p


def test_d_column_tags_with_leaders_are_counts_not_lengths():
    d = fitz.open()
    p = steel_sheet(d, "S-101", "FOUNDATION PLAN")
    ms = structural.members(p, PPU, "ft")
    cols = [m for m in ms if m["name"] == "HSS4X4X1/4"]
    assert len(cols) == 3, [(m["name"], m["kind"], m["why"]) for m in ms]
    assert all(m["kind"] == "column" for m in cols), cols
    assert all(m["length"] is None and m["why"] == "height unknown"
               for m in cols)
    beam = [m for m in ms if m["name"] == "W8X21"]
    assert len(beam) == 1 and beam[0]["kind"] == "beam"
    assert beam[0]["length"] == pytest.approx(20, abs=0.3)


def test_d_steel_on_two_plans_counted_once_with_weight_when_known():
    d = fitz.open()
    steel_sheet(d, "S-101", "FOUNDATION PLAN")
    steel_sheet(d, "S-201", "ROOF FRAMING PLAN")
    rows = ait.plan_set(d)
    assert all(r["engines"] == ["steel"] for r in rows), \
        [r["engines"] for r in rows]
    res = ait.run(d, rows)
    tot = ait.totals(res)
    assert tot["steel"].get("HSS4X4X1/4") == 3, tot["steel"]   # not 6
    assert tot["steel"].get("W8X21") == 1
    lens = [pl["measure"]["value"] for _p, k, pl in res["marks"]
            if pl["measure"]["group"] == "HSS4X4X1/4" and
            pl["measure"]["type"] != "count"]
    assert lens == []                     # never the leader's length
    q = {x["name"]: x for x in res["quantities"] if x["engine"] == "steel"}
    assert "HSS4X4X1/4" not in q          # height unknown: no weight
    assert q["W8X21"]["unit"] == "LB"
    assert q["W8X21"]["qty"] == pytest.approx(20 * 21, rel=0.02)
    assert any(x["name"] == "HSS4X4X1/4" and "height unknown" in x["why"]
               for x in res["review"])
    assert res["steel_dup"]


def test_d_steel_in_a_second_view_is_not_counted_twice():
    d = fitz.open()
    p = steel_sheet(d, "S-201", "ROOF FRAMING PLAN")
    view_title(p, 150, 640, "ROOF FRAMING PLAN")
    # the attic framing view repeats the W8X21 beam
    line(p, (1100, 300), (1100 + 20 * PPU, 300), 1.4)
    put(p, 1100 + 8 * PPU, 293, "W8X21")
    view_title(p, 1100, 640, "ATTIC FRAMING PLAN")
    rows = ait.plan_set(d)
    res = ait.run(d, rows)
    tot = ait.totals(res)["steel"]
    assert tot.get("W8X21") == 1, tot
    assert tot.get("HSS4X4X1/4") == 3, tot
    assert any(x["name"] == "W8X21" and "ATTIC FRAMING PLAN" in x["why"]
               for x in res["review"]), res["review"]


def test_d_column_height_from_a_note_gives_weight():
    d = fitz.open()
    p = steel_sheet(d, "S-101", "FOUNDATION PLAN",
                    note="STEEL COLUMN HEIGHT = 10'-3\" TYP.")
    ms = structural.members(p, PPU, "ft", note_text=p.get_text())
    cols = [m for m in ms if m["kind"] == "column"]
    assert cols and all(m["length"] == pytest.approx(10.25) for m in cols)
    assert structural.feet("10'-3\"") == pytest.approx(10.25)
    assert structural.dims("4'-0\" x 4'-0\" x 1'-0\"") == [4.0, 4.0, 1.0]


def test_d_footings_from_the_schedule_to_cy():
    lines = [{"kind": "footing", "key": "F4", "qty": 5, "status":
              "taken off", "page": 0, "why": ""},
             {"kind": "footing", "key": "WF2", "qty": 3, "status":
              "taken off", "page": 0, "why": ""}]
    tables = [{"kind": "footing", "key": "MARK",
               "columns": ["MARK", "SIZE", "REINFORCING"],
               "rows": [{"MARK": "F4", "SIZE": "4'-0\" x 4'-0\" x 1'-0\""},
                        {"MARK": "WF2", "SIZE": "2'-0\" x 1'-0\"",
                         "REINFORCING": "CONT."}]}]
    out = {f["mark"]: f for f in structural.footings(lines, tables)}
    assert out["F4"]["status"] == "taken off"
    assert out["F4"]["cy"] == pytest.approx(5 * 16 / 27)
    assert out["WF2"]["status"] == "review"
    assert "continuous" in out["WF2"]["why"]


# ---- (e) ducts ------------------------------------------------------------------------
def test_e_duct_groups_keep_tagged_and_drop_fragments(monkeypatch):
    def pc(L, w, x=0):
        return {"p0": (x, 0), "p1": (x + L * PPU, 0), "length": L,
                "length_ft": L, "width": w, "mid": (0, 0)}

    def by_tag(page, ppu, unit="ft", **k):
        return ([
            {"name": "24x12", "w": 24, "h": 12, "tagged": True,
             "lbsf": 1.156, "pieces": [pc(30, 24), pc(0.34, 24, 900)]},
            {"name": '10" round', "w": 10, "h": None, "tagged": True,
             "lbsf": 0.906, "pieces": [pc(12, 10, 2000)]},
            {"name": "66x20", "w": 66, "h": 20, "tagged": True,
             "lbsf": 1.5, "pieces": [pc(8, 66, 4000)]}],
            [{"name": "Duct 10in wide", "length": 4.0,
              "why": "duct-width lines with no size tag near"}])

    def loose(page, ppu, unit="ft", **k):
        return [
            {"name": "24x12", "w": 24, "h": 12, "tagged": True,
             "pieces": [pc(30, 24)]},
            {"name": "Duct 18in wide", "w": 18, "h": None, "tagged": False,
             "pieces": [pc(20, 18, 3000)]},
            {"name": "Duct 103in wide", "w": 103, "h": None,
             "tagged": False, "pieces": [pc(0.5, 103, 5000)]}]
    monkeypatch.setattr(tt, "ducts_by_tag", by_tag)
    monkeypatch.setattr(tt, "ducts", loose)
    kept, review, dropped = ait.duct_groups(None, PPU, "ft")
    by = {g["name"]: g for g in kept}
    assert set(by) == {"24x12", '10" round'}
    assert by["24x12"]["length"] == pytest.approx(30)
    assert by["24x12"]["sf"] == pytest.approx(2 * 36 / 12 * 30)
    assert by['10" round']["length"] == pytest.approx(12)
    rv = {n: (L, why) for n, L, why in review}
    assert rv["Duct 18in wide"][0] == pytest.approx(20)
    assert "no size tag" in rv["Duct 18in wide"][1]
    assert rv["Duct 10in wide"][0] == pytest.approx(4)
    assert "over 60 in wide" in rv["66x20"][1]
    assert "Duct 103in wide" not in rv
    assert dropped == 2                  # 0.34 LF, the 103 in fragment


def test_e_ducts_follow_the_run_from_the_tag():
    """A tagged size is followed along its run (pieces joined end to
    end), and a duct face never pairs with a wall far across the room."""
    d = fitz.open()
    p = sheet(d, "M-101", "MECHANICAL PLAN")
    # a 12" round in three straight pieces (40 ft), tagged once at the start
    for x0, x1 in ((5, 15), (15.5, 30), (30.5, 45)):
        line(p, P(x0, 20), P(x1, 20))
        line(p, P(x0, 21), P(x1, 21))
    put(p, *P(7, 19.3), '12" round')
    # a wall 4 ft away, drawn in the same style: never part of the duct
    line(p, P(5, 25), P(45, 25))
    kept, review, dropped = ait.duct_groups(d[0], 18.0, "ft")
    by = {g["name"]: g for g in kept}
    assert by['12" round']["length"] == pytest.approx(39.0, abs=1.5), by
    assert all(abs(pc["width"] - 12) <= 1.5 for pc in
               by['12" round']["pieces"])


def test_e_ducts_on_a_mechanical_plan_through_ai_takeoff():
    d = fitz.open()
    p = sheet(d, "M-101", "MECHANICAL PLAN")
    line(p, P(5, 10), P(35, 10))
    line(p, P(5, 12), P(35, 12))
    put(p, *P(18, 11.3), "24x12")
    # an untagged 18" duct far from any tag
    line(p, P(5, 40), P(25, 40))
    line(p, P(5, 41.5), P(25, 41.5))
    rows = ait.plan_set(d)
    assert "ducts" in rows[0]["engines"]
    res = ait.run(d, rows, engines=["ducts"])
    tot = ait.totals(res)["ducts"]
    assert tot.get("24x12") == pytest.approx(30, abs=0.6), tot
    assert all(n == "24x12" for n in tot), tot
    marks = [pl["measure"] for _p, _k, pl in res["marks"]]
    assert marks and all(m["method"] == "AI takeoff: ducts" for m in marks)
    assert any(x.get("engine") == "ducts" and "no size tag" in x["why"]
               for x in res["review"]), res["review"]


# ---- (f) civil: grading AND utility plans counted once --------------------------------
def test_f_civil_pipe_from_one_plan(monkeypatch):
    d = fitz.open()
    sheet(d, "C-201", "GRADING AND DRAINAGE PLAN", "1\" = 20'")
    sheet(d, "C-301", "UTILITY PLAN", "1\" = 20'")
    run_ = {"pts": [(0, 0), (100, 0)], "depth": None}
    storm = {"name": '8" PVC storm', "existing": False, "size": 8,
             "system": "storm", "material": "PVC",
             "runs": [dict(run_, page=0, length=919.4),
                      dict(run_, page=1, length=919.4)],
             "bands": {"unknown": 1838.8}, "length": 1838.8,
             "label_length": 1800.0, "label_by_page": {0: 900.0, 1: 900.0},
             "pages": [0, 1]}
    monkeypatch.setattr(civiltakeoff, "takeoff", lambda *a, **k: {
        "pipes": [storm], "structures": [], "pages": [0, 1],
        "checks": ['8" PVC storm: measured 1839 LF but the labels add up '
                   'to 900 LF (+104%) - check it on the plan'],
        "grade": None})
    rows = ait.plan_set(d)
    assert [r["engines"] for r in rows] == [["civil"], ["civil"]]
    res = ait.run(d, rows)
    tot = ait.totals(res)
    assert tot["pipe"] == {'8" PVC storm': pytest.approx(919.4)}, tot["pipe"]
    msg = [p for p in res["problems"] if p.startswith('8" PVC storm: drawn')]
    assert msg and "taken from C-301 only" in msg[0] and \
        "C-201 not counted again" in msg[0], res["problems"]
    assert not any("utility plans only" in p for p in res["problems"])
    assert not any("+104%" in p for p in res["problems"])
    pages = {p for p, _k, pl in res["marks"]}
    assert pages == {1}


def test_f_two_utility_plans_of_different_areas_add_up():
    rows_by_page = {0: {"number": "C-301", "title": "UTILITY PLAN - AREA A"},
                    1: {"number": "C-302", "title": "UTILITY PLAN - AREA B"}}
    g = {"name": '6" PVC sanitary', "existing": False, "runs": [
        {"page": 0, "length": 100.0, "depth": None},
        {"page": 1, "length": 50.0, "depth": None}], "length": 150.0,
        "label_length": 0.0}
    cres = {"pipes": [g], "checks": []}
    assert ait.civil_same_pipe(cres, rows_by_page) == []
    assert g["length"] == 150.0
    assert ait.civil_rank("GRADING AND DRAINAGE PLAN") == 2
    assert ait.civil_rank("UTILITY PLAN") == 0
    assert ait.civil_rank("SANITARY SEWER PLAN") == 1


# ---- (g) split label ------------------------------------------------------------------
def test_g_length_label_with_the_material_on_the_next_line():
    d = fitz.open()
    p = d.new_page(width=800, height=600)
    p.insert_text((100, 100), "110 LF-4\"", fontsize=8)
    p.insert_text((104, 110), "PVC", fontsize=8)
    p.insert_text((400, 100), "8\" PVC SAN", fontsize=8)
    labs = civiltakeoff.pipe_labels(p)
    by = {l["name"]: l for l in labs}
    assert set(by) == {'4" PVC sanitary', '8" PVC sanitary'}, list(by)
    assert by['4" PVC sanitary']["length"] == 110
    assert civiltakeoff.SPLIT_LABEL.match('110 LF-4"')
    assert civiltakeoff.SPLIT_LABEL.match('4" - 110 LF')
    assert not civiltakeoff.SPLIT_LABEL.match('8" PVC SAN')
    assert civiltakeoff.parse_pipe_label('110 LF-4"') is None


# ---- (h) not a plan for the rooms engine ----------------------------------------------
def test_h_wall_types_and_detail_scales_are_not_room_plans():
    d = fitz.open()
    sheet(d, "A-103", "WALL TYPES", "1-1/2\" = 1'-0\"")
    sheet(d, "A-107", "FURNITURE PLAN")
    sheet(d, "A-110", "ENLARGED TOILET PLAN", "1-1/2\" = 1'-0\"")
    sheet(d, "A-101", "FLOOR PLAN")
    rows = ait.plan_set(d)
    by = {r["number"]: r for r in rows}
    for n in ("A-103", "A-107", "A-110"):
        assert "rooms" not in by[n]["engines"], (n, by[n])
        assert "rooms" not in by[n]["wanted"], (n, by[n])
    assert by["A-103"]["kind"] == "detail"
    assert "detail scale" in by["A-110"]["note"]
    assert by["A-101"]["engines"] == ["rooms"]
    assert ait.rooms_reason("WALL TYPES", None)
    assert ait.rooms_reason("FLOOR PLAN", ("1-1/2\" = 1'-0\"", 108.0, "ft"))
    assert not ait.rooms_reason("FLOOR PLAN", ("1/4\" = 1'-0\"", 18.0, "ft"))


# ---- (i) raster-only sheets -----------------------------------------------------------
def test_i_raster_sheet_is_reported_not_measured():
    d = fitz.open()
    p = d.new_page(width=W, height=H)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 48), False)
    pix.clear_with(200)
    p.insert_image(fitz.Rect(20, 20, W - 20, H - 20), pixmap=pix)
    v = sheet(d, "A-201", "FLOOR PLAN")          # vector, with a logo
    v.insert_image(fitz.Rect(W - 280, 60, W - 200, 100), pixmap=pix)
    assert ait.raster_only(d[0])
    assert not ait.raster_only(d[1])
    rows = ait.plan_set(d)
    assert rows[0]["kind"] == "raster" and rows[0]["engines"] == []
    assert "raster sheet, measure by hand" in rows[0]["note"]
    assert rows[1]["kind"] == "plan"
    res = ait.run(d, rows, engines=[])
    assert "Raster sheets, measure by hand" in ait.summary_text(rows, res)
