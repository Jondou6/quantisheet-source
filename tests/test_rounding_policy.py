"""Venice #15/#16 (Nov 4): quantities add up exactly whatever order the
markups were drawn in, and the rounding policy is stated with the job."""
import csv
import decimal

import fitz

from app import estimate, rounding


def test_float_drift_is_gone(monkeypatch):
    vals = [0.1] * 10
    items = [{"page": 0, "value": v, "type": "length", "unit": "LF",
              "group": "Pipe"} for v in vals]
    monkeypatch.setattr(estimate.annotate, "totals_items", lambda d: items)
    monkeypatch.setattr(estimate, "roof_rows", lambda d: [])
    monkeypatch.setattr(estimate, "set_items", lambda d: [])
    monkeypatch.setattr(estimate, "read_prices", lambda d: {
        estimate.key_of("Pipe", "length", "LF"):
            {"unit_cost": 3.0, "waste": 10}})
    g, = estimate.lines(object())
    run = 0.0
    for v in vals:                               # += one at a time, as the
        run += v                                 # old code added markups
    assert run != 1.0                            # float drifts...
    assert g["quantity"] == 1.0                  # ...the estimate doesn't
    assert g["adjusted"] == 1.1
    assert g["total"] == 3.3
    items.reverse()                               # order never matters
    assert estimate.lines(object())[0]["total"] == 3.3


def test_adjusted_kept_to_four_places():
    assert rounding.qty(decimal.Decimal("1.23456")) == \
        decimal.Decimal("1.2346")
    assert rounding.qty(decimal.Decimal("0.00005")) == \
        decimal.Decimal("0.0001")                 # half up


def test_policy_in_the_csv(tmp_path):
    d = fitz.open()
    d.new_page()
    p = tmp_path / "e.csv"
    estimate.export_csv(d, str(p))
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    flat = [r[0] for r in rows if r]
    assert any(x.startswith("Rounding (policy v") for x in flat)
    assert any("sum of the rounded lines" in x for x in flat)


def test_prices_and_links_follow_a_rename():
    """Name matching (Nov 4 scope): renaming a takeoff item kept its price
    and linked lines under the old name - they now go with it."""
    from app import estimate_lines
    d = fitz.open()
    d.new_page()
    estimate.set_price(d, "Pipe A", "length", "LF", unit_cost=12)
    estimate.set_price(d, "Pipe A", "length", "ft", unit_cost=11)
    estimate.set_price(d, "Pipe A|x", "length", "LF", unit_cost=1)  # json key
    ln = estimate_lines.new_line(desc="Hangers", unit="EA") \
        if hasattr(estimate_lines, "new_line") else {"desc": "Hangers"}
    ln["link"] = {"name": "Pipe A", "type": "length", "unit": "LF"}
    estimate_lines.add(d, [ln])
    moved, relinked = estimate.follow_rename(d, "Pipe A", "length", "Pipe B")
    assert (moved, relinked) == (2, 1)
    p = estimate.read_prices(d)
    assert p[estimate.key_of("Pipe B", "length", "LF")]["unit_cost"] == 12
    assert estimate.key_of("Pipe A", "length", "LF") not in p
    assert estimate.key_of("Pipe A|x", "length", "LF") in p
    assert estimate_lines.read(d)[0]["link"]["name"] == "Pipe B"
    # a price already on the new name is kept
    estimate.set_price(d, "Pipe C", "length", "LF", unit_cost=99)
    estimate.follow_rename(d, "Pipe B", "length", "Pipe C")
    p = estimate.read_prices(d)
    assert p[estimate.key_of("Pipe C", "length", "LF")]["unit_cost"] == 99


def test_source_line_points_at_the_public_repo(monkeypatch):
    """Jon, Nov 4 (go at 8:59 PM ET): the AGPL source line points at
    quantisheet-source and this release's tag; off shows nothing."""
    from app import __version__, legal
    assert legal.SOURCE_PUBLISHED is True
    assert "quantisheet-source" in legal.about_html()
    monkeypatch.setattr(legal, "SOURCE_PUBLISHED", False)
    assert legal.source_line() == ""
    monkeypatch.setattr(legal, "SOURCE_PUBLISHED", True)
    line = legal.source_line()
    assert legal.SOURCE_URL in line and f"v{__version__}" in line
    assert "pdfstudio-construction" not in line
