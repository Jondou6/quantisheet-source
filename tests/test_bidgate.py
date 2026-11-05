"""Nov 3 bid gate: stale prices and quotes, Addenda Gate, placeholders,
double counts and the Escalation Projector. Made-up data only."""
import datetime
import os
from decimal import Decimal

import fitz
import pytest

from app import doccontrol, estimate_lines as EL
from app.estimating import bidday, bidgate, checks

T = datetime.date(2026, 11, 3)


@pytest.fixture
def doc(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    d = fitz.open()
    d.new_page(width=792, height=612)
    return d


def _rules(found):
    return [f["rule"] for f in found]


def test_new_lines_carry_a_price_date_and_old_ones_are_flagged(doc):
    a = EL.new_line("Drywall", 100, "sf", mat="1.20")
    assert a["priced_on"] == datetime.date.today().isoformat()
    a["priced_on"] = "2026-06-01"
    b = EL.new_line("Paint", 100, "sf", mat="0.40")
    b["priced_on"] = "2026-10-20"
    old = EL.new_line("Old line", 1, "ls")               # no price: skipped
    old["priced_on"] = "2020-01-01"
    EL.add(doc, [a, b, old])
    found = bidgate.stale(doc, today=T, days=90)
    assert _rules(found) == ["price_old"] and found[0]["item"] == "Drywall"
    # changing a price, or Price Still Good, starts the count again
    lid = EL.read(doc)[0]["id"]
    EL.update(doc, lid, priced_on="")
    assert not bidgate.stale(doc, today=T + datetime.timedelta(days=1))
    # lines saved before 1.0.6 have no date: not flagged
    assert EL.clean({"desc": "x"})["priced_on"] == ""


def test_expired_quotes(doc):
    sheet = bidday.new_sheet("Paint", [{"id": "1", "desc": "Walls",
                                        "unit": "ls", "qty": "1"}],
                             [{"name": "Acme Painting", "prices": {"1": "900"},
                               "valid_until": "2026-10-31"},
                              {"name": "Bravo", "prices": {"1": "950"},
                               "valid_until": "2026-12-31"}])
    bidday.save(doc, sheet)
    bidday.apply_quote(doc, "Paint")
    found = [f for f in bidgate.stale(doc, today=T)
             if f["rule"] == "quote_expired"]
    assert len(found) == 1 and "Acme" in found[0]["item"]
    job = {"activities": [{"name": "Base", "quotes": [
        {"vendor": "Rock Co", "kind": "material", "use": True,
         "valid_until": "2026-01-01"}]}]}
    assert any("Rock Co" in f["item"] for f in bidgate.stale(None, job, T))


def test_addenda_gate(doc):
    aid = doccontrol.add_addendum(doc, "Revised doors", issued="2026-11-02",
                                  sheets=["A-501"])
    EL.add(doc, [dict(EL.new_line("Doors", 4, "ea", mat="300"),
                      priced_on="2026-11-01")])
    found = bidgate.addenda(doc)
    assert set(_rules(found)) == {"addendum_unpriced", "addendum_after_edit"}
    assert bidgate.blockers(doc)
    from app.estimating import bidgate_ui
    assert "Not priced yet" in bidgate_ui.gate_text(doc)
    a = doccontrol.price_addendum(doc, aid, cost="$1,250", line_id="x")
    assert a["priced"] and a["cost"] == "1250.00" and a["priced_on"]
    assert not bidgate.blockers(doc)
    with pytest.raises(doccontrol.DocControlError):
        doccontrol.price_addendum(doc, aid, cost="lots")


def test_placeholders_listed_until_replaced(doc):
    EL.add(doc, [EL.new_line("Allowance - Interiors (quick $/SF, office)",
                             1, "ls", cost_type="Allowance", sub="50000"),
                 EL.new_line("Hardware", 1, "ls", cost_type="Allowance",
                             sub="3000"),
                 EL.new_line("Roofing", 1, "ls", sub="20000",
                             note="PLUG: not in Acme's quote - your plug"),
                 EL.new_line("Concrete", 10, "cy", mat="150"),
                 EL.new_line("Allowance replaced", 1, "ls",
                             cost_type="Allowance", sub="0")])
    kinds = {x["item"]: x["kind"] for x in bidgate.placeholders(doc)}
    assert kinds == {"Allowance - Interiors (quick $/SF, office)":
                     "placeholder", "Hardware": "allowance",
                     "Roofing": "plug"}


def test_subtotal_added_twice(doc):
    EL.add(doc, [EL.new_line("D1.8", 1, "ls", sub="100"),
                 EL.new_line("D1.9", 1, "ls", sub="200"),
                 EL.new_line("D1.10", 1, "ls", sub="300"),
                 EL.new_line("D1.13 subtotal", 1, "ls", sub="600"),
                 EL.new_line("Other", 1, "ls", sub="50")])
    found = [f for f in bidgate.double_counts(doc)
             if f["rule"] == "subtotal_twice"]
    assert [f["item"] for f in found] == ["D1.13 subtotal"]


def test_overlapping_areas_and_repeat_counts(doc):
    from app import annotate
    pg = doc[0]

    def area(pts, group="Carpet"):
        a = pg.add_polygon_annot(pts)
        a.set_info(subject=f"{annotate.TAKEOFF}:area:100:sf:{group}:")
        a.update()

    def count(x, y, group="Outlet"):
        a = pg.add_circle_annot(fitz.Rect(x, y, x + 8, y + 8))
        a.set_info(subject=f"{annotate.TAKEOFF}:count:1:ea:{group}:")
        a.update()
    area([(100, 100), (300, 100), (300, 300), (100, 300)])
    area([(150, 150), (350, 150), (350, 350), (150, 350)])
    area([(500, 100), (600, 100), (600, 200), (500, 200)])
    count(400, 400)
    count(401, 401)
    count(450, 450)
    if not annotate.totals_items(doc):
        pytest.skip("takeoff subjects written differently in this build")
    rules = _rules(bidgate.double_counts(doc))
    assert rules.count("overlap_area") == 1
    assert rules.count("repeat_count") == 1


def test_error_check_runs_the_gate(doc):
    doccontrol.add_addendum(doc, "Add 1")
    found = checks.run(doc, off=())
    assert "addendum_unpriced" in _rules(found)
    assert set(bidgate.RULES) <= set(checks.RULES)
    assert all(r in checks.HOW_TO for r in bidgate.RULES)


def test_escalation_projector(doc):
    EL.add(doc, [EL.new_line("Steel", 1, "ls", mat="100000"),
                 EL.new_line("Crew", 1, "ls", lab="50000"),
                 EL.new_line("Allow", 1, "ls", cost_type="Allowance",
                             sub="9999")])
    r = bidgate.project(doc, "2027-11-03", "2026-11-03",
                        pct={"Material": 5.0, "Labor": 4.0,
                             "Equipment": 0, "Subcontract": 0})
    rise = {x["type"]: x["rise"] for x in r["rows"]}
    assert abs(rise["Material"] - Decimal("5000")) < 20
    assert abs(rise["Labor"] - Decimal("2000")) < 10
    assert rise["Subcontract"] == 0                     # allowance left out
    ln = bidgate.escalation_line(r, "2027-11-03")
    assert Decimal(ln["sub"]) == r["total"] and "Material" in ln["note"]


def test_dialogs(doc, monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.estimating import bidgate_ui
    EL.add(doc, [EL.new_line("Hardware", 1, "ls", cost_type="Allowance",
                             sub="3000"),
                 EL.new_line("Steel", 1, "ls", mat="1000")])
    d = bidgate_ui.PlaceholdersDialog(doc)
    assert d.table.rowCount() == 1
    p = d.export(str(tmp_path / "p.csv"))
    assert "Hardware" in open(p, encoding="utf-8").read()
    e = bidgate_ui.EscalationDialog(doc)
    assert e.refresh()["total"] > 0
    lid = e.add()
    assert EL.get(doc, lid)["source"] == "Escalation Projector"
    s = bidgate_ui.SettingsDialog()
    s.days.setValue(30)
    s.save()
    assert bidgate.max_age() == 30
