"""Nov 11, bidding phase F: fill a form from what QuantiSheet knows
(every value with where it comes from), sign only on request, keep the
signature protected, and record who signed. Made-up companies only."""
import csv
import datetime as dt
import json
import os
import sys

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (fillsign as F, money, proposal, settings,       # noqa: E402
                 sigstore)

SIG = {"w": 1.0, "h": 0.4, "strokes": [[[0.0, 0.2], [0.3, 0.0], [0.6, 0.4],
                                         [1.0, 0.1]], [[0.5, 0.2]]]}


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    proposal.save_company({"name": "Example Builders",
                           "address": "123 Example St\nExample City, SC "
                                      "29000", "phone": "555-0100",
                           "email": "office@example-builders.example",
                           "license": "G-12345"})


FIELDS = [("ProjectName", "Project name", "text"),
          ("Owner Name", "Owner", "text"),
          ("ContractorName", "Contractor", "text"),
          ("Contractor Address", "Address", "text"),
          ("Phone", "Phone", "text"),
          ("License No", "License no.", "text"),
          ("Taxpayer ID", "Taxpayer identification number", "text"),
          ("Text7", "Bank account number", "text"),
          ("Text8", "Printed name", "text"),
          ("Title", "Title", "text"),
          ("Name", "Name", "text"),
          ("Text11", "Favorite color", "text"),
          ("Retainage", "Retainage held", "text"),
          ("Sig1", "Signature", "text"),
          ("Date", "Date", "text"),
          ("Agree", "I agree", "check")]


def _form(path, prefill=None):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 50), "CONDITIONAL WAIVER (made-up form)", fontsize=14)
    y = 80
    for name, label, kind in FIELDS:
        p.insert_text((50, y + 13), label + ":", fontsize=9)
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX if kind == "check" \
            else fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(230, y, 245 if kind == "check" else 520, y + 18)
        if kind == "text":
            w.field_value = (prefill or {}).get(name, "")
        p.add_widget(w)
        y += 32
    d.save(str(path))
    d.close()
    return str(path)


def _job():
    job = fitz.open()
    job.new_page()
    money.set_info(job, project="Sample Tower", owner="Demo Holdings LLC")
    return job


def _rows(path, **kw):
    doc = fitz.open(path)
    try:
        return {r["name"]: r for r in F.propose(doc, F.known(**kw))}
    finally:
        doc.close()


# ---- what would be filled, and from where ------------------------------------

def test_every_value_says_where_it_comes_from(tmp_path):
    p = _form(tmp_path / "waiver.pdf")
    rows = _rows(p, job_doc=_job(), signer={"name": "Pat Morgan",
                                            "title": "Project Manager"})
    assert rows["ProjectName"]["value"] == "Sample Tower"
    assert "billing info" in rows["ProjectName"]["source"]
    assert rows["Owner Name"]["value"] == "Demo Holdings LLC"
    assert rows["ContractorName"]["value"] == "Example Builders"
    assert "company settings" in rows["ContractorName"]["source"]
    assert rows["Contractor Address"]["value"] == "123 Example St"
    assert rows["Phone"]["value"] == "555-0100"
    assert rows["License No"]["value"] == "G-12345"
    assert rows["Title"]["value"] == "Project Manager" and \
        rows["Title"]["source"] == "the signer you entered"
    for n in ("ProjectName", "Owner Name", "ContractorName", "Phone",
              "License No", "Title"):
        assert rows[n]["status"] == F.READY and rows[n]["tick"], n
    # every proposed value has a source
    assert all(r["source"] for r in rows.values() if r["value"] and
               r["status"] in (F.READY, F.UNSURE))


def test_unsure_fields_are_flagged_and_not_ticked(tmp_path):
    rows = _rows(_form(tmp_path / "w.pdf"), job_doc=_job(),
                 signer={"name": "Pat Morgan"})
    # a field named only "Name" could be anyone's
    assert rows["Name"]["status"] == F.UNSURE and not rows["Name"]["tick"]
    assert "more than one thing" in rows["Name"]["why"]
    # "Text8" says nothing; the words beside it do
    assert rows["Text8"]["status"] == F.UNSURE and \
        rows["Text8"]["value"] == "Pat Morgan" and \
        "words beside the field" in rows["Text8"]["why"]
    assert rows["Date"]["status"] == F.UNSURE and \
        rows["Date"]["value"] == dt.date.today().strftime("%m/%d/%Y")
    # nothing known, nothing guessed
    assert rows["Text11"]["status"] == F.BLANK and \
        rows["Text11"]["value"] == ""
    assert rows["Retainage"]["status"] == F.BLANK
    assert rows["Agree"]["status"] == F.BLANK and "Not a text field" in \
        rows["Agree"]["why"]
    assert "ready" in F.summary(list(rows.values()))


def test_tax_and_bank_numbers_are_never_filled(tmp_path):
    rows = _rows(_form(tmp_path / "w.pdf"), job_doc=_job(),
                 extra={"tax_id": ("12-3456789", "someone's notes")})
    for n in ("Taxpayer ID", "Text7"):
        assert rows[n]["status"] == F.NEVER and rows[n]["value"] == "" \
            and not rows[n]["tick"], n
    out, done = F.fill(_form(tmp_path / "w2.pdf"), [
        dict(r, tick=True) for r in rows.values()])
    vals = {w.field_name: w.field_value for w in fitz.open(out)[0].widgets()}
    assert vals["Taxpayer ID"] == "" and vals["Text7"] == ""
    assert "Taxpayer ID" not in done
    for word in ("ssn", "Social Security No", "EIN", "Routing number",
                 "Account #", "TIN"):
        assert F._NEVER.search(F._clean(word)), word
    assert not F._NEVER.search(F._clean("Printing"))


def test_a_form_about_a_sub_gets_the_subs_details_not_ours(tmp_path):
    sub = {"company": "Sample Piping LLC", "address": "9 Sample Way",
           "city": "Sampleton", "state": "SC", "zip": "29001",
           "phone": "555-0199", "license": "P-2201"}
    rows = _rows(_form(tmp_path / "w.pdf"), job_doc=_job(), contact=sub)
    assert rows["ContractorName"]["value"] == "Sample Piping LLC"
    assert rows["ContractorName"]["source"] == \
        "Company Directory: Sample Piping LLC"
    assert rows["Phone"]["value"] == "555-0199"
    # what the directory doesn't have is left blank, never ours
    rows = _rows(_form(tmp_path / "w3.pdf"),
                 contact={"company": "Sample Piping LLC"})
    assert rows["Phone"]["status"] == F.BLANK and \
        rows["License No"]["value"] == ""


def test_filled_fields_are_left_alone(tmp_path):
    p = _form(tmp_path / "w.pdf", {"ProjectName": "Typed By Hand"})
    rows = _rows(p, job_doc=_job())
    assert rows["ProjectName"]["status"] == F.HAS and \
        rows["ProjectName"]["value"] == "Typed By Hand"


# ---- filling -----------------------------------------------------------------

def test_fill_writes_only_ticked_rows_into_a_new_file(tmp_path):
    p = _form(tmp_path / "waiver.pdf")
    before = open(p, "rb").read()
    rows = _rows(p, job_doc=_job(), signer={"name": "Pat Morgan"})
    lst = list(rows.values())
    rows["Name"]["tick"] = True                    # the user ticked it
    out, done = F.fill(p, lst, values={rows["Name"]["id"]: "Pat Morgan"})
    assert out.endswith("waiver - filled.pdf") and os.path.isfile(out)
    assert open(p, "rb").read() == before          # the form is untouched
    vals = {w.field_name: w.field_value for w in fitz.open(out)[0].widgets()}
    assert vals["ProjectName"] == "Sample Tower" and \
        vals["ContractorName"] == "Example Builders"
    assert vals["Name"] == "Pat Morgan"            # typed over the proposal
    assert vals["Text8"] == "" and vals["Date"] == ""   # unsure, not ticked
    assert vals["Text11"] == ""
    assert done["ProjectName"] == "Sample Tower"
    out2, _d = F.fill(p, lst)
    assert out2.endswith("waiver - filled 2.pdf")  # never over a file


# ---- the signature -------------------------------------------------------------

def test_signature_is_kept_out_of_settings_and_moved_there(tmp_path):
    from app import signature
    settings.set("signature", dict(SIG))           # how it used to be kept
    assert signature.saved("signature") == SIG     # moved on first use
    assert settings.get("signature") is None
    raw = open(sigstore.path("signature"), "rb").read()
    assert os.path.isfile(sigstore.path("signature"))
    if sys.platform == "win32":
        assert raw.startswith(sigstore.MAGIC_DPAPI) and sigstore.protected()
        assert b"strokes" not in raw
        import base64
        assert b"strokes" not in base64.b64decode(
            raw[len(sigstore.MAGIC_DPAPI):])        # encrypted, not encoded
    assert "strokes" not in open(settings.PATH, encoding="utf-8").read()
    assert sigstore.load("signature") == SIG
    assert sigstore.load("initials") is None
    with pytest.raises(ValueError):
        sigstore.save("signature", {"strokes": []})
    with pytest.raises(ValueError):
        sigstore.save("stamp", SIG)
    # a damaged file is no signature, not a crash
    with open(sigstore.path("signature"), "wb") as f:
        f.write(sigstore.MAGIC_DPAPI + b"not really")
    assert sigstore.load("signature") is None
    sigstore.save("signature", SIG)
    sigstore.forget("signature")
    assert sigstore.load("signature") is None


def test_sign_only_a_signature_box_and_record_it(tmp_path):
    p = _form(tmp_path / "waiver.pdf")
    rows = _rows(p, job_doc=_job(), signer={"name": "Pat Morgan"})
    lst = list(rows.values())
    sig = rows["Sig1"]
    assert sig["status"] == F.SIGN and not sig["tick"]
    with pytest.raises(ValueError):
        F.sign(p, rows["ProjectName"], SIG, "Pat Morgan")   # not a sig box
    with pytest.raises(ValueError):
        F.sign(p, sig, None, "Pat Morgan")                  # nothing drawn
    with pytest.raises(ValueError):
        F.sign(p, sig, SIG, "  ")                           # nobody named
    assert not os.path.exists(tmp_path / "waiver - signed.pdf")
    before = open(p, "rb").read()
    when = dt.datetime(2026, 11, 11, 14, 30)
    dates = F.date_rows_for(lst, sig)
    assert [d["name"] for d in dates] == ["Date"]
    got = F.sign(p, sig, SIG, "Pat Morgan", date_rows=dates, when=when)
    assert open(p, "rb").read() == before
    assert got["path"].endswith("waiver - signed.pdf")
    assert got["before"] == F.sha256(p) and got["after"] == \
        F.sha256(got["path"]) and got["before"] != got["after"]
    doc = fitz.open(got["path"])
    # ink where the box is, and nowhere else new
    r = fitz.Rect(sig["rect"])
    ink = [d for d in doc[0].get_drawings()
           if fitz.Rect(d["rect"]).intersects(r)]
    assert ink and all(fitz.Rect(d["rect"]).y0 >= r.y0 - 30 and
                       fitz.Rect(d["rect"]).y1 <= r.y1 + 2 for d in ink)
    vals = {w.field_name: w.field_value for w in doc[0].widgets()}
    assert vals["Date"] == "11/11/2026" and vals["ProjectName"] == ""
    # the file's own audit trail
    from app.sign import embed
    trail = embed.read_audit(got["path"])
    assert trail.verify()
    e = trail.entries[-1]
    assert e.action == "signed" and e.actor == "Pat Morgan" and \
        e.detail["sha256_before"] == got["before"] and \
        "not a certificate" in e.detail["kind"]
    # ... and the log beside it
    with open(got["log"], encoding="utf-8", newline="") as f:
        log = list(csv.reader(f))
    assert os.path.basename(got["log"]) == F.LOG_NAME
    assert log[0][:3] == ["When", "Signed by", "File"]
    assert log[1][:4] == ["2026-11-11T14:30:00", "Pat Morgan",
                          "waiver - signed.pdf", "Sig1"]
    assert log[1][4] == got["before"] and log[1][5] == got["after"]
    # a second signing adds a line, never rewrites the first
    F.sign(got["path"], sig, SIG, "Lee Brooks", when=when)
    with open(got["log"], encoding="utf-8", newline="") as f:
        assert len(list(csv.reader(f))) == 3


# ---- the window -----------------------------------------------------------------

@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    said = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: said.append(a[2]) or 0))
    return said


def test_window_review_fill_then_sign_on_request(tmp_path, qt):
    from PySide6.QtCore import Qt
    from app import fillsign_ui as ui
    p = _form(tmp_path / "waiver.pdf")
    opened = []
    dlg = ui.FillSignDialog(p, None, _job(), [
        {"company": "Sample Piping LLC", "phone": "555-0199"}],
        on_open=opened.append)
    dlg.signer.setText("Pat Morgan")
    dlg.propose()
    t = dlg.table
    by = {r["name"]: i for i, r in enumerate(dlg.rows)}
    assert t.item(by["ProjectName"], ui.C_TICK).checkState() == Qt.Checked
    assert t.item(by["Name"], ui.C_TICK).checkState() == Qt.Unchecked
    assert "billing info" in t.item(by["ProjectName"], ui.C_SRC).text()
    assert t.item(by["Taxpayer ID"], ui.C_STATUS).text().startswith(
        "TYPE THIS YOURSELF")
    assert not (t.item(by["Taxpayer ID"], ui.C_TICK).flags() &
                Qt.ItemIsUserCheckable)
    assert "ready" in dlg.note.text() and not opened    # nothing written
    assert not os.path.exists(tmp_path / "waiver - filled.pdf")
    # the form is a sub's: their details, with the directory as the source
    dlg.who.setCurrentText("Sample Piping LLC")
    assert t.item(by["ContractorName"], ui.C_VALUE).text() == \
        "Sample Piping LLC"
    dlg.who.setCurrentText(ui.OURS)
    t.item(by["Phone"], ui.C_VALUE).setText("555-0111")  # typed over
    out = dlg.fill()
    assert opened == [out] and "your form was not changed" in dlg.note.text()
    vals = {w.field_name: w.field_value for w in fitz.open(out)[0].widgets()}
    assert vals["Phone"] == "555-0111" and vals["ProjectName"] == \
        "Sample Tower"
    # signing: a box must be selected, and it is that box only
    assert dlg.sign(strokes=SIG) is None and "Select a signature box" in \
        qt[-1]
    by = {r["name"]: i for i, r in enumerate(dlg.rows)}
    t.selectRow(by["Sig1"])
    dlg.signer.setText("")
    assert dlg.sign(strokes=SIG) is None and "signer's name" in qt[-1]
    dlg.signer.setText("Pat Morgan")
    got = dlg.sign(strokes=SIG)
    assert got["by"] == "Pat Morgan" and opened[-1] == got["path"]
    assert "not a certificate signature" in dlg.note.text() and \
        "Nothing was sent" in dlg.note.text()
    assert os.path.isfile(os.path.join(str(tmp_path), F.LOG_NAME))


def test_a_pdf_with_no_fields_says_so(tmp_path, qt):
    from app import fillsign_ui as ui
    d = fitz.open()
    d.new_page().insert_text((50, 60), "A flat form", fontsize=12)
    p = str(tmp_path / "flat.pdf")
    d.save(p)
    dlg = ui.FillSignDialog(p)
    assert dlg.table.rowCount() == 0 and "no fillable fields" in \
        dlg.note.text()
    assert not dlg.fill_btn.isEnabled() and not dlg.sign_btn.isEnabled()
