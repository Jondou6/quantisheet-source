from decimal import Decimal as D
import fitz
from app import assembly_codes as ac, change_report as chg
from costlayer_helpers import LIB_ROWS, blank, wall, door


def lib(tmp_path):
    p = tmp_path / "lib.csv"
    ac.write_rows(str(p), LIB_ROWS)
    return ac.read(str(p))


def bound(doc):
    ac.bind(doc, "Interior Wall", "length", "ft", "00100")
    ac.bind(doc, "Door", "count", "ea", "00200")
    return doc


def test_added_removed_moved_listed_separately(tmp_path):
    L = lib(tmp_path)
    old = bound(blank())
    door(old, 0, 50); door(old, 0, 90); wall(old, 0, 40)
    new = bound(blank())
    door(new, 0, 50)          # unchanged
    door(new, 0, 300, 400)    # moved (was at 90)
    wall(new, 0, 40)          # unchanged
    wall(new, 0, 25, x=200)   # added
    r = chg.compare(old, new, L)
    assert len(r["moved"]) == 1 and r["moved"][0]["group"] == "Door"
    assert len(r["added"]) == 1 and r["added"][0]["qty"] == D("25")
    assert r["removed"] == []
    assert len(r["unchanged"]) == 2
    # moved door not double counted: net = added wall only = 25*0.25*60 + 25*1.5*4 + 25*0.02*150
    assert r["net_direct"] == D("375.00") + D("150.00") + D("75.00")


def test_removed_and_net_with_markups(tmp_path):
    L = lib(tmp_path)
    old = bound(blank())
    door(old, 0, 50); door(old, 0, 90)
    new = bound(blank())
    door(new, 0, 50)
    r = chg.compare(old, new, L, cascade=[("gc", "10"), ("profit", "10")],
                    tax_pct="8")
    assert len(r["removed"]) == 1
    assert r["net_direct"] == D("-560.00")         # 2*55 + 450
    # old total: 1120 + tax 72 = 1192 -> 1311.20 -> 1442.32
    # new total: 560 + 36 = 596 -> 655.60 -> 721.16
    assert r["net_with_markups"] == D("-721.16")


def test_orphans_sheet_gone_and_unbound(tmp_path):
    L = lib(tmp_path)
    old = bound(blank(2))
    door(old, 0, 50); door(old, 1, 50)
    wall(old, 0, 10, group="Soffit")       # not bound to any assembly
    new = bound(blank(1))
    door(new, 0, 50)
    wall(new, 0, 10, group="Soffit")
    r = chg.compare(old, new, L, pair=lambda o, n: [(0, 0, "A-101"), (1, None, "A-102")])
    kinds = {(o["why"], o["group"]) for o in r["orphans"]}
    assert ("sheet removed in new revision", "Door") in kinds
    assert ("no assembly bound", "Soffit") in kinds
    assert all(x["group"] != "Door" or x["page"] != 1 for x in r["removed"])


def test_text_report(tmp_path):
    L = lib(tmp_path)
    old = bound(blank()); door(old, 0, 50)
    new = bound(blank()); door(new, 0, 50); door(new, 0, 200)
    r = chg.compare(old, new, L)
    t = chg.text(r)
    assert "ADDED (1)" in t and "MOVED (0)" in t and "REMOVED (0)" in t
    assert "Net direct change: 560.00" in t


def test_unbound_changes_still_listed(tmp_path):
    L = lib(tmp_path)
    old = bound(blank()); wall(old, 0, 10, group="Soffit")
    new = bound(blank()); wall(new, 0, 10, group="Soffit")
    wall(new, 0, 300, group="Soffit")                 # one more soffit
    r = chg.compare(old, new, L)
    assert len(r["added"]) == 1 and r["added"][0]["group"] == "Soffit"
    assert r["added"][0]["cost"] is None and r["net_direct"] == 0
    assert [o["group"] for o in r["orphans"]] == ["Soffit"]   # one line
    assert "not priced" in chg.text(r)
