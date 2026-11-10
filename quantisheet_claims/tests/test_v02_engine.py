"""ClaimIT 0.2 engine: room measurements, line kits, diary and payments,
the before-you-send checklist and the practice claim. Made-up data only."""
import dataclasses
import json
from decimal import Decimal

import pytest

from quantisheet_claims import (checklist, diary, kits, library, practice,
                                rooms, settle, store)
from quantisheet_claims import model as m
from .helpers import t1_claim


def test_room_measurements():
    r = rooms.new_room("Kitchen", "14", "12", "8", doors=1, windows=1)
    ms = rooms.measure(r)
    assert ms.floor == Decimal("168.00") and ms.ceiling == ms.floor
    assert ms.perimeter == Decimal("52.00")
    assert ms.walls_gross == Decimal("416.00")
    assert ms.openings == Decimal("32.00")    # 3 x 6'8" (20.00) + 3x4
    assert ms.walls == Decimal("384.00")
    assert ms.walls_ceiling == Decimal("552.00")
    assert ms.floor_sy == Decimal("18.67")
    assert rooms.qty_q4(r, "perimeter") == 520_000
    assert rooms.qty_q4(r, "each") == 10_000
    assert rooms.unit_for("walls") == "SF" and rooms.unit_for("perimeter") == "LF"


def test_room_edge_cases():
    blank = rooms.new_room("Closet")
    assert rooms.measure(blank).walls == 0 and "no dimensions" in \
        rooms.summary(blank)
    tiny = rooms.new_room("Nook", "2", "2", "2", doors=3)   # openings > walls
    assert rooms.measure(tiny).walls == 0
    with pytest.raises(rooms.RoomError):
        rooms.new_room("", "10", "10")
    with pytest.raises(rooms.RoomError):
        rooms.new_room("Bad", "-1", "10")
    with pytest.raises(rooms.RoomError):
        rooms.new_room("Bad", "ten", "10")
    r = rooms.set_openings(rooms.new_room("Den", "10", "10", "8", 1, 2), 2, 0)
    assert rooms.count(r, "door") == 2 and rooms.count(r, "window") == 0


def _lib():
    library.add_item("EX-DRY", "Example drywall", "DRYWALL", "SF", other="2.00")
    library.add_item("EX-BASE", "Example base", "FLOORING", "LF", other="1.50")


def test_kit_applies_room_measurements():
    _lib()
    kits.save_kit("Example flood cut", [("ex-dry", "perimeter", "2"),
                                        ("EX-BASE", "perimeter", "1")])
    room = rooms.new_room("Kitchen", "14", "12", "8", structure_id="S1")
    lines = kits.apply("Example flood cut", room, first_ordinal=5)
    assert [ln.item_code for ln in lines] == ["EX-DRY", "EX-BASE"]
    assert lines[0].qty_q4 == 1_040_000 and lines[1].qty_q4 == 520_000
    assert all(ln.room_id == room.id and ln.structure_id == "S1" for ln in lines)
    assert lines[0].ordinal == 5 and lines[0].rc == 20_800
    assert "kit: Example flood cut" == lines[0].note


def test_kit_checks():
    _lib()
    with pytest.raises(kits.KitError):
        kits.save_kit("", [("EX-DRY", "floor", "1")])
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [("NOT-MINE", "floor", "1")])     # not in library
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [("EX-DRY", "volume", "1")])
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [("EX-DRY", "floor", "0")])
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [])
    kits.save_kit("K", [("EX-DRY", "floor", "1.5")])
    assert list(kits.all_kits()) == ["K"]
    kits.remove_kit("K")
    assert kits.all_kits() == {}
    with pytest.raises(kits.KitError):
        kits.apply("K", rooms.new_room("A", "1", "1"))


def test_nothing_shipped_in_kits():
    assert kits.all_kits() == {}


def test_diary_and_payments():
    c = t1_claim()
    d = diary.add_entry(c, "2026-10-02", "call", "Example: owner called")
    d = diary.add_entry(dataclasses.replace(c, diary=d), "2026-10-01",
                        "inspection", "Example: inspected")
    assert [e.on for e in d] == ["2026-10-01", "2026-10-02"]
    with pytest.raises(diary.DiaryError):
        diary.add_entry(c, "10/01/2026", "call", "x")
    with pytest.raises(diary.DiaryError):
        diary.add_entry(c, "2026-10-01", "fax", "x")
    with pytest.raises(diary.DiaryError):
        diary.add_entry(c, "2026-10-01", "note", "  ")
    p = diary.add_payment(c, "2026-10-05", "1,000.00", "acv", "CHK 100")
    c = dataclasses.replace(c, diary=d, payments=p)
    assert c.paid_cents() == 100_000
    with pytest.raises(diary.DiaryError):
        diary.add_payment(c, "2026-10-05", "0", "acv")
    with pytest.raises(diary.DiaryError):
        diary.add_payment(c, "2026-10-05", "5", "cash-back")
    s = settle.settle_claim(c)
    b = diary.balance(c, s)
    assert b["paid"] == 100_000
    assert b["open_now"] == s.total_indemnity - 100_000
    assert b["open_total"] == s.total_indemnity + s.recoverable_holdback - 100_000
    assert "inspection" in diary.text(c)
    assert diary.remove_payment(c, p[0].id) == ()


def test_diary_and_payments_go_on_after_submission():
    c = m.edit(t1_claim(), "Example", "submit", status="submitted")
    p = diary.add_payment(c, "2026-10-05", "10.00", "acv")
    c = m.edit(c, "Example", "payment received", payments=p)
    assert c.paid_cents() == 1000
    with pytest.raises(m.FrozenClaimError):
        m.edit(c, "Example", "edit", insured="Someone else")


def test_old_claim_files_still_open(tmp_path):
    """A 0.1 claim file has no diary, payments or kits - it opens as
    before, with empty ones."""
    c = t1_claim()
    p = store.save(c)
    data = json.load(open(p, encoding="utf-8"))
    claim_data = data["claim"] if "claim" in data else data
    claim_data.pop("diary", None)
    claim_data.pop("payments", None)
    json.dump(data, open(p, "w", encoding="utf-8"))
    c2, _ = store.load(p)
    assert c2.diary == () and c2.payments == ()
    assert c2.lines == c.lines


def test_new_fields_round_trip():
    c = practice.claim()
    c = dataclasses.replace(c, payments=diary.add_payment(
        c, "2026-10-10", "250.00", "acv", "CHK 1"))
    p = store.save(c)
    c2, _ = store.load(p)
    assert c2.diary == c.diary and c2.payments == c.payments
    assert c2.rooms == c.rooms


def test_checklist():
    c = m.Claim(id="x", claim_number="NEW-CLAIM")
    texts = [i.text for i in checklist.check(c)]
    assert "Give the claim its claim number" in texts
    assert "Add the insured's name" in texts
    assert "No line items yet" in texts
    assert "Enter the date of loss as YYYY-MM-DD" in texts
    assert all(i.tab in checklist.TAB for i in checklist.check(c))
    future = dataclasses.replace(t1_claim(), loss_date="2999-01-01")
    assert any("future" in i.text for i in checklist.check(future))
    ln = m.Line(id="l", item_code="NEW", description="New item",
                category="NOPE", qty_q4=0, unit="EA", unit_cost=m.UnitCost())
    bad = dataclasses.replace(t1_claim(), lines=(ln,))
    t = " | ".join(i.text for i in checklist.check(bad))
    assert "quantity is 0" in t and "no unit cost" in t and \
        "unknown category" in t and "placeholder" in t
    assert checklist.summary([]) == "Ready: nothing to check"


def test_practice_claim_is_clean_and_made_up():
    c = practice.claim()
    assert c.claim_number == practice.NUMBER
    assert "example.invalid" in c.loss_address and c.insured == "Example Owner"
    assert all("(practice price)" in ln.description for ln in c.lines)
    assert all(ln.room_id for ln in c.lines)
    assert [i.text for i in checklist.check(c)] == []
    s = settle.settle_claim(c)
    assert s.rcv > 0 and s.acv < s.rcv


def test_export_lists_room_measurements():
    from quantisheet_claims.export import build_model
    md = build_model(practice.claim(), printed="2026-10-31", author="Example")
    names = [r[0] for r in md.rooms]
    assert names == ["Kitchen", "Hall"]
    assert md.rooms[0][2] == "168.00" and md.rooms[0][5] == "52.00"


def test_kit_units_must_fit_the_measurement():
    """Review: a per-SY item on floor area would be ~9x too much."""
    library.add_item("EX-CPT", "Example carpet", "FLOORING", "SY", other="30")
    library.add_item("EX-FAN", "Example fan", "WATER", "EA", other="50")
    with pytest.raises(kits.KitError) as e:
        kits.save_kit("K", [("EX-CPT", "floor", "1")])
    assert "square yards" in str(e.value)
    kits.save_kit("K", [("EX-CPT", "floor_sy", "1")])
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [("EX-FAN", "walls", "1")])
    kits.save_kit("K", [("EX-FAN", "each", "3")])          # 3 fans


def test_nan_is_not_a_number():
    for bad in ("nan", "NaN", "inf", "-Infinity"):
        with pytest.raises(rooms.RoomError):
            rooms.new_room("Example", bad, "10")
    _lib()
    with pytest.raises(kits.KitError):
        kits.save_kit("K", [("EX-DRY", "floor", "nan")])


def test_new_files_are_version_2_and_old_ones_open():
    c = practice.claim()
    p = store.save(c)
    data = json.load(open(p, encoding="utf-8"))
    assert data["schema_version"] == 2
    data["schema_version"] = 1
    json.dump(data, open(p, "w", encoding="utf-8"))
    assert store.load(p)[0].claim_number == c.claim_number
    assert store.claim_id_in(p) == c.id
    json.dump([1, 2], open(p, "w", encoding="utf-8"))
    with pytest.raises(ValueError):
        store.load(p)
    assert store.claim_id_in(p) is None


# ---- r47 review (Chief, Oct 31) ------------------------------------------
def test_r47_credit_lines_and_depreciation_limits():
    ln = m.Line(id="c", item_code="CREDIT", description="Example credit",
                category="OTHER", qty_q4=-100_000, unit="SF",
                unit_cost=m.UnitCost(other=100))
    c = dataclasses.replace(t1_claim(), lines=(ln,))
    texts = " | ".join(i.text for i in checklist.check(c))
    assert "quantity is 0" not in texts                 # a credit is fine
    bad = dataclasses.replace(ln, qty_q4=100_000, dep_bp=15_000)
    c = dataclasses.replace(t1_claim(), lines=(bad,))
    assert any("0% to 100%" in i.text for i in checklist.check(c))


def test_r47_sent_claim_never_goes_back_to_draft():
    c = m.edit(t1_claim(), "Example", "submit", status="submitted")
    for st in ("draft", "review"):
        with pytest.raises(m.FrozenClaimError):
            m.edit(c, "Example", "status", status=st)
    c2 = m.edit(c, "Example", "start supplement", reopen=True, status="draft")
    assert c2.status == "draft" and c2.audit[-1].action == "start supplement"


def test_r47_baseboard_and_feet_inches():
    r = rooms.new_room("Example", "12'6\"", "10", "8", doors=2)
    ms = rooms.measure(r)
    assert ms.floor == Decimal("125.00")
    assert ms.perimeter == Decimal("45.00") and ms.baseboard == Decimal("39.00")
    assert rooms._d("6\"") == Decimal("0.5")
    with pytest.raises(rooms.RoomError):
        rooms._d("10'14\"")


def test_r47_kit_lines_remember_their_measurement():
    _lib()
    kits.save_kit("K", [("EX-BASE", "baseboard", "1")])
    big = rooms.new_room("Big", "20", "10", "8", doors=1)
    small = rooms.new_room("Small", "10", "10", "8", doors=1)
    ln = kits.apply("K", big)[0]
    assert ln.qty_from == "baseboard" and ln.qty_q4 == 570_000
    assert rooms.requantify(ln, small) == 370_000
    hand = dataclasses.replace(ln, qty_from="")
    assert rooms.requantify(hand, small) is None


def test_r47_overpaid_claim_is_flagged():
    c = practice.claim()
    c = dataclasses.replace(c, payments=diary.add_payment(
        c, "2026-10-10", "1,000,000.00", "acv"))
    assert any("more than the claim" in i.text for i in checklist.check(c))


def test_r47_pdf_model_lists_payments():
    from quantisheet_claims.export import build_model
    c = practice.claim()
    c = dataclasses.replace(c, payments=diary.add_payment(
        c, "2026-10-10", "100.00", "acv", "CHK 7"))
    md = build_model(c, printed="2026-10-31", author="Example")
    assert md.payments == (("2026-10-10", "acv", 10_000, "CHK 7"),)
    s = settle.settle_claim(c)
    assert md.still_open == s.total_indemnity + s.recoverable_holdback - 10_000


def test_r47_claims_folder_never_leaves_home(monkeypatch, tmp_path):
    from quantisheet_claims import settings as st
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(st, "_known_documents", lambda: "/somewhere/else/Docs")
    assert st._documents() == str(tmp_path / "Documents")
    inside = str(tmp_path / "OneDrive" / "Documents")
    monkeypatch.setattr(st, "_known_documents", lambda: inside)
    assert st._documents() == inside
    (tmp_path / "Documents" / st.DOCS_DIR).mkdir(parents=True)
    assert st._documents() == str(tmp_path / "Documents")   # existing wins
