"""r36 v2 step 2: customer quote PDF fixes found on the real-job test -
a long item description must not run into the quantity column, and a
measured quantity is shown to at most 2 decimals (277.66 ft, not
277.6622 ft) - the customer sees what a person would write. The amounts
are unchanged. Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, proposal as P, settings  # noqa: E402,E501
from app.estimating import quotes                             # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402

LONG = ("Test WALL MOUNTED DATA OUTLET - STUBBED ABOVE LIFT-OUT CEILING "
        "WITH PULL STRING AND BUSHING")          # plan text is often capitals


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    EL.add(d, [EL.new_line(LONG, 12, "ea", sub=165),
               EL.new_line("Test wall framing", "277.6622", "ft", mat=55)])
    return d


def _spans(out):
    for page in out:
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    yield sp


def test_long_description_stays_left_of_the_quantity_column():
    out = quotes.make_pdf(_doc(), quotes.blank(), comp={"name": "Test Co"},
                          data={"project": "Test"})
    descs = [sp for sp in _spans(out) if sp["text"].startswith(
        "Test Wall Mounted")]     # v2 step 4: friendly quote names
    assert descs, "description missing"
    assert all(sp["bbox"][2] <= P.LEFT + 326 for sp in descs)
    qtys = [sp["text"] for sp in _spans(out) if sp["text"].endswith(" ea")]
    assert qtys == ["12 ea"]


def test_quantity_shown_to_two_decimals_amount_unchanged(tmp_path):
    d = _doc()
    out = quotes.make_pdf(d, quotes.blank(), comp={"name": "Test Co"},
                          data={"project": "Test"})
    texts = [sp["text"] for sp in _spans(out)]
    assert "277.66 ft" in texts and "277.6622 ft" not in texts
    q = quotes.compute(d, quotes.blank())
    framing = next(ln for ln in q["base"]["lines"]
                   if ln["desc"] == "Test wall framing")
    assert framing["price"] == Decimal("15271.42")      # 277.6622 x 55
    assert quotes.qty_text(Decimal("12.0000"), "ea") == "12 ea"
    assert quotes.qty_text(Decimal("0.005"), "cy") == "0.01 cy"
