"""Brief Phase 3: P3-02 ERP sync by files (2.1), P3-03 live connectors only
with vendor agreements (3.1), P3-04 WIP and over/under billing (4.1)."""
import logging

import pytest

from quantisheet_backoffice import (ap, assistant, billing, connectors,
                                    erpsync, security, wip)

from .helpers import ap_invoice, approve_ap


# ---- P3-02 -----------------------------------------------------------------

def test_2_1_likely_vendor_match_confirmed_by_a_person_never_renamed(office):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Framing")
    ap.add_vendor(office, "Example Paint")
    office.act_as("ctl@bo.test")
    text = ("Vendor ID,Vendor Name,Email,Tax ID,Bank Account\n"
            "V100,Example Framing LLC,ap@framing.example,00-0000001,"
            "000099990001\n"
            "V200,Example Paint,,,\n"
            "V300,Example Roofing Inc.,,,\n")
    r = erpsync.import_file(office, "Sage 300 CRE", "vendors", text=text)
    d = r["differences"]
    assert [(x["erp_name"], x["local_name"]) for x in d["likely"]] == \
        [("Example Framing LLC", "Example Framing")]
    assert d["likely"][0]["reason"].startswith("same name apart from")
    assert [x["erp_name"] for x in d["matched"]] == ["Example Paint"]
    assert [x["erp_name"] for x in d["new"]] == ["Example Roofing Inc."]
    assert r["ignored"] == ["Tax ID", "Bank Account"]
    stored = office.db.rows("SELECT data FROM erp_records")
    assert all("00-0000001" not in s["data"] and "000099990001" not in
               s["data"] for s in stored)
    assert ap.vendor(office, vid)["name"] == "Example Framing"   # untouched
    erpsync.confirm_match(office, r["id"], "V100", vid)
    assert ap.vendor(office, vid)["name"] == "Example Framing"
    again = erpsync.import_file(office, "Sage 300 CRE", "vendors", text=text)
    assert [x["erp_key"] for x in again["differences"]["changed"]] == ["V100"]
    out = erpsync.apply(office, again["id"], ["V300"])
    assert ap.vendor_by_name(office, "Example Roofing Inc.")
    assert ap.vendor(office, vid)["name"] == "Example Framing"
    assert any("Likely" in ln or "Changed" in ln for ln in out["report"])
    assert security.audit_rows(office.db, action="sync link")


def test_sync_checks_cost_codes_against_the_snapshot_and_refuses_files(
        office, job, tmp_path):
    office.act_as("ctl@bo.test")
    text = ("Job,Cost Code,Description\n2611,03-3000,Concrete\n"
            "2611,03-9000,Rebar\n2611,06-1000,Rough carpentry\n")
    r = erpsync.import_file(office, "Vista", "cost_codes", text=text)
    c = r["counts"]
    assert (c["matched"], c["new"], c["changed"], c["only_here"]) == \
        (1, 1, 1, 2)
    with pytest.raises(erpsync.SyncError, match="QuantiSheet"):
        erpsync.apply(office, r["id"], ["03-9000"])
    qbw = tmp_path / "Company.QBW"
    qbw.write_bytes(b"x")
    with pytest.raises(Exception):
        erpsync.import_file(office, "QuickBooks", "vendors", path=str(qbw))
    office.act_as("ap@bo.test")
    with pytest.raises(security.Denied):
        erpsync.import_file(office, "Vista", "cost_codes", text=text)


# ---- P3-03 -----------------------------------------------------------------

SECRET = "s3cret-token-XYZ"


def test_3_1_connector_needs_agreement_and_credentials_never_logged(
        office, caplog, monkeypatch):
    office.act_as("ctl@bo.test")
    with pytest.raises(connectors.ConnectorError, match="agreement"):
        connectors.run(office, "Vista")
    office.act_as("admin@bo.test")
    connectors.save(office, "Vista", "https://erp.example.test/api",
                    agreement_ref="")
    with pytest.raises(connectors.ConnectorError, match="agreement"):
        connectors.run(office, "Vista")
    connectors.save(office, "Vista", "https://erp.example.test/api",
                    agreement_ref="PARTNER-2026-17")
    with pytest.raises(connectors.ConnectorError, match="credentials"):
        connectors.run(office, "Vista")
    connectors.save(office, "Vista", "https://erp.example.test/api",
                    agreement_ref="PARTNER-2026-17", credentials=SECRET)
    with pytest.raises(connectors.ConnectorError, match="file-based"):
        connectors.run(office, "Vista")             # none shipped
    assert connectors.status(office, "Vista").startswith("File-based")

    def fake(endpoint, creds):
        assert creds == SECRET
        raise RuntimeError(f"401 for token {creds}")
    monkeypatch.setitem(connectors.REGISTRY, "Vista", fake)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(connectors.ConnectorError) as e:
            connectors.run(office, "Vista")
    assert SECRET not in str(e.value) and "[credentials]" in str(e.value)
    assert SECRET not in caplog.text
    db_text = "\n".join(str(r) for t in ("audit", "connectors", "erp_runs")
                        for r in office.db.rows(f"SELECT * FROM {t}"))
    assert SECRET not in db_text
    with pytest.raises(connectors.ConnectorError, match="https"):
        connectors.save(office, "Spectrum", "http://erp.example.test")


# ---- P3-04 -----------------------------------------------------------------

def _billed_job(office, job3):
    office.act_as("bill@bo.test")
    billing.set_contract(office, job3)
    for n in (1, 2, 3):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    office.act_as("admin@bo.test")
    # snapshot direct costs 97,850.00 + a vendor bill 74,150.00 = 172,000.00
    approve_ap(office, ap_invoice(office, "Example Framing", "AF-9",
                                  "2026-10-10", "74150.00", job_id=job3,
                                  code="06-1000", cat="S"))


def test_4_1_wip_over_billed(office, job3, tmp_path, fake_ollama):
    _billed_job(office, job3)
    wip.set_estimate(office, job3, "430000.00", "PM forecast Oct")
    [r] = wip.wip(office, "2026-10-31")
    assert (r["contract"], r["estimated_cost"], r["cost_to_date"]) == \
        (52_500_000, 43_000_000, 17_200_000)
    assert r["pct_complete"] == "40.0" and r["earned"] == 21_000_000
    assert r["billed"] == 22_500_000 and r["over_under"] == 1_500_000
    x = wip.to_xlsx(office, "2026-10-31", str(tmp_path / "wip.xlsx"))
    from openpyxl import load_workbook
    ws = load_workbook(x).active
    assert [c.value for c in ws[2]][:3] == ["Job", "Name", "Contract"]
    from decimal import Decimal
    assert Decimal(str(ws["I3"].value)) == Decimal("15000.00")
    p = wip.to_pdf(office, "2026-10-31", str(tmp_path / "wip.pdf"))
    import fitz
    txt = fitz.open(p)[0].get_text()
    assert "$15,000.00" in txt and "40.0%" in txt
    assert "Billed" in txt and "% complete" in txt
    assert "$225,000.00" in txt                          # billed to date
    for bad in ("AIA", "G702", "G703"):
        assert bad not in txt
    from .ai_fake import router
    fake_ollama.reply = router({"over-billed": {
        "tool": "wip", "job": "2611", "period": "as of 2026-10-31"}})
    a = assistant.ask(office, "Are we over-billed on 2611 as of 2026-10-31?")
    assert a["tool"] == "wip" and "over-billed $15,000.00" in a["text"]


def test_4_1_estimate_defaults_to_the_job_cost_forecast(office, job3):
    _billed_job(office, job3)
    [r] = wip.wip(office, "2026-10-31")
    assert r["estimate_source"] == "job cost forecast"
    from quantisheet_backoffice import jobcost
    assert r["estimated_cost"] == sum(x["forecast"] for x in
                                      jobcost.job_cost(office, job3))
    office.act_as("ap@bo.test")
    with pytest.raises(security.Denied):
        wip.set_estimate(office, job3, "1.00")


def test_4_1_forecast_is_as_of_the_report_date(office, job3):
    _billed_job(office, job3)
    from quantisheet_backoffice import jobcost
    [r] = wip.wip(office, "2026-10-05")       # before the 10-10 vendor bill
    assert r["estimated_cost"] == sum(
        x["forecast"] for x in jobcost.job_cost(office, job3,
                                                date_to="2026-10-05"))
    assert r["cost_to_date"] == 9_785_000


def test_4_1_zero_estimate_with_cost_is_flagged_not_zero_pct(office, job3,
                                                             tmp_path):
    _billed_job(office, job3)
    wip.set_estimate(office, job3, "0.00", "not set yet")
    [r] = wip.wip(office, "2026-10-31")
    assert r["estimate_needed"] and r["pct_complete"] == "n/a"
    assert r["estimate_source"] == "estimate needed"
    p = wip.to_pdf(office, "2026-10-31", str(tmp_path / "w.pdf"))
    import fitz
    txt = fitz.open(p)[0].get_text()
    assert "Estimate needed" in txt and "0.0%" not in txt
    x = wip.to_xlsx(office, "2026-10-31", str(tmp_path / "w.xlsx"))
    from openpyxl import load_workbook
    assert load_workbook(x).active["F3"].value == "n/a"


def test_sync_file_size_and_row_limits(office, tmp_path, monkeypatch):
    office.act_as("ctl@bo.test")
    big = tmp_path / "vendors.csv"
    big.write_text("Vendor ID,Vendor Name\n" + "V1,Example A\n" * 10)
    monkeypatch.setattr(erpsync, "MAX_BYTES", 50)
    with pytest.raises(erpsync.SyncError, match="larger than"):
        erpsync.import_file(office, "Vista", "vendors", path=str(big))
    with pytest.raises(erpsync.SyncError, match="larger than"):
        erpsync.import_file(office, "Vista", "vendors",
                            text=big.read_text())
    monkeypatch.setattr(erpsync, "MAX_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(erpsync, "MAX_ROWS", 5)
    with pytest.raises(erpsync.SyncError, match="more than 5 rows"):
        erpsync.import_file(office, "Vista", "vendors", text=big.read_text())
    assert office.db.rows("SELECT * FROM erp_runs") == []


def test_sync_vendor_name_checks(office):
    office.act_as("ctl@bo.test")
    text = ("Vendor ID,Vendor Name\n"
            "V1,Example Good Vendor\n"
            "V2,=HYPERLINK(\"http://x.example\")\n"
            "V3,+SUM(A1)\n"
            "V4,@cmd\n"
            "V5," + "X" * 121 + "\n"
            "V6,Example\x07Bell\n"
            "V7,-1+2\n"
            ",Example No Key\n")
    r = erpsync.import_file(office, "Vista", "vendors", text=text)
    assert [x["erp_name"] for x in r["differences"]["new"]] == [
        "Example Good Vendor"]
    rej = {x["row"]: x["reason"] for x in r["differences"]["rejected"]}
    assert set(rej) == {3, 4, 5, 6, 7, 8, 9}
    assert rej[9] == "empty key"
    assert "formula" in rej[3] and "longer than 120" in rej[6]
    assert "control" in rej[7]
    assert r["counts"]["rejected"] == 7
    with pytest.raises(erpsync.SyncError, match="not a new record"):
        erpsync.apply(office, r["id"], ["V2"])
    assert erpsync.check_name("Example O'Brien & Sons, Inc.") == ""
    assert erpsync.check_name("-Example") == ""
