"""AI Takeoff wiring, phase 2B: the rooms, finishes and walls engines in
the whole-set run (and the Aiken harness lines they make). Every drawing
here is made up in the test - no real project drawings.

(a) a two-plan set (floor plan + finish plan, the same rooms) with a room
    finish schedule: floor / base / ceiling / wall finish lines once, not
    twice, with their CSI divisions; the harness maps them
(b) a WALL TYPES legend sheet + a floor plan (and a dimension plan of the
    same floor): LF per wall type once, CMU type 04 22 00, partitions
    09 21 16, SF where the legend gives the height, "height unknown"
    otherwise, the exterior wall as its outer face loop
(c) a room the tracer flags for review is in res["review"]; overlapping
    traces make a problem line
(d) a rooms pass stopped by its time budget is listed unfinished
(e) every Group_ID the map names is in the reviewer's Mapping sheet (when
    the workbook is on this computer)

The room tracer itself (autotakeoff.all_rooms, tested in
test_rooms_walls_phase2) is replaced here by made-up results, so these
tests check the wiring.
"""
import json
import math
import os
import sys

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, autotakeoff  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PPU = 18.0                                   # 1/4" = 1'-0"
W, H = 1728, 1152
OX, OY = 120, 160
BLACK = (0, 0, 0)


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


def table(page, x, y, title, header, rows, widths, size=8):
    """A ruled schedule: title, header lines, rows."""
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
    sh = page.new_shape()
    for xx in xs:
        sh.draw_line((xx, top), (xx, yy - 6))
    sh.draw_line((xs[0], top), (xs[-1], top))
    sh.draw_line((xs[0], yy - 6), (xs[-1], yy - 6))
    sh.finish(color=BLACK, width=0.5)
    sh.commit()
    return yy


def fake_rooms(by_page, info_by_page=None, calls=None):
    """A stand-in for autotakeoff.all_rooms: made-up rooms per page
    number, and what the caller passed."""
    def all_rooms(page, scale, progress=None, skip_measured=True,
                  budget_s=None, info=None):
        if calls is not None:
            calls.append({"page": page.number, "budget_s": budget_s,
                          "info": info is not None})
        info = {} if info is None else info
        info.update({"stopped": False, "why": "", "ignored": [],
                     "overlaps": 0, "elapsed": 0.01})
        info.update((info_by_page or {}).get(page.number, {}))
        if info.get("stopped"):
            return [], [{"name": r["name"]} for r in
                        by_page.get(page.number, [])]
        return [dict(r, flags=list(r.get("flags", ())))
                for r in by_page.get(page.number, [])], []
    return all_rooms


def room(name, number, sf, perim, x, y, w=10, h=10, review=False,
         flags=()):
    pts = [fitz.Point(OX + x * PPU, OY + y * PPU),
           fitz.Point(OX + (x + w) * PPU, OY + y * PPU),
           fitz.Point(OX + (x + w) * PPU, OY + (y + h) * PPU),
           fitz.Point(OX + x * PPU, OY + (y + h) * PPU)]
    return {"pts": pts, "sqft": float(sf), "value": float(sf),
            "unit": "sq ft", "name": name, "number": number,
            "tag_sf": float(sf), "net_sf": float(sf),
            "perimeter_lf": float(perim), "flags": list(flags),
            "review": review, "trace_confidence": 0.5 if review else 0.95}


def quantities(res, engine):
    return {(q["name"], q["unit"]): q for q in res["quantities"]
            if q["engine"] == engine}


# ---- (a) finishes once from a two-plan set -------------------------------------
FIN_HDR = [["ROOM", "ROOM", "FLOOR", "BASE", "WALL", "CEILING", "CEILING"],
           ["NO.", "NAME", "", "", "", "", "HEIGHT"]]
FIN_W = [50, 90, 50, 45, 50, 60, 60]


def finish_set():
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    sheet(d, "A-102", "FINISH PLAN")
    p = sheet(d, "A-601", "ROOM FINISH SCHEDULE")
    table(p, 200, 200, "ROOM FINISH SCHEDULE", FIN_HDR,
          [["101", "OFFICE", "EPX", "RB", "PT-1", "ACT", "9'-0\""],
           ["102", "CORRIDOR", "PC", "RB", "PT-1", "GB", "10'-0\""],
           ["103", "STORAGE", "PC", "EPX", "PT-1 / CWT", "ACT", "8'-0\""]],
          FIN_W)
    rs = [room("OFFICE 101", "101", 200, 60, 0, 0, 20, 10),
          room("CORRIDOR 102", "102", 150, 70, 0, 12, 30, 5),
          room("STORAGE 103", "103", 80, 36, 22, 0, 10, 8)]
    return d, {0: rs, 1: [dict(r) for r in rs]}


def test_a_finish_lines_once_from_a_two_plan_set(monkeypatch):
    d, by = finish_set()
    monkeypatch.setattr(autotakeoff, "all_rooms", fake_rooms(by))
    rows = ait.plan_set(d)
    num = {r["number"]: r for r in rows}
    assert "rooms" in num["A-101"]["engines"]
    assert "rooms" in num["A-102"]["engines"]
    assert "schedules" in num["A-601"]["engines"]
    res = ait.run(d, rows)
    # the rooms once, from the floor plan
    assert res["rooms_dup"] and all(kp == 0 for _r, kp, _p in res["rooms_dup"])
    assert res["finishes"] is not None
    q = quantities(res, "finishes")
    assert q[("Floor EPX", "SF")]["qty"] == pytest.approx(200)
    assert q[("Floor PC", "SF")]["qty"] == pytest.approx(230)   # not 460
    assert q[("Base RB", "LF")]["qty"] == pytest.approx(130)
    assert q[("Base EPX", "LF")]["qty"] == pytest.approx(36)
    assert q[("Ceiling ACT", "SF")]["qty"] == pytest.approx(280)
    assert q[("Ceiling GB", "SF")]["qty"] == pytest.approx(150)
    assert q[("Wall finish PT-1", "SF")]["qty"] == pytest.approx(
        60 * 9 + 70 * 10)
    assert q[("Wall finish PT-1 / CWT", "SF")]["qty"] == pytest.approx(
        36 * 8)
    csi = {k[0]: v["csi"] for k, v in q.items()}
    assert csi["Floor EPX"] == "09 67 23"
    assert csi["Floor PC"] == "03 35 00"
    assert csi["Base RB"] == "09 65 13"
    assert csi["Base EPX"] == "09 67 23"
    assert csi["Ceiling ACT"] == "09 51 13"
    assert csi["Ceiling GB"] == "09 29 00"
    assert csi["Wall finish PT-1"] == "09 91 00"
    assert any("mixes finishes" in p for p in res["problems"])
    # in the totals and the summary, once
    tot = ait.totals(res)["finishes"]
    assert tot[("Floor PC", "SF")] == pytest.approx(230)
    text = ait.summary_text(rows, res)
    assert "Finishes" in text and "Floor EPX: 200 SF" in text
    assert text.count("Floor PC:") == 1
    # every room is in the schedule: none sent to review for its finishes
    assert not [x for x in res["review"] if x.get("engine") == "finishes"]
    # the harness reads them as lines and the map takes them to the
    # human groups
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import aiken_eval
    lines, _t = aiken_eval.ai_lines(d, rows, res)
    by = {(ln["key"], ln["status"]): ln for ln in lines}
    assert by[("finishes:Floor EPX", "taken off")]["qty"] == pytest.approx(
        200)
    assert by[("finishes:Floor EPX", "taken off")]["csi"] == "09"
    assert by[("finishes:Floor PC", "taken off")]["csi"] == "03"
    mp = aiken_eval.load_map(aiken_eval.MAP)
    g = {k: aiken_eval.map_line(k, mp[1], mp[2]) for k in
         ("finishes:Floor EPX", "finishes:Floor PC", "finishes:Base RB",
          "finishes:Base EPX", "finishes:Ceiling ACT",
          "finishes:Ceiling ACT / GB", "finishes:Wall finish PT-1 / CWT",
          "finishes:Wall finish EPP-1", "finishes:Wall finish WP-1")}
    assert g == {"finishes:Floor EPX": "H09-EPX-FLOOR",
                 "finishes:Floor PC": "H03-POLISH",
                 "finishes:Base RB": "H09-RB",
                 "finishes:Base EPX": "H09-EPX-BASE",
                 "finishes:Ceiling ACT": "H09-CEIL-ALL",
                 "finishes:Ceiling ACT / GB": "H09-CEIL-ALL",
                 "finishes:Wall finish PT-1 / CWT": "H09-PAINT-WALL",
                 "finishes:Wall finish EPP-1": "H09-EPP1-WALL",
                 "finishes:Wall finish WP-1": "H09-WALLPANEL"}


def test_a_finish_rows_and_codes():
    t = {"kind": "finish", "confident": True, "key": "ROOM NO.",
         "page": 4, "columns": ["ROOM NO.", "ROOM NAME", "FLOOR FINISH",
                                "BASE", "WALL FINISH", "CEILING MATERIAL",
                                "CEILING FINISH", "CEILING HEIGHT"],
         "rows": [{"ROOM NO.": "101", "ROOM NAME": "LOBBY",
                   "FLOOR FINISH": "PC", "BASE": "RB",
                   "WALL FINISH": "PT-1 / PT-2", "CEILING MATERIAL": "ACT",
                   "CEILING FINISH": "ACT-1", "CEILING HEIGHT": "9'-0\"",
                   "_key_rect": (0, 0, 1, 1)}]}
    rows, bad = ait.finish_rows([t])
    assert not bad
    r = rows[0]
    assert (r["room"], r["floor"], r["base"], r["walls"], r["ceiling"],
            r["ceiling_height"]) == ("101", "PC", "RB", "PT-1 / PT-2",
                                     "ACT", "9'-0\"")
    assert ait.finish_csi("ceiling", "ACT / GB")[0] == "09 51 13"
    assert ait.finish_csi("floor", "XYZ-9") == (
        "09 00 00", "floor code 'XYZ-9' not recognised - CSI 09 00 00")
    assert ait.finish_csi("floor", "(unknown)")[0] == "09 00 00"
    assert ait.finish_csi("floor", "CT-1")[0] == "09 30 00"
    assert ait.finish_csi("floor", "VCT-1")[0] == "09 65 00"


def test_a_no_finish_schedule_lists_codes_unknown_for_review(monkeypatch):
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    monkeypatch.setattr(autotakeoff, "all_rooms", fake_rooms(
        {0: [room("OFFICE 101", "101", 200, 60, 0, 0)]}))
    rows = ait.plan_set(d)
    res = ait.run(d, rows)
    assert not quantities(res, "finishes")
    rv = [x for x in res["review"] if x.get("engine") == "finishes"]
    assert {x["name"] for x in rv} == {"Floor (code unknown)",
                                       "Base (code unknown)"}
    assert all(x["csi"] == "09 00 00" for x in rv)
    assert any("no finish schedule" in p for p in res["problems"])


# ---- (b) walls by type -----------------------------------------------------------------
def _hexagon(pg, c, r=7.0):
    pts = [fitz.Point(c[0] + r * math.cos(math.radians(60 * k)),
                      c[1] + r * math.sin(math.radians(60 * k)))
           for k in range(7)]
    pg.draw_polyline(pts, color=BLACK, width=0.3)


def _tag(pg, c, code):
    _hexagon(pg, c)
    pg.insert_text((c[0] - 2.2 * len(code), c[1] + 2.5), code, fontsize=6)


def _wall(sh, a, b, t_in, horizontal):
    """A wall's two face lines and end caps, centerline a -> b (ft)."""
    h = t_in / 12 / 2

    def P(x, y):
        return fitz.Point(OX + x * PPU, OY + y * PPU)
    (x0, y0), (x1, y1) = a, b
    if horizontal:
        sh.draw_line(P(x0, y0 - h), P(x1, y0 - h))
        sh.draw_line(P(x0, y0 + h), P(x1, y0 + h))
        sh.draw_line(P(x0, y0 - h), P(x0, y0 + h))
        sh.draw_line(P(x1, y0 - h), P(x1, y0 + h))
    else:
        sh.draw_line(P(x0 - h, y0), P(x0 - h, y1))
        sh.draw_line(P(x0 + h, y0), P(x0 + h, y1))
        sh.draw_line(P(x0 - h, y0), P(x0 + h, y0))
        sh.draw_line(P(x0 - h, y1), P(x0 + h, y1))


def walls_plan(page):
    """A 50' x 30' building, 8" CMU exterior (7-5/8"), two 3-5/8" stud
    partitions (4-7/8") with a door opening each; 1A tagged on two
    exterior walls, 2A on one partition."""
    te, tp = 7.625, 4.875
    sh = page.new_shape()
    _wall(sh, (0, 0), (50, 0), te, True)
    _wall(sh, (0, 30), (50, 30), te, True)
    _wall(sh, (0, 0), (0, 30), te, False)
    _wall(sh, (50, 0), (50, 30), te, False)
    e = te / 24
    for x, (g0, g1) in ((20, (10, 13)), (35, (20, 23))):
        _wall(sh, (x, e), (x, g0), tp, False)
        _wall(sh, (x, g1), (x, 30 - e), tp, False)
    sh.finish(color=BLACK, width=0.25)
    sh.commit()

    def P(x, y):
        return (OX + x * PPU, OY + y * PPU)
    _tag(page, P(25, -1.0), "1A")
    _tag(page, P(-1.0, 15), "1A")
    _tag(page, P(21.2, 5), "2A")
    put(page, OX + 8 * PPU, OY + 20 * PPU, "OFFICE", 7)
    put(page, OX + 8 * PPU, OY + 20 * PPU + 9, "101", 7)


def legend_sheet(doc):
    p = sheet(doc, "G-004", "WALL TYPES", scale="1 1/2\" = 1'-0\"")
    put(p, 200, 200, "WALL TYPES", 9)
    for i, (code, text) in enumerate((
            ("1A", "8\" CMU, 7/8\" FURRING, 5/8\" GB, H= 10'-0\""),
            ("2A", "3-5/8\" MTL STUD, 5/8\" GB EA SIDE"))):
        c = (210, 230 + 30 * i)
        _tag(p, c, code)
        put(p, 230, c[1] + 2, text, 6)


def walls_set():
    d = fitz.open()
    legend_sheet(d)
    walls_plan(sheet(d, "A-101", "FLOOR PLAN"))
    walls_plan(sheet(d, "A-102", "DIMENSION PLAN"))
    return d


def test_b_wall_legend_and_plan_give_lf_per_type_once(monkeypatch):
    pytest.importorskip("cv2")
    d = walls_set()
    monkeypatch.setattr(autotakeoff, "all_rooms", fake_rooms({}))
    rows = ait.plan_set(d)
    num = {r["number"]: r for r in rows}
    assert "rooms" in num["A-101"]["engines"]
    assert "rooms" in num["A-102"]["engines"]
    assert ait.walls_pages(rows) == ([1], [(2, 1)])
    legend, pages = ait.wall_legend(d, rows)
    assert pages == [0] and set(legend) == {"1A", "2A"}
    res = ait.run(d, rows)
    assert 2 not in res["walls"]                     # A-102 not counted
    assert any("A-102" in p and "taken from A-101" in p
               for p in res["problems"])
    tot = ait.totals(res)["walls"]
    # every exterior wall is 1A (two tagged, two of its class inferred)
    assert tot[("Wall Type 1A", "LF")] == pytest.approx(160, rel=0.03)
    part = 2 * (30 - 7.625 / 12) - 2 * 3          # two partitions, doors
    assert tot[("Wall Type 2A", "LF")] == pytest.approx(part, rel=0.05)
    # marks: one group per type, CMU 04 22 00, partitions 09 21 16
    ms = [m for m in res["marks"]
          if m[2]["measure"].get("method") == "AI takeoff: walls"]
    csi = {m[2]["measure"]["group"]: m[2]["measure"].get("csi") for m in ms}
    assert csi["Wall Type 1A"] == "04 22 00"
    assert csi["Wall Type 2A"] == "09 21 16"
    assert all(m[0] == 1 for m in ms)
    # wall SF: 1A has its height in the legend, 2A has none
    q = quantities(res, "walls")
    assert q[("Wall Type 1A wall area", "SF")]["qty"] == pytest.approx(
        tot[("Wall Type 1A", "LF")] * 10, rel=0.01)
    assert q[("Wall Type 1A wall area", "SF")]["csi"] == "04 22 00"
    rv = {x["name"]: x for x in res["review"] if x.get("engine") == "walls"}
    assert "height unknown" in rv["Wall Type 2A wall area"]["why"]
    # the exterior wall: the outer face loop, 2 x (50.64 + 30.64)
    ext = tot[("Exterior Walls", "LF")]
    assert ext == pytest.approx(2 * (50 + 30 + 2 * 7.625 / 12), rel=0.03)
    assert q[("Exterior Walls wall area", "SF")]["qty"] == pytest.approx(
        ext * 10, rel=0.01)
    sh = res["sheets"][1]
    assert {c["label"] for c in sh["wall_classes"]}
    assert "Exterior" in sh["wall_roles"]
    text = ait.summary_text(rows, res)
    assert "Walls (one floor plan per level)" in text
    assert "Wall Type 1A:" in text
    # the harness: wall LF lines and the map
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import aiken_eval
    lines, _t = aiken_eval.ai_lines(d, rows, res)
    keys = {(ln["key"], ln["unit"], ln["status"]) for ln in lines}
    assert ("walls:Wall Type 2A", "LF", "taken off") in keys
    assert ("walls:Exterior Walls", "LF", "taken off") in keys
    assert ("walls:Wall Type 1A wall area", "SF", "taken off") in keys
    mp = aiken_eval.load_map(aiken_eval.MAP)
    assert aiken_eval.map_line("walls:Wall Type 2A", mp[1], mp[2]) == \
        "H09-INTWALL"
    assert aiken_eval.map_line("walls:Exterior Walls", mp[1], mp[2]) == \
        "H09-EXTWALL-LF"
    assert aiken_eval.map_line("walls:Exterior Walls wall area", mp[1],
                               mp[2]) == "H04-CMU8-SF"
    assert aiken_eval.map_line("walls:Wall Type 1A wall area", mp[1],
                               mp[2]) == "H09-GB-EXT"


def test_b_wall_type_details_and_heights():
    d = fitz.open()
    p = sheet(d, "G-004", "WALL TYPES", scale="1 1/2\" = 1'-0\"")
    for i, (code, notes) in enumerate((("1A", ["8\" CMU", "7/8\" MTL FURRING",
                                                "5/8\" TYPE X GYPBOARD"]),
                                       ("2A", ["3 5/8\" MTL. STUDS @ 16\" O.C.",
                                               "5/8\" TYPE X GYPBOARD"]))):
        x = 200 + 400 * i
        for k, t in enumerate(notes):
            put(p, x, 300 + 14 * k, t, 7)
        put(p, x, 500, f"WALL TYPE {code}", 10)
    leg = ait.detail_legend(p)
    assert set(leg) == {"1A", "2A"}
    assert "8\" CMU" in leg["1A"] and "CMU" not in leg["2A"]
    h = ait.wall_heights({"1A": "8\" CMU, H= 11'-0\"",
                          "2A": "STUDS, SILL HEIGHT 2'-0\""},
                         "GENERAL NOTES: WALL HEIGHTS: 10'-8\" U.N.O.")
    assert h["types"] == {"1A": 11.0}
    assert h["all"] == pytest.approx(10 + 8 / 12)


# ---- (c) rooms for review ----------------------------------------------------------------
def test_c_room_flagged_review_is_in_review(monkeypatch):
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    sure = room("OFFICE 101", "101", 100, 40, 0, 0)
    odd = room("STORAGE 102", "102", 100, 40, 12, 0,
               review=True, flags=["trace +20.0% from its tag (100 SF) - "
                                   "check the outline",
                                   "overlaps OFFICE 101 by 6 SF"])
    odd["net_sf"] = 120.0
    monkeypatch.setattr(autotakeoff, "all_rooms", fake_rooms(
        {0: [sure, odd]}, {0: {"overlaps": 1}}))
    rows = ait.plan_set(d)
    res = ait.run(d, rows)
    rv = [x for x in res["review"] if x.get("engine") == "rooms"]
    assert len(rv) == 1
    x = rv[0]
    assert (x["sheet"], x["page"], x["name"], x["qty"], x["unit"]) == (
        "A-101", 0, "STORAGE 102", 120.0, "sq ft")
    assert x["why"] == ("trace +20.0% from its tag (100 SF) - check the "
                        "outline; overlaps OFFICE 101 by 6 SF")
    assert any("overlap" in p and p.startswith("A-101") for p in
               res["problems"])
    # still measured (marked), and listed in the summary for a person
    assert len([m for m in res["marks"] if m[1] == "add_polygon"]) == 2
    assert "STORAGE 102 (120 sq ft)" in ait.summary_text(rows, res)


# ---- (d) a stopped rooms pass ---------------------------------------------------------------
def test_d_stopped_rooms_pass_is_listed_unfinished(monkeypatch):
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    calls = []
    monkeypatch.setattr(autotakeoff, "all_rooms", fake_rooms(
        {0: [room("OFFICE 101", "101", 100, 40, 0, 0)]},
        {0: {"stopped": True, "why": "time budget (7 s) used up",
             "partial": [{"name": "OFFICE 101"}]}}, calls))
    rows = ait.plan_set(d)
    res = ait.run(d, rows, sheet_time_limit=7)
    assert calls and calls[0]["budget_s"] == 7 and calls[0]["info"]
    un = [u for u in res["unfinished"] if u["engine"] == "rooms"]
    assert len(un) == 1 and un[0]["sheet"] == "A-101"
    assert "time budget (7 s) used up" in un[0]["why"]
    assert "1 room(s) traced" in un[0]["why"]
    assert not [m for m in res["marks"] if m[1] == "add_polygon"]
    assert res["finishes"] is None
    assert any("rooms not finished" in p for p in res["problems"])
    assert "Not finished" in ait.summary_text(rows, res)


# ---- (e) the map's groups exist --------------------------------------------------------------
def _xlsx():
    """The comparison workbook, from QS_AIKEN_* or settings. None when
    those are unset or the file is not on this computer."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import aiken_eval
    cfg = aiken_eval.plan_config("aiken")
    rel = cfg["xlsx"]
    if not rel:
        return None
    path = rel if os.path.isabs(rel) else (
        os.path.join(cfg["src"], rel) if cfg["src"] else "")
    if path and os.path.isfile(path):
        return path
    return None


def test_e_every_map_group_is_in_the_mapping_sheet():
    with open(os.path.join(ROOT, "tools", "aiken_map.json"),
              encoding="utf-8") as f:
        m = json.load(f)
    groups = {r["group"] for r in m["rules"]}
    assert {"H09-EPX-FLOOR", "H03-POLISH", "H09-EPX-BASE", "H09-RB",
            "H09-CEIL-ALL", "H09-PAINT-WALL", "H09-EPP1-WALL",
            "H09-WALLPANEL", "H09-INTWALL", "H09-EXTWALL-LF", "H09-GB-EXT",
            "H04-CMU8-SF"} <= groups
    x = _xlsx()
    if x is None:
        pytest.skip("QS_AIKEN_SRC and QS_AIKEN_XLSX are not set (settings "
                    "aiken_src and aiken_xlsx also work), or the workbook "
                    "is not on this computer")
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(x, read_only=True, data_only=True)
    ws = wb["Mapping"]
    it = ws.iter_rows(values_only=True)
    head = [str(h or "") for h in next(it)]
    gi = head.index("Group_ID")
    have = {str(r[gi]).strip() for r in it if r and r[gi]}
    wb.close()
    have |= {f"R{n}" for n in range(1, 2000)}
    have |= set(m.get("regroup") or {})       # rows joined by the map
    missing = sorted(g for g in groups if g not in have)
    assert not missing, missing
