"""Estimating Dashboard: cost per SF (median, range, outliers, trend),
hit rate, margin, sub price history across projects, damaged projects
skipped, filters, Excel formulas, PDF, and the window. Made-up jobs,
companies and numbers only."""
import json
import os
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import dashboard as db, pricedb, pricehistory as ph, settings  # noqa
from app.pm import scope_sheet as ss                                     # noqa

try:                                     # the window tests' fixtures
    from test_gui import win, qapp       # noqa: F401
    from test_pm import qapp_pm          # noqa: F401
except Exception:                        # noqa: BLE001  (no Qt here)
    pass


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test Estimator"})
    os.makedirs(settings.DIR, exist_ok=True)
    db._CACHE.clear()
    from app.pm import store
    monkeypatch.setattr(store, "_OPEN", {})


def _set_sf(jid, sf):
    m = pricedb.meta(db.SF_META) or {}
    m[str(jid)] = str(sf)
    pricedb.set_meta(db.SF_META, m)


def _db_job(number, btype, sf, est, bid, when, client="Test Owner A",
            estimator="Est One", region="SC Test Region"):
    """A Job Cost Feedback job: 60% of the estimate in 03, 40% in 09."""
    est = Decimal(est)
    jid = ph.add_job(number, f"Test job {number}", lines=[
        {"code": "03 31 13", "desc": "Test slab", "unit": "LS",
         "qty": Decimal(1), "unit_cost": est * Decimal("0.6")},
        {"code": "09 29 00", "desc": "Test board", "unit": "LS",
         "qty": Decimal(1), "unit_cost": est * Decimal("0.4")}],
        client=client, type=btype, estimator=estimator, region=region,
        bid_date=when, bid_total=Decimal(bid))
    if sf:
        _set_sf(jid, sf)
    return jid


def _project(root, name, st=None, sheets=(), packages=()):
    folder = os.path.join(str(root), name)
    os.makedirs(os.path.join(folder, ".quantisheet"), exist_ok=True)
    recs = {"scopesheet": {}, "bidpkg": {}}
    for i, sh in enumerate(sheets):
        d = ss.to_dict(sh)
        d["_id"] = f"s{i}"
        recs["scopesheet"][d["_id"]] = d
    for i, p in enumerate(packages):
        p = dict(p, _id=f"p{i}")
        recs["bidpkg"][p["_id"]] = p
    data = {"name": name, "hub": None, "seq": 0, "records": recs,
            "pending": [], "next": {}, "settings": dict(st or {})}
    with open(os.path.join(folder, db.PROJECT_FILE), "w",
              encoding="utf-8") as f:
        json.dump(data, f)
    return folder


def _sheet(csi_, trade, bids, award=None, when=""):
    """bids: [(company, "amount")] as stated bid prices."""
    sh = ss.new_sheet(csi_, trade, bidders=0, header={"bid_date": when})
    for company, amt in bids:
        b = ss.add_bidder(sh, company)
        b["price"] = ss.parse_money(amt)
        if company == award:
            sh["award"]["bidder"] = b["id"]
    return sh


def _office_set(tmp_path):
    """Five office jobs at $100, $104, $108, $112 and $300 per SF (the
    last an outlier) and one retail job; three in the price database,
    three as Project Center projects."""
    _db_job("T-1", "Test Office", 1000, 90000, 100000, "2024-01-15")
    _db_job("T-2", "Test Office", 2000, 190000, 208000, "2024-07-15")
    j3 = _db_job("T-3", "Test Office", 1500, 150000, 162000, "2025-01-15",
                 estimator="Est Two")
    folders = [
        _project(tmp_path, "P4", {"building_type": "Test Office",
                                  "building_sf": "1,000",
                                  "bid_amount": "$112,000.00",
                                  "bid_date": "2025-07-15",
                                  "location": "Testville, NC",
                                  "estimator": "Est One",
                                  "owner": "Test Owner B",
                                  "bid_result": "Won"}),
        _project(tmp_path, "P5", {"building_type": "test office",
                                  "building_sf": "500",
                                  "bid_amount": "150000",
                                  "bid_date": "2026-01-15",
                                  "location": "Testville, NC 99901",
                                  "owner": "Test Owner B",
                                  "bid_result": "Lost"}),
        _project(tmp_path, "P6", {"building_type": "Test Retail",
                                  "building_sf": "800",
                                  "bid_amount": "96000.01",
                                  "bid_date": "2026-02-01",
                                  "bid_result": "No bid"})]
    return j3, folders


# ============================================================ statistics
def test_statistics_match_excel():
    vals = [Decimal(x) for x in ("100", "104", "108", "112", "300")]
    st = db.stats(vals)
    assert st["median"] == Decimal("108")
    assert (st["q1"], st["q3"]) == (Decimal("104"), Decimal("112"))
    assert db.outlier(Decimal("300"), st) == "high"
    assert db.outlier(Decimal("100"), st) == ""
    assert db.quartile([Decimal(1), Decimal(2)], 1) == Decimal("1.25")
    assert db.median([Decimal("1.00"), Decimal("1.01")]) == \
        Decimal("1.005")
    # three values are too few to call one an outlier
    assert db.outlier(Decimal(900), db.stats([1, 2, Decimal(900)])) == ""
    pts = [(date(2024, 1, 1), Decimal(100)), (date(2025, 1, 1),
                                              Decimal(110)),
           (date(2026, 1, 1), Decimal(120))]
    assert db.trend_per_year(pts) == Decimal("9.99")   # 10 / 365.5 days
    assert db.trend_per_year(pts[:2]) is None


def test_parsers():
    assert db.parse_date("2026-03") == date(2026, 3, 1)
    assert db.parse_date("2026-02", end=True) == date(2026, 2, 28)
    assert db.parse_date("3/14/26") == date(2026, 3, 14)
    assert db.parse_date("soon") is None
    assert db.state_of("Testville, NC 99901") == "NC"
    assert db.state_of("", "SC Test Region") == "SC"
    assert db.money("$1,234.505") == Decimal("1234.51")
    assert db.money("twelve") is None
    assert db.company_key("Example Drywall, LLC") == \
        db.company_key("EXAMPLE DRYWALL")
    assert db.section_of("09 29 00 Gypsum board") == "09 29 00"


def test_sf_key_is_quick_sf_s():
    try:
        from app import quick_sf
    except Exception:                                  # noqa: BLE001
        pytest.skip("quick_sf not importable here")
    assert quick_sf.META_SF == db.SF_META


# ============================================================ cost per SF
def test_cost_per_sf_by_type_median_range_outlier(tmp_path):
    _j3, folders = _office_set(tmp_path)
    data = db.load(folders)
    assert not data["skipped"]
    r = db.build(data)
    by = {g["label"]: g for g in r["by_type"]}
    off = by["Test Office"]                    # both spellings, one group
    # cost = our bid (no actuals yet): 100, 104, 108, 112, 300 $/SF
    assert off["n"] == 5
    assert off["median"] == Decimal("108.00")
    assert (off["low"], off["high"]) == (Decimal("100.00"),
                                         Decimal("300.00"))
    flags = {d["name"]: d["flag"] for d in off["detail"]}
    assert flags["P5"] == "high" and off["outliers"] == 1
    assert sum(1 for f in flags.values() if f) == 1
    assert off["trend"] is not None and off["trend"] > 0
    assert by["Test Retail"]["median"] == Decimal("120.00")   # 96000.01/800
    assert r["by_type"][0]["label"] == "All jobs"
    assert r["by_type"][0]["n"] == 6


def test_cost_per_sf_by_division_from_job_lines(tmp_path):
    _office_set(tmp_path)
    r = db.build(db.load([]))
    by = {g["division"]: g for g in r["by_division"]}
    # T-1: 54,000 / 1000 = 54.00; T-2: 114,000 / 2000 = 57.00;
    # T-3: 90,000 / 1500 = 60.00 (60% of each estimate in 03)
    assert by["03"]["median"] == Decimal("57.00")
    assert (by["03"]["low"], by["03"]["high"]) == (Decimal("54.00"),
                                                   Decimal("60.00"))
    assert by["09"]["median"] == Decimal("38.00")
    assert by["03"]["label"].startswith("03 Concrete")


def test_actual_cost_wins_for_sf(tmp_path):
    j3, folders = _office_set(tmp_path)
    ph.set_actuals(j3, [{"code": "03 31 13", "cost": "100000.00"},
                        {"code": "09 29 00", "cost": "65000.50"}])
    r = db.build(db.load(folders))
    j = r["index"][f"db:{j3}"]
    assert j["cost_basis"] == "actual cost"
    assert j["cost"] == Decimal("165000.50")
    assert db.per_sf(j["cost"], j["sf"]) == Decimal("110.00")
    assert j["divisions"]["09"] == Decimal("65000.50")


# ============================================================ hit rate
def test_hit_rate_by_type_owner_month(tmp_path):
    j3, folders = _office_set(tmp_path)
    ph.close_job(j3, record=False)             # built -> counts as Won
    r = db.build(db.load(folders))
    t = {g["label"]: g for g in r["hit"]["type"]}
    off = t["Test Office"]
    # T-1, T-2 pending; T-3 closed (Won); P4 Won; P5 Lost
    assert (off["won"], off["lost"], off["pending"]) == (2, 1, 2)
    assert off["rate"] == Decimal("66.7")
    # $: won 162,000 + 112,000 of decided 424,000
    assert off["won_amount"] == Decimal("274000.00")
    assert off["dollar_rate"] == Decimal("64.6")
    assert t["Test Retail"]["no_bid"] == 1 and t["Test Retail"]["rate"] \
        is None
    allrow = r["hit"]["type"][-1]
    assert allrow["label"] == "All jobs" and allrow["decided"] == 3
    owners = {g["label"]: g for g in r["hit"]["owner"]}
    assert owners["Test Owner B"]["rate"] == Decimal("50.0")
    months = [g["label"] for g in r["hit"]["month"]]
    assert months[:2] == ["2024-01", "2024-07"]
    j = r["index"][f"db:{j3}"]
    assert j["result_source"] == "closed in Job Cost Feedback"


def test_set_result_saves_in_project_and_price_db(tmp_path):
    jid = _db_job("T-9", "Test Office", 1000, 90000, 100000, "2025-03-01")
    folder = _project(tmp_path, "P9", {"number": "T-9"})
    data = db.load([folder])
    job = data["index"][f"db:{jid}"]
    assert job["folder"] == os.path.abspath(folder)        # linked by number
    assert job["result"] == "Pending"
    assert db.set_result(job, "Lost") == ["price database",
                                          "project settings"]
    with pricedb.connect() as con:
        assert con.execute("SELECT result FROM jobs WHERE id=?",
                           (jid,)).fetchone()[0] == "Lost"
    with open(os.path.join(folder, db.PROJECT_FILE), encoding="utf-8") as f:
        assert json.load(f)["settings"]["bid_result"] == "Lost"
    again = db.load([folder])["index"][f"db:{jid}"]
    assert again["result"] == "Lost"


def test_old_price_db_gets_the_result_column(tmp_path):
    p = pricedb.path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES ('schema', '3');"
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY, number TEXT UNIQUE, "
        "name TEXT, client TEXT, type TEXT, estimator TEXT, book TEXT, "
        "region TEXT, bid_date TEXT, status TEXT, bid_total TEXT, "
        "contract TEXT, closed TEXT, folder TEXT, file TEXT, added TEXT, "
        "added_by TEXT);"
        "INSERT INTO jobs (number, name, status, bid_total) VALUES "
        "('OLD-1', 'Old test job', 'Bid', '1000.00');")
    con.commit()
    con.close()
    data = db.load([])
    assert data["jobs"][0]["result"] == "Pending"
    with pricedb.connect() as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    assert "result" in cols


# ============================================================ margin
def test_margin_bid_vs_estimate_and_actual(tmp_path):
    j3, folders = _office_set(tmp_path)
    ph.set_actuals(j3, [{"code": "03 31 13", "cost": "95000"},
                        {"code": "09 29 00", "cost": "60000.25"}])
    r = db.build(db.load(folders))
    m = {g["label"]: g for g in r["margin"]}["Test Office"]
    # jobs with bid and estimate: T-1..T-3 (projects have no estimate)
    assert m["n"] == 3
    assert m["bid"] == Decimal("470000.00")
    assert m["est_cost"] == Decimal("430000.00")
    assert m["markup"] == Decimal("40000.00")
    assert m["margin_pct"] == Decimal("8.5")
    assert m["n_actual"] == 1
    assert m["actual"] == Decimal("155000.25")
    assert m["actual_vs_est"] == Decimal("5000.25")
    jm = {x["name"]: x for x in r["job_margins"]}["Test job T-3"]
    assert jm["actual_vs_est_pct"] == Decimal("3.3")
    assert jm["partial"] is True                  # not closed yet


# ============================================================ subs
def test_sub_prices_across_jobs(tmp_path):
    a = _project(tmp_path, "S1", {"bid_date": "2025-02-01",
                                  "building_type": "Test Office"},
                 sheets=[_sheet("09 29 00", "Test board",
                                [("Alpha Test Drywall LLC", "100,000"),
                                 ("Beta Test Walls", "110,000"),
                                 ("Gamma Test Interiors", "120,000")],
                                award="Beta Test Walls")],
                 packages=[{"title": "Drywall", "trades": "09 29 00 Board",
                            "status": "Awarded",
                            "awarded_to": "Beta Test Walls",
                            "bidders": [{"company": "BETA TEST WALLS",
                                         "amount": "110000",
                                         "status": "Awarded"}]}])
    b = _project(tmp_path, "S2", {"bid_date": "2026-02-01"},
                 sheets=[_sheet("092900", "Board again",
                                [("Alpha Test Drywall", "90,000.00"),
                                 ("Beta Test Walls", "99,000.00")],
                                award="Alpha Test Drywall")],
                 packages=[{"title": "Sealed one", "trades": "09 29 00",
                            "sealed": "Yes",
                            "bidders": [{"company": "Alpha Test Drywall",
                                         "amount": "1"}]}])
    r = db.build(db.load([a, b]))
    rows = [s for s in r["subs"] if s["trade_key"] == "csi:09 29 00"]
    by = {s["company"]: s for s in rows}
    alpha = by["Alpha Test Drywall"]
    beta = by["Beta Test Walls"]
    # S1 median 110,000: alpha -9.1%; S2 median 94,500: alpha -4.8%
    assert alpha["bids"] == 2 and alpha["low"] == 2
    assert [b_["pct"] for b_ in alpha["history"]] == [Decimal("-9.1"),
                                                      Decimal("-4.8")]
    assert alpha["median_pct"] == Decimal("-7.0")       # (-9.1 + -4.8) / 2
    assert alpha["awarded"] == 1
    # the package repeats Beta's scope-sheet bid: counted once, awarded
    assert beta["bids"] == 2 and beta["awarded"] == 1 and beta["low"] == 0
    assert beta["latest"] == Decimal("99000.00")
    assert alpha["first"] == date(2025, 2, 1)
    assert by["Gamma Test Interiors"]["median_pct"] == Decimal("9.1")
    # the sealed, unopened package's numbers stay out
    assert all(x["amount"] != Decimal("1.00") for x in r["bids"])
    assert r["trades"][0][0] == "csi:09 29 00"


def test_bid_tabs_feed_sub_prices(tmp_path):
    from app import bidtab
    from types import SimpleNamespace as N
    rows = [N(bidder="Tab Bidder One", item_no="1", desc="Test paving",
              unit="SY", qty=100.0, price=10.5, trade="Paving"),
            N(bidder="Tab Bidder Two", item_no="1", desc="Test paving",
              unit="SY", qty=100.0, price=12.0, trade="Paving")]
    bidtab.add_rows(rows, "Test tab", state="SC", bid_date="2025-05")
    r = db.build(db.load([]))
    s = {x["company"]: x for x in r["subs"]}
    assert s["Tab Bidder One"]["latest"] == Decimal("1050.00")
    assert s["Tab Bidder One"]["low"] == 1
    assert s["Tab Bidder One"]["award_known"] == 0
    assert s["Tab Bidder Two"]["median_pct"] == Decimal("6.7")
    # a building-type filter leaves bid tabs (no type) out
    assert db.build(db.load([]), {"type": "Test Office"})["bids"] == []


# ============================================================ damaged
def test_damaged_project_skipped_and_listed(tmp_path):
    good = _project(tmp_path, "Good", {"building_type": "Test Office",
                                       "building_sf": "1000",
                                       "bid_amount": "100000"})
    bad = os.path.join(str(tmp_path), "Bad")
    os.makedirs(os.path.join(bad, ".quantisheet"))
    with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:
        f.write('{"records": {"scopesheet": ')            # cut off
    worse = _project(tmp_path, "Worse", {})
    with open(os.path.join(worse, db.PROJECT_FILE), "w") as f:
        json.dump({"records": [1, 2], "settings": {}}, f)
    nothing = os.path.join(str(tmp_path), "NotAProject")
    os.makedirs(nothing)
    gone = os.path.join(str(tmp_path), "Gone")
    data = db.load([bad, good, worse, nothing, gone])
    assert [j["name"] for j in data["jobs"]] == ["Good"]
    why = {os.path.basename(s["folder"]): s["reason"]
           for s in data["skipped"]}
    assert set(why) == {"Bad", "Worse", "NotAProject", "Gone"}
    assert "damaged" in why["Bad"] and "damaged" in why["Worse"]
    # read-only: the damaged file is left where it was
    assert os.path.isfile(os.path.join(bad, db.PROJECT_FILE))
    assert not os.path.exists(os.path.join(bad, db.PROJECT_FILE +
                                           ".damaged"))


def test_bad_record_inside_a_project_skips_only_that_record(tmp_path):
    sh = _sheet("09 29 00", "Board", [("Alpha Test Drywall", "1000")])
    f = _project(tmp_path, "Mixed", {}, sheets=[sh])
    path = os.path.join(f, db.PROJECT_FILE)
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    d["records"]["scopesheet"]["bad"] = {"schema": 99, "csi": "03"}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    data = db.load([f])
    assert not data["skipped"] and len(data["bids"]) == 1
    assert any("scope sheet was skipped" in w for w in data["warnings"])


def test_project_reads_are_cached(tmp_path, monkeypatch):
    f = _project(tmp_path, "C1", {"building_sf": "10"})
    db.load([f])
    calls = []
    real = json.load
    monkeypatch.setattr(db.json, "load", lambda *a, **k: calls.append(1)
                        or real(*a, **k))
    db.load([f])
    assert calls == []


# ============================================================ filters
def test_filters(tmp_path):
    _j3, folders = _office_set(tmp_path)
    data = db.load(folders)
    names = lambda f: sorted(j["name"] for j in db.build(data, f)["jobs"])
    assert names({"date_from": "2025-01-01", "date_to": "2025-12"}) == \
        ["P4", "Test job T-3"]
    assert names({"type": "TEST RETAIL"}) == ["P6"]
    assert names({"state": "NC"}) == ["P4", "P5"]
    assert names({"estimator": "Est Two"}) == ["Test job T-3"]
    opts = db.filter_options(data)
    assert opts["type"] == ["Test Office", "Test Retail"]
    assert "SC" in opts["state"] and "NC" in opts["state"]


def test_drill_down_lists_the_jobs_behind_a_number(tmp_path):
    _j3, folders = _office_set(tmp_path)
    r = db.build(db.load(folders))
    g = {g["label"]: g for g in r["hit"]["owner"]}["Test Owner B"]
    assert [j["name"] for j in db.jobs_for(r, g["jobs"])] == ["P4", "P5"]


def test_empty_dashboard():
    r = db.build(db.load([]))
    assert r["empty"] and r["by_type"] == [] and r["subs"] == []


# ============================================================ exports
def _cell_values(ws, col):
    return {c.row: c.value for c in ws[col]}


def test_excel_export_formulas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    _j3, folders = _office_set(tmp_path)
    a = _project(tmp_path, "S1", {"bid_date": "2025-02-01"},
                 sheets=[_sheet("09 29 00", "Board",
                                [("Alpha Test Drywall", "100,000"),
                                 ("Beta Test Walls", "110,000")])])
    r = db.build(db.load(folders + [a]))
    path = db.export_xlsx(r, str(tmp_path / "out" / "dash.xlsx"))
    wb = openpyxl.load_workbook(path)
    js = wb["Jobs"]
    head = [c.value for c in js[1]]
    assert head[8:12] == ["Building SF", "Cost", "Cost basis", "$/SF"]
    assert js["L2"].value.startswith("=IF(AND(ISNUMBER(I2)")
    assert "ROUND(J2/I2,2)" in js["L2"].value
    last = js.max_row
    assert js[f"A{last}"].value == "Total"
    assert js[f"M{last}"].value == f"=SUM(M2:M{last - 1})"
    # exact cents are written, not floats
    bids = [js[f"M{i}"].value for i in range(2, last)]
    assert Decimal(str(sum(Decimal(str(b)) for b in bids if b is not None))) \
        == sum(j["bid"] for j in r["jobs"] if j["bid"] is not None)
    # the median formula covers exactly the office jobs' $/SF cells, and
    # those cells' inputs give the dashboard's median
    cs = wb["Cost per SF"]
    rows = {cs[f"A{i}"].value: i for i in range(2, cs.max_row + 1)}
    f = cs[f"C{rows['Test Office']}"].value
    assert f.startswith("=ROUND(MEDIAN('Jobs'!L") and f.endswith(",2)")
    refs = f[len("=ROUND(MEDIAN("):-len("),2)")].split(",")
    cells = []
    for ref in refs:
        rng = ref.split("!")[1]
        lo, _, hi = rng.partition(":")
        a_, b_ = int(lo[1:]), int((hi or lo)[1:])
        cells += list(range(a_, b_ + 1))
    vals = [db.cents(Decimal(str(js[f"J{i}"].value)) /
                     Decimal(str(js[f"I{i}"].value))) for i in cells]
    off = {g["label"]: g for g in r["by_type"]}["Test Office"]
    assert db.cents(db.median(vals)) == off["median"]
    assert cs[f"B{rows['Test Office']}"].value.startswith("=COUNT(")
    assert "P5 (high)" in cs[f"I{rows['Test Office']}"].value
    # hit rate and margin rates are formulas over the counts
    hs = wb["Hit Rate"]
    assert any(str(c.value).startswith("=IF(B") for c in hs["F"])
    ms = wb["Margin"]
    assert ms["E2"].value == "=C2-D2"
    assert ms["C2"].value.startswith("=SUM('Jobs'!M")
    # subs: % vs median per bid, medians over them
    sb = wb["Sub Bids"]
    assert sb["G2"].value == '=IF(F2<>0,ROUND((E2-F2)/F2*100,1),"")'
    su = wb["Sub Summary"]
    assert su["F2"].value.startswith("=ROUND(MEDIAN('Sub Bids'!G")
    assert su["D2"].value.startswith("=COUNTIF('Sub Bids'!H")
    assert wb["By Division"]["C2"].value.startswith(
        "=ROUND(MEDIAN('Division Lines'!F")


def test_excel_export_of_empty_dashboard(tmp_path):
    pytest.importorskip("openpyxl")
    r = db.build(db.load([]))
    assert os.path.isfile(db.export_xlsx(r, str(tmp_path / "e.xlsx")))


def test_pdf_export(tmp_path):
    fitz = pytest.importorskip("fitz")
    if not hasattr(fitz, "open") or not callable(getattr(fitz, "open")):
        pytest.skip("no PyMuPDF")
    _j3, folders = _office_set(tmp_path)
    r = db.build(db.load(folders))
    path = db.export_pdf(r, str(tmp_path / "dash.pdf"))
    doc = fitz.open(path)
    text = "".join(p.get_text() for p in doc)
    assert "Estimating Dashboard" in text
    assert "Cost per SF by building type" in text
    assert "$108.00" in text
    doc.close()
    empty = db.export_pdf(db.build(db.load([])), str(tmp_path / "e.pdf"))
    assert os.path.isfile(empty)


# ============================================================ window
def test_window_opens_filters_and_drills(qtbot, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    from app import dashboard_ui
    _j3, folders = _office_set(tmp_path)
    w = dashboard_ui.EstimatingDashboard(None, folders)
    qtbot.addWidget(w)
    assert not w.hint.isVisible() or not w.isVisible()
    assert w.sf_table.rowCount() == 3                   # All, Office, Retail
    assert w.sf_table.item(1, 0).text() == "Test Office"
    assert w.sf_table.item(1, 2).text() == "$108.00"
    w.sf_table.selectRow(1)
    assert w.drill.rowCount() == 5
    assert "Test Office" in w.drill_label.text()
    w.set_filters(type="Test Retail")
    assert w.jobs_table.rowCount() == 1
    assert w.sf_table.item(1, 0).text() == "Test Retail"
    w.set_filters(type="", state="NC")
    assert w.jobs_table.rowCount() == 2
    w.clear_filters()
    assert w.jobs_table.rowCount() == 6
    w.hit_by.setCurrentIndex(w.hit_by.findData("owner"))
    labels = [w.hit_table.item(i, 0).text()
              for i in range(w.hit_table.rowCount())]
    assert "Test Owner B" in labels
    w.hit_table.selectRow(labels.index("Test Owner B"))
    assert w.drill.rowCount() == 2
    w.sf_by.setCurrentIndex(w.sf_by.findData("division"))
    assert w.sf_table.item(0, 0).text().startswith("03")
    # set a result from the Jobs tab
    names = [w.jobs_table.item(i, 0).text()
             for i in range(w.jobs_table.rowCount())]
    w.jobs_table.selectRow(names.index("Test job T-1"))
    assert w.set_result("Won") == ["price database"]
    t = {g["label"]: g for g in w.report["hit"]["type"]}["Test Office"]
    assert t["won"] == 2
    out = w.export_excel(str(tmp_path / "w.xlsx"))
    assert out and os.path.isfile(out)
    w.close()


def test_window_empty_shows_hint_without_a_dialog(qtbot, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QMessageBox
    from app import dashboard_ui
    for n in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, **k: pytest.fail("no message box when empty")))
    w = dashboard_ui.EstimatingDashboard(None, [])
    qtbot.addWidget(w)
    w.show()
    assert w.hint.isVisible()
    assert w.sf_table.rowCount() == 0 and w.drill.rowCount() == 0
    assert not w.skipped_btn.isVisible()
    w.sf_bars.repaint()
    w.sf_trend.repaint()
    w.close()


def test_window_lists_skipped_projects(qtbot, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    from app import dashboard_ui
    bad = os.path.join(str(tmp_path), "Bad")
    os.makedirs(os.path.join(bad, ".quantisheet"))
    with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:
        f.write("not json")
    w = dashboard_ui.EstimatingDashboard(None, [bad])
    qtbot.addWidget(w)
    w.show()
    assert w.skipped_btn.isVisible()
    assert "1 project(s) skipped" in w.skipped_btn.text()
    w.close()


def test_project_settings_has_dashboard_fields(qapp_pm, qtbot, tmp_path,
                                               monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QLineEdit
    from app.pm import center
    from app.pm.store import open_store
    st = open_store(str(tmp_path / "PS"))
    st.save(now=True)
    w = center.ProjectCenter(st)
    qtbot.addWidget(w)

    def fill(dlg, *a):
        f = dlg.layout()
        seen = {}
        for row in range(f.rowCount()):
            lab = f.itemAt(row, QFormLayout.ItemRole.LabelRole)
            fld = f.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if lab is None or fld is None:
                continue
            seen[lab.widget().text()] = fld.widget()
        assert isinstance(seen["Bid result"], QComboBox)
        for k, v in (("Building type", "Test Office"),
                     ("Building SF", "12,000"), ("Bid date", "2026-04-01"),
                     ("Our bid amount", "1,500,000.00")):
            assert isinstance(seen[k], QLineEdit)
            seen[k].setText(v)
        seen["Bid result"].setCurrentText("Won")
        return 1
    monkeypatch.setattr(QDialog, "exec", fill)
    w.project_settings()
    assert st.setting("building_type") == "Test Office"
    assert st.setting("bid_result") == "Won"
    st.flush(force=True)
    j = db.load([st.folder])["jobs"][0]
    assert (j["sf"], j["bid"], j["result"]) == (
        Decimal("12000.00"), Decimal("1500000.00"), "Won")
    w.close()


def test_main_window_command(win):
    from app import simple_menu
    names = [n for _t, _g, ns, _a in simple_menu.TREE for n in ns]
    assert "Estimating Dashboard" in names
    assert win.command("Estimating Dashboard") is not None
    dlg = win.estimating_dashboard(folders=[])
    assert dlg.isVisible() and dlg.hint.isVisible()
    dlg.close()
