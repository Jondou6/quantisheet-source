"""Form Library: add, open a copy, clear, fill from the job."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import formlib, money, proposal, settings          # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _form(path, filled=True):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 60), "CHANGE ORDER", fontsize=16)
    y = 100
    for name, val in (("ProjectName", "Old Job" if filled else ""),
                      ("OwnerName", ""), ("ContractorName", ""),
                      ("ContractorAddress", ""), ("Date", ""),
                      ("Text20", "keep me" if filled else "")):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(150, y, 450, y + 18)
        w.field_value = val
        p.add_widget(w)
        y += 30
    c = fitz.Widget()
    c.field_name = "Owner"
    c.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    c.rect = fitz.Rect(150, y, 165, y + 15)
    c.field_value = filled
    p.add_widget(c)
    d.save(path)
    d.close()
    return path


def test_add_open_clear_and_fill(tmp_path):
    src = _form(str(tmp_path / "G701 Change Order.pdf"))
    e = formlib.add(src, "AIA Contract Administration", "AIA G701 Change "
                    "Order", "test")
    assert e["fields"] == 7 and e["filled"] == 3 and e["pages"] == 1
    assert os.path.exists(formlib.path_of(e))
    assert [x["name"] for x in formlib.entries()] == ["AIA G701 Change Order"]
    assert formlib.categories() == ["AIA Contract Administration"]
    # a copy: the library file stays as it was
    doc = formlib.open_copy(e, clear=True)
    vals = {w.field_name: w.field_value for w in doc[0].widgets()}
    assert vals["ProjectName"] == "" and vals["Text20"] == ""
    assert vals["Owner"] in (False, "Off")
    assert formlib.inspect(formlib.path_of(e))["filled"]
    # fill from the job and the company details
    proposal.save_company({"name": "Example Builders",
                           "address": "123 Example St\nExample "
                                      "City, SC 29000"})
    job = fitz.open()
    job.new_page()
    money.set_info(job, project="Shelter Cove", owner="City of MB")
    done = formlib.fill_from_job(doc, job)
    vals = {w.field_name: w.field_value for w in doc[0].widgets()}
    assert vals["ProjectName"] == "Shelter Cove"
    assert vals["OwnerName"] == "City of MB"
    assert vals["ContractorName"] == "Example Builders"
    assert vals["ContractorAddress"] == "123 Example St"
    assert vals["Date"] and len(done) == 5
    # without clearing, filled fields are left alone
    doc2 = formlib.open_copy(e)
    formlib.fill_from_job(doc2, job)
    assert {w.field_name: w.field_value for w in doc2[0].widgets()}[
        "ProjectName"] == "Old Job"


def test_manage_and_hand_dropped_files(tmp_path):
    e = formlib.add(_form(str(tmp_path / "a.pdf"), False), "Safety", "Report")
    formlib.update(e["id"], name="Incident Report", category="Field Forms")
    e2 = formlib.entries()[0]
    assert e2["name"] == "Incident Report" and \
        e2["category"] == "Field Forms" and os.path.exists(
            formlib.path_of(e2))
    # a PDF copied into the folder by hand shows up
    os.makedirs(os.path.join(formlib.folder(), "Bidding"))
    _form(os.path.join(formlib.folder(), "Bidding", "ITB.pdf"), False)
    names = {x["name"]: x for x in formlib.entries()}
    assert "ITB" in names and names["ITB"]["category"] == "Bidding"
    formlib.remove(e2["id"])
    assert [x["name"] for x in formlib.entries()] == ["ITB"]
    with pytest.raises(ValueError):
        formlib.add(str(tmp_path / "x.txt"), "General")


def test_new_from_form_in_the_app(qapp, win, tmp_path):
    from app.formlib_ui import FormLibraryDialog
    e = formlib.add(_form(str(tmp_path / "co.pdf")), "AIA", "AIA G701")
    money.set_info(win._view.doc, project="Main St Clinic")
    dlg = FormLibraryDialog(win, "plan.pdf")
    assert dlg.tree.topLevelItemCount() == 1
    assert dlg.clear.isChecked()                  # it has past entries
    assert "past job" in dlg.info.text()
    dlg.search.setText("nothing like this")
    assert dlg.tree.topLevelItemCount() == 0
    dlg.search.setText("")
    doc, filled = win.new_from_form((e, True, True))
    vals = {w.field_name: w.field_value for w in win._view.doc[0].widgets()}
    assert vals["ProjectName"] == "Main St Clinic"
    assert win._view.doc is doc and win._path is None
    assert formlib.inspect(formlib.path_of(e))["filled"]   # blank untouched
    done = win.fill_form()
    assert done == {} or isinstance(done, dict)
