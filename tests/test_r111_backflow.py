"""Backflow test report: our own layout, fillable fields, annual due date."""
import os

import fitz
import pytest

from app.service import backflow, pdfdoc
from r111_support import COMPANY, isolate, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_source_names_no_outside_organization():
    src = open(backflow.__file__, encoding="utf-8").read().lower()
    for word in ("purveyor", "water department", "city of", "utility",
                 "acme", "your company"):
        assert word not in src
    assert "proposal.company" in src or "proposal" in src


def test_filled_from_the_service_record_and_due_in_one_year(tmp_path, monkeypatch):
    use_company(monkeypatch)
    rec, prop, eq = records()
    report = backflow.from_service(rec, prop, eq, test_date="2026-04-01")
    assert report["acct_name"] == "Test Smith"
    assert report["acct_address"] == "1 Test St"
    assert report["dev_name"] == "Furnace"
    assert report["dev_model"] == "TF-80"
    assert report["dev_serial"] == "SN-TEST-1"
    assert report["cert_company"] == "Test Plumbing Co"
    assert report["cert_phone"] == "555-0100"
    assert report["next_due"] == "2027-04-01"
    leap = backflow.from_service(rec, prop, test_date="2024-02-29")
    leap["dev_name"] = "Assembly"
    assert leap["next_due"] == "2025-02-28"
    report.update({
        "dev_size": "2", "dev_application": "Domestic",
        "dev_location": "Mechanical room", "acct_no": "ACCT-19",
        "meter_no": "M-19", "c1_before_tight": True, "c1_before_leaked": False,
        "c1_before_psi": "1.4", "c2_after_leaked": True,
        "rv_before_psi": "2.0", "so1_before_tight": True,
        "repair_materials": "Test check kit", "tester": "A Tester",
        "cert_no": "BF-77", "category": "General",
        "method": "Differential", "kit": "Differential gauge",
        "signature": "A Tester", "comments": "Held tight.",
    })
    path = backflow.write_pdf(report, str(tmp_path / "bf.pdf"))
    fields = pdfdoc.read_fields(path)
    assert fields["acct_name"] == "Test Smith"
    assert fields["dev_serial"] == "SN-TEST-1"
    assert fields["dev_application"] == "Domestic"
    assert fields["c1_before_psi"] == "1.4"
    assert fields["rv_before_psi"] == "2.0"
    assert fields["repair_materials"] == "Test check kit"
    assert fields["category"] == "General"
    assert fields["method"] == "Differential"
    assert fields["kit"] == "Differential gauge"
    assert fields["signature"] == "A Tester"
    assert fields["next_due"] == "2027-04-01"
    assert str(fields["c1_before_leaked"]).lower() in ("off", "no", "")
    assert str(fields["c1_before_tight"]).lower() not in ("off", "no", "")
    with fitz.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
        kinds = {}
        choices = {}
        for page in doc:
            for w in page.widgets() or []:
                kinds[w.field_name] = w.field_type
                if w.field_name == "dev_application":
                    choices = list(w.choice_values or [])
    assert "Test Plumbing Co" in text
    assert "555-0100" in text
    assert "Customer & Site" in text
    assert "Test Results" in text
    assert "Certification" in text
    assert "Closed tight" in text
    assert kinds["c1_before_leaked"] == fitz.PDF_WIDGET_TYPE_CHECKBOX
    assert kinds["c1_before_tight"] == fitz.PDF_WIDGET_TYPE_CHECKBOX
    assert kinds["so2_after_tight"] == fitz.PDF_WIDGET_TYPE_CHECKBOX
    assert kinds["dev_application"] == fitz.PDF_WIDGET_TYPE_COMBOBOX
    assert kinds["method"] == fitz.PDF_WIDGET_TYPE_COMBOBOX
    assert kinds["kit"] == fitz.PDF_WIDGET_TYPE_COMBOBOX
    for word in ("Domestic", "Fire Line", "Irrigation", "Other"):
        assert word in choices
    # header came from proposal.company(), not a name baked into the module
    assert COMPANY["name"] not in open(backflow.__file__, encoding="utf-8").read()


def test_window_saves_and_prints(qapp, tmp_path, monkeypatch):
    use_company(monkeypatch)
    from app.estimating import service
    from app.service.backflow_ui import BackflowWindow
    rec, _prop, _eq = records()
    service.save(rec)
    win = BackflowWindow()
    win.site.setCurrentIndex(1)
    win.fill_clicked()
    assert win.acct.text() == "Test Smith"
    assert win.company.text() == "Test Plumbing Co"
    win.dev_name.setText(win.dev_name.text() or "Furnace")
    win.test_date.setText("2026-05-02")
    win.tester.setText("A Tester")
    win.category.setCurrentText("Limited")
    win.method.setCurrentText("Direction of flow")
    win.kit.setCurrentText("Vertical tube")
    rid = win.save_clicked()
    assert rid
    assert win.next_due.text() == "2027-05-02"
    path = win.print_to(str(tmp_path / "bf-window.pdf"))
    assert path and os.path.isfile(path)
    fields = pdfdoc.read_fields(path)
    assert fields["next_due"] == "2027-05-02"
    assert fields["method"] == "Direction of flow"
    win.close()


def test_data_sheet_for_the_district_form(tmp_path):
    """Review 2 (Nov 4): districts want their own form - one page with
    every value to copy onto it."""
    import fitz
    from app.service import backflow
    rep = backflow.empty_report()
    rep.update(dev_name="Example Valve Co", dev_serial="EX-123",
               dev_size='3/4"', test_date="2026-10-20", tester="A. Example",
               cert_no="T-0001", c1_before_tight=True, c1_before_psi="5.2",
               c1_repair_note="Replaced check 1 disc")
    lines = backflow.data_sheet_lines(rep)
    vals = {lab: v for _s, lab, v in lines}
    assert vals["Serial no."] == "EX-123"
    assert vals["Next test due"] == "2027-10-20"
    assert "5.2 psi" in vals["Check 1 - Before repairs"]
    assert vals["Check 1"] == "Replaced check 1 disc"
    out = backflow.write_data_sheet(rep, str(tmp_path / "d.pdf"))
    text = fitz.open(out)[0].get_text()
    assert "EX-123" in text and "not that form" in text
