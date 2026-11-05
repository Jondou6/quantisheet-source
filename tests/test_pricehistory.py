"""Upgrade spec Phase 2: bid vs actual, and a cost book priced from what
jobs really cost (never changed without you accepting it)."""
import csv
import datetime as dt
import os
import sqlite3
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import costbook, pricedb, pricehistory as ph, settings  # noqa


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    os.makedirs(settings.DIR, exist_ok=True)


def _book():
    b = costbook.Book({"name": "Mine", "items": {
        "P-8": {"desc": "8 in PVC", "unit": "lf", "material": 11.0},
        "MH-4": {"desc": "Manhole", "unit": "ea", "material": 4000.0}}})
    pricedb.save_book(b.to_dict())
    return b


LINES = [{"code": "P-8", "desc": "8 in PVC", "unit": "LF",
          "qty": Decimal("1200"), "unit_cost": Decimal("42.50")},
         {"code": "MH-4", "desc": "Manhole", "unit": "EA",
          "qty": Decimal("6"), "unit_cost": Decimal("5200.00")}]


def test_schema_1_migrates_with_data_intact():
    p = pricedb.path()
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                      "INSERT INTO meta VALUES ('schema', '1');"
                      "CREATE TABLE books (name TEXT PRIMARY KEY, effective "
                      "TEXT, region TEXT, escalation REAL, notes TEXT, "
                      "version TEXT, index_json TEXT, regions_json TEXT, "
                      "created TEXT, modified TEXT, modified_by TEXT);"
                      "INSERT INTO books (name) VALUES ('Old Book');")
    con.commit()
    con.close()
    with pricedb.connect() as c:
        assert c.execute("SELECT value FROM meta WHERE key='schema'") \
            .fetchone()[0] == str(pricedb.SCHEMA)
        assert c.execute("SELECT name FROM books").fetchone()[0] == \
            "Old Book"
        c.execute("SELECT * FROM jobs").fetchall()
        c.execute("SELECT * FROM unit_cost_obs").fetchall()


def test_newer_database_is_refused():
    with pricedb.connect(write=True) as c:
        c.execute("UPDATE meta SET value='99' WHERE key='schema'")
    with pytest.raises(pricedb.PriceDBError, match="newer"):
        with pricedb.connect():
            pass


def test_variance_is_exact_cents(tmp_path):
    jid = ph.add_job("24-031", "Sewer job", LINES, bid_total="82200.00")
    with pytest.raises(ph.HistoryError):
        ph.add_job("24-031", "again")
    rep = tmp_path / "jc.csv"
    with open(rep, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Cost Code", "Description", "Quantity", "Unit",
                    "Actual Cost"])
        w.writerow(["P-8", "pipe", "1250", "LF", "$55,312.50"])
        w.writerow(["MH-4", "manholes", "6", "EA", "30,000.00"])
        w.writerow(["XTRA", "dewatering", "", "LS", "4,100.10"])
    m, a = ph.set_actuals(jid, ph.read_actuals_csv(str(rep)))
    assert (m, a) == (2, 1)
    v = {r["code"]: r for r in ph.variance(jid)}
    assert v["P-8"]["est_cost"] == Decimal("51000.00")
    assert v["P-8"]["act_unit"] == Decimal("44.25")
    assert v["P-8"]["diff"] == Decimal("4312.50")
    assert v["P-8"]["pct"] == Decimal("8.5") and not v["P-8"]["flag"]
    assert v["MH-4"]["diff"] == Decimal("-1200.00") and \
        v["MH-4"]["pct"] == Decimal("-3.8")
    assert v["XTRA"]["act_cost"] == Decimal("4100.10") and \
        v["XTRA"]["est_cost"] == Decimal("0.00")
    # closing records unit costs for lines with a quantity
    assert ph.close_job(jid) == 2
    obs = ph.observations("P-8")
    assert len(obs) == 1 and obs[0]["unit_cost"] == "44.2500" and \
        obs[0]["kind"] == "actual"
    with pytest.raises(ph.HistoryError, match="already closed"):
        ph.close_job(jid)


def test_weighted_median():
    D = Decimal
    assert ph.weighted_median([D(10), D(12), D(30)], [D(1)] * 3) == 12
    assert ph.weighted_median([D(10), D(12), D(30)],
                              [D(1), D(1), D(5)]) == 30
    assert ph.weighted_median([], []) is None


def test_suggest_and_apply_only_when_accepted():
    b = _book()
    today = dt.date(2026, 10, 1)
    ph.add_observation("P-8", "12.00", qty=500, kind="actual",
                       date="2026-09-01")
    ph.add_observation("P-8", "13.00", qty=800, kind="actual",
                       date="2026-08-01")
    ph.add_observation("P-8", "30.00", qty=10, kind="quote",
                       date="2020-01-01")
    s = ph.suggest("P-8", b, today=today, escalation=0)
    assert s["count"] == 3 and s["book"] == Decimal("11.00")
    assert s["price"] == Decimal("13.00")          # recent, big jobs win
    assert s["min"] == Decimal("12.00") and s["max"] == Decimal("30.00")
    # nothing changed in the book yet
    assert costbook.load(costbook.DB + "Mine").get("P-8")["material"] == 11
    changed, skipped = ph.apply("Mine", {"P-8": s["price"],
                                         "NOPE": Decimal(1)},
                                note="job 24-031")
    assert changed == ["P-8"] and skipped == ["NOPE"]
    assert costbook.load(costbook.DB + "Mine").get("P-8")["material"] == 13
    h = pricedb.history("Mine", "P-8")
    assert h and h[0]["note"] == "history: job 24-031" and h[0]["by"]
    assert costbook.load(costbook.DB + "Mine").get("NOPE") is None


def test_job_from_locked_bid_and_project_actuals(tmp_path):
    from app import annotate, assemblies, prebid
    d = fitz.open()
    d.new_page(width=1224, height=792)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft"))
    assemblies.set_job_assembly(d, {
        "name": "Pipe", "measure": "length",
        "parts": [{"name": "8 in PVC", "code": "P-8", "unit": "LF",
                   "qty": "Length", "cost": 11.0}]})
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, 100], [1900 * 0 + 1000, 100]],
        measure={"type": "length", "value": 50, "unit": "ft",
                 "group": "Pipe"}))
    prebid.set_reviewed(d, 0)
    lk = prebid.lock(d, 550)
    assert lk["estimate"][0]["code"] == "P-8"
    jid = ph.job_from_doc(d, "25-002", "Pipe job")
    ln = ph.lines(jid)
    assert ln[0]["code"] == "P-8" and ln[0]["est_qty"] == "50.0000"

    class Store:
        def list(self, coll):
            return [{"cost_code": "P-8", "amount": 300, "quantity": 20,
                     "unit": "LF"},
                    {"cost_code": "P-8", "amount": 400, "quantity": 30}] \
                if coll == "cost" else []
    acts = ph.actuals_from_store(Store())
    assert acts[0]["cost"] == Decimal(700) and acts[0]["qty"] == Decimal(50)
    ph.set_actuals(jid, acts, "project center")
    v = ph.variance(jid)[0]
    assert v["act_unit"] == Decimal("14.00") and v["flag"]


def test_dialog_smoke(qapp=None):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    from app.pricehistory_ui import JobCostDialog
    QApplication.instance() or QApplication([])
    _book()
    jid = ph.add_job("26-001", "Test", LINES)
    ph.set_actuals(jid, [{"code": "P-8", "cost": "60000", "qty": "1200"}])
    ph.close_job(jid)
    dlg = JobCostDialog()
    dlg.refresh(select=jid)
    rows = dlg.show_job()
    assert any(r["flag"] for r in rows)
    sug = dlg.suggest("Mine")
    assert sug and sug[0]["code"] == "P-8"
    dlg.tick(0)
    changed, skipped = dlg.apply()
    assert changed == ["P-8"]
