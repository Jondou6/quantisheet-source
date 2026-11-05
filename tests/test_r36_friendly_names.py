"""r36 v2 step 4: friendly quote line names. The customer quote shows a
clean name for each line instead of the raw takeoff group name (an AI
takeoff's capitals and ', depth unknown'); you can type your own name for
any line, kept with the quote. The estimate, takeoff and amounts are
unchanged. Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate, settings                # noqa: E402
from app.estimating import quotes                             # noqa: E402
from estimate_helpers import area, blank_doc                  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


@pytest.mark.parametrize("raw,nice", [
    ('2" water, depth unknown', '2" Water'),
    ("BREAK ROOM 110", "Break Room 110"),
    ('8" PVC SANITARY SEWER, 6-10 ft deep', '8" PVC Sanitary Sewer, 6-10 ft deep'),
    ('1/2"-HB HOSE BIBB', '1/2"-HB Hose Bibb'),
    ("Test wall framing", "Test wall framing"),
    ("  ADA   TLT 123 ", "ADA TLT 123"),
    ("ELECTRICAL", "Electrical"),
    ("10x10", "10x10"),
])
def test_friendly_name(raw, nice):
    assert quotes.friendly_name(raw) == nice


def test_quote_lines_use_friendly_or_your_own_name(tmp_path):
    d = blank_doc()
    area(d, "BREAK ROOM 110", 10, 10)
    area(d, "TEST LOBBY 101", 10, 20, x0=300)
    for g in ("BREAK ROOM 110", "TEST LOBBY 101"):
        estimate.set_price(d, g, "area", "sq ft", unit_cost=5,
                           cost_type="Material")
    q = quotes.compute(d, quotes.blank())
    by = {ln["takeoff_name"]: ln for ln in q["base"]["lines"]}
    assert by["BREAK ROOM 110"]["desc"] == "Break Room 110"
    assert by["BREAK ROOM 110"]["price"] == Decimal("500.00")
    lobby = by["TEST LOBBY 101"]["id"]
    spec = quotes.blank()
    spec["names"] = {lobby: "Lobby flooring"}
    quotes.write(d, spec)
    assert quotes.read(d)["names"] == {lobby: "Lobby flooring"}
    q = quotes.compute(d)
    assert {ln["desc"] for ln in q["base"]["lines"]} == {
        "Break Room 110", "Lobby flooring"}
    out = quotes.make_pdf(d, comp={"name": "Test Co"},
                          data={"project": "Test"})
    text = "".join(p.get_text() for p in out)
    assert "Lobby flooring" in text and "TEST LOBBY 101" not in text
    p = quotes.export_csv(d, str(tmp_path / "q.csv"))
    body = open(p, encoding="utf-8-sig").read()
    assert "Break Room 110" in body and "BREAK ROOM 110" not in body


def test_quote_page_customer_name_column(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.estimating import ui
    QApplication.instance() or QApplication([])
    d = blank_doc()
    area(d, "BREAK ROOM 110", 10, 10)
    estimate.set_price(d, "BREAK ROOM 110", "area", "sq ft", unit_cost=5,
                       cost_type="Material")
    dlg = ui.EstimatingTools(None, d, "quote")
    p = dlg.page("quote")
    head = [p.table.horizontalHeaderItem(c).text()
            for c in range(p.table.columnCount())]
    col = head.index("Customer name")
    assert p.table.item(0, col).text() == "Break Room 110"
    assert p.table.item(0, 0).text() == "BREAK ROOM 110"
    p.save_spec()
    assert quotes.read(d)["names"] == {}          # default kept as default
    p.table.item(0, col).setText("Break room flooring")
    p.save_spec()
    rid = p.rows[0]["id"]
    assert quotes.read(d)["names"] == {rid: "Break room flooring"}
    dlg.close()
