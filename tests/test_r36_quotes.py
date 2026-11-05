"""r36 A3 + D1: customer quote from the estimate - markup or margin,
inclusions / exclusions, optional items the customer may add and
Good / Better / Best options (the customer picks one) - as a PDF and a
plain CSV. Made-up data only."""
import csv
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings   # noqa: E402
from app.estimating import quotes                             # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    ids = EL.add(d, [
        EL.new_line("Test demo", 1, "ls", sub=1000),             # base
        EL.new_line("Test basic shingles", 20, "sq", mat=100),   # Good
        EL.new_line("Test arch shingles", 20, "sq", mat=150),    # Better
        EL.new_line("Test metal roof", 20, "sq", mat=400),       # Best
        EL.new_line("Test gutter guards", 1, "ls", mat=500),     # option
    ])
    return d, ids


def _spec(ids, mode="markup", pct="25"):
    s = quotes.blank()
    s.update(mode=mode, pct=pct,
             assign={ids[1]: "Good", ids[2]: "Better", ids[3]: "Best",
                     ids[4]: "option"},
             inclusions=["Test tear-off and haul away"],
             exclusions=["Test rotten deck boards"])
    return s


def test_tier_totals_with_markup():
    d, ids = _doc()
    q = quotes.compute(d, _spec(ids))
    assert q["base"]["cost"] == D("1000.00")
    assert q["base"]["price"] == D("1250.00")
    t = {x["name"]: x for x in q["tiers"]}
    assert list(t) == ["Good", "Better", "Best"]
    assert t["Good"]["price"] == D("2500.00")       # 2000 x 1.25
    assert t["Good"]["total"] == D("3750.00")       # + base
    assert t["Better"]["total"] == D("1250.00") + D("3750.00")
    assert t["Best"]["total"] == D("1250.00") + D("10000.00")
    assert [o["price"] for o in q["options"]] == [D("625.00")]
    assert q["selected"]["total"] is None           # nothing picked yet


def test_margin_is_on_the_price_not_the_cost():
    d, ids = _doc()
    q = quotes.compute(d, _spec(ids, "margin", "20"))
    assert q["base"]["price"] == D("1250.00")       # 1000 / (1 - .20)
    with pytest.raises(quotes.QuoteError):
        quotes.compute(d, _spec(ids, "margin", "100"))


def test_customer_picks_a_tier_and_options_saved_in_pdf(tmp_path):
    d, ids = _doc()
    quotes.write(d, _spec(ids))
    quotes.select(d, "Better", [ids[4]])
    q = quotes.compute(d)
    assert q["selected"]["tier"] == "Better"
    assert q["selected"]["total"] == D("5000.00") + D("625.00")
    with pytest.raises(quotes.QuoteError):
        quotes.select(d, "Platinum")
    p = str(tmp_path / "job.pdf")
    d.save(p)
    d2 = fitz.open(p)
    assert quotes.read(d2)["selected_tier"] == "Better"
    assert quotes.FILE in d2.embfile_names()


def test_no_tiers_is_a_single_price():
    d, ids = _doc()
    s = quotes.blank()
    s.update(pct="10")
    q = quotes.compute(d, s)
    assert q["tiers"] == [] and q["options"] == []
    assert q["selected"]["total"] == D("15950.00")      # 14,500 x 1.10


def test_quote_pdf_has_options_inclusions_and_exclusions(tmp_path):
    d, ids = _doc()
    quotes.write(d, _spec(ids))
    out = quotes.save_pdf(d, str(tmp_path / "quote.pdf"),
                          comp={"name": "Test Roofing LLC"})
    text = "".join(pg.get_text() for pg in fitz.open(out))
    for s in ("Test Roofing LLC", "Good", "Better", "Best",
              "$3,750.00", "Optional", "Test gutter guards", "$625.00",
              "Test tear-off and haul away", "Test rotten deck boards"):
        assert s in text, s
    # the customer never sees your cost or markup
    assert "Markup" not in text and "markup" not in text


def test_quote_csv_export_is_generic(tmp_path):
    d, ids = _doc()
    quotes.write(d, _spec(ids))
    p = quotes.export_csv(d, str(tmp_path / "quote.csv"))
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[0][:4] == ["Section", "Description", "Quantity", "Unit"]
    secs = {r[0] for r in rows[1:]}
    assert {"Base", "Good", "Better", "Best", "Optional"} <= secs


def test_assignment_to_a_line_that_was_deleted_is_ignored():
    d, ids = _doc()
    s = _spec(ids)
    EL.delete(d, [ids[3]])
    q = quotes.compute(d, s)
    assert {x["name"]: x["price"] for x in q["tiers"]}["Best"] == D("0.00")


def test_unreadable_percent_is_refused_not_zero():
    d, ids = _doc()
    with pytest.raises(quotes.QuoteError):
        quotes.compute(d, _spec(ids, pct="twenty"))
