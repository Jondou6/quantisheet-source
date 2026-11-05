"""Help > Report an Issue (Nov 3): words + screenshot + drawing facts in
an email to support that the tester sends; the drawing only if ticked."""
import json
import os
import zipfile

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QMessageBox          # noqa: E402

import make_sample                                                # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import app.main as main_mod
    from app import mail, settings
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "quantisheet.log").write_text(
        "INFO start\nINFO user someone@example.com opened a set\n",
        encoding="utf-8")
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(logs))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    box = []
    monkeypatch.setattr(mail, "OUTBOX", box)
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    pdf = str(tmp_path / "plan.pdf")
    make_sample.make(pdf)
    return tmp_path, pdf, box


def test_facts_have_no_content(setup):
    from app import issue_report
    _tmp, pdf, _box = setup
    doc = fitz.open(pdf)
    f = issue_report.doc_facts(doc, pdf)
    assert f["pages"] == doc.page_count and f["file_mb"] >= 0
    assert sum(f["sheets"].values()) == doc.page_count
    words = doc[0].get_text("words")
    blob = json.dumps(f)
    assert not any(w[4] in blob for w in words if len(w[4]) > 5)
    assert issue_report.doc_facts(None) == {"pages": 0}
    assert "Pages:" in issue_report.facts_text(f)


def test_build_and_email(setup):
    from app import issue_report
    tmp, pdf, box = setup
    doc = fitz.open(pdf)
    z, att, facts = issue_report.build(
        "Page 4 stayed white", b"\x89PNGfake", doc=doc, doc_path=pdf,
        attach_doc=False, view_page=3, folder=str(tmp / "rep"))
    assert facts["page_on_screen"] == 4
    names = zipfile.ZipFile(z).namelist()
    for n in ("what_happened.txt", "drawing_facts.json", "version.txt",
              "screenshot.png"):
        assert n in names
    assert any(n.startswith("support/") for n in names)
    assert pdf not in att and len(att) == 2
    log = "".join(zipfile.ZipFile(z).read(n).decode("utf-8", "replace")
                  for n in names if n.startswith("support/"))
    assert "someone@example.com" not in log
    _z, att2, _f = issue_report.build("x", None, doc=doc, doc_path=pdf,
                                      attach_doc=True,
                                      folder=str(tmp / "rep2"))
    assert pdf in att2 and len(att2) == 2
    how = issue_report.open_email(issue_report.message(
        "Page 4 stayed white", facts, att))
    assert how == "captured"
    m = box[-1]
    assert m["to"] == [issue_report.SUPPORT_EMAIL]
    assert m["subject"].startswith("QuantiSheet issue: Page 4")
    assert "About the drawing" in m["body"] and m["attachments"] == att


def test_dialog_from_help_menu(setup, qapp):
    from app.main_window import MainWindow
    _tmp, pdf, box = setup
    w = MainWindow()
    w.resize(1000, 700)
    assert w.open_path(pdf)
    qapp.processEvents()
    acts = [a.text() for m in w.menuBar().actions() if m.menu()
            for a in m.menu().actions()]
    assert "Report an Issue…" in acts
    from app import issue_report_ui
    dlg = issue_report_ui.open_dialog(w, "", show=False)
    assert dlg.shot is not None and not dlg.shot.isNull()
    assert not dlg.attach.isChecked() and dlg.attach.isEnabled()
    assert dlg.send() is None and not box          # needs words first
    dlg.text.setPlainText("Clicked print and it froze")
    assert dlg.send() == "captured"
    m = box[-1]
    assert any(a.endswith("screenshot.png") for a in m["attachments"])
    assert pdf not in m["attachments"]
    dlg2 = issue_report_ui.open_dialog(w, "hi", show=False)
    dlg2.use_shot.setChecked(False)
    dlg2.attach.setChecked(True)
    assert dlg2.send() == "captured"
    assert pdf in box[-1]["attachments"]
    assert not any(a.endswith("screenshot.png")
                   for a in box[-1]["attachments"])
    w._view.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_crash_notice_has_report_button(setup, qapp, monkeypatch):
    from app import crashreport
    seen = []

    class W:
        def report_issue(self, text=""):
            seen.append(text)
    boxes = []
    orig = QMessageBox.open
    monkeypatch.setattr(QMessageBox, "open",
                        lambda self: (boxes.append(self), orig(self)))
    monkeypatch.setattr(crashreport, "_last_notice", [-1e9])
    holder = {}
    monkeypatch.setattr(QApplication, "activeWindow",
                        staticmethod(lambda: holder.get("w")))
    from PySide6.QtWidgets import QWidget

    class Top(QWidget, W):
        pass
    top = Top()
    holder["w"] = top
    crashreport._notify("x.txt", previous=True)
    for _ in range(5):
        qapp.processEvents()
    assert boxes
    b = [x for x in boxes[-1].buttons() if x.text() == "Report This…"]
    assert b
    b[0].click()
    assert seen and seen[0].startswith("QuantiSheet closed unexpectedly")
    boxes[-1].close()
    top.deleteLater()


def test_crash_checkbox_is_passed_to_the_report(monkeypatch, tmp_path):
    """Venice #8 (Nov 4): leaving the box off keeps crash reports out."""
    from app import diagnostics, issue_report
    seen = {}
    real = diagnostics.bundle

    def spy(path, crashes=True):
        seen["crashes"] = crashes
        return real(path, crashes=crashes)
    monkeypatch.setattr(diagnostics, "bundle", spy)
    issue_report.build("x", None, folder=str(tmp_path / "f"), crashes=False)
    assert seen["crashes"] is False
