"""v20: addendum 'what changed' summary from the drawings, and which bid
packages it goes to."""
import fitz

from app import addendum_summary as ads, annotate
from test_overlay import _sets, _sheet


def _docs(tmp_path):
    po, pn = _sets(tmp_path)
    old, new = fitz.open(po), fitz.open(pn)
    _sheet(old, "E-101", [(80, 80, 380, 80)])          # removed later
    annotate.apply_op(old, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    annotate.apply_op(old, annotate.new_op(
        "add_polyline", 0, pts=[[60, 300], [290, 300]],
        measure={"type": "length", "value": 12.8, "unit": "ft",
                 "group": "Wall"}))
    return old, new


def test_summary_lists_changed_new_removed_and_takeoffs(tmp_path):
    old, new = _docs(tmp_path)
    s = ads.summarize(old, new)
    assert [c["sheet"] for c in s["changed"]] == ["A-101"]
    assert s["changed"][0]["takeoffs"] == {"Wall": 1}
    assert s["added"] == ["A-103"] and s["removed"] == ["E-101"]
    assert s["unchanged"] == ["A-102"]


def test_text_reads_like_an_addendum(tmp_path):
    old, new = _docs(tmp_path)
    t = ads.text(ads.summarize(old, new), "Addendum 2")
    assert t.startswith("Addendum 2 changes 1 sheet: A-101")
    assert "1 takeoff affected (Wall)" in t
    assert "New sheet: A-103" in t and "Removed: E-101" in t
    assert "No change: A-102" in t


def test_packages_affected_by_trade_and_listed_sheets(tmp_path):
    old, new = _docs(tmp_path)
    s = ads.summarize(old, new)
    pkgs = [{"_id": "p1", "title": "Drywall", "trades": "Drywall, finishes"},
            {"_id": "p2", "title": "Electrical", "trades": "26 Electrical"},
            {"_id": "p3", "title": "Sitework", "trades": "Earthwork",
             "sheets": "C-101 to C-120"}]
    hit = ads.packages_affected(s, pkgs)
    assert [p["_id"] for p, _ in hit] == ["p1", "p2"]  # A- changed, E- removed
    assert dict((p["_id"], sh) for p, sh in hit)["p2"] == ["E-101"]


def test_per_package_draft(tmp_path):
    old, new = _docs(tmp_path)
    s = ads.summarize(old, new)
    d = ads.draft({"title": "Drywall", "trades": "drywall"}, s, "Addendum 2")
    assert "A-101" in d and "A-103" in d and "E-101" not in d
