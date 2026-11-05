"""AI Takeoff accuracy, phase 1 (the Aiken review, Oct 2026): numbers that
were wrong are fixed or flagged, never guessed. Every drawing here is made
up in the test - no real project drawings.

(a) same-name pipe systems are added up, not overwritten
(b) a room shown on several plans is taken off once, from the floor plan
(c) a sheet number bound twice / revised: only the latest is taken off
(d) legend notes, lists and schedule text never become devices
(e) a size tag spreads only along its own connected pipe; a system longer
    than the drawing can hold is flagged; a tag on a wall isn't a pipe
(f) existing work (EX., EXIST., (E)) is listed, not in the totals
(g) roof pitch written 5"/1'-0", 2"/1'-0", 6:12, 6 in 12
(h) the submittal register from a CSI 3-part spec whose numbers come out
    on their own lines
(i) time limits: what isn't finished is listed, not dropped
"""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, civiltakeoff, practice              # noqa: E402
from app import tradetakeoff as tt                                    # noqa: E402
from app.pm import submittals                                         # noqa: E402

PPU = 18.0                                   # 1/4" = 1'-0"
W, H = 1728, 1152
OX, OY = 120, 120
BLUE, RED, BLACK = (0, 0, 0.9), (0.9, 0, 0), (0, 0, 0)


def P(x, y):
    return (OX + x * PPU, OY + y * PPU)


def sheet(doc, number, title, date=None):
    """A made-up sheet with a title block the sheet reader understands."""
    page = doc.new_page(width=W, height=H)
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(36, 36, W - 36, H - 36))
    sh.draw_rect(fitz.Rect(W - 300, 36, W - 36, H - 36))
    sh.finish(color=BLACK, width=1.5)
    sh.commit()
    page.insert_text((W - 285, H - 300), "MADE-UP TEST PROJECT", fontsize=9)
    if date:
        page.insert_text((W - 285, H - 240), date, fontsize=8)
    page.insert_text((W - 285, H - 200), "SHEET TITLE:", fontsize=7)
    page.insert_text((W - 285, H - 182), title, fontsize=12)
    page.insert_text((W - 285, H - 110), "SCALE: 1/4\" = 1'-0\"",
                     fontsize=10)
    page.insert_text((W - 285, H - 60), number, fontsize=28)
    return page


def line(page, pts, color=BLUE, width=1.4, dashes=None):
    sh = page.new_shape()
    for a, b in zip(pts, pts[1:]):
        sh.draw_line(P(*a), P(*b))
    sh.finish(color=color, width=width, dashes=dashes, closePath=False)
    sh.commit()


def text(page, xy, s, size=8):
    page.insert_text(P(*xy), s, fontsize=size)


def recept(page, c):
    sh = page.new_shape()
    sh.draw_circle(c, 5)
    sh.draw_line(c + (-7, -2), c + (-5, -2))
    sh.draw_line(c + (-7, 2), c + (-5, 2))
    sh.finish(color=BLACK, width=0.8)
    sh.commit()


def legend(page, lx=W - 560, ly=120):
    page.insert_text((lx, ly), "LEGEND", fontsize=12)
    recept(page, fitz.Point(lx + 10, ly + 24))
    page.insert_text((lx + 30, ly + 27), "DUPLEX RECEPTACLE", fontsize=8)


def run_set(doc, **kw):
    rows = ait.plan_set(doc)
    return rows, ait.run(doc, rows, **kw)


# ---- (a) same-name systems are summed -----------------------------------------------
def test_a_same_name_pipe_systems_add_up():
    d = fitz.open()
    p = sheet(d, "P-101", "PLUMBING PLAN")
    line(p, [(2, 6), (42, 6)], BLUE)                         # 40 ft solid
    text(p, (12, 5.4), '2" W')
    line(p, [(2, 20), (27, 20)], BLUE, 1.0, "[4 2] 0")       # 25 ft dashed
    text(p, (10, 19.4), '2" W')
    rows, res = run_set(d)
    pipes = res["sheets"][0]["pipes"]
    assert pipes['2" W'] == pytest.approx(65, abs=0.6), pipes
    assert ait.totals(res)["pipe"]['2" W'] == pytest.approx(65, abs=0.6)
    marked = sum(pl["measure"]["value"] for _p, _k, pl in res["marks"]
                 if pl["measure"]["group"] == '2" W')
    assert marked == pytest.approx(pipes['2" W'])        # summary == marks
    assert "2\" W: 65 ft" in ait.summary_text(rows, res)


# ---- (b) rooms on several plans -----------------------------------------------------
def floor_sheet(d, number, title):
    page = sheet(d, number, title)
    practice._walls(page)
    for x, y, name, sf in ((38, 9, "EXAM 101", 675), (8, 29, "OFFICE 102",
                                                       441),
                           (30, 29, "KENNEL 103", 333),
                           (48, 29, "STORAGE 104", 320)):
        page.insert_text(practice._p(x, y), name, fontsize=12)
        page.insert_text(practice._p(x, y + 1.3), f"{sf} SF", fontsize=10)
    return page


def test_b_room_on_several_plans_taken_off_once_from_the_floor_plan():
    pytest.importorskip("cv2")
    one = fitz.open()
    floor_sheet(one, "A-101", "FLOOR PLAN")
    _rows, res1 = run_set(one)
    n1 = ait.totals(res1)["rooms"]
    assert n1 >= 3
    d = fitz.open()
    floor_sheet(d, "A-901", "FLOOR FINISH PLAN")       # finish plan first
    floor_sheet(d, "A-102", "DIMENSION FLOOR PLAN")
    floor_sheet(d, "A-101", "FLOOR PLAN")
    rows, res = run_set(d)
    assert [r["engines"] for r in rows] == [["rooms"]] * 3
    tot = ait.totals(res)
    assert tot["rooms"] == n1, tot
    assert tot["rooms_sf"] == pytest.approx(ait.totals(res1)["rooms_sf"],
                                            rel=0.01)
    pages = {p for p, kind, _pl in res["marks"] if kind == "add_polygon"}
    assert pages == {2}, pages                     # the FLOOR PLAN's page
    assert res["rooms_dup"]
    assert any("taken off once, from A-101" in p for p in res["problems"])
    # missed on one sheet but taken off from another isn't "not found"
    assert not any("not found" in p for p in res["problems"]
                   if p.startswith(("A-901", "A-102")))


def test_b_room_matching_rules():
    a = {"name": "PUBLIC DOG INTAKE 108", "sqft": 278, "tag_sf": 278}
    assert ait._same_room(a, {"name": "PUBLIC DOG INTAKE 108", "sqft": 281,
                              "tag_sf": None})
    assert ait._same_room(a, {"name": "108", "sqft": 280, "tag_sf": None})
    assert not ait._same_room(a, {"name": "OFFICE 108", "sqft": 278,
                                  "tag_sf": 278})       # another building
    assert not ait._same_room(a, {"name": "DOG INTAKE 109", "sqft": 278,
                                  "tag_sf": 278})
    assert not ait._same_room(a, {"name": "PUBLIC DOG INTAKE 108",
                                  "sqft": 600, "tag_sf": None})
    assert ait.plan_rank({"title": "FLOOR PLAN"}) == 0
    assert ait.plan_rank({"title": "ENLARGED PLANS"}) == 2
    assert ait.plan_rank({"title": "FLOOR FINISH PLAN"}) == 3


# ---- (c) duplicate and superseded sheets --------------------------------------------
def device_sheet(d, number, n, date):
    page = sheet(d, number, "POWER PLAN", date=date)
    legend(page)
    for i in range(n):
        recept(page, fitz.Point(*P(4 + 7 * i, 10)))
    return page


def test_c_only_the_latest_issue_is_taken_off():
    pytest.importorskip("cv2")
    d = fitz.open()
    device_sheet(d, "E-101", 5, "07/31/26")            # rev B: 5 outlets
    device_sheet(d, "E-101", 6, "09/23/26")            # rev C: 6 outlets
    device_sheet(d, "E-201", 2, "07/31/26")
    rows, res = run_set(d)
    assert rows[0]["kind"] == "superseded" and rows[0]["engines"] == []
    assert "page 2" in rows[0]["note"] and "09/23/2026" in rows[0]["note"]
    assert rows[1]["engines"] == ["devices"]
    assert rows[2]["engines"] == ["devices"]
    tot = ait.totals(res)["devices"]
    assert tot == {"DUPLEX RECEPTACLE": 8}, tot          # 6 + 2, not 13
    assert not any(p == 0 for p, _k, _pl in res["marks"])
    text_ = ait.summary_text(rows, res)
    assert "Superseded / duplicate sheets" in text_


def test_c_the_latest_date_wins_wherever_it_is_bound():
    d = fitz.open()
    sheet(d, "A-803", "DOOR DETAILS", date="09/23/26")
    sheet(d, "A-803", "DOOR DETAILS", date="08/10/26")
    rows = ait.plan_set(d)
    assert rows[1]["kind"] == "superseded" and rows[1]["superseded_by"] == 0
    assert rows[0]["kind"] != "superseded"


def test_c_no_dates_takes_the_later_page_and_says_so():
    d = fitz.open()
    sheet(d, "A-903", "FINISH SCHEDULE")
    sheet(d, "A-903", "FINISH SCHEDULE")
    rows = ait.plan_set(d)
    assert rows[0]["kind"] == "superseded"
    assert "can't tell" in rows[0]["note"]


# ---- (d) legends: a symbol and a short name, or it isn't a device -------------------
def test_d_notes_lists_and_schedules_are_not_devices():
    pytest.importorskip("cv2")
    d = fitz.open()
    p = sheet(d, "E-001", "ELECTRICAL LEGEND AND NOTES")
    lx, ly = 900, 120
    p.insert_text((lx, ly), "ELECTRICAL SYMBOLS:", fontsize=10)
    recept(p, fitz.Point(lx + 10, ly + 24))
    p.insert_text((lx + 30, ly + 27), "DUPLEX RECEPTACLE", fontsize=8)
    # a list with a small drawn mark beside it: not a device name
    sh = p.new_shape()
    sh.draw_rect(fitz.Rect(lx + 5, ly + 41, lx + 15, ly + 51))
    sh.finish(color=BLACK, width=0.8)
    sh.commit()
    p.insert_text((lx + 30, ly + 49), 'ANGLE STOPS, 3/8" SUPPLIES, AND TRAP',
                  fontsize=8)
    # notes with no symbol at all
    p.insert_text((lx + 30, ly + 71),
                  "SPILLWAYS THAT MUST BE LOCATED ON FILL MATERIAL.",
                  fontsize=8)
    p.insert_text((lx + 30, ly + 93), "SEE ELECTRICAL DRAWINGS FOR FIXTURE "
                  "SCHED.", fontsize=8)
    # a schedule below its own heading: ruled cells, text only
    p.insert_text((lx, ly + 160), "FIXTURE SCHEDULE", fontsize=10)
    sh = p.new_shape()
    for i in range(4):
        sh.draw_line((lx - 20, ly + 170 + 20 * i), (lx + 400, ly + 170 + 20 * i))
    for x in (lx - 20, lx + 20, lx + 400):
        sh.draw_line((x, ly + 170), (x, ly + 230))
    sh.finish(color=BLACK, width=0.5)
    sh.commit()
    p.insert_text((lx + 30, ly + 185), "#J-35 STRAINER, AMERICAN STANDARD "
                  "6540.178 FAUCET,", fontsize=8)
    p.insert_text((lx + 30, ly + 205), "FOR ALL RELATED ITEMS .", fontsize=8)
    # "SEE LEGEND ..." in a sentence is not a legend heading
    p.insert_text((200, 900), "SEE LEGEND FOR SYMBOLS NOT SHOWN.", fontsize=8)
    for i in range(4):
        recept(p, fitz.Point(*P(4 + 7 * i, 10)))
    rej = []
    rows = tt.legend_rows(p, rejects=rej)
    assert [r[0] for r in rows] == ["DUPLEX RECEPTACLE"], rows
    assert any("ANGLE STOPS" in t for t, _why in rej), rej
    rep = {}
    counts = {c["name"]: len(c["hits"])
              for c in tt.legend_counts(d, report=rep)}
    assert counts == {"DUPLEX RECEPTACLE": 4}, counts
    assert rep["rejected"] and rep["not_counted"] == []


def test_d_device_label_rules():
    assert tt.device_label("DUPLEX RECEPTACLE") == "DUPLEX RECEPTACLE"
    assert tt.device_label("FIRE ALARM MANUAL PULL STATION. MOUNT 48\" TO "
                           "TOP OF BOX") == "FIRE ALARM MANUAL PULL STATION"
    assert tt.device_label("CEILING / WALL MOUNTED EXIT SIGN - SHADING "
                           "INDICATES FACE(S)") == \
        "CEILING / WALL MOUNTED EXIT SIGN"
    assert tt.device_label("FIRE ALARM WALL MOUNTED VISUAL DEVICE 80\" "
                           "A.F.F.") == "FIRE ALARM WALL MOUNTED VISUAL DEVICE"
    for bad in ("SPILLWAYS THAT MUST BE LOCATED ON FILL MATERIAL.",
                'ANGLE STOPS, 3/8" SUPPLIES, AND TRAP',
                "#J-35 STRAINER, AMERICAN STANDARD 6540.178 FAUCET,",
                "FOR ALL RELATED ITEMS .",
                "SEE ELECTRICAL DRAWINGS FOR FIXTURE SCHED.",
                "DD SUBMITTAL FOR OWNER REVIEW",
                "DUPLEX RECEPTACLE CONCEALED BEHIND OR WITHIN ENCLOSURE OF "
                "ELECTRIC WATER"):
        assert tt.device_label(bad) is None, bad


# ---- (e) pipe runs: connected or straight on, never just nearby ---------------------
def test_e_tag_spreads_only_along_its_own_pipe():
    d = fitz.open()
    p = sheet(d, "P-101", "PLUMBING PLAN")
    practice._walls(p)                                # black double walls
    # 2" W: broken where its tag sits, with a tee branch
    line(p, [(2, 10), (30, 10)], BLUE)
    line(p, [(32, 10), (42, 10)], BLUE)
    line(p, [(20, 10), (20, 16)], BLUE)
    text(p, (30.2, 10.25), '2" W', 7)
    # casework and a dimension line in another style, within 6 ft of the
    # tag but not part of the pipe
    line(p, [(25, 13), (45, 13)], BLACK, 0.5)
    line(p, [(25, 7), (45, 7)], BLACK, 0.5)
    # a stray size tag sitting on a wall face: no pipe there
    text(p, (50, 0.55), '1/2" HW', 7)
    sys_ = tt.mep_runs(p, PPU, "ft")
    by = {g["name"]: g for g in sys_ if g["labelled"]}
    assert by['2" W']["suggested"]
    assert by['2" W']["length"] == pytest.approx(44, abs=0.6), \
        [(g["name"], round(g["length"], 1)) for g in sys_]
    hw = by.get('1/2" HW')
    assert hw is None or not hw["suggested"]
    assert hw is None or hw["flag"]


def test_e_a_system_longer_than_the_drawing_is_flagged_not_taken_off():
    d = fitz.open()
    p = sheet(d, "P-101", "PLUMBING PLAN")
    # one style drawing a dense grid (a wall / ceiling grid), single lines,
    # with a size tag on it
    grid = []
    for x in range(0, 61, 2):
        grid.append([(x, 0), (x, 40)])
    for y in range(0, 41, 2):
        grid.append([(0, y), (60, y)])
    for g in grid:
        line(p, g, BLUE, 1.0)
    text(p, (10.3, 9.7), '2" W', 7)
    rows, res = run_set(d)
    sys_ = tt.mep_runs(p, PPU, "ft")
    w = [g for g in sys_ if g["name"] == '2" W'][0]
    assert w["flag"] and not w["suggested"]
    assert '2" W' not in ait.totals(res)["pipe"]
    assert any(r["name"] == '2" W' for r in res["review"])
    assert "not measured with confidence" in ait.summary_text(rows, res)


def test_e_plausible_extent():
    box = [(0, 0, 90 * PPU, 47 * PPU)]
    cap = tt.plausible_ft(box, PPU)
    assert 3 * 2 * (90 + 47) == pytest.approx(cap)
    assert cap < 2583                         # the Aiken 2" W


# ---- (f) existing work ----------------------------------------------------------------
def test_f_existing_pipe_is_listed_not_totalled():
    d = fitz.open()
    p = sheet(d, "P-101", "PLUMBING PLAN")
    line(p, [(2, 6), (42, 6)], BLUE)
    text(p, (12, 5.4), '4" W')
    line(p, [(2, 20), (32, 20)], (0.5, 0.5, 0.5))
    text(p, (10, 19.4), 'EX. 4" W')
    line(p, [(2, 30), (22, 30)], RED, 1.0)
    text(p, (8, 29.4), '2" CW (E)')
    rows, res = run_set(d)
    tot = ait.totals(res)
    assert tot["pipe"] == {'4" W': pytest.approx(40, abs=0.6)}, tot["pipe"]
    ex = {e["name"]: e["length"] for e in res["existing"]}
    assert ex.get('4" W (existing)') == pytest.approx(30, abs=0.6), ex
    assert ex.get('2" CW (existing)') == pytest.approx(20, abs=0.6), ex
    assert "not in the totals" in ait.summary_text(rows, res)


def test_f_civil_existing_labels():
    for t in ('6" PVC SAN (E)', '(E) 8" PVC SANITARY', 'EXIST. 6" W',
              '18" RCP EXISTING', 'EX. 18" RCP STORM'):
        assert civiltakeoff.parse_pipe_label(t)["existing"], t
    for t in ('8" PVC SAN TO EXISTING MH', '6" PVC SDR-26 SAN'):
        assert not civiltakeoff.parse_pipe_label(t)["existing"], t


def test_f_civil_existing_never_in_ai_totals(monkeypatch):
    d = fitz.open()
    sheet(d, "C-301", "UTILITY PLAN")
    run_ = {"pts": [P(0, 0), P(50, 0)], "length": 50.0, "page": 0,
            "depth": None}
    new = {"name": '6" PVC sanitary', "existing": False, "size": 6,
           "system": "sanitary", "runs": [dict(run_)], "bands": {None: 50.0},
           "length": 50.0, "label_length": 0.0}
    old = dict(new, name='6" water (existing)', existing=True,
               system="water", runs=[dict(run_, length=900.0)],
               length=900.0)
    monkeypatch.setattr(civiltakeoff, "takeoff", lambda *a, **k: {
        "pipes": [new, old], "structures": [], "pages": [0], "checks": [],
        "grade": None})
    rows, res = run_set(d)
    tot = ait.totals(res)
    assert all("existing" not in n for n in tot["pipe"]), tot["pipe"]
    assert sum(tot["pipe"].values()) == pytest.approx(50)
    assert not any("existing" in pl["measure"]["group"]
                   for _p, _k, pl in res["marks"])
    assert tot["existing"] == {'6" water (existing)': 900.0}


# ---- (g) roof pitch -------------------------------------------------------------------
def test_g_roof_pitch_notations():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    for i, s in enumerate(('5"/1\'-0"', '2"/1\'-0"', "6:12", "6 in 12",
                           '1/4"/1\'-0"')):
        p.insert_text((100 + 200 * i, 300), s, fontsize=9)
    got = sorted(v for v, _c in tt.pitch_labels(p))
    assert got == [0.25, 2, 5, 6, 6], got
    for s, v in (('5"/1\'-0"', 5), ("6 IN 12", 6), ("SLOPE 2\"/1'-0\"", 2),
                 ("4/12", 4), ('1/4" PER FT', 0.25), ("6:12 PITCH", 6)):
        assert tt.pitch_value(s) == v, s
    for s in ("A-501", '3/4" CW', "1/A-301", "12"):
        assert tt.pitch_value(s) is None, s
    poly = [(90, 280), (300, 280), (300, 320), (90, 320)]
    assert tt.pitch_for(poly, tt.pitch_labels(p)) == 5


# ---- (h) submittals from a CSI 3-part spec --------------------------------------------
HEAD = ["MADE-UP CLINIC FOR TESTS", "SOMEWHERE, SC", "1234.5678"]
SPEC_PAGES = [
    HEAD + ["SECTION 033000 - CAST-IN-PLACE CONCRETE", "PART 1 - GENERAL",
            "1.1", "SUMMARY", "A.", "Section Includes:", "1.", "2.",
            "Concrete materials.", "Admixtures.", "B.",
            "Related Requirements:", "1.",
            'Section 031000 "Concrete Forming and Accessories" for form-'
            "facing materials.",
            "1.2", "ACTION SUBMITTALS", "A.", "Product Data:", "1.", "2.",
            "Fly ash.", "Aggregates.",
            "CAST-IN-PLACE CONCRETE", "033000 - 1"],
    HEAD + ["B.", "Design Mixtures: For each concrete mixture.",
            "1.3", "INFORMATIONAL SUBMITTALS", "A.",
            "Material Test Reports: For each material.",
            "1.4", "QUALITY ASSURANCE", "A.",
            "Installer Qualifications: A qualified installer.",
            "CAST-IN-PLACE CONCRETE", "033000 - 2"],
    HEAD + ["PART 2 - PRODUCTS", "2.1", "CONCRETE MATERIALS", "A.",
            "Portland cement: ASTM C150.", "END OF SECTION 033000",
            "CAST-IN-PLACE CONCRETE", "033000 - 3"],
    HEAD + ["SECTION 087100 - DOOR HARDWARE", "PART 1 - GENERAL",
            "1.1", "SUBMITTALS", "A.", "Product Data: For each type.",
            "B.", "Door Hardware Schedule: Prepared by the consultant.",
            "PART 2 - PRODUCTS", "END OF SECTION 087100",
            "DOOR HARDWARE", "087100 - 1"],
]


def test_h_submittals_with_numbers_on_their_own_lines():
    props = submittals.from_spec_text(["\n".join(p) for p in SPEC_PAGES])
    got = {(p["spec"], p["title"]) for p in props}
    assert ("03 30 00", "Cast-In-Place Concrete - Product Data") in got
    assert ("03 30 00", "Cast-In-Place Concrete - Design Mixtures") in got
    assert ("03 30 00", "Cast-In-Place Concrete - Material Test Reports") \
        in got
    assert ("08 71 00", "Door Hardware - Product Data") in got
    assert ("08 71 00", "Door Hardware - Door Hardware Schedule") in got
    # a cross reference doesn't start a section; QA and PART 2 aren't
    # submittals; the running header isn't an item
    assert not [g for g in got if g[0] == "03 10 00"]
    assert not [g for g in got if "Installer" in g[1] or "Portland" in g[1]
                or "1234" in g[1] or "MADE-UP" in g[1]]
    assert len(props) == 5, got


def test_h_from_spec_book_reads_a_pdf(tmp_path):
    d = fitz.open()
    for lines in SPEC_PAGES:
        pg = d.new_page()
        for i, ln in enumerate(lines):
            pg.insert_text((72, 60 + 16 * i), ln, fontsize=9)
    path = str(tmp_path / "made_up_spec.pdf")
    d.save(path)
    props = submittals.from_spec_book(path)
    assert len(props) == 5, [p["title"] for p in props]


# ---- (i) time limits never drop work silently -----------------------------------------
def test_i_device_time_limit_lists_what_was_not_counted():
    pytest.importorskip("cv2")
    d = fitz.open()
    device_sheet(d, "E-101", 3, "07/31/26")
    rows, res = run_set(d, device_time_limit=1e-9)
    assert any(u["engine"] == "devices" and "time limit" in u["why"]
               for u in res["unfinished"]), res["unfinished"]
    assert any("not counted" in p for p in res["problems"])
    assert "Not finished" in ait.summary_text(rows, res)


def test_i_sheet_time_limit_lists_the_sheet():
    pytest.importorskip("cv2")
    d = fitz.open()
    floor_sheet(d, "A-101", "FLOOR PLAN")
    rows, res = run_set(d, sheet_time_limit=1e-9)
    assert res["unfinished"] and res["unfinished"][0]["sheet"] == "A-101"
    assert res["unfinished"][0]["engine"] == "rooms"
    assert not [m for m in res["marks"] if m[1] == "add_polygon"]


def test_i_stop_lists_every_sheet_not_reached():
    d = fitz.open()
    for n in ("P-101", "P-102", "P-103"):
        p = sheet(d, n, "PLUMBING PLAN")
        line(p, [(2, 6), (42, 6)], BLUE)
        text(p, (12, 5.4), '2" W')
    rows = ait.plan_set(d)
    calls = []

    def progress(k, n, t):
        calls.append(t)
        return len(calls) < 2                 # stop on the second step
    res = ait.run(d, rows, progress)
    assert "Stopped before the end." in res["problems"]
    left = {u["sheet"] for u in res["unfinished"]}
    assert {"P-102", "P-103"} <= left, res["unfinished"]
