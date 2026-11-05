"""Rooms and walls, phase 2 (Colleton C2/C4/C5, Aiken N2/N4/#11).

Every drawing here is made up: CAD-style plans drawn with PyMuPDF.

* all_rooms stays fast on a dense 40-room plan and reports, per room,
  net SF, perimeter LF, tag SF, a trace confidence and flags;
* traces that overlap, or that hold another room's tag, are flagged;
* the room-tag sample in a legend is not a room;
* multi-line room names and decimal room numbers (115.1) are read;
* room_finishes turns rooms into floor / base / ceiling / wall-paint
  quantities, with and without a finish schedule;
* wall thicknesses cluster to the same nominal classes on two drawings
  of the same walls at different line weights;
* wall-type tags (hexagons keyed to a legend) give LF per wall type;
* the exterior is the building's outer face loop, porch linework left out.
"""
import time

import fitz
import pytest

from app import autotakeoff, autowalls, room_finishes, wall_roles  # noqa

PPF8 = 9.0                    # 1/8" = 1'-0": 9 points per foot
PPF4 = 18.0                   # 1/4" = 1'-0"


# ---- drawing helpers ------------------------------------------------------------
class _Plan:
    """Draws walls as two face lines (hollow, like a CAD export) on a page,
    in feet from an origin."""

    def __init__(self, page, ppf, ox, oy, width=0.5):
        self.pg, self.ppf, self.ox, self.oy = page, ppf, ox, oy
        self.sh = page.new_shape()
        self.width = width

    def P(self, x, y):
        return fitz.Point(self.ox + x * self.ppf, self.oy + y * self.ppf)

    def line(self, x0, y0, x1, y1):
        self.sh.draw_line(self.P(x0, y0), self.P(x1, y1))

    def hwall(self, y, x0, x1, t_in, gaps=()):
        """A horizontal wall, centerline y, from x0 to x1 (ft), `gaps`
        [(a, b)] openings; the ends of each piece are capped."""
        h = t_in / 12 / 2
        xs = [x0]
        for a, b in sorted(gaps):
            xs += [a, b]
        xs.append(x1)
        for a, b in zip(xs[::2], xs[1::2]):
            self.line(a, y - h, b, y - h)
            self.line(a, y + h, b, y + h)
            self.line(a, y - h, a, y + h)
            self.line(b, y - h, b, y + h)

    def vwall(self, x, y0, y1, t_in, gaps=()):
        h = t_in / 12 / 2
        ys = [y0]
        for a, b in sorted(gaps):
            ys += [a, b]
        ys.append(y1)
        for a, b in zip(ys[::2], ys[1::2]):
            self.line(x - h, a, x - h, b)
            self.line(x + h, a, x + h, b)
            self.line(x - h, a, x + h, a)
            self.line(x - h, b, x + h, b)

    def done(self, color=(0, 0, 0)):
        self.sh.finish(color=color, width=self.width)
        self.sh.commit()
        self.sh = self.pg.new_shape()

    def swing(self, hx, hy, r, dx, dy):
        """A door swing: the leaf from the hinge, a quarter arc to the
        latch side. (dx, dy): the leaf's direction; the arc turns to the
        wall."""
        s = self.pg.new_shape()
        h = self.P(hx, hy)
        tip = self.P(hx + dx * r, hy + dy * r)
        s.draw_line(h, tip)
        # latch end: the leaf turned 90 degrees (into the wall line)
        lx, ly = (-dy, dx)
        latch = self.P(hx + lx * r, hy + ly * r)
        s.draw_curve(tip, self.P(hx + (dx + lx) * r, hy + (dy + ly) * r),
                     latch)
        s.finish(color=(0, 0, 0), width=0.25)
        s.commit()


def dense_plan(n_rooms=40, ppf=PPF8, legend=True, swings=2, vector_text=0,
               detail=False):
    """A double-loaded corridor: n_rooms offices (12' c-c, 15'-6" deep)
    either side of an 8' corridor, 8" exterior walls, 4-7/8" partitions,
    a 3' door with a swing into each office, furniture, dimension strings,
    a notes column and a title block. Each office is tagged "OFFICE / 1nn /
    179 SF"; the corridor "CORRIDOR / 100 / <sf> SF". `swings`: a swing is
    drawn at every n-th office door only (the others are plain openings,
    as when a CAD export's swings can't be read), so at narrow door
    bridging the whole floor is one open space. `vector_text`: that many
    characters of SHX-style text drawn as tiny strokes (CAD exports often
    draw text as linework - tens of thousands of paths); `detail`: an
    enlarged plan at 1/4" with two more rooms. Returns (doc, {number: tag
    sf})."""
    d = fitz.open()
    pg = d.new_page(width=2592, height=1728)               # 36" x 24"
    n = n_rooms // 2
    L = 12.0 * n
    pl = _Plan(pg, ppf, 100, 260)
    te, tp = 8.0, 4.875
    he, hp = te / 24, tp / 24
    yc1, yc2, ys = 16.0, 24.5, 40.5
    # exterior: doors at the corridor ends
    pl.hwall(0, 0, L, te)
    pl.hwall(ys, 0, L, te)
    pl.vwall(0, 0, ys, te, gaps=[(18.75, 21.75)])
    pl.vwall(L, 0, ys, te, gaps=[(18.75, 21.75)])
    # corridor walls, a 3' door into each office
    gaps = [(12 * k + 2, 12 * k + 5) for k in range(n)]
    pl.hwall(yc1, he, L - he, tp, gaps=gaps)
    pl.hwall(yc2, he, L - he, tp, gaps=gaps)
    for k in range(1, n):
        pl.vwall(12 * k, he, yc1 - hp, tp)
        pl.vwall(12 * k, yc2 + hp, ys - he, tp)
    pl.done()
    tags = {}
    room_sf = (12 - 2 * hp) * (yc1 - hp - he)
    for k in range(0, n, swings or n + 1):
        # swings into the rooms, hinged at the jamb
        pl.swing(12 * k + 2, yc1 - hp, 3.0, 0, -1)
        pl.swing(12 * k + 5, yc2 + hp, 3.0, 0, 1)
    # the exterior doors at the corridor ends
    pl.swing(0, 18.75, 3.0, 1, 0)
    pl.swing(L, 21.75, 3.0, -1, 0)
    num = 101
    for row, (y0, y1) in enumerate(((he, yc1 - hp), (yc2 + hp, ys - he))):
        for k in range(n):
            x0 = 12 * k + hp if k else he
            x1 = 12 * (k + 1) - hp if k < n - 1 else L - he
            sf = (x1 - x0) * (y1 - y0)
            # furniture: a desk and a chair (fine pen)
            s = pg.new_shape()
            s.draw_rect(fitz.Rect(pl.P(x0 + 1, y0 + 1), pl.P(x0 + 6, y0 + 3.5)))
            s.draw_rect(fitz.Rect(pl.P(x0 + 3, y0 + 4), pl.P(x0 + 5, y0 + 6)))
            s.finish(color=(0, 0, 0), width=0.1)
            s.commit()
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + 2
            p = pl.P(cx - 2, cy)
            pg.insert_text(p, f"OFFICE\n{num}\n{sf:.0f} SF", fontsize=6)
            tags[str(num)] = round(sf)
            num += 1
    csf = (L - 2 * he) * (yc2 - yc1 - 2 * hp)
    pg.insert_text(pl.P(L / 2 - 3, 20.3), f"CORRIDOR\n100\n{csf:.0f} SF",
                   fontsize=6)
    tags["100"] = round(csf)
    # dimension strings above the plan (thin lines and text)
    s = pg.new_shape()
    for k in range(n + 1):
        s.draw_line(pl.P(12 * k, -6), pl.P(12 * k, -3))
    s.draw_line(pl.P(0, -4.5), pl.P(L, -4.5))
    s.finish(color=(0, 0, 0), width=0.15)
    s.commit()
    for k in range(n):
        pg.insert_text(pl.P(12 * k + 4.5, -5), "12'-0\"", fontsize=5)
    # a notes column and a title block (text that is not rooms)
    for i in range(60):
        pg.insert_text((2300, 120 + i * 9),
                       f"{i + 1}. CONTRACTOR SHALL VERIFY ALL DIMENSIONS "
                       f"ROOM {200 + i} SEE SPEC", fontsize=5)
    pg.insert_text((2350, 1600), "FLOOR PLAN\nSHEET A-101\nSCALE 1/8\"",
                   fontsize=9)
    if legend:
        add_room_tag_legend(pg, 2300, 900)
    if vector_text:
        _vector_text(pg, vector_text)
    if detail:
        tags.update(_enlarged_plan(pg, 300, 1000))
    return d, tags


def _vector_text(pg, n):
    """n characters of "text" drawn as strokes, each its own path, in
    the notes column and under the plan."""
    import random
    rnd = random.Random(7)
    spots = [(2300, 2560, 120, 860), (100, 2200, 700, 950),
             (1300, 2200, 950, 1650)]
    s = pg.new_shape()
    for i in range(n):
        x0, x1, y0, y1 = spots[i % len(spots)]
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        s.draw_polyline([(x, y), (x + 1.5, y - 4), (x + 3, y),
                         (x + 1, y - 2)])
        if i % 4 == 0:
            s.draw_curve((x + 3.2, y - 2), (x + 3.2, y - 4), (x + 4.5, y - 4))
        s.finish(color=(0, 0, 0), width=0.2)      # each character a path
    s.commit()


def _enlarged_plan(pg, x, y):
    """An enlarged plan at 1/4" = 1'-0" on the 1/8" sheet: TOILET 150
    (9'-6" x 7'-6") and STOR 151 (5'-6" x 7'-6") with 6" walls, its title
    and scale under it."""
    pl = _Plan(pg, PPF4, x, y)
    pl.hwall(0, 0, 16.5, 6)
    pl.hwall(8, 0, 16.5, 6)
    pl.vwall(0, 0, 8, 6)
    pl.vwall(10, 0, 8, 6)
    pl.vwall(16.5, 0, 8, 6)
    pl.done()
    pg.insert_text(pl.P(3, 3.5), "TOILET\n150\n71 SF", fontsize=6)
    pg.insert_text(pl.P(11.5, 3.5), "STOR\n151\n45 SF", fontsize=6)
    pg.insert_text(pl.P(0, 10.5), "3  ENLARGED TOILET PLAN", fontsize=10)
    pg.insert_text(pl.P(0, 11.5), 'SCALE: 1/4" = 1\'-0"', fontsize=7)
    return {"150": 71, "151": 45}


def add_room_tag_legend(pg, x, y):
    """A symbols legend with a room-tag sample: '12'-0"' over 'ROOM NAME'
    over '101' in a box, described 'ROOM NAME AND AREA'."""
    pg.insert_text((x, y), "SYMBOLS LEGEND", fontsize=9)
    pg.insert_text((x + 10, y + 30), "12'-0\"\nROOM NAME\n101\n150 SF",
                   fontsize=6)
    pg.draw_rect(fitz.Rect(x + 5, y + 20, x + 60, y + 62), color=(0, 0, 0),
                 width=0.25)
    pg.insert_text((x + 80, y + 40), "ROOM NAME AND AREA", fontsize=6)


def _scale(ppf):
    return {"ppu": ppf, "unit": "ft"}


# ---- C2: speed on a dense plan -----------------------------------------------------
def test_dense_plan_of_40_rooms_is_fast_and_complete():
    d, tags = dense_plan(40)
    pg = d[0]
    calls = []

    def progress(i, n):
        calls.append((i, n))
        return True
    t0 = time.perf_counter()
    info = {}
    found, missed = autotakeoff.all_rooms(pg, _scale(PPF8), progress=progress,
                                          skip_measured=False, info=info)
    dt = time.perf_counter() - t0
    # Colleton A-101 took 123 s; the work per room must not grow with the
    # size of the building
    assert dt < 25, f"all_rooms took {dt:.1f} s"
    assert calls, "progress is reported"
    got = {autotakeoff.room_number(r["name"]): r for r in found}
    assert not missed, [t["name"] for t in missed]
    assert set(got) == set(tags)
    for num, sf in tags.items():
        r = got[num]
        assert r["net_sf"] == pytest.approx(sf, rel=0.03), num
        assert r["tag_sf"] == sf
        assert r["perimeter_lf"] > 0
        assert 0 <= r["trace_confidence"] <= 1
        assert isinstance(r["flags"], list)
    office = got["101"]
    # the west-end office: 11.46' x 15.46' inside the faces
    w = 12 - 4.875 / 24 - 8 / 24
    h = 16 - 4.875 / 24 - 8 / 24
    assert office["net_sf"] == pytest.approx(w * h, rel=0.02)
    assert office["perimeter_lf"] == pytest.approx(2 * (w + h), rel=0.02)
    assert office["trace_confidence"] >= 0.8 and not office["review"]
    # the legend's sample tag is not a room
    assert not any("ROOM NAME" in (r["name"] or "") for r in found)
    assert any("ROOM NAME" in (t.get("name") or "")
               for t in info.get("ignored", []))


def test_dense_sheet_with_vector_text_and_an_enlarged_plan():
    """The Colleton A-101 / A-901 case: text exported as linework (tens of
    thousands of paths) and an enlarged plan at its own scale. Each
    drawing walk is done once per sheet, not once per scale or per
    tool."""
    d, tags = dense_plan(40, vector_text=20000, detail=True)
    t0 = time.perf_counter()
    found, missed = autotakeoff.all_rooms(d[0], _scale(PPF8),
                                          skip_measured=False)
    dt = time.perf_counter() - t0
    assert dt < 40, f"all_rooms took {dt:.1f} s"
    assert not missed
    got = {r["number"]: r for r in found}
    assert set(got) == set(tags)
    for num, sf in tags.items():
        assert got[num]["net_sf"] == pytest.approx(sf, rel=0.03), num
    # the enlarged plan's rooms are measured at 1/4", and say so
    assert got["150"]["detail_scale"] and got["151"]["detail_scale"]
    assert any("detail" in f for f in got["150"]["flags"])


def test_budget_stops_a_sheet_and_says_so():
    d, _tags = dense_plan(20)
    info = {}
    found, missed = autotakeoff.all_rooms(d[0], _scale(PPF8),
                                          skip_measured=False, budget_s=0.0,
                                          info=info)
    assert found == [] and info["stopped"]
    assert missed                        # the tags are handed back


# ---- C4: traces agree with their tags ------------------------------------------------
def _two_rooms_one_space(page, ppf=PPF4):
    """Two tags in one 20' x 15' space (the partition between them never
    drawn). 109's tag is printed hard against the east wall - a tag on a
    wall can't say which room it is in, so tracing 101 lets it through:
    101's trace holds both tags (Colleton's 101 / 109)."""
    pl = _Plan(page, ppf, 100, 100)
    pl.hwall(0, 0, 20, 6)
    pl.hwall(15, 0, 20, 6)
    pl.vwall(0, 0, 15, 6)
    pl.vwall(20, 0, 15, 6)
    pl.done()
    page.insert_text(pl.P(4, 7), "OFFICE\n101\n280 SF", fontsize=7)
    # the area line ends a point short of the wall face: its middle is
    # about 0.6' from the wall
    w = fitz.get_text_length("150 SF", fontsize=6)
    face = pl.P(20 - 0.25, 7)
    page.insert_text(fitz.Point(face.x - 1 - w, face.y),
                     "OFFICE\n109\n150 SF", fontsize=6)
    return pl


def test_a_trace_holding_two_tags_is_flagged_not_guessed():
    d = fitz.open()
    pg = d.new_page(width=900, height=600)
    _two_rooms_one_space(pg)
    found, missed = autotakeoff.all_rooms(pg, _scale(PPF4),
                                          skip_measured=False)
    # nothing is silently merged: 101 is reported with the other tag
    # inside it, for review; 109 can't be traced on its own
    assert len(found) + len(missed) == 2
    by = {r["number"]: r for r in found}
    assert "101" in by
    r = by["101"]
    assert r["review"] and r["trace_confidence"] < 0.5
    assert any("another room's tag" in f and "109" in f for f in r["flags"])
    assert "109" not in by or by["109"]["review"]


def test_overlapping_traces_are_both_flagged():
    a = {"name": "LOBBY 101", "pts": [fitz.Point(0, 0), fitz.Point(100, 0),
                                       fitz.Point(100, 100),
                                       fitz.Point(0, 100)],
         "sqft": 100.0, "tag_sf": 100, "flags": [], "trace_confidence": 0.95}
    b = {"name": "OFFICE 109", "pts": [fitz.Point(50, 0), fitz.Point(150, 0),
                                        fitz.Point(150, 100),
                                        fitz.Point(50, 100)],
         "sqft": 100.0, "tag_sf": 100, "flags": [], "trace_confidence": 0.95}
    c = {"name": "STOR 110", "pts": [fitz.Point(300, 0), fitz.Point(400, 0),
                                      fitz.Point(400, 100),
                                      fitz.Point(300, 100)],
         "sqft": 100.0, "tag_sf": 100, "flags": [], "trace_confidence": 0.95}
    n = autotakeoff.flag_overlaps([a, b, c], pts_per_ft=10.0)
    assert n == 1
    assert any("overlaps" in f and "109" in f for f in a["flags"])
    assert any("overlaps" in f and "101" in f for f in b["flags"])
    assert a["review"] and b["review"] and not c.get("review")
    assert a["trace_confidence"] < 0.5 and c["trace_confidence"] == 0.95


def test_trace_confidence_and_tag_difference():
    r = {"name": "TOILET 125", "sqft": 146.8, "tag_sf": 111, "flags": [],
         "pts": []}
    autotakeoff.score_room(r)
    # 146.8 against a tag of 111: 32% over - for review, never taken as is
    assert r["tag_diff_sf"] == pytest.approx(35.8)
    assert r["tag_diff_pct"] == pytest.approx(32.3, abs=0.1)
    assert r["review"] and r["trace_confidence"] < 0.5
    ok = {"name": "OFFICE 102", "sqft": 180.9, "tag_sf": 180, "flags": [],
          "pts": []}
    autotakeoff.score_room(ok)
    assert not ok["review"] and ok["trace_confidence"] >= 0.9


def test_legend_and_title_block_samples_are_not_rooms():
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((200, 200), "OFFICE\n102\n120 SF", fontsize=7)
    add_room_tag_legend(pg, 900, 200)
    # a sample in a title block corner
    pg.insert_text((1100, 700), "ROOM NAME\n101", fontsize=6)
    info = {}
    tags = autotakeoff.room_tags(pg, info=info)
    tags += autotakeoff.room_labels(pg, skip=[t["pt"] for t in tags],
                                    info=info)
    names = [t["name"] for t in tags]
    assert names == ["OFFICE 102"]
    assert any("ROOM NAME" in t["name"] for t in info["ignored"])


# ---- multi-line names, decimal numbers ------------------------------------------------
def test_multi_line_names_and_decimal_room_numbers():
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((100, 100), "WOMEN\nTLT & SHOWER 114", fontsize=7)
    pg.insert_text((300, 100), "CORRIDOR\n102", fontsize=7)
    pg.insert_text((500, 100), "COVERED\nPATIO\nEXT.", fontsize=7)
    pg.insert_text((700, 100), "PREP STORAGE\n115.1", fontsize=7)
    pg.insert_text((100, 300), "JAN\n113", fontsize=7)
    pg.insert_text((300, 300), "OFFICE 102A", fontsize=7)
    # not rooms: a dimension, a note, a sheet reference
    pg.insert_text((500, 300), "12'-6\"", fontsize=7)
    pg.insert_text((700, 300), "SEE DETAIL 5\nA-501", fontsize=7)
    names = sorted(t["name"] for t in autotakeoff.room_labels(pg))
    assert names == sorted(["WOMEN TLT & SHOWER 114", "CORRIDOR 102",
                            "COVERED PATIO EXT.", "PREP STORAGE 115.1",
                            "JAN 113", "OFFICE 102A"])
    assert autotakeoff.room_number("PREP STORAGE 115.1") == "115.1"
    assert autotakeoff.room_number("COVERED PATIO EXT.") == "EXT"
    # with an area: the name lines over the area figure
    pg2 = d.new_page(width=1224, height=792)
    pg2.insert_text((100, 100), "WOMEN\nTLT & SHOWER\n114\n86 SF",
                    fontsize=7)
    (t,) = autotakeoff.room_tags(pg2)
    assert t["name"] == "WOMEN TLT & SHOWER 114" and t["sf"] == 86


def test_decimal_room_traced_on_a_plan():
    d = fitz.open()
    pg = d.new_page(width=900, height=600)
    pl = _Plan(pg, PPF4, 100, 100)
    pl.hwall(0, 0, 10, 6)
    pl.hwall(8, 0, 10, 6)
    pl.vwall(0, 0, 8, 6)
    pl.vwall(10, 0, 8, 6)
    pl.done()
    pg.insert_text(pl.P(2.5, 3.5), "PREP STORAGE\n115.1", fontsize=7)
    found, missed = autotakeoff.all_rooms(pg, _scale(PPF4),
                                          skip_measured=False)
    assert not missed
    (r,) = found
    assert r["name"] == "PREP STORAGE 115.1"
    # 9'-6" x 7'-6" inside
    assert r["net_sf"] == pytest.approx(71.25, rel=0.03)
    assert r["perimeter_lf"] == pytest.approx(34.0, rel=0.03)
    assert r["tag_sf"] is None and any("no area" in f for f in r["flags"])


# ---- N2: room finishes -------------------------------------------------------------------
def _rooms():
    return [
        {"name": "OFFICE 101", "sqft": 180.0, "net_sf": 180.0,
         "perimeter_lf": 54.0, "tag_sf": 180, "flags": [], "review": False},
        {"name": "OFFICE 102", "sqft": 150.0, "net_sf": 150.0,
         "perimeter_lf": 50.0, "tag_sf": 150, "flags": [], "review": False},
        {"name": "CORRIDOR 100", "sqft": 400.0, "net_sf": 400.0,
         "perimeter_lf": 116.0, "tag_sf": 400, "flags": [], "review": False},
        {"name": "STORAGE 115.1", "sqft": 60.0, "net_sf": 60.0,
         "perimeter_lf": 32.0, "tag_sf": None,
         "flags": ["no area in the tag - size check only"],
         "review": True},
    ]


def test_room_finishes_with_a_schedule():
    sched = [
        {"room": "101", "name": "OFFICE", "floor": "CPT-1", "base": "RB-1",
         "walls": "PT-1", "ceiling": "ACT-1", "ceiling_height": "9'-0\""},
        {"room": "102", "floor": "CPT-1", "base": "RB-1", "walls": "PT-1",
         "ceiling": "ACT-1", "ceiling_height": 9},
        {"room": "100", "floor": "LVT-1", "base": "RB-1", "walls": "PT-2",
         "ceiling": "GYP", "ceiling_height": "10'-6\""},
    ]
    doors = [{"number": "101A", "width": "3'-0\""},
             {"number": "102", "width": 3.0},
             {"rooms": ["100", "101"], "width": 3.0}]
    out = room_finishes.room_finishes(_rooms(), sched, doors=doors)
    assert out["floor"] == pytest.approx({"CPT-1": 330.0, "LVT-1": 400.0,
                                          "(unknown)": 60.0})
    # base: perimeter less the door openings (101: two doors, 102: one,
    # 100: the door it shares with 101)
    assert out["base"]["RB-1"] == pytest.approx((54 - 6) + (50 - 3) +
                                                (116 - 3))
    assert out["ceiling"] == pytest.approx({"ACT-1": 330.0, "GYP": 400.0,
                                            "(unknown)": 60.0})
    assert out["walls"]["PT-1"] == pytest.approx(54 * 9 + 50 * 9)
    assert out["walls"]["PT-2"] == pytest.approx(116 * 10.5)
    by = {r["number"]: r for r in out["rooms"]}
    assert by["101"]["ceiling_height_ft"] == 9.0
    assert by["101"]["base_lf"] == pytest.approx(48.0)
    # the room the schedule doesn't list: quantities, codes unknown, flagged
    assert by["115.1"]["floor_code"] is None and by["115.1"]["review"]
    assert any("not in the finish schedule" in f
               for f in by["115.1"]["flags"])


def test_room_finishes_without_a_schedule():
    out = room_finishes.room_finishes(_rooms())
    assert out["floor"] == pytest.approx({"(unknown)": 790.0})
    assert out["base"] == pytest.approx({"(unknown)": 252.0})
    assert out["ceiling"] == {} and out["walls"] == {}
    for r in out["rooms"]:
        assert r["floor_sf"] > 0 and r["base_lf"] > 0
        assert r["floor_code"] is None and r["review"]
        assert any("codes unknown" in f for f in r["flags"])
        assert any("door" in f for f in r["flags"])     # widths unknown
    assert any("no finish schedule" in f for f in out["flags"])


# ---- C5: wall thickness classes ----------------------------------------------------------
def _walls_sheet(width, extras):
    """The same building drawn twice: 8" CMU exterior (7-5/8"), 3-5/8"
    stud + 5/8" GB partitions (4-7/8"), a 6" stud wall (7-1/4"). Sheet A
    draws the partitions' stud and board lines at a fine pen; sheet B only
    the faces, at a heavy pen, with casework lines beside two walls and
    the drafting a hair off."""
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pl = _Plan(pg, PPF4, 80, 80, width=width)
    j = 0.04 if extras else 0.0                      # inches of slop
    te, tp, ts = 7.625 + j, 4.875 - j, 7.25 + j
    pl.hwall(0, 0, 50, te)
    pl.hwall(30, 0, 50, te)
    pl.vwall(0, 0, 30, te)
    pl.vwall(50, 0, 30, te)
    pl.vwall(20, te / 24, 30 - te / 24, tp, gaps=[(10, 13)])
    pl.vwall(35, te / 24, 30 - te / 24, tp, gaps=[(20, 23)])
    pl.hwall(15, 20 + tp / 24, 35 - tp / 24, ts, gaps=[(26, 29)])
    if not extras:
        # stud lines inside the partitions' board lines
        for x in (20, 35):
            for o in (-tp / 24 + 0.625 / 12, tp / 24 - 0.625 / 12):
                pl.line(x + o, te / 24, x + o, 10)
    pl.done()
    if extras:
        s = pg.new_shape()
        # base cabinets / counter fronts 2'-0" off a partition, a counter
        # edge 11" off the exterior: parallel lines that aren't walls
        s.draw_line(pl.P(22, 2), pl.P(22, 9))
        s.draw_line(pl.P(5, 0.33 + 11 / 12), pl.P(14, 0.33 + 11 / 12))
        s.finish(color=(0, 0, 0), width=0.2)
        s.commit()
    return d


def test_wall_classes_stable_across_two_drawings_of_one_building():
    res = []
    for width, extras in ((0.25, False), (1.4, True)):
        d = _walls_sheet(width, extras)
        ws = autowalls.walls(d[0], PPF4, "ft")
        res.append(autowalls.thickness_classes(ws))
    a, b = ({c["nominal_in"] for c in r} for r in res)
    assert a == b == {7.625, 4.875, 7.25}
    for r in res:
        by = {c["nominal_in"]: c for c in r}
        assert by[7.625]["assembly"].startswith('8" CMU')
        assert by[4.875]["assembly"].startswith('3-5/8" stud')
        assert by[7.625]["median_in"] == pytest.approx(7.625, abs=0.1)
        assert by[4.875]["median_in"] == pytest.approx(4.875, abs=0.1)
        # the exterior: 2 x 50 + 2 x 30 at the centerlines
        assert by[7.625]["lf"] == pytest.approx(160.0, rel=0.02)
    # each wall carries its class
    ws = autowalls.walls(_walls_sheet(0.25, False)[0], PPF4, "ft")
    assert all("nominal_in" in w and "measured" in w for w in ws)


def test_snap_to_nominal_assemblies():
    assert autowalls.snap_thickness(4.95)[0] == 4.875
    assert autowalls.snap_thickness(7.58)[0] == 7.625
    nom, label, snapped = autowalls.snap_thickness(13.1)
    assert not snapped and nom == pytest.approx(13.125)


# ---- N4: LF by wall type -------------------------------------------------------------------
def _hexagon(pg, c, r=7.0):
    import math
    pts = [fitz.Point(c.x + r * math.cos(math.radians(60 * k)),
                      c.y + r * math.sin(math.radians(60 * k)))
           for k in range(7)]
    pg.draw_polyline(pts, color=(0, 0, 0), width=0.3)


def _tag(pg, c, code):
    _hexagon(pg, c)
    pg.insert_text((c.x - 2.2 * len(code), c.y + 2.5), code, fontsize=6)


def test_wall_type_tags_give_lf_per_type():
    d = _walls_sheet(0.25, False)
    pg = d[0]

    def P(x, y):
        return fitz.Point(80 + x * PPF4, 80 + y * PPF4)
    # tags beside the walls: 1A on two exterior walls, 3 on a partition,
    # W6 on the stud wall (the other partition is left untagged)
    _tag(pg, P(25, -1.0), "1A")
    _tag(pg, P(-1.0, 15), "1A")
    _tag(pg, P(21.2, 5), "3")
    _tag(pg, P(28, 16.2), "W6")
    # the legend, off to the side
    pg.insert_text((1000, 120), "WALL TYPES", fontsize=9)
    for i, (code, text) in enumerate((("1A", "8\" CMU, PAINTED"),
                                      ("3", "3-5/8\" MTL STUD, 5/8\" GB EA SIDE"),
                                      ("W6", "6\" MTL STUD, 5/8\" GB EA SIDE"))):
        c = fitz.Point(1010, 150 + 30 * i)
        _tag(pg, c, code)
        pg.insert_text((1030, c.y + 2), text, fontsize=6)
    ws = autowalls.walls(pg, PPF4, "ft")
    res = autowalls.wall_types(pg, PPF4, "ft", ws=ws)
    by = res["by_type"]
    assert set(by) >= {"1A", "3", "W6"}
    assert by["1A"]["description"].startswith("8\" CMU")
    cls = {c["nominal_in"]: c["lf"] for c in autowalls.thickness_classes(ws)}
    # every exterior wall is 1A: two tagged, the other two of the same
    # class (and the same tag everywhere it is tagged) inferred from
    # their thickness
    assert by["1A"]["lf"] == pytest.approx(80, rel=0.03)
    assert by["1A"]["lf"] + by["1A"]["lf_inferred"] == pytest.approx(
        cls[7.625])
    assert cls[7.625] == pytest.approx(160, rel=0.02)
    # partitions: the tagged one runs on through its door opening; the
    # untagged one takes 3 by its thickness (flagged)
    assert by["3"]["lf"] + by["3"]["lf_inferred"] == pytest.approx(
        cls[4.875])
    assert by["3"]["lf"] == pytest.approx(cls[4.875] / 2, rel=0.05)
    assert by["3"]["lf_inferred"] > 0
    # the stud wall: tagged beside its door opening, both pieces counted
    assert by["W6"]["lf"] == pytest.approx(cls[7.25])
    assert by["W6"]["nominal_in"] == 7.25 and by["W6"]["lf_inferred"] == 0
    assert res["untagged"] == {}
    assert any("inferred" in f for f in res["flags"])
    # the legend's own tags are not counted on the plan
    assert by["1A"]["tags"] == 2
    assert res["legend"]["W6"].startswith("6\" MTL STUD")


def test_wall_type_tags_without_a_legend_still_group_by_tag():
    d = _walls_sheet(0.25, False)
    pg = d[0]

    def P(x, y):
        return fitz.Point(80 + x * PPF4, 80 + y * PPF4)
    _tag(pg, P(25, -1.0), "A")
    _tag(pg, P(28, 16.2), "B")
    ws = autowalls.walls(pg, PPF4, "ft")
    res = autowalls.wall_types(pg, PPF4, "ft", ws=ws)
    assert {"A", "B"} <= set(res["by_type"])
    assert res["legend"] == {}
    assert any("no wall-type legend" in f for f in res["flags"])


# ---- #11: exterior = the outer face loop ---------------------------------------------------
def test_exterior_is_the_outer_face_loop_not_porch_linework():
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    pl = _Plan(pg, PPF4, 100, 100)
    te = 8.0
    # a 40' x 30' building (outside faces), windows breaking the walls
    h = te / 24
    pl.hwall(h, 0, 40, te, gaps=[(6, 10), (16, 22), (28, 32)])
    pl.hwall(30 - h, 0, 40, te, gaps=[(8, 11), (25, 31)])
    pl.vwall(h, 0, 30, te, gaps=[(10, 14)])
    pl.vwall(40 - h, 0, 30, te, gaps=[(12, 18)])
    pl.vwall(20, 2 * h, 30 - 2 * h, 4.875, gaps=[(12, 15)])
    pl.done()
    # a covered porch beside it: a beam line pair and column boxes
    s = pg.new_shape()
    for k in range(4):
        x = 42 + k * 4
        s.draw_rect(fitz.Rect(pl.P(x, 4), pl.P(x + 1, 5)))
    s.finish(color=(0, 0, 0), width=0.5)
    s.commit()
    pl.hwall(10, 40, 56, 6)
    pl.hwall(26, 40, 56, 6)
    pl.vwall(56, 10, 26, 6, gaps=[(14, 22)])
    pl.done()
    pg.insert_text(pl.P(46, 18), "COVERED\nPORCH\nEXT.", fontsize=7)
    pg.insert_text(pl.P(8, 20), "OFFICE\n101", fontsize=7)
    ws = autowalls.walls(pg, PPF4, "ft")
    labels = wall_roles.labels_from_words(pg.get_text("words"))
    ext = wall_roles.exterior_outline(ws, PPF4, "ft", labels=labels)
    # 2 x (40 + 30) = 140 ft of outside face, windows included
    assert ext["outer_face_lf"] == pytest.approx(140.0, rel=0.02)
    assert ext["centerline_lf"] == pytest.approx(140.0 - 8 * h, rel=0.02)
    assert ext["openings_lf"] > 20
    pieces = wall_roles.classify(ws, labels, PPF4, "ft")
    sm = wall_roles.summary(pieces)
    # the porch walls are not exterior walls of the building
    assert sm.get("Exterior", 0) < 140
    res = wall_roles.find_ex(pg, PPF4, "ft")
    assert res["exterior"]["outer_face_lf"] == pytest.approx(140.0, rel=0.02)
    assert res["summary"]["Exterior"] == pytest.approx(
        res["exterior"]["outer_face_lf"])


def test_door_swings_drawn_as_short_lines_are_counted():
    """Revit draws a swing as a run of short straight lines: Aiken A-101 /
    A-102 gave no doors at all."""
    import math
    d = fitz.open()
    pg = d.new_page(width=900, height=600)
    pl = _Plan(pg, PPF4, 100, 100)
    pl.hwall(0, 0, 20, 6, gaps=[(5, 8)])
    pl.done()
    s = pg.new_shape()
    hinge = pl.P(5, 0.25)
    pts = [fitz.Point(hinge.x + 3 * PPF4 * math.cos(math.radians(a)),
                      hinge.y + 3 * PPF4 * math.sin(math.radians(a)))
           for a in range(0, 91, 6)]
    s.draw_polyline(pts)
    s.draw_line(hinge, pts[-1])
    s.finish(color=(0, 0, 0), width=0.25)
    s.commit()
    ds = autowalls.doors(pg, PPF4, "ft")
    assert len(ds) == 1
    assert ds[0]["width"] == pytest.approx(3.0, abs=0.1)
    assert autowalls.summary([], ds)["doors"] == {"Door 3'-0\"": 1}


def test_exterior_marks_follow_the_outer_face_loop():
    walls = [{"p0": (0, 0), "p1": (360, 0), "thickness": 8.0},
             {"p0": (360, 0), "p1": (360, 180), "thickness": 8.0},
             {"p0": (360, 180), "p1": (0, 180), "thickness": 8.0},
             {"p0": (0, 180), "p1": (0, 0), "thickness": 8.0}]
    ext = wall_roles.exterior_outline(walls, PPF4, "ft")
    # 20' x 10' at the centerlines, 8" walls: 2 x (20.67 + 10.67) outside
    assert ext["outer_face_lf"] == pytest.approx(62.67, rel=0.005)
    assert ext["centerline_lf"] == pytest.approx(60.0, rel=0.005)
    ms = wall_roles.exterior_marks(0, ext, _scale(PPF4))
    assert len(ms) == 4
    assert sum(m[2]["measure"]["value"] for m in ms) == pytest.approx(
        ext["outer_face_lf"], abs=0.01)
    assert {m[2]["measure"]["group"] for m in ms} == {"Exterior Walls"}


def test_type_marks_group_by_wall_type():
    d = _walls_sheet(0.25, False)
    pg = d[0]
    _tag(pg, fitz.Point(80 + 25 * PPF4, 80 - PPF4), "1A")
    ws = autowalls.walls(pg, PPF4, "ft")
    res = autowalls.wall_types(pg, PPF4, "ft", ws=ws)
    ms = autowalls.type_marks(0, res["walls"], _scale(PPF4))
    groups = {m[2]["measure"]["group"] for m in ms}
    assert "Wall Type 1A" in groups
    assert any(g.endswith("- untagged") for g in groups)


def test_scanned_walls_group_at_the_scan_resolution():
    """Walls traced from a scan measure to a pixel or so (150 dpi: about
    1/2" at 1/4" = 1'-0"): one 8" wall type read as 8.3" and 7.2" is one
    class, not "Wall 8in" and "Wall 7in"; on vector linework the two
    stay apart."""
    def ws():
        return [{"thickness": 8.3, "length": 51.9},
                {"thickness": 7.2, "length": 9.4},
                {"thickness": 5.1, "length": 11.3}]
    scan = ws()
    autowalls._cluster(scan, 0.5)
    assert autowalls.summary(scan, [])["walls"] == pytest.approx(
        {"Wall 8in": 61.3, "Wall 5in": 11.3})
    vec = ws()
    autowalls._cluster(vec)
    assert set(autowalls.summary(vec, [])["walls"]) == {
        "Wall 8in", "Wall 7in", "Wall 5in"}
    # segments traced from a picture carry their pixel size to walls()
    segs = autowalls.RasterSegs([(0, 0, 100, 0)], 0.5)
    assert segs.px_in == 0.5 and list(segs) == [(0, 0, 100, 0)]
