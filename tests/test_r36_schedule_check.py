"""r36 v2 step 6 item 1: the takeoff checked against the plan's own
schedules (door, window, fixture, equipment and finish schedules read from
the PDF's text with the host's own table reader - no OCR, nothing sent
anywhere). Advisory only: findings carry a confidence and the takeoff is
never changed. Every drawing here is made up in the test."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, settings                  # noqa: E402
from app.estimating import checks, schedcheck                    # noqa: E402
from estimate_helpers import area                                # noqa: E402
from test_aitakeoff_phase2 import sheet, table                   # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    schedcheck.clear_cache()


def _count(d, group, n, page=0, x=200, y=200):
    for i in range(n):
        annotate.apply_op(d, annotate.new_op(
            "add_count", page, pt=[x + 14 * i, y], n=i + 1,
            color=[0.8, 0.2, 0.1],
            measure={"type": "count", "value": 1, "unit": "ea",
                     "group": group}))


def made_up_set(misaligned=False):
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    s = sheet(d, "A-801", "SCHEDULES")
    table(s, 100, 100, "DOOR SCHEDULE",
          [["DOOR", "WIDTH", "TYPE", "HDW"], ["NO.", "", "", "SET"]],
          [["101", "3'-0\"", "A", "1.0"],
           ["102", "3'-0\"", "A", "2.0"],
           ["103", "3'-0\"", "B", "2.0"]], [60, 60, 50, 60])
    table(s, 900, 300, "WINDOW SCHEDULE",
          [["MARK", "DESCRIPTION", "QTY"]],
          [["A", "FIXED ALUMINUM WINDOW", "2"],
           ["B", "OPERABLE ALUMINUM WINDOW", "1"]], [50, 160, 40])
    table(s, 100, 600, "ROOM FINISH SCHEDULE",
          [["ROOM", "NAME", "FLOOR", "BASE", "WALLS", "CEILING"]],
          [["101", "OFFICE", "CPT-1", "RB-1", "PT-1", "ACT-1"],
           ["102", "LOBBY", "LVT-1", "RB-1", "PT-1", "ACT-1"]],
          [50, 80, 50, 50, 50, 50])
    p = sheet(d, "P-301", "PLUMBING SCHEDULES")
    rows = [["P-1", "WALL HUNG LAVATORY", "KOHLER K-2005", "2"],
            ["P-2", "WATER CLOSET", "KOHLER K-4325", "2"],
            ["P-3", "SINGLE BOWL SINK", "ELKAY LR-1918", "2"]]
    if misaligned:          # every description runs across the QTY column
        p.insert_text((100, 100), "PLUMBING FIXTURE SCHEDULE", fontsize=12)
        for x, t in ((104, "MARK"), (200, "FIXTURE"), (330, "QTY")):
            p.insert_text((x, 122), t, fontsize=8)
        for i, (k, desc) in enumerate((
                ("P-1", "WALL HUNG LAVATORY WITH CARRIER"),
                ("P-2", "WATER CLOSET FLOOR MOUNTED TANK"),
                ("P-3", "SINK SINGLE BOWL STAINLESS"))):
            p.insert_text((104, 140 + 13 * i), k, fontsize=8)
            p.insert_text((200, 140 + 13 * i), desc, fontsize=8)
    else:
        table(p, 100, 100, "PLUMBING FIXTURE SCHEDULE",
              [["MARK", "FIXTURE", "MANUFACTURER", "QTY"]], rows,
              [50, 140, 120, 40])
    e = sheet(d, "E-601", "ELECTRICAL SCHEDULES")
    table(e, 100, 100, "LIGHT FIXTURE SCHEDULE",
          [["TYPE", "DESCRIPTION", "MANUFACTURER"]],
          [["A", "2X4 LED TROFFER", "MADE-UP CO"],
           ["B", "LED DOWNLIGHT", "MADE-UP CO"]], [50, 140, 120])
    # the takeoff on the floor plan
    _count(d, "Doors", 2)
    _count(d, "Hardware set 2.0", 2, y=230)
    _count(d, "Window A", 2, y=260)
    _count(d, "Window B", 3, y=290)
    _count(d, "Window C", 1, y=320)
    _count(d, "P-1 WALL HUNG LAVATORY", 2, y=350)
    _count(d, "P-3 SINGLE BOWL SINK", 1, y=380)
    _count(d, "P-9 MYSTERY FIXTURE", 1, y=410)
    _count(d, "Light A 2X4 LED TROFFER", 4, y=440)
    _count(d, "DUPLEX CONVENIENCE OUTLET", 6, y=470)
    area(d, "OFFICE 101", 10, 12, x0=700, y0=200)
    area(d, "STORAGE 105", 8, 8, x0=900, y0=200)
    return d


def _by(found, check, kind=None):
    return {f["key"]: f for f in found
            if f["check"] == check and (kind is None or f["kind"] == kind)}


def test_the_schedules_are_found_in_the_pdf_text():
    res = schedcheck.check(made_up_set())
    kinds = sorted(t["kind"] for t in res["schedules"])
    assert kinds == ["door", "finish", "light fixtures", "plumbing fixtures",
                     "window"], res["schedules"]
    door = next(t for t in res["schedules"] if t["kind"] == "door")
    assert door["rows"] == 3 and door["sheet"] == "A-801"
    assert door["confident"]


def test_count_mismatches_are_flagged():
    f = schedcheck.check(made_up_set())["findings"]
    c = _by(f, "count")
    assert c["Doors"]["schedule_qty"] == 3 and c["Doors"]["takeoff_qty"] == 2
    assert c["B"]["kind"] == "window" and c["B"]["schedule_qty"] == 1 \
        and c["B"]["takeoff_qty"] == 3
    assert c["P-3"]["schedule_qty"] == 2 and c["P-3"]["takeoff_qty"] == 1
    # agreeing counts are not findings
    assert "A" not in _by(f, "count", "window") and "P-1" not in c
    assert "2.0" not in c                 # hardware set 2.0: 2 on both
    for x in c.values():
        assert x["confidence"] in ("high", "medium", "low")
        assert "schedule" in x["message"].lower()


def test_missing_types_are_flagged():
    f = schedcheck.check(made_up_set())["findings"]
    m = _by(f, "missing")
    assert m["P-2"]["kind"] == "plumbing fixtures"
    assert m["P-2"]["schedule_qty"] == 2 and m["P-2"]["takeoff_qty"] == 0
    assert m["1.0"]["kind"] == "hardware"          # door 101's set
    assert m["B"]["kind"] == "light fixtures"
    assert m["B"]["schedule_qty"] is None   # the schedule gives no count
    assert m["102"]["kind"] == "finish"      # room on the finish schedule
    assert "A" not in _by(f, "missing", "window")
    assert "101" not in _by(f, "missing", "finish")


def test_takeoff_items_not_on_any_schedule_are_flagged():
    f = schedcheck.check(made_up_set())["findings"]
    x = _by(f, "extra")
    assert x["C"]["kind"] == "window" and x["C"]["group"] == "Window C"
    assert x["P-9"]["kind"] == "plumbing fixtures"
    assert x["P-9"]["takeoff_qty"] == 1
    assert x["105"]["kind"] == "finish"
    # takeoff that no schedule covers (outlets) is left alone
    assert not any("OUTLET" in v["group"] for v in x.values())


def test_confidence_is_lower_for_a_table_not_read_with_confidence():
    good = schedcheck.check(made_up_set())["findings"]
    p3 = _by(good, "count")["P-3"]
    assert p3["confidence"] == "high"
    # a light fixture schedule with no QTY column: presence only
    assert _by(good, "missing")["B"]["confidence"] in ("medium", "low")
    bad = schedcheck.check(made_up_set(misaligned=True))
    t = next(t for t in bad["schedules"] if t["kind"] == "plumbing fixtures")
    assert not t["confident"]
    pf = [v for v in bad["findings"] if v["kind"] == "plumbing fixtures"]
    assert pf and all(v["confidence"] == "low" for v in pf)


def test_the_takeoff_is_never_changed():
    d = made_up_set()
    before = [dict(i) for i in annotate.takeoff_items(d)]
    n = sum(len(list(d[i].annots())) for i in range(d.page_count))
    schedcheck.check(d)
    checks.run(d)
    assert [dict(i) for i in annotate.takeoff_items(d)] == before
    assert sum(len(list(d[i].annots())) for i in range(d.page_count)) == n


def test_a_drawing_with_no_schedules_has_no_findings():
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    _count(d, "Window A", 2)
    res = schedcheck.check(d)
    assert res["schedules"] == [] and res["findings"] == []


def test_a_schedule_sheet_issued_twice_is_read_once():
    d = made_up_set()
    again = fitz.open()
    again.insert_pdf(d, from_page=1, to_page=1)
    d.insert_pdf(again)                           # A-801 again at the end
    res = schedcheck.check(d)
    assert sorted(t["kind"] for t in res["schedules"]).count("door") == 1
    assert _by(res["findings"], "count")["Doors"]["schedule_qty"] == 3


def test_schedule_findings_are_error_check_rules():
    found = checks.run(made_up_set())
    rules = {f["rule"] for f in found}
    assert {"sched_count", "sched_missing", "sched_extra"} <= rules
    for f in found:
        if f["rule"].startswith("sched_"):
            assert f["severity"] == "warning"           # advisory only
            assert "confidence" in f["message"]
            assert f["confidence"] in ("high", "medium", "low")


def test_report_lists_quantities_only():
    res = schedcheck.check(made_up_set())
    text = schedcheck.report(res)
    assert "DOOR SCHEDULE" in text and "P-3" in text
    assert "$" not in text


def test_a_drawing_index_naming_schedule_sheets_is_not_a_schedule():
    # real sets list 'HVAC SCHEDULES' / 'DOOR SCHEDULE' as sheet titles in
    # the cover sheet's index; its rows are sheet numbers, not types
    d = made_up_set()
    c = sheet(d, "G-001", "COVER SHEET")
    table(c, 100, 100, "HVAC SCHEDULES",
          [["SHEET", "TITLE"]],
          [["A-101", "FLOOR PLAN"], ["A-801", "SCHEDULES"],
           ["P-301", "PLUMBING SCHEDULES"]], [60, 200])
    res = schedcheck.check(d)
    assert not any(t["sheet"] == "G-001" for t in res["schedules"])
    assert any(t["sheet"] == "G-001" and "index" in t["why"]
               for t in res["not_read"])
    assert "G-001" in schedcheck.report(res)
    assert not any(f["key"] in ("A-101", "A-801", "P-301")
                   for f in res["findings"])


def test_an_empty_schedule_gives_no_count_finding():
    d = fitz.open()
    s = sheet(d, "A-801", "SCHEDULES")
    s.insert_text((100, 100), "DOOR SCHEDULE", fontsize=12)
    _count(d, "Doors", 5)
    res = schedcheck.check(d)
    assert not [f for f in res["findings"] if f["check"] == "count"]


def test_hardware_sets_named_longer_on_the_schedule_add_up():
    d = fitz.open()
    sheet(d, "A-101", "FLOOR PLAN")
    s = sheet(d, "A-801", "SCHEDULES")
    table(s, 100, 100, "DOOR SCHEDULE",
          [["DOOR", "WIDTH", "TYPE", "HDW"], ["NO.", "", "", "SET"]],
          [["101", "3'-0\"", "A", "ACCESS CTRL ALUM"],
           ["102", "3'-0\"", "A", "ACCESS CTRL HM"],
           ["103", "3'-0\"", "B", "ACCESS CTRL HM"]], [60, 60, 50, 110])
    _count(d, "Doors", 3)
    _count(d, "Hardware set ACCESS CTRL", 3, y=230)
    f = schedcheck.check(d)["findings"]
    assert not [x for x in f if x["kind"] == "hardware"], f


def test_the_same_finding_is_listed_once():
    f = schedcheck.check(made_up_set())["findings"]
    keys = [(x["check"], x["kind"], x["key"]) for x in f]
    assert len(keys) == len(set(keys))
