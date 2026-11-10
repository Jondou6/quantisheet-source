"""Chief's re-test of 6f57cd7 (message 0NTYGK2N, Nov 7) and Jon's two
invoice additions (sales tax rate 5834XDGT, card fee 7B67ZQ4K). Made-up
data only."""
import os

import fitz
import pytest

from app import settings
from app.service import agreements, invoice_route as IR, sage_ar, workorder
from r111_support import isolate, qapp, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _ticket(st, customer="Test Customer", call_type="call"):
    w = workorder.add(st, customer=customer, site="1 Test Lane",
                      complaint="No heat", call_type=call_type)
    workorder.add_time(st, w, "A Tester", "2", when="2026-11-02")
    workorder.add_part(st, w, "Test igniter", "1", cost="20",
                       price="45.50")                 # 200 + 45.50
    return w


def _store():
    st = workorder.blank()
    workorder.set_rates(st, "100", "40")
    return st


def _no_agreements():
    return agreements.blank()


# ---- sales tax (5834XDGT) --------------------------------------------------

def test_tax_rates_are_zero_and_six_to_ten_by_halves():
    assert workorder.TAX_RATES == ["0", "6.0", "6.5", "7.0", "7.5", "8.0",
                                   "8.5", "9.0", "9.5", "10.0"]
    assert workorder.tax_rate_text("0") == "No tax (0%)"
    assert workorder.tax_rate_text("7.0") == "7.0%"
    assert workorder.default_tax_rate() == "0"
    settings.set("service_tax_rate", "8.5")
    assert workorder.default_tax_rate() == "8.5"
    settings.set("service_tax_rate", "12")           # not on the list
    assert workorder.default_tax_rate() == "0"


def test_tax_line_in_cents_half_up_and_in_amount_due(tmp_path, monkeypatch):
    use_company(monkeypatch)
    st = _store()
    w = _ticket(st)
    inv = workorder.close_and_invoice(
        st, w, notes="Replaced the igniter.", when="2026-11-02",
        tax_rate="7.0", agreements_store=_no_agreements(),
        pdf_path=str(tmp_path / "inv.pdf"))
    # 245.50 x 7% = 17.185 -> 17.19 (half-up)
    assert inv["subtotal"] == "245.50" and inv["tax"] == "17.19"
    assert inv["tax_rate"] == "7.0" and inv["total"] == "262.69"
    tax = [ln for ln in inv["lines"] if ln.get("kind") == "tax"]
    assert tax and tax[0]["desc"] == "Sales tax (7.0%)"
    assert tax[0]["amount"] == "17.19"
    text = fitz.open(inv["pdf"])[0].get_text()
    for word in ("Subtotal", "Sales tax (7.0%)", "$17.19", "Amount due",
                 "$262.69"):
        assert word in text, word
    # a new default never changes a past invoice
    settings.set("service_tax_rate", "10.0")
    p2 = workorder.invoice_pdf(st, inv["id"], str(tmp_path / "again.pdf"))
    assert "Sales tax (7.0%)" in fitz.open(p2)[0].get_text()
    assert inv["total"] == "262.69"


def test_no_tax_says_so_and_adds_nothing(tmp_path, monkeypatch):
    use_company(monkeypatch)
    st = _store()
    w = _ticket(st)
    inv = workorder.close_and_invoice(
        st, w, notes="x", when="2026-11-02", tax_rate="0",
        agreements_store=_no_agreements(),
        pdf_path=str(tmp_path / "inv.pdf"))
    assert inv["tax"] == "0.00" and inv["total"] == "245.50"
    assert not [ln for ln in inv["lines"] if ln.get("kind")]
    assert "Sales tax (No tax (0%))" in fitz.open(inv["pdf"])[0].get_text()


def test_a_rate_off_the_list_is_refused():
    st = _store()
    w = _ticket(st)
    with pytest.raises(workorder.WorkOrderError, match="from the list"):
        workorder.set_payment(st, w, tax_rate="7.25")
    workorder.set_payment(st, w, tax_rate="7")         # 7 -> 7.0
    assert workorder.get(st, w)["tax_rate"] == "7.0"


# ---- card fee (7B67ZQ4K) ---------------------------------------------------

def test_card_fee_on_the_total_with_tax(tmp_path, monkeypatch):
    use_company(monkeypatch)
    st = _store()
    w = _ticket(st)
    inv = workorder.close_and_invoice(
        st, w, notes="x", when="2026-11-02", tax_rate="7.0", card=True,
        agreements_store=_no_agreements(),
        pdf_path=str(tmp_path / "inv.pdf"))
    # (245.50 + 17.19) x 3.5% = 9.19415 -> 9.19
    assert inv["card"] and inv["card_fee_pct"] == "3.5"
    assert inv["card_fee"] == "9.19" and inv["total"] == "271.88"
    fee = [ln for ln in inv["lines"] if ln.get("kind") == "card_fee"]
    assert fee[0]["desc"] == "Credit card service fee (3.5%)"
    text = fitz.open(inv["pdf"])[0].get_text()
    assert "Credit card service fee (3.5%)" in text and "$271.88" in text
    # profit is the work (245.50 less 80.00 labor cost and 20.00 parts),
    # not the tax or the fee
    assert inv["profit"] == "145.50"


def test_card_fee_rate_is_a_setting_kept_per_invoice():
    settings.set("service_card_fee_pct", "3")
    assert workorder.card_fee_pct() == "3"
    settings.set("service_card_fee_pct", "99")        # out of range
    assert workorder.card_fee_pct() == "3.5"
    st = _store()
    w = _ticket(st)
    inv = workorder.close_and_invoice(st, w, notes="x", when="2026-11-02",
                                      card=False, write_pdf=False,
                                      agreements_store=_no_agreements())
    assert not inv["card"] and inv["card_fee"] == "0.00"
    assert not [ln for ln in inv["lines"] if ln.get("kind") == "card_fee"]


def test_fee_and_tax_are_lines_of_their_own_in_every_export(tmp_path):
    st = _store()
    w = _ticket(st)
    inv = workorder.close_and_invoice(st, w, notes="x", when="2026-11-02",
                                      tax_rate="7.0", card=True,
                                      write_pdf=False,
                                      agreements_store=_no_agreements())
    rows, held = sage_ar.rows(st, [inv])
    assert not held
    descs = [r["desc"] for r in rows]
    assert "Sales tax (7.0%)" in descs
    assert "Credit card service fee (3.5%)" in descs
    got = []
    IR.send_backoffice(st, invoices=[inv], start=got.append)
    item = got[0]["service_invoices"][0]
    kinds = [ln["kind"] for ln in item["lines"]]
    assert kinds.count("tax") == 1 and kinds.count("card_fee") == 1
    assert item["total"] == "271.88"
    assert sum(float(ln["amount"]) for ln in item["lines"]) == \
        pytest.approx(271.88)
    out = IR.export_hh2(st, str(tmp_path / "hh2"), invoices=[inv],
                        again=True)
    import csv
    man = list(csv.reader(open(out["manifest"], encoding="utf-8-sig")))
    h = man[0]
    assert man[1][h.index("Sales Tax")] == "17.19"
    assert man[1][h.index("Card Fee")] == "9.19"
    assert man[1][h.index("Subtotal")] == "245.50"
    assert man[1][h.index("Amount")] == "271.88"


# ---- F6: member discount and auto-renew ------------------------------------

def _agreement(customer="Test Customer", **kw):
    ag = agreements.blank()
    agreements.add(ag, customer, "300", "2", "2027-06-01", site="1 Test Lane",
                   start="2026-06-01", **kw)
    return ag


def test_member_repair_gets_ten_percent_off_before_tax(tmp_path, monkeypatch):
    use_company(monkeypatch)
    st = _store()
    w = _ticket(st)
    ag = _agreement()
    assert ag["agreements"][0]["discount_pct"] == "10"
    assert ag["agreements"][0]["auto_renew"] is True
    inv = workorder.close_and_invoice(
        st, w, notes="x", when="2026-11-02", tax_rate="7.0", card=True,
        agreements_store=ag, pdf_path=str(tmp_path / "inv.pdf"))
    # 245.50 - 24.55 = 220.95; tax 15.4665 -> 15.47; fee 236.42 x 3.5%
    # = 8.2747 -> 8.27; due 244.69
    assert inv["discount"] == "24.55" and inv["discount_pct"] == "10"
    assert inv["tax"] == "15.47" and inv["card_fee"] == "8.27"
    assert inv["total"] == "244.69" and inv["agreement"] == "SA-0001"
    disc = [ln for ln in inv["lines"] if ln.get("kind") == "discount"]
    assert disc[0]["amount"] == "-24.55"
    assert "Member discount (10%)" in fitz.open(inv["pdf"])[0].get_text()


def test_no_discount_for_planned_visits_or_other_customers():
    st = _store()
    ag = _agreement()
    pm = _ticket(st, call_type="pm")
    other = _ticket(st, customer="Someone Else")
    for w in (pm, other):
        inv = workorder.close_and_invoice(st, w, notes="x",
                                          when="2026-11-02", write_pdf=False,
                                          agreements_store=ag)
        assert inv["discount"] == "0.00", inv["customer"]


def test_lapsed_or_cancelled_agreement_gives_no_discount():
    st = _store()
    ag = _agreement()
    agreements.cancel(ag, ag["agreements"][0]["id"])
    inv = workorder.close_and_invoice(st, _ticket(st), notes="x",
                                      when="2026-11-02", write_pdf=False,
                                      agreements_store=ag)
    assert inv["discount"] == "0.00"


def test_agreement_terms_can_be_set_and_auto_renew_rolls_the_term():
    ag = _agreement(discount_pct="12.5", auto_renew=False)
    a = ag["agreements"][0]
    assert a["discount_pct"] == "12.5" and a["auto_renew"] is False
    assert agreements.renew_due(ag, today="2027-06-02") == []
    agreements.set_terms(ag, a["id"], "10", True)
    assert agreements.renew_due(ag, today="2027-06-02") == ["SA-0001"]
    assert a["start"] == "2027-06-01" and a["renewal"] == "2028-06-01"
    assert len(agreements.visit_dates(a)) == 2       # next year's visits
    with pytest.raises(agreements.AgreementError):
        agreements.set_terms(ag, a["id"], "75")


def test_windows_have_the_new_controls(qapp):
    from app.service.agreements_ui import AgreementsWindow
    from app.service.workorder_ui import WorkOrderWindow
    w = WorkOrderWindow()
    try:
        assert w.tax.count() == len(workorder.TAX_RATES)
        assert w.tax.currentData() == "0"
        assert "credit card" in w.card.text().lower()
        assert "3.5%" in w.card.text()
    finally:
        w.close()
    a = AgreementsWindow()
    try:
        assert a.discount.text() == "10" and a.auto_renew.isChecked()
        heads = [a.table.horizontalHeaderItem(i).text()
                 for i in range(a.table.columnCount())]
        assert "Member discount" in heads and "Auto-renew" in heads
    finally:
        a.close()


# ---- F5: the summary uses the document's own words -------------------------

def test_made_up_expansions_are_taken_out():
    from app.ai import review
    src = ("SHEET A-101 FIRST FLOOR REFLECTED CEILING PLAN. RCP NOTES. "
           "SEE A-302 AND A-303. GWB = gypsum wall board")
    reply = ("- A-101 is the Roofing Construction Plan (RCP).\n"
             "- RCP (Reflected Ceiling Plan) notes.\n"
             "- GWB (Gypsum Wall Board).")
    out, removed = review.check_expansions(reply, src)
    assert "Roofing" not in out
    assert "Reflected Ceiling Plan" in out and "Gypsum Wall Board" in out
    assert removed == ["RCP = Roofing Construction Plan"]
    assert review.referenced_sheets(src, ["A-101"]) == ["A-302", "A-303"]


def test_summary_separates_sheets_in_the_set(monkeypatch):
    from app.ai import review
    seen = {}

    def fake(p, **k):
        seen["p"] = p
        return "- The RCP is the Roofing Construction Plan (RCP)."
    monkeypatch.setattr(review, "_ollama", fake)
    out = review.summarize_text(
        "[Page 1]\nA-101 REFLECTED CEILING PLAN RCP see A-302", False,
        "Reviewed the whole document.", ["A-101"])
    assert "Roofing" not in out.split("Taken out")[0]
    assert "Sheets in this set: A-101." in out
    assert "Referenced, not in this set: A-302." in out
    assert "Taken out" in out
    assert "Sheets in this set (from the title blocks): A-101" in seen["p"]
    assert "spell it out only" in seen["p"]


# ---- F8: each part to the cent ----------------------------------------------

def test_each_part_is_rounded_to_the_cent():
    from app import assemblies
    assert assemblies._cent(0.005) == 0.01
    assert assemblies._cent(2.675) == 2.68             # not float's 2.67
    assert assemblies._cent(-1.005) == -1.01


# ---- D3 (F8): each copy of a typical to the cent ----------------------------

def test_typical_copies_are_priced_each_to_the_cent():
    """Four individually rounded copies, not one 4-copy lump (Chief's
    re-test, Nov 7: the chiller row came out .69 where the hand check of
    four 100-ton copies gives .68)."""
    from app import annotate, assemblies
    d = fitz.open()
    d.new_page(width=800, height=600)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    first = annotate.new_op("add_count", 0, pt=[100, 100], n=1,
                            measure={"type": "count", "value": 1,
                                     "unit": "ea", "group": "Example Unit"})
    annotate.apply_op(d, first)
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=first["id"],
                                         multiplier=3))
    annotate.apply_op(d, annotate.new_op(
        "add_count", 0, pt=[300, 100], n=1,
        measure={"type": "count", "value": 1, "unit": "ea",
                 "group": "Example Unit"}))
    assemblies.set_job_assembly(d, {
        "name": "Example Unit", "measure": "count",
        "parts": [{"name": "Example part", "unit": "ea", "qty": "Count",
                   "cost": 0.125, "labor": 0.0, "fv": 2}]})
    rows, totals, errors = assemblies.rollup(d, book=None)
    assert not errors, errors
    row = {r["name"]: r for r in rows}["Example Unit"]
    assert row["quantity"] == pytest.approx(4)
    # each copy 0.125 -> 0.13; four copies 0.52 (one lump: 0.50)
    assert row["material"] == pytest.approx(0.52)


# ---- D6: retainage rows add up to the total ---------------------------------

def test_retainage_rows_add_up_to_the_total():
    from app import money
    d = fitz.open()
    d.new_page()
    money.set_info(d, 10, 10, project="Example Clinic", owner="Example Owner",
                   contractor="Example Builders")
    money.set_sov(d, [{"desc": f"Example line {k}", "scheduled": 1000}
                      for k in range(500)])
    no = money.new_pay_app(d, "2026-01-31")
    for item in [l["item"] for l in money.sov(d)]:
        money.set_progress(d, no, item, work=210.12)   # 21.012 each held
    v = money.compute(d, no)
    rows = v["rows"]
    held = sum(round(r["retainage"] * 100) for r in rows)
    assert held == round(v["totals"]["retainage"] * 100)
    assert v["totals"]["retainage"] == pytest.approx(10506.00)
    assert v["g702"]["5a"] == pytest.approx(10506.00)
    assert all(round(r["retainage"], 2) in (21.01, 21.02) for r in rows)


# ---- D4, D5: the work order preview and huge numbers ------------------------

def test_preview_is_replaced_not_piled_up(qapp):
    from app.service.workorder_ui import WorkOrderWindow
    w = WorkOrderWindow()
    try:
        w.customer.setText("Test Customer")
        w.site.addItem("1 Test Lane")
        w.site.setCurrentText("1 Test Lane")
        w.complaint.setText("No heat")
        w.tech.setText("A Tester")
        w.add_clicked()
        w.hours.setText("2")
        w.add_time_clicked()
        first = w.profit.text()
        for _ in range(20):
            w.card.setChecked(not w.card.isChecked())
        w.card.setChecked(False)
        assert w.profit.text() == first
        assert w.profit.text().count("amount due") == 1
        for _ in range(5):
            w.add_time_clicked()
        assert w.profit.text().count("amount due") == 1
    finally:
        w.close()


def test_absurd_amounts_get_a_plain_message(qapp):
    from app.service import files
    from app.service.workorder_ui import WorkOrderWindow
    with pytest.raises(files.FileError, match="too large"):
        files.money("1e29", "Labor price")
    with pytest.raises(files.FileError, match="too large"):
        files.qty("1e29", "Hours")
    w = WorkOrderWindow()
    try:
        w.customer.setText("Test Customer")
        w.site.addItem("1 Test Lane")
        w.site.setCurrentText("1 Test Lane")
        w.complaint.setText("No heat")
        w.tech.setText("A Tester")
        w.add_clicked()
        w.bill.setText("1e29")
        w.hours.setText("1")
        w.add_time_clicked()                  # no exception escapes
        assert "too large" in w.msg.text()
    finally:
        w.close()


# ---- D7: the card fee rate in Settings --------------------------------------

def test_service_settings_window_saves_the_card_fee(qapp):
    from app.service import settings_ui
    w = settings_ui.SettingsWindow()
    try:
        assert w.card_fee.text() == "3.5"
        w.card_fee.setText("3")
        w.tax.setCurrentIndex(w.tax.findData("7.0"))
        w.save_clicked()
        assert workorder.card_fee_pct() == "3"
        assert workorder.default_tax_rate() == "7.0"
        assert "Saved" in w.msg.text()
        w.card_fee.setText("abc")
        w.save_clicked()
        assert "percent" in w.msg.text()
        assert workorder.card_fee_pct() == "3"      # nothing half-saved
        assert w.close_button.text() == "Close"
    finally:
        w.close()
    with pytest.raises(settings_ui.SettingsError):
        settings_ui.save(card_fee_pct="11")
    settings_ui.save(discount_pct="12.5")
    assert str(agreements.defaults()["discount_pct"]) == "12.5"


# ---- D1: the summary with the real failures ----------------------------------

def test_summary_keeps_only_the_documents_own_abbreviations():
    from app.ai import review
    src = ("A-101 FLOOR PLAN. ET/FOLD DOWN EXAM TABLE. DS. GRAB BAR B-233, "
           "B-224. SEE A-302 AND A-303. RCP REFLECTED CEILING PLAN")
    reply = ("- ET (Electrical) outlets at each room; DS = Drywall.\n"
             "- The exam table (ET) folds down.\n"
             "- AHU - Air Handling Unit replaced on the roof.\n"
             "- RCP (Reflected Ceiling Plan).\n"
             "- The set includes A-302 and A-303.")
    out, removed = review.check_expansions(reply, src)
    assert "Electrical" not in out and "Drywall" not in out
    assert "exam table (ET)" in out and "Reflected Ceiling Plan" in out
    assert "AHU replaced on the roof" in out
    assert {"ET = Electrical", "DS = Drywall"} <= set(removed)
    refs = review.referenced_sheets(src, ["A-101"])
    assert refs == ["A-302", "A-303"]              # never B-233 / B-224
    marked = review._mark_referenced(out, refs)
    assert "A-302 (referenced, not in this set)" in marked
    assert review.referenced_sheets(src, []) == []


# ---- D9: Translate runs off the window's thread ------------------------------

def test_translate_runs_in_the_background(qapp, monkeypatch):
    import inspect
    from app import main_window
    src = inspect.getsource(main_window.MainWindow.translate_markups)
    assert "bg.run(lambda: review.run_cancellable(" in src
    assert "review.translate_texts, texts, language)" in src
    assert "QProgressDialog" in src and "Cancel" in src


def test_long_ai_reviews_can_be_stopped(qapp, monkeypatch):
    from app import bg
    from app.ai import dialogs, review
    monkeypatch.setattr(review, "TEXT_LIMIT", 600)
    doc = fitz.open()
    for i in range(12):
        doc.new_page().insert_textbox(fitz.Rect(72, 72, 540, 700),
                                      f"Example page {i + 1} " +
                                      "word " * 60, fontsize=9)
    d = dialogs.SpecCheckDialog(doc)
    calls = []
    runs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None:
                        runs.append((fn, ok)))

    def fake(text):
        calls.append(text)
        return [{"finding": "Example finding", "page": 1}]
    d._run(fake)
    assert d.stop_btn.isEnabled()
    fn, ok = runs.pop()
    ok(fn())                                     # part 1 done
    d.stop()
    fn, ok = runs.pop()
    ok(fn())                                     # the part in progress
    assert not runs                              # nothing more started
    assert "Stopped: 2 of" in d.status.text()
    assert not d.stop_btn.isEnabled()
