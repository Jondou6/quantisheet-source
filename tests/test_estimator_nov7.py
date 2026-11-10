"""Chief's deep estimator test of 4235a254 (message 7ENXYYXJ, Nov 7): one
test per finding. Made-up data only."""
import csv
import decimal
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402

from r111_support import isolate, qapp, use_company            # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


# ---- 1 (HIGH): a counted driver was put in twice --------------------------

def _chiller():
    from app import assembly_csv
    with open(assembly_csv.CATALOG, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r["Assembly_ID"] == "A-HTL-23-CHILLER"]
    assert rows
    out, problems = assembly_csv.parse(rows)
    assert not problems
    return out[0]


def test_counted_driver_is_not_squared():
    from app import assemblies
    a = _chiller()
    install = next(p for p in a["parts"] if p["name"].startswith("Install"))
    assert install["qty"].count("Count") == 1, install["qty"]
    a = dict(a, props={"T": 100})
    # 1 chiller x3 typical, then 1 more: 6,400 hr in all (16 hr a ton)
    hours = sum(next(p["qty"] for p in assemblies.compute(a, {"count": n})
                     if p["name"].startswith("Install")) for n in (3, 1))
    assert hours == pytest.approx(6400)


def _bad_chiller():
    """The chiller as the bad parse saved it (driver in twice, no fv)."""
    import copy
    from app import assembly_csv
    with open(assembly_csv.CATALOG, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r["Assembly_ID"] == "A-HTL-23-CHILLER"]
    a = copy.deepcopy(assembly_csv.parse(rows, _buggy=True)[0][0])
    for p in a["parts"]:
        p.pop("fv", None)
    return a


def test_a_formula_saved_before_the_fix_is_put_right_once():
    """Chief's re-tests (F3, D2): only formulas the bad version saved are
    changed - once, by provenance - and nothing is rewritten at every
    calculation."""
    from app import assemblies, assembly_csv
    old = _bad_chiller()
    install = next(p for p in old["parts"] if p["name"].startswith("Install"))
    assert install["qty"].count("Count") == 2          # the bad formula
    assert assembly_csv.migrate(old) >= 1
    assert install["qty"].count("Count") == 1
    assert all(p["fv"] == assembly_csv.FORMULA_VERSION for p in old["parts"])
    assert assembly_csv.migrate(old) == 0               # once only
    old["props"] = {"T": 100}
    hrs = next(p["qty"] for p in assemblies.compute(old, {"count": 3})
               if p["name"].startswith("Install"))
    assert hrs == pytest.approx(4800)
    # an unversioned catalog formula the bad parse never produced stays
    # as written: (Count*(Count*T))*16 with Count 3, T 100 is 14,400
    mine = {"name": "Example", "source": "catalog", "props": {"T": 100},
            "parts": [{"name": "Install", "qty": "(Count*(Count*T))*16"}]}
    assert assembly_csv.migrate(mine) == 0
    assert assemblies.compute(mine, {"count": 3})[0]["qty"] == \
        pytest.approx(14400)
    # and compute never rewrites anything on its own
    raw = {"name": "Example", "props": {"T": 100}, "source": "catalog",
           "parts": [{"name": "Install", "qty": "(Count*(Count*T))*16"}]}
    assert assemblies.compute(raw, {"count": 3})[0]["qty"] == \
        pytest.approx(14400)
    assert all(p.get("fv") == assembly_csv.FORMULA_VERSION
               for p in _chiller()["parts"])


def test_a_job_saved_by_the_bad_version_is_migrated_on_read():
    from app import assemblies
    d = fitz.open()
    d.new_page()
    old = _bad_chiller()
    assemblies.set_job_assembly(d, old)
    job = assemblies.read_job(d)
    a = job["assemblies"][old["name"]]
    install = next(p for p in a["parts"] if p["name"].startswith("Install"))
    assert install["qty"].count("Count") == 1 and install["fv"] == 2


# ---- 2 (HIGH): Copy Back with the original open --------------------------

def test_copy_back_refused_cleanly_when_windows_holds_the_file(
        tmp_path, monkeypatch):
    from app import jobsafe
    orig = tmp_path / "share" / "Example.pdf"
    orig.parent.mkdir()
    d = fitz.open()
    d.new_page()
    d.save(str(orig))
    d.close()
    local = jobsafe.make_local_copy(str(orig), root=str(tmp_path / "loc"))
    real = os.replace

    def locked(a, b):
        if str(b) == str(orig):
            raise PermissionError(5, "Access is denied", str(b))
        return real(a, b)
    monkeypatch.setattr(jobsafe.os, "replace", locked)
    with pytest.raises(jobsafe.CopyBackError, match="open somewhere"):
        jobsafe.copy_back(local)
    assert not os.path.exists(str(orig) + ".qscopy")
    monkeypatch.setattr(jobsafe.os, "replace", real)
    assert jobsafe.copy_back(local) == str(orig)


def test_copy_back_closes_the_originals_tab_first(qapp, tmp_path,
                                                 monkeypatch):
    import make_sample
    from app import settings
    from app.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", None)
    for n in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    orig = str(tmp_path / "Example plan.pdf")
    make_sample.make(orig)
    w = MainWindow()
    try:
        assert w.open_path(orig)
        local = w.work_on_local_copy()
        assert local and local != orig
        assert w.open_path(orig)                 # the original again
        paths = [getattr(w.tabs.widget(i), "path", "")
                 for i in range(w.tabs.count())]
        assert orig in paths
        w.tabs.setCurrentIndex(paths.index(local))
        qapp.processEvents()
        out = w.copy_back_original()
        assert out == orig
        left = [getattr(w.tabs.widget(i), "path", "")
                for i in range(w.tabs.count())]
        assert orig not in left
        assert not os.path.exists(orig + ".qscopy")
    finally:
        for i in range(w.tabs.count()):
            v = getattr(w.tabs.widget(i), "view", None)
            if v is not None:
                v.dirty = False
        w.close()
        w.deleteLater()
        qapp.processEvents()


# ---- 3, 4: assembly-priced items are priced in every export ---------------

def _fake_job(monkeypatch):
    from app import assemblies, estimate
    rows = [{"name": "Example Wall Assembly", "trade": "Framing",
             "csi": "06 10 00", "measure": "length", "quantity": 100.0,
             "unit": "ft", "items": 1, "material": 1000.0,
             "labor_hours": 10.0, "labor_cost": 500.0, "total": 1500.0,
             "parts": []}]
    lines = [{"name": "Example Wall", "type": "length", "unit": "ft",
              "count": 1, "quantity": 100.0, "adjusted": 100.0,
              "waste": 0.0, "multiplier": 1.0, "unit_cost": 0.0,
              "total": 0.0, "pages": "1", "code": "", "cost_type": ""},
             {"name": "Example Curb", "type": "length", "unit": "ft",
              "count": 1, "quantity": 10.0, "adjusted": 10.0,
              "waste": 0.0, "multiplier": 1.0, "unit_cost": 0.0,
              "total": 0.0, "pages": "1", "code": "", "cost_type": ""}]
    monkeypatch.setattr(assemblies, "rollup",
                        lambda *a, **k: (list(rows), {}, []))
    monkeypatch.setattr(estimate, "lines", lambda *a, **k: list(lines))
    monkeypatch.setattr(assemblies, "read_job",
                        lambda doc: {"assemblies": {}})
    monkeypatch.setattr(assemblies, "library", lambda: {
        "Example Wall": {"name": "Example Wall Assembly"}})
    monkeypatch.setattr(assemblies, "find", lambda doc, n, job=None,
                        lib=None: (lib or {}).get(n))
    monkeypatch.setattr(assemblies, "any_known",
                        lambda doc, names: "Example Wall" in names)
    return rows, lines


def test_summary_does_not_list_assembly_priced_items_as_unpriced(
        monkeypatch):
    from app import estimate_export
    _fake_job(monkeypatch)
    doc = fitz.open()
    doc.new_page()
    s = estimate_export.summary(doc)
    assert s["total"] == decimal.Decimal("1500.00")
    names = [u["desc"] for u in s["unpriced"]]
    assert names == ["Example Curb"]                 # truly unpriced only


def test_estimate_csv_carries_the_assembly_price(monkeypatch, tmp_path):
    from app import estimate, estimate_lines
    _fake_job(monkeypatch)
    monkeypatch.setattr(estimate, "annotate", estimate.annotate)
    monkeypatch.setattr(estimate_lines, "priced", lambda *a, **k: [])
    monkeypatch.setattr(estimate, "set_items", lambda doc: [])
    monkeypatch.setattr(estimate.annotate, "totals_items", lambda doc: [])
    doc = fitz.open()
    doc.new_page()
    out = str(tmp_path / "est.csv")
    estimate.export_csv(doc, out)
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    head = rows[0]
    wall = next(r for r in rows if r and r[0] == "Example Wall")
    assert wall[head.index("Priced By")] == \
        "Assembly: Example Wall Assembly"
    assert wall[head.index("Total")] == ""            # not a false 0
    assert ["Assembly Lines"] in rows
    grand = next(r for r in rows if r and r[0] == "Grand Total")
    assert float(grand[9]) == 1500.0


# ---- 5, 7: the customer's invoice and work order --------------------------

def _closed_ticket():
    from app.service import workorder
    store = workorder.blank()
    workorder.set_rates(store, "100", "40")
    wid = workorder.add(store, customer="Test Smith", site="1 Test Lane",
                        complaint="No cooling")
    workorder.add_time(store, wid, "A Tester", "2")
    workorder.no_parts(store, wid)
    return store, wid


def test_invoice_has_terms_due_date_tax_and_remit_to(home, monkeypatch,
                                                     tmp_path):
    from app.service import workorder
    from app import settings
    comp = use_company(monkeypatch)
    store, wid = _closed_ticket()
    inv = workorder.close_and_invoice(
        store, wid, notes="Example notes.", when="2026-11-02",
        pdf_path=str(tmp_path / "inv.pdf"))
    text = fitz.open(inv["pdf"])[0].get_text()
    for word in ("Terms", "Net 30", "Due date", "2026-12-02", "Sales tax",
                 "Amount due", "Remit to", comp["name"], "9 Test Ave",
                 "INV-0001"):
        assert word in text, word
    settings.set("service_invoice_terms_days", 0)
    assert workorder.terms_text() == "Due on receipt"
    assert workorder.terms_text(15) == "Net 15"
    # the invoice keeps the terms it was made with
    assert inv["terms_days"] == 30


def test_customer_work_order_has_no_cost_or_profit(home, monkeypatch,
                                                   tmp_path):
    from app.service import workorder
    use_company(monkeypatch)
    store, wid = _closed_ticket()
    p = workorder.print_work_order(store, wid, str(tmp_path / "wo.pdf"))
    text = "".join(pg.get_text() for pg in fitz.open(p))
    assert "Profit" not in text and "Cost " not in text
    p = workorder.print_work_order(store, wid, str(tmp_path / "wo2.pdf"),
                                   office=True)
    text = "".join(pg.get_text() for pg in fitz.open(p))
    assert "Office copy" in text and "Profit" in text


def test_missing_company_is_named(home, monkeypatch):
    from app.service import workorder
    use_company(monkeypatch, {"name": "", "address": ""})
    assert workorder.missing_company() == ["name", "address"]


# ---- 6: backflow ----------------------------------------------------------

def test_backflow_repair_column_is_a_note_per_part(home, qapp):
    from app.service import backflow
    from app.service.backflow_ui import BackflowWindow
    w = BackflowWindow()
    try:
        assert set(w.repairs) == {pid for pid, _l, _k in backflow.POINTS}
        assert not any(phase == "repair" for (_p, phase, _w) in w.boxes)
        assert not any(phase == "repair" for (_p, phase) in w.psis)
        w.repairs["c1"].setText("Replaced the example spring")
        rep = w.report()
        assert rep["c1_repair_note"] == "Replaced the example spring"
    finally:
        w.close()


def test_long_comments_get_a_taller_box(tmp_path):
    from app.service import backflow
    short = backflow._box_height("ok", 540, 28)
    long = backflow._box_height("Example comment. " * 60, 540, 28)
    assert short == 28 and long > 60
    rep = backflow.empty_report()
    rep.update(comments="Example comment that runs on. " * 40,  # 1,200

               test_date="2026-11-02")
    p = backflow.write_pdf(rep, str(tmp_path / "bf.pdf"), comp={})
    with fitz.open(p) as d:
        w = next(x for pg in d for x in pg.widgets()
                 if x.field_name == "comments")
        assert w.rect.height >= long - 1


def test_one_line_district_box_never_wraps_onto_the_rule():
    from app.service import district_form as DF
    doc = fitz.open()
    page = doc.new_page()
    box = fitz.Rect(50, 50, 150, 64)                       # one line
    ok, size = DF._put(page, box, "Example short text")
    assert ok
    lines = {round(b[1]) for b in page.get_text("words")}
    assert len(lines) == 1
    ok, _s = DF._put(page, fitz.Rect(50, 100, 90, 114),
                     "A much longer example that cannot fit on one line")
    assert not ok
    doc.close()


# ---- 8 and 13 are ClaimIT: quantisheet_claims/tests/test_nov7_payments.py


# ---- 9, 10, 11, 12: billing words, cents, percents ------------------------

def test_billing_errors_are_in_words():
    from app.billing_ui import friendly
    t = friendly(ValueError("could not convert string to float: 'abc'"))
    assert t == '"abc" isn\'t a number. Type a number, such as 1250.00.'
    assert "float" not in t
    assert friendly(ValueError("The example is closed.")) == \
        "The example is closed."


def test_pay_app_excel_is_in_cents(monkeypatch, tmp_path):
    from app import acrobat, money
    noisy = 3516.3500000000004
    g = {k: noisy for k, _l in money.G702_LINES}
    row = {"item": "1", "csi": "", "desc": "Example", "scheduled": noisy,
           "previous": 0.1 + 0.2, "this": noisy, "stored": 0.0,
           "completed": noisy, "percent": 33.333, "balance": noisy,
           "retainage": noisy}
    v = {"no": 1, "period_to": "2026-11-30", "status": "draft",
         "g702": g, "rows": [row], "totals": dict(row)}
    monkeypatch.setattr(money, "compute", lambda doc, no: v)
    got = {}
    monkeypatch.setattr(acrobat, "write_xlsx",
                        lambda path, sheets: got.update(dict(sheets)))
    money.pay_app_xlsx(None, 1, str(tmp_path / "p.xlsx"))
    cells = [c for r in got["Summary"] + got["Detail"] for c in r
             if isinstance(c, float)]
    assert 3516.35 in cells and 0.3 in cells
    assert all(round(c, 2) == c for c in cells)


def test_percent_complete_never_hides_a_little_work():
    from app import money
    assert money._pct(0) == "0%"
    assert money._pct(0.4) == "0.4%"
    assert money._pct(5) == "5.0%"
    assert money._pct(62.6) == "63%"


def test_zero_location_adjustment_is_not_printed(monkeypatch):
    from app import estimate_lines
    monkeypatch.setattr(estimate_lines, "location_adjustment",
                        lambda *a: {"total": decimal.Decimal("0.00"),
                                    "lines": []})
    assert estimate_lines.location_lines(1000, 500, 500, 0, "Example") == []


def test_part_cents_add_up_the_same_in_every_format():
    from app.proposal import _split_cents
    amounts = [799.594, 2333.275, 414.4949, 0.333, 0.333, 0.334]
    total = sum(amounts)
    c = _split_cents(amounts, total)
    assert sum(c) == round(total * 100)
    assert all(abs(x - a * 100) < 1 for x, a in zip(c, amounts))
    assert _split_cents([], 0) == []
    assert sum(_split_cents([1.005, 2.005], 3.01)) == 301


# ---- 14: the work order message follows what was done ---------------------

def test_work_order_message_after_time_and_parts(home, qapp):
    from app.service import workorder
    from app.service.workorder_ui import WorkOrderWindow
    w = WorkOrderWindow()
    try:
        w.customer.setText("Test Smith")
        w.site.addItem("1 Test Lane")
        w.site.setCurrentText("1 Test Lane")
        w.complaint.setText("No cooling")
        w.tech.setText("A Tester")
        w.add_clicked()
        assert w.msg.text() == "Ticket opened."
        w.hours.setText("1.5")
        w.add_time_clicked()
        assert "Ticket opened" not in w.msg.text()
        assert "1.5 hr" in w.msg.text() and "Ticket now" in w.msg.text()
        w.no_parts_clicked()
        assert "no parts" in w.msg.text()
    finally:
        w.close()


# ---- 15: Ctrl+Shift+Z is Redo ----------------------------------------------

def test_redo_keys(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from app import settings
    from app.main_window import MainWindow
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", None)
    w = MainWindow()
    try:
        redo = [s.toString() for s in w._redo_act.shortcuts()]
        undo = [s.toString() for s in w._undo_act.shortcuts()]
        assert "Ctrl+Shift+Z" in redo and "Ctrl+Y" in redo
        assert "Ctrl+Shift+Z" not in undo and undo == ["Ctrl+Z"]
        others = [a for a in w.findChildren(type(w._redo_act))
                  if a is not w._redo_act and
                  QKeySequence("Ctrl+Shift+Z") in a.shortcuts()]
        assert not others
    finally:
        w.close()
        w.deleteLater()


# ---- 16: labels that were cut off ------------------------------------------

def test_long_labels_wrap_and_page_label_fits(qapp):
    from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout
    from app.estimating.ui import wrap_long_labels, EstimatingTools
    host = QWidget()
    lay = QVBoxLayout(host)
    long = QLabel("An example sentence that is long enough to need "
                  "wrapping in a narrow window.")
    short = QLabel("Short")
    lay.addWidget(long)
    lay.addWidget(short)
    wrap_long_labels(host)
    assert long.wordWrap() and not short.wordWrap()
    t = EstimatingTools(None, None)
    try:
        lab = next(x for x in t.findChildren(QLabel) if x.text() == "&Page:")
        assert lab.minimumWidth() >= lab.fontMetrics().horizontalAdvance(
            "Page:")
        om = [x for x in t.findChildren(QLabel) if "M years" in x.text()]
        assert om and all("O&&M" in x.text() for x in om)
    finally:
        t.close()


def test_redact_and_sheet_setup_text_wraps(qapp):
    from app.acrobat_dialogs import RedactDialog
    from app.sheets_dialog import SheetSetupDialog
    doc = fitz.open()
    doc.new_page()
    r = RedactDialog(doc)
    assert r.result.wordWrap() and r.note.wordWrap()
    s = SheetSetupDialog([], None)
    assert s.intro.wordWrap()


# ---- 17, 18: the local AI says what it read --------------------------------

def _parts(n, size):
    return [f"[Page {i + 1}]\n" + "x" * size for i in range(n)]


def test_long_documents_are_reviewed_in_parts():
    from app.ai import review
    parts = _parts(687, 2600)
    ch = review.chunks(parts, limit=review.TEXT_LIMIT)
    assert ch[0][1] == 0 and ch[-1][2] == 686
    covered = [p for _t, a, b in ch for p in range(a, b + 1)]
    assert covered == list(range(687))                    # every page once
    assert all(len(t) <= review.TEXT_LIMIT for t, _a, _b in ch)
    note = review.range_note(parts, 0, ch[0][2], 1)
    assert note.startswith("Pages 1-") and "of 687" in note
    assert "%" in note
    whole = review.range_note(parts, 0, 686, len(ch))
    assert whole.startswith("The whole document (687 pages)")
    assert f"in {len(ch)} parts" in whole and "a while" in whole
    # a page longer than the limit is split, never cut (Chief, Nov 7: a
    # 36,036-character page lost its tail and was called "whole")
    page = "[Page 1]\n" + "".join(f"w{k:05d} " for k in range(6006))
    big = review.chunks([page], limit=24000)
    assert len(big) == 2
    assert all(len(t) <= 24000 for t, _a, _b in big)
    assert "".join(t.split("]\n", 1)[1] for t, _a, _b in big) == page
    assert big[0][0].startswith("[Page 1, piece 1 of 2]")
    assert review.range_note([page], 0, 0, len(big)).startswith(
        "The whole document (1 page), in 2 parts")


def test_summary_says_what_it_read_and_that_it_is_a_draft(monkeypatch):
    from app.ai import review
    seen = {}
    monkeypatch.setattr(review, "_ollama",
                        lambda p, **k: seen.setdefault("p", p) and "- x")
    out = review.summarize_text("[Page 1]\nexample", False,
                                "Reviewed the whole document (9 characters).")
    assert out.startswith("Reviewed the whole document")
    assert "check it against the drawings" in out
    assert "never guess" in seen["p"]


def test_spec_check_runs_every_part_and_reports_coverage(qapp, monkeypatch):
    from app import bg
    from app.ai import dialogs, review
    monkeypatch.setattr(review, "TEXT_LIMIT", 600)
    doc = fitz.open()
    for i in range(12):
        doc.new_page().insert_textbox(fitz.Rect(72, 72, 540, 700),
                                      f"Example page {i + 1} " +
                                      "word " * 60, fontsize=9)
    calls = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None:
                        ok(fn()))
    d = dialogs.SpecCheckDialog(doc)
    d.first.setValue(1)
    d.last.setValue(12)
    assert "whole document" in d.range_label.text().lower()

    def fake(text):
        calls.append(text)
        return [{"finding": f"Example finding {len(calls)}", "page": 1}]
    d._run(fake)
    assert len(calls) > 1                           # more than one part
    assert d.table.rowCount() == len(calls)
    assert "Reviewed: The whole document (12 pages)" in d.status.text()


def test_find_rfis_says_what_it_checked():
    from app.ai import rfi_rules
    plans = [(0, "A-101", "Plan", "Example text " * 10), (1, "", "", "")]
    t = rfi_rules.coverage_text(plans, 0)
    assert "Checked 2 page(s)" in t and "page 2" in t and "OCR" in t
    assert "doesn't mean" in t


# ---- 19: every window can be closed with the mouse ------------------------

def test_dialogs_get_a_close_button(qapp):
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                   QPushButton, QVBoxLayout, QFormLayout)
    from app import closebutton
    bare = QDialog()
    QVBoxLayout(bare).addWidget(QLabel("Example"))
    b = closebutton.ensure(bare)
    assert b is not None and b.text() == "Close"
    assert closebutton.ensure(bare) is None               # once only
    form = QDialog()
    QFormLayout(form).addRow("Example", QLabel("x"))
    assert closebutton.ensure(form) is not None
    has = QDialog()
    lay = QVBoxLayout(has)
    lay.addWidget(QDialogButtonBox(QDialogButtonBox.Ok))
    assert closebutton.ensure(has) is None
    own = QDialog()
    QVBoxLayout(own).addWidget(QPushButton("Cancel"))
    assert closebutton.ensure(own) is None
    bare.show()
    qapp.processEvents()
    b.click()
    qapp.processEvents()
    assert not bare.isVisible()


def test_company_directory_and_project_center_close(home, qapp):
    from app.subdir_ui import DirectoryDialog
    d = DirectoryDialog()
    assert d.close_button is not None and d.close_button.text() == "Close"
    src = open(os.path.join(ROOT, "app", "pm", "center.py"),
               encoding="utf-8").read()
    assert 'self.close_btn = QPushButton("Close")' in src
    assert 'QShortcut(QKeySequence("Ctrl+W"), self, self.close)' in src
    with open(os.path.join(ROOT, "app", "dialog_fit.py"),
              encoding="utf-8") as fh:
        assert "closebutton.ensure(obj)" in fh.read()


def test_estimate_csv_does_not_open_the_price_database(monkeypatch,
                                                       tmp_path, home):
    """No takeoff group has an assembly: no roll-up, so no price database
    is made (the practice job keeps everything in its sandbox)."""
    from app import assemblies, pricedb
    doc = fitz.open()
    doc.new_page()
    assert not os.path.exists(pricedb.path())
    assert assemblies.any_known(doc, ["Example Unknown Group"]) is False
    assert not os.path.exists(pricedb.path())
    name = next(iter(assemblies.BUILT_IN))["name"]
    assert assemblies.any_known(doc, [name]) is True
    assert not os.path.exists(pricedb.path())


def test_district_data_sheet_keeps_long_comments_on_the_page(tmp_path):
    """Chief's re-test (F4): a 2,000-character comment was cut after about
    80 characters and a long line ran off the page."""
    from app.service import backflow
    words = " ".join(f"example{k:04d}" for k in range(160))     # 1,919
    rep = backflow.empty_report()
    rep.update(comments=words, test_date="2026-11-02",
               repair_materials="X" * 300)
    p = backflow.write_data_sheet(rep, str(tmp_path / "data.pdf"))
    with fitz.open(p) as d:
        text = " ".join(pg.get_text() for pg in d)
        for pg in d:
            for b in pg.get_text("words"):
                assert b[2] <= pg.rect.width - 20, b      # inside the page
    flat = " ".join(text.split())
    assert "example0000" in flat and "example0159" in flat
    assert flat.count("X") >= 300
