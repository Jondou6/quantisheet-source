"""P1-10 contracts/SOV/COs (10.1-10.3), P1-11 progress invoices
(11.1-11.4), P1-12 retainage (12.1-12.3), P1-13 T&M (13.1-13.3)."""
import pytest

from quantisheet_backoffice import (approvals, billing, cents, jobs, output,
                                    payments, timeentry)

from .helpers import ap_invoice, approve_ap, import_stage


def test_10_1_contract_summary(office, job):
    billing.set_contract(office, job)
    s = billing.contract_summary(office, job)
    assert s["original"] == 50_000_000 and s["executed_changes"] == 2_500_000
    assert cents.fmt(s["contract_sum_to_date"]) == "$525,000.00"
    assert cents.fmt(s["pending_changes"]) == "$8,500.00"
    pend = billing.changes_view(office, job)["pending"]
    assert [c["cor"] for c in pend] == ["COR-002"]


def test_10_2_new_co_after_reimport_not_yet_billed(office, job):
    billing.set_contract(office, job)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job, n))
    import_stage(office, 3)
    view = {l["item"]: l for l in billing.sov_view(office, job)}
    assert "CO-002" in view
    assert view["CO-002"]["is_change"] and view["CO-002"]["status"] == \
        "not yet billed"
    assert view["CO-002"]["scheduled"] == 850_000
    assert view["1"]["status"] == "billed"


def test_10_3_sov_read_only_in_contract_page(office, job, qapp):
    billing.set_contract(office, job)
    from quantisheet_backoffice.ui.billing_page import ContractPage
    pg = ContractPage(office, job)
    assert pg.sov_table.editTriggers() == pg.sov_table.EditTrigger.NoEditTriggers
    assert pg.co_table.editTriggers() == pg.co_table.EditTrigger.NoEditTriggers
    assert "edit in QuantiSheet > Billing" in pg.note.text()
    assert all(l["read_only"] for l in billing.sov_view(office, job))
    pg.close()


def test_11_1_invoice_from_app_3(office, job3):
    billing.set_contract(office, job3)
    office.db.set_counter("INV", 999)
    for n in (1, 2):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))
    iid = billing.invoice_from_payapp(office, job3, 3)
    inv = billing.invoice(office, iid)
    v = billing.payapp_numbers(office, iid)
    assert inv["number"] == "INV-1001"
    assert (v["1"], v["2"], v["3"]) == (50_000_000, 2_500_000, 52_500_000)
    assert v["4"] == 21_000_000 + 1_500_000 == 22_500_000
    assert (v["5a"], v["5b"], v["5"]) == (2_100_000, 150_000, 2_250_000)
    assert (v["6"], v["7"]) == (20_250_000, 13_500_000)
    assert inv["total"] == v["8"] == 6_750_000
    assert cents.fmt(inv["total"]) == "$67,500.00"
    assert v["9"] == 32_250_000
    assert inv["retainage"] == 750_000


def test_11_2_printed_numbers_equal_certified(office, job3, tmp_path):
    billing.set_contract(office, job3)
    ids = [billing.invoice_from_payapp(office, job3, n) for n in (1, 2, 3)]
    snap = {a["number"]: a for a in jobs.section(office, job3, "payapps")}
    # change an SOV line after certification: invoices keep the certified math
    office.db.conn.execute(
        "UPDATE snap_records SET data = replace(data, '250000.00', '260000.00')"
        " WHERE section = 'sov'")
    for n, iid in zip((1, 2, 3), ids):
        p = output.invoice_pdf(office, iid, str(tmp_path / f"i{n}.pdf"))
        import fitz
        txt = "".join(pg.get_text() for pg in fitz.open(p))
        for k, val in snap[n]["summary"].items():
            assert cents.fmt(cents.to_cents(val)) in txt, (n, k)
        assert billing.payapp_numbers(office, iid) == \
            {k: cents.to_cents(x) for k, x in snap[n]["summary"].items()}


def test_11_3_draft_app_refused(office, job):
    billing.set_contract(office, job)
    with pytest.raises(billing.BillingError,
                       match="certify it in QuantiSheet first"):
        billing.invoice_from_payapp(office, job, 3)


def test_11_4_no_aia_strings(office, job3, tmp_path):
    import fitz
    billing.set_contract(office, job3)
    iid = billing.invoice_from_payapp(office, job3, 1)
    p = output.invoice_pdf(office, iid, str(tmp_path / "a.pdf"))
    doc = fitz.open(p)
    txt = "".join(pg.get_text() for pg in doc) + str(doc.metadata)
    for bad in ("AIA", "G702", "G703", "Application and Certificate for Payment",
                "Continuation Sheet"):
        assert bad not in txt
    assert output.SUMMARY_TITLE in txt


def _three_apps(office, job3):
    billing.set_contract(office, job3)
    for n in (1, 2, 3):
        billing.approve(office, billing.invoice_from_payapp(office, job3, n))


def test_12_1_retainage_held_this_period(office, job3):
    _three_apps(office, job3)
    held = [r["amount"] for r in office.db.rows(
        "SELECT amount FROM retainage_ledger WHERE kind = 'held' ORDER BY id")]
    assert held == [600_000, 900_000, 750_000]
    assert billing.retainage_outstanding(office, job3)["outstanding"] == 2_250_000
    assert sum(cents.to_cents(a["summary"]["5"]) for a in
               jobs.section(office, job3, "payapps")) == 4_350_000   # not this


def test_12_2_release_half(office, job3):
    _three_apps(office, job3)
    rid = billing.create_retainage_release(office, job3, pct="50",
                                           invoice_date="2026-11-20",
                                           note="substantial completion")
    inv = billing.invoice(office, rid)
    assert inv["number"] == "RET-0001" and inv["total"] == 1_125_000
    billing.approve(office, rid)
    r = billing.retainage_outstanding(office, job3)
    assert r["outstanding"] == 1_125_000
    payments.receive(office, inv["customer"], "2026-12-01", "11250.00",
                     applications=[(rid, "11250.00")])
    assert billing.retainage_outstanding(office, job3)["received"] == 1_125_000


def test_12_3_release_more_than_held(office, job3):
    _three_apps(office, job3)
    with pytest.raises(billing.BillingError, match=r"\$22,500.00"):
        billing.create_retainage_release(office, job3, amount="30000.00")


def seed_tm(office, job):
    """13.1: 2 carpenters 8 h + 2 h OT, 1 laborer 8 h with a skid steer
    4 h, $1,240.00 of materials, all on 2026-10-20."""
    billing.set_contract(office, job, material_markup="15", sub_markup="10",
                         contact_email="dana@example.test")
    billing.set_rate(office, job, "labor", "CARP", "85.00", "127.50", "170.00")
    billing.set_rate(office, job, "labor", "LAB", "62.00", "93.00", "124.00")
    billing.set_rate(office, job, "equipment", "SKID", rate="95.00")
    timeentry.add_labor_class(office, "CARP", "Carpenter", "40.00", "25")
    timeentry.add_labor_class(office, "LAB", "Laborer", "30.00", "25")
    approvals.set_path(office, "time_line", [approvals.step("jobrole:PM")],
                       job_id=job)
    ids = []
    for name in ("C1", "C2"):
        w = timeentry.add_worker(office, name, "CARP")
        ids.append(timeentry.add_line(office, w, "2026-10-20", job, "03-3000",
                                      "8"))
        ids.append(timeentry.add_line(office, w, "2026-10-20", job, "03-3000",
                                      "2", pay_type="OT"))
    w = timeentry.add_worker(office, "L1", "LAB")
    ids.append(timeentry.add_line(office, w, "2026-10-20", job, "03-3000", "8",
                                  equipment_code="SKID", equipment_hours="4"))
    timeentry.submit(office, ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, ids, "approve")
    office.act_as("admin@bo.test")
    m = ap_invoice(office, "Example Lumber", "HL-77", "2026-10-20", "1240.00",
                   job_id=job, code="03-3000", cat="M")
    approve_ap(office, m)
    return ids, m


def test_13_1_tm_invoice(office, job):
    seed_tm(office, job)
    office.db.set_counter("INV", 1002)
    pv = billing.tm_preview(office, job, "2026-10-20", "2026-10-20")
    amounts = {l["description"].split(":")[0]: l["amount"] for l in pv["lines"]}
    assert amounts["Labor CARP REG"] == 136_000
    assert amounts["Labor CARP OT"] == 51_000
    assert amounts["Labor LAB REG"] == 49_600
    labor = sum(l["amount"] for l in pv["lines"] if l["kind"] == "labor")
    assert labor == 236_600
    assert [l["amount"] for l in pv["lines"] if l["kind"] == "material"] == [124_000]
    assert [l["amount"] for l in pv["lines"] if l["kind"] == "markup"] == [18_600]
    assert [l["amount"] for l in pv["lines"] if l["kind"] == "equipment"] == [38_000]
    iid = billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20",
                                    change_ref="COR-002")
    inv = billing.invoice(office, iid)
    assert inv["number"] == "INV-1002" and cents.fmt(inv["total"]) == "$4,172.00"


def test_13_2_same_day_again_finds_nothing(office, job):
    seed_tm(office, job)
    office.db.set_counter("INV", 1002)
    billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")
    pv = billing.tm_preview(office, job, "2026-10-20", "2026-10-20")
    assert pv["lines"] == [] and pv["message"] == "already billed on INV-1002"
    with pytest.raises(billing.BillingError, match="already billed on INV-1002"):
        billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")


def test_13_3_void_frees_lines_keeps_number(office, job):
    seed_tm(office, job)
    office.db.set_counter("INV", 1002)
    iid = billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")
    billing.approve(office, iid)
    billing.void(office, iid, "2026-10-22", "wrong rates")
    reg = {i["number"]: i["status"] for i in billing.register(office)}
    assert reg["INV-1002"] == "Void"
    pv = billing.tm_preview(office, job, "2026-10-20", "2026-10-20")
    assert pv["total"] == 417_200
    again = billing.create_tm_invoice(office, job, "2026-10-20", "2026-10-20")
    assert billing.invoice(office, again)["number"] == "INV-1003"
