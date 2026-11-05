"""ClaimIT 0.2.2: odd-shaped rooms (an alcove / extra leg, a corner cut
out) and room measurements + payments in the CSV and Excel exports.
Made-up data only."""
import csv
import dataclasses
import json
from decimal import Decimal

import pytest

from quantisheet_claims import diary, practice, rooms, store
from quantisheet_claims import model as m
from quantisheet_claims.export import build_model, to_csv, to_xlsx


def test_alcove_adds_floor_and_two_side_walls():
    r = rooms.set_part(rooms.new_room("Den", "12", "10", "8"), "bump",
                       "4", "3")
    ms = rooms.measure(r)
    assert ms.floor == Decimal("132.00")             # 120 + 4 x 3
    assert ms.perimeter == Decimal("50.00")          # 44 + 2 x 3
    assert ms.walls == Decimal("400.00")             # 50 x 8
    assert ms.ceiling == ms.floor


def test_corner_cut_makes_an_l_with_the_same_perimeter():
    r = rooms.set_part(rooms.new_room("Ell", "20", "15", "8"), "cut",
                       "8", "6")
    ms = rooms.measure(r)
    assert ms.floor == Decimal("252.00")             # 300 - 48
    assert ms.perimeter == Decimal("70.00")          # L-shape: same as 20x15
    assert ms.baseboard == Decimal("70.00")


def test_parts_take_feet_and_inches_and_can_be_removed():
    r = rooms.set_part(rooms.new_room("Hall", "10", "4", "8"), "bump",
                       "3'6\"", "2'")
    assert rooms.measure(r).floor == Decimal("47.00")       # 40 + 3.5 x 2
    r = rooms.set_part(r, "bump", "0", "0")
    assert r.parts == () and rooms.measure(r).floor == Decimal("40.00")


def test_bad_parts_are_refused():
    base = rooms.new_room("Box", "10", "10", "8")
    with pytest.raises(rooms.RoomError):
        rooms.set_part(base, "cut", "10", "10")      # as big as the room
    with pytest.raises(rooms.RoomError):
        rooms.set_part(base, "bump", "-2", "3")
    with pytest.raises(rooms.RoomError):
        rooms.set_part(base, "wing", "2", "3")
    with pytest.raises(rooms.RoomError):
        rooms.set_part(rooms.new_room("Blank"), "cut", "2", "2")


def test_size_text_and_summary_show_the_parts():
    r = rooms.set_part(rooms.set_part(rooms.new_room("Ell", "20", "15", "8"),
                                      "cut", "8", "6"), "bump", "4", "2")
    assert rooms.size_text(r) == "20 x 15 x 8 ft - 8 x 6 + 4 x 2"
    assert "20 x 15 x 8 ft - 8 x 6 + 4 x 2" in rooms.summary(r)


def test_requantify_follows_the_shape():
    from quantisheet_claims import kits, library
    library.add_item("EX-PAD", "Example pad", "FLOORING", "SF", other="1")
    kits.save_kit("Pad", [("EX-PAD", "floor", "1")])
    plain = rooms.new_room("Ell", "20", "15", "8")
    ln = kits.apply("Pad", plain, first_ordinal=1)[0]
    shaped = rooms.set_part(plain, "cut", "8", "6")
    assert rooms.requantify(ln, shaped) == 2_520_000


def _shaped_claim():
    c = practice.claim()
    r0 = rooms.set_part(c.rooms[0], "bump", "4", "3")
    return dataclasses.replace(c, rooms=(r0,) + c.rooms[1:])


def test_file_version_3_only_with_odd_shapes(tmp_path):
    plain = practice.claim()
    p = store.save(plain, folder=str(tmp_path / "a"))
    assert json.load(open(p))["schema_version"] == 2
    shaped = _shaped_claim()
    p = store.save(shaped, folder=str(tmp_path / "b"))
    assert json.load(open(p))["schema_version"] == 3
    back, _ = store.load(p)
    assert back.rooms[0].parts == shaped.rooms[0].parts
    assert rooms.measure(back.rooms[0]).floor == \
        rooms.measure(shaped.rooms[0]).floor


def test_a_shape_only_in_a_revision_still_marks_the_file(tmp_path):
    from quantisheet_claims.revision import Revision
    rev = Revision(number=1, claim=_shaped_claim())
    p = store.save(practice.claim(), [rev], folder=str(tmp_path))
    assert json.load(open(p))["schema_version"] == 3


def _paid(c):
    return dataclasses.replace(c, payments=diary.add_payment(
        c, "2026-10-10", "100.00", "acv", "CHK 7"))


def test_csv_lists_rooms_and_payments(tmp_path):
    md = build_model(_paid(_shaped_claim()), printed="2026-11-01",
                     author="Example")
    p = to_csv(md, str(tmp_path / "x.csv"))
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    i = rows.index(["Room", "Size (L x W x H)", "Floor SF", "Walls SF",
                    "Ceiling SF", "Perimeter LF"])
    assert rows[i + 1][0] == "Kitchen" and "+ 4 x 3" in rows[i + 1][1]
    j = rows.index(["Payment date", "Kind", "Amount", "Reference"])
    assert rows[j + 1][0] == "2026-10-10" and rows[j + 1][3] == "CHK 7"
    assert rows[j + 2][0] == "Still open"


def test_xlsx_has_rooms_and_payments_sheets(tmp_path):
    from openpyxl import load_workbook
    md = build_model(_paid(practice.claim()), printed="2026-11-01",
                     author="Example")
    p = to_xlsx(md, str(tmp_path / "x.xlsx"))
    wb = load_workbook(p)
    rm = wb["Rooms"]
    assert rm["A2"].value == "Kitchen"
    assert Decimal(str(rm["C2"].value)) == Decimal("168")     # a number
    pa = wb["Payments"]
    assert pa["A2"].value == "2026-10-10"
    assert Decimal(str(pa["C2"].value)) == Decimal("100")
    assert pa["A3"].value == "Still open"


def test_no_rooms_or_payments_no_extra_sheets(tmp_path):
    from openpyxl import load_workbook
    c = dataclasses.replace(practice.claim(), rooms=(), payments=())
    p = to_xlsx(build_model(c, printed="2026-11-01", author="Example"),
                str(tmp_path / "y.xlsx"))
    assert "Rooms" not in load_workbook(p).sheetnames
    assert "Payments" not in load_workbook(p).sheetnames


def test_room_dialog_sets_and_keeps_parts(qtbot):
    from quantisheet_claims.ui.extras import RoomDialog
    d = RoomDialog()
    qtbot.addWidget(d)
    d.name.setText("Ell")
    d.length.setText("20")
    d.width.setText("15")
    d.parts["cut"][0].setText("8")
    d.parts["cut"][1].setText("6")
    assert "Floor 252.00 SF" in d.update_preview()
    r = d.room()
    assert rooms.part(r, "cut").along_ft == Decimal("8")
    d2 = RoomDialog(r)
    qtbot.addWidget(d2)
    assert d2.parts["cut"][0].text() == "8"
    assert d2.room().parts == r.parts and d2.room().id == r.id
    d2.parts["cut"][0].setText("30")
    assert d2.update_preview().startswith("⚠")


# ---- long names wrap in the PDF (r47 #8 left item) ------------------------
LONG = "Second floor primary bedroom walk-in closet and dressing area"


def test_pdf_wraps_long_room_names_instead_of_cutting(tmp_path):
    import pymupdf as fitz
    from quantisheet_claims.export import to_pdf
    c = practice.claim()
    r0 = dataclasses.replace(c.rooms[0], name=LONG)
    c = dataclasses.replace(c, rooms=(r0,) + c.rooms[1:])
    p = to_pdf(build_model(c, printed="2026-11-01", author="Example"),
               str(tmp_path / "long.pdf"))
    txt = " ".join(" ".join(pg.get_text().split()) for pg in fitz.open(p))
    for word in ("walk-in", "closet", "dressing", "area"):
        assert word in txt
    assert "..." not in txt.split("Room measurements")[-1].split("Settlement")[0]


def test_wrap_helper():
    from quantisheet_claims.export import _wrap
    lines = _wrap(LONG, 130, 8)
    assert 1 < len(lines) <= 3 and " ".join(lines) == LONG
    assert _wrap("", 100, 8) == [""]
    many = _wrap("word " * 200, 60, 8, max_lines=2)
    assert len(many) == 2 and many[-1].endswith("...")
    huge = _wrap("x" * 300, 60, 8, max_lines=100)
    assert all(len(t) < 300 for t in huge) and "".join(huge) == "x" * 300


def test_install_waits_for_a_running_build(tmp_path, monkeypatch):
    """Nov 1: an install queued behind a background build ran first and
    put the old ClaimIT back."""
    import importlib.util
    import os
    import time
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    src = open(os.path.join(root, "tools", "install_release.py"),
               encoding="utf-8").read()
    start = src.index("def wait_for_build")
    end = src.index("\nwait_for_build()")
    ns = {"os": os, "STATUS": str(tmp_path / "s")}
    exec(src[start:end], ns)
    wait = ns["wait_for_build"]
    wait()                                           # no status file: go
    (tmp_path / "s").write_text("done C:\\x")
    wait()
    (tmp_path / "s").write_text("failed (claims) - see the log")
    with pytest.raises(SystemExit):
        wait()
    (tmp_path / "s").write_text("running (claims)")
    old = time.time() - 6000
    os.utime(tmp_path / "s", (old, old))
    wait()                                           # stale: a dead build
    os.utime(tmp_path / "s", None)
    with pytest.raises(SystemExit):
        wait(limit_s=-1)                             # still running
    assert "ClaimIT-Setup-{CV}.exe" in src
