"""The starter cost book (8 states), the default book, and RSMeans import."""
import csv
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, assembly_csv, costbook,  # noqa: E402
                 labor, pricedb, proposal, rsmeans, settings)
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

STARTER = os.path.join(costbook.SHIPPED, "QuantiSheet Starter 2026.json")
STATES = ["South Carolina", "North Carolina", "Florida", "Virginia",
          "Georgia", "Tennessee", "Pennsylvania", "New Jersey"]
SOG = "Slab on grade, 4 in, 6x6-W1.4 mesh"
RAS = "RAS pump"

# made-up lines in the RSMeans export layout (not real RSMeans data)
SAMPLE = """RSMeans ASSEMBLIES  |  3 assemblies  |  city: National average (1.00)  |  O&P 15%

== A Substructure - Standard Foundations ==
A1010 110   Strip footings, 12 x 12 in                    C-14A  LF   M 20.00     L 30.00     E 2.00     TOTAL 52.00      Incl O&P 59.80
== D Services - Cooling Generating ==
D3050 170   Split systems with air cooled condensing units C-1    TON  M 1,000.00  L 600.00    E 50.00    TOTAL 1,650.00   Incl O&P 1,897.50
== Wastewater treatment plant ==
WW 46 35 28 RAS pump                                      P-1    EA   M 40,000.00 L 16,000.00 E 2,000.00 TOTAL 58,000.00  Incl O&P 66,700.00
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_starter_book_prices_every_catalog_part():
    b = costbook.load(STARTER)
    assert b.name == "QuantiSheet Starter 2026" and b.version
    assert set(STATES) <= set(b.region_names())
    assert b.region_names()[0] == "national"
    rows = list(csv.DictReader(open(assembly_csv.CATALOG,
                                    encoding="utf-8-sig")))
    crews = labor.crews()
    for r in rows:
        it = b.get(f"{r['Assembly_ID']}.{r['Item_Seq']}")
        assert it, r["Assembly_ID"]
        assert it.get("basis") in ("researched", "estimate", "allowance")
        assert it.get("source")
        if r["Cost_Type"] == "Labor":
            assert it["crew"] in crews and it["labor"] > 0
    for reg in ["national"] + STATES:
        rates = b.labor_rates(reg, b.effective)
        for code in {it["crew"] for it in b.items.values() if it["crew"]}:
            members = [t for t, _ in crews[code]["members"]]
            assert all(t in rates for t in members), (reg, code)
        assert 25 < rates["Carpenter"] < 80
    # New Jersey costs more than South Carolina, for labor and materials
    sc, nj = b.labor_rates("South Carolina"), b.labor_rates("New Jersey")
    assert nj["Electrician"] > sc["Electrician"]
    assert b.factor("New Jersey", b.effective) > \
        b.factor("South Carolina", b.effective)
    # labor rates escalate with the book
    later = b.labor_rates("national", "2027-01-01")
    assert later["Carpenter"] == pytest.approx(
        b.labor_rates("national", b.effective)["Carpenter"] * 1.035,
        rel=1e-3)


def test_install_shipped_and_home_region():
    proposal.save_company({"name": "Acme", "address": "1 Main St\n"
                           "Myrtle Beach, SC 29588"})
    assert costbook.install_shipped() == ["QuantiSheet Starter 2026.json"]
    d = settings.get("default_costbook")
    assert d == {"name": "QuantiSheet Starter 2026",
                 "region": "South Carolina"}
    assert "QuantiSheet Starter 2026" in costbook.list_books()
    # an edited book is left alone by a newer shipped version
    b = costbook.find("QuantiSheet Starter 2026")
    b.set("A-03-SOG-4.4", "cy", material=999)
    costbook.save(b)
    marks = pricedb.meta("shipped")
    marks["QuantiSheet Starter 2026.json"]["version"] = "old"
    pricedb.set_meta("shipped", marks)
    assert costbook.install_shipped() == []
    assert costbook.find("QuantiSheet Starter 2026").get(
        "A-03-SOG-4.4")["material"] == 999
    # an unedited one is updated
    other = costbook.Book(json.load(open(STARTER, encoding="utf-8")))
    costbook.save(other)
    marks = pricedb.meta("shipped")
    marks["QuantiSheet Starter 2026.json"] = {
        "version": "old", "hash": pricedb.content_hash(
            pricedb.load_book("QuantiSheet Starter 2026"))}
    pricedb.set_meta("shipped", marks)
    assert costbook.install_shipped() == ["QuantiSheet Starter 2026.json"]


def _job(sf=1000.0):
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    side = 18 * sf ** 0.5
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[100, 100], [100 + side, 100],
                               [100 + side, 100 + side], [100, 100 + side]],
        measure={"type": "area", "value": sf, "unit": "sq ft",
                 "group": SOG}))
    return d


def test_default_book_prices_new_jobs_by_state():
    d = _job()
    rows, totals, _ = assemblies.rollup(d)
    assert totals["material"] == 0 and totals["costbook"] == ""  # no book
    costbook.install_shipped()
    book = costbook.find("QuantiSheet Starter 2026")
    totals_by = {}
    for reg in ("South Carolina", "New Jersey"):
        costbook.set_default(book, reg)
        rows, totals, errors = assemblies.rollup(d)
        assert not errors and totals["region"] == reg
        assert totals["costbook"] == "QuantiSheet Starter 2026"
        totals_by[reg] = totals
        conc = {p["name"]: p for p in rows[0]["parts"]}["Concrete, 3500 psi"]
        assert conc["cost"] == pytest.approx(
            170 * book.factor(reg), rel=1e-6)
    assert totals_by["New Jersey"]["labor_cost"] > \
        totals_by["South Carolina"]["labor_cost"] * 1.2
    # the job can opt out, or pick a book (which then travels in the PDF)
    assemblies.set_costbook(d, None)
    assert assemblies.rollup(d)[1]["material"] == 0
    assemblies.set_costbook(d, book, "Florida")
    assert assemblies.rollup(d)[1]["region"] == "Florida"


def test_rsmeans_import_catalog_book_and_calibration(tmp_path):
    costbook.install_shipped()
    src = tmp_path / "rs.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    res = rsmeans.import_file(str(src))
    assert res["assemblies"] == 3 and res["header"]["op"] == 0.15
    lib = assemblies.library()
    foot = lib["Strip footings, 12 x 12 in (RSMeans A1010 110)"]
    assert foot["measure"] == "length" and foot["csi"].startswith("03")
    split = lib["Split systems with air cooled condensing units "
                "(RSMeans D3050 170)"]
    assert split["inputs"] == {"T": "tons per item"}
    book = costbook.find(res["book"])
    assert book.get("RSM-A1010-110.1")["material"] == 20
    nat = rsmeans.national_rate("F-4", book)
    assert book.get("RSM-A1010-110.2")["crew"] == "F-4"
    m, e, lab = rsmeans.per_unit(foot, book)
    assert (m, e) == (20, 2)
    assert lab == pytest.approx(30 / 1.6, rel=1e-3)
    assert nat > 0
    # the catalog's RAS pump is calibrated to the RSMeans line
    assert any(c[0] == RAS for c in res["calibrated"])
    m, e, lab = rsmeans.per_unit(lib[RAS], book)
    assert m + e == pytest.approx(42000) and \
        lab == pytest.approx(16000 / 1.6, rel=1e-3)
    # state labor follows the state's crew rates
    _, _, lab_sc = rsmeans.per_unit(lib[RAS], book, "South Carolina")
    _, _, lab_nj = rsmeans.per_unit(lib[RAS], book, "New Jersey")
    assert lab_sc < lab < lab_nj
    with pytest.raises(ValueError):
        rsmeans.import_text("nothing here")
    # importing again (with the RSMeans book as the default) rebuilds the
    # same book from the starter prices
    costbook.set_default(book, "Georgia")
    again = rsmeans.import_file(str(src), make_default=True)
    assert again["book"] == res["book"] == "RSMeans + QuantiSheet Starter 2026"
    assert settings.get("default_costbook") == {
        "name": res["book"], "region": "Georgia"}


def test_cost_book_window_regions_default_and_rsmeans(qapp, win, tmp_path):
    from app.estimating_ui import CostBookDialog, LaborDialog
    costbook.install_shipped()
    dlg = CostBookDialog(win._view.doc, win)
    names = [dlg.books.item(i).data(0x0100) for i in range(dlg.books.count())]
    dlg.books.setCurrentRow(names.index("QuantiSheet Starter 2026"))
    regs = [dlg.region.itemData(i) for i in range(dlg.region.count())]
    assert set(STATES) <= set(regs)
    dlg.region.setCurrentIndex(regs.index("Georgia"))
    assert "Carpenter $" in dlg.region_info.text()
    dlg._make_default()
    assert settings.get("default_costbook")["region"] == "Georgia"
    assert "default book" in dlg.now.text()
    src = tmp_path / "rs.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    res = dlg._import_rsmeans(str(src))
    assert res and res["book"] in costbook.list_books()
    lab = LaborDialog(win._view.doc, win)
    ga = costbook.find("QuantiSheet Starter 2026").labor_rates("Georgia")
    row = next(r for r in range(lab.rates.rowCount())
               if lab.rates.item(r, 0).text() == "Carpenter")
    assert float(lab.rates.item(row, 1).text()) == pytest.approx(
        ga["Carpenter"], abs=0.01)
