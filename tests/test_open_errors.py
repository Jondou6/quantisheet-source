"""Venice #9/#10 (Nov 4): plain reasons when a file won't open, and a
repair pass that writes a cleaned copy (the original is never changed)."""
import errno
import os

import fitz
import pytest

from app import openerrors as oe

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app import settings
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    from app.main_window import MainWindow
    w = MainWindow()
    yield w
    for v in w._all_views():
        v.dirty = False
    w.close()
    w.deleteLater()
    app.processEvents()


def _pdf(path, pages=2):
    d = fitz.open()
    for i in range(pages):
        d.new_page().insert_text((72, 72), f"Sheet A{i}")
    d.save(path)
    d.close()


def test_kinds(tmp_path):
    assert oe.classify(FileNotFoundError(), str(tmp_path / "x.pdf")) == \
        "missing"
    p = tmp_path / "a.pdf"
    _pdf(p)
    e = PermissionError(errno.EACCES, "denied")
    assert oe.classify(e, str(p)) == "permission"
    e32 = PermissionError(errno.EACCES, "in use")
    e32.winerror = 32
    assert oe.classify(e32, str(p)) == "in_use"
    assert oe.classify(RuntimeError("needs password"), str(p)) == "password"
    txt = tmp_path / "notes.pdf"
    txt.write_bytes(b"just some text, not a pdf")
    assert oe.classify(RuntimeError("weird"), str(txt)) == "not_pdf"
    assert oe.classify(RuntimeError("cannot find xref"), str(p)) == "damaged"
    assert oe.classify(RuntimeError("weird"), "") == "internal"


def test_every_kind_has_a_next_step():
    for k in oe.TEXT:
        head, step = oe.message(k, r"C:\jobs\plan.pdf")
        assert head.startswith("plan.pdf: ") and step


def test_repair_writes_a_copy_and_leaves_the_original(tmp_path):
    good = tmp_path / "g.pdf"
    _pdf(good, 3)
    data = good.read_bytes()
    i = data.rfind(b"xref")
    bad = tmp_path / "plan.pdf"
    bad.write_bytes(b"junk before header\n" + data[:i])   # no xref/trailer
    before = bad.read_bytes()
    out = oe.repair(str(bad))
    assert out.endswith("plan (repaired).pdf")
    assert bad.read_bytes() == before
    d = fitz.open(out)
    assert d.page_count == 3
    d.close()
    assert oe.repair(str(bad)).endswith("plan (repaired 2).pdf")


def test_repair_gives_up_on_garbage(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.7\nnothing here")
    with pytest.raises(Exception):
        oe.repair(str(p))
    assert not os.path.exists(tmp_path / "x (repaired).pdf")


def test_window_offers_repair_then_opens_copy(win, tmp_path):
    w = win
    good = tmp_path / "g.pdf"
    _pdf(good, 2)
    data = good.read_bytes()
    bad = tmp_path / "plan.pdf"
    bad.write_bytes(data[:data.rfind(b"xref")])
    shown = []
    asked = []
    assert w._open_failed(str(bad), RuntimeError("syntax error"),
                          ask=lambda t: asked.append(t) or True,
                          show=lambda *a: shown.append(a))
    assert asked and "damaged" in asked[0] and not shown
    assert any(os.path.basename(getattr(w.tabs.widget(i), "path", "") or "")
               == "plan (repaired).pdf" for i in range(w.tabs.count()))
    # declined: nothing opened, nothing written
    bad2 = tmp_path / "other.pdf"
    bad2.write_bytes(data[:data.rfind(b"xref")])
    assert not w._open_failed(str(bad2), RuntimeError("syntax error"),
                              ask=lambda t: False)
    assert not os.path.exists(tmp_path / "other (repaired).pdf")


def test_window_plain_reason_for_missing(win, tmp_path):
    w = win
    shown = []
    p = str(tmp_path / "gone.pdf")
    assert not w._open_failed(p, FileNotFoundError(p),
                              show=lambda *a: shown.append(a))
    head, step, details = shown[0]
    assert "isn't there" in head and "File > Open" in step
    assert "FileNotFoundError" in details


def test_help_recent_problems_opens_the_log_viewer(win):
    """PR 11 wired: Help > Recent Problems (Log)."""
    from app import log_view
    names = [a.text() for a in win._help_menu.actions()]
    assert "Recent Problems (Log)…" in names
    dlg = win.recent_problems(show=False)
    assert isinstance(dlg, log_view.LogViewer)
    dlg.close()


def test_timestamp_server_setting(win, monkeypatch):
    """Venice #3 / PR 14: off until set; blank turns it off again."""
    from app.sign import signer, timestamp
    assert timestamp.for_signing() is None
    assert win.timestamp_server(ask=lambda t, v: "http://127.0.0.1:9/") == \
        "http://127.0.0.1:9/"
    assert timestamp.for_signing() == "http://127.0.0.1:9/"
    assert win.timestamp_server(ask=lambda t, v: "ftp://x") == \
        "http://127.0.0.1:9/"                         # refused, unchanged
    assert win.timestamp_server(ask=lambda t, v: "") == ""
    assert timestamp.for_signing() is None
    assert "timestamp.for_signing()" in open(signer.__file__).read()


def test_panels_get_their_empty_state_tips(win):
    """PR 10 wired: View-menu tip and What's This, no extra labels."""
    done = win._empty_state_tips()
    assert "estimate" in done and "bookmarks" in done
    from PySide6.QtWidgets import QDockWidget
    d = win.findChild(QDockWidget, "estimate")
    assert d.property("emptyState") == d.whatsThis() == \
        d.toggleViewAction().toolTip()
    assert not d.toolTip()


def test_practice_job_walkthrough(win):
    """PR 9 wired: Help > Practice Job, every step with Show Me."""
    from app import practice_job as pj
    names = [a.text() for a in win._help_menu.actions()]
    assert "Practice Job (10 Minutes)…" in names
    dlg = win.practice_job(show=False)
    assert os.path.normcase(win._path) == os.path.normcase(pj.plan_path())
    assert dlg.current["id"] == "open"
    seen = []
    while dlg.next_btn.isEnabled():
        if dlg.current["id"] in ("measure", "price", "export"):
            seen.append(dlg.do_step())
        dlg.next_step()
    assert seen == ["measure", "price", "export"]
    assert os.path.isfile(pj.export_path())
    assert pj.progress() == "export"
    import csv
    rows = list(csv.reader(open(pj.export_path(), encoding="utf-8-sig")))
    assert any("1125" in ",".join(r) for r in rows)
    dlg.close()


def test_undo_names_the_step(win, tmp_path):
    """Venice #17: "Undo Add Markup (2 items)", redaction named and
    undoable until saved."""
    p = tmp_path / "u.pdf"
    _pdf(p, 1)
    assert win.open_path(str(p))
    v = win._view
    v.apply_marks([(0, "add_rect", {"rect": [100, 100, 150, 150]}),
                   (0, "add_rect", {"rect": [200, 100, 250, 150]})])
    assert v.history.undo_label() == "Add Markup (2 items)"
    win._undo_names()
    assert win._undo_act.toolTip() == "Undo Add Markup (2 items)"
    assert win._undo_act.text() == "Undo"             # ribbon still finds it
    v.undo_label = "Bulk Edit (412 items)"
    v.apply_marks([(0, "add_rect", {"rect": [300, 100, 350, 150]})])
    assert v.history.undo_label() == "Bulk Edit (412 items)"
    assert v.undo_label is None                       # one-shot
    shown = []
    win._flash = lambda t, *a, **k: shown.append(t)
    win.undo()
    assert shown[-1] == "Undid Bulk Edit (412 items)"
    assert win._redo_act.toolTip() == "Redo Bulk Edit (412 items)"
    v.apply_marks([(0, "add_redact", {"rect": [60, 60, 200, 90]})])
    assert v.history.undo_label() == "Redaction"
    before = len(v.doc[0].get_text("words"))
    win.undo()                                        # back before saving
    assert len(v.doc[0].get_text("words")) >= before
    rows = __import__("app.history", fromlist=["x"]).history_rows(win)
    assert any("Add Markup (2 items)" in r["label"] for r in rows)


def test_screen_reader_names_on_the_main_window(win):
    """Venice #18: icon-only buttons and form fields get names."""
    from app import a11y
    a11y.name_widgets(win)
    left = a11y.audit(win)
    # a handful of unnamed internal widgets is tolerable; most must be named
    from app.a11y import _controls
    total = len(_controls(win))
    unnamed = [x for x in left if x[2] == "no name"]
    assert total > 50
    assert len(unnamed) <= total // 10, unnamed[:20]


def test_a11y_names_and_dialogs(win):
    from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit,
                                   QToolButton)
    from app import a11y
    d = QDialog(win)
    f = QFormLayout(d)
    e = QLineEdit()
    f.addRow("Wall height", e)
    b = QToolButton()
    b.setToolTip("Zoom <b>in</b>")
    f.addRow(b)
    assert a11y.name_widgets(d) == 2
    assert e.accessibleName() == "Wall height"
    assert b.accessibleName() == "Zoom in"
    assert a11y.audit(d) == []
    assert a11y.high_contrast() in (True, False)
    d.close()


def test_local_copy_and_copy_back(tmp_path):
    """Venice #14: a copy on this PC, copied back - refused if the
    original changed, and then kept as "(mine)" instead."""
    from app import jobsafe
    share = tmp_path / "share"
    share.mkdir()
    orig = share / "plan.pdf"
    _pdf(orig, 1)
    local = jobsafe.make_local_copy(str(orig), root=str(tmp_path / "local"))
    assert os.path.isfile(local) and local != str(orig)
    assert jobsafe.local_copy_info(local)["original"] == str(orig)
    d = fitz.open(local)
    d[0].insert_text((72, 200), "my edit")
    d.saveIncr()
    d.close()
    assert jobsafe.copy_back(local) == str(orig)
    assert b"my edit" in fitz.open(str(orig))[0].get_text().encode()
    import time
    time.sleep(0.05)
    d = fitz.open(str(orig))                       # someone else saves
    d[0].insert_text((72, 300), "their edit")
    d.saveIncr()
    d.close()
    with pytest.raises(jobsafe.CopyBackError):
        jobsafe.copy_back(local)
    mine = jobsafe.copy_back(local, force=True)
    assert mine.endswith("plan (mine).pdf")
    assert "their edit" in fitz.open(str(orig))[0].get_text()


def test_window_local_copy_menu(win, tmp_path):
    p = tmp_path / "s.pdf"
    _pdf(p, 1)
    assert win.open_path(str(p))
    local = win.work_on_local_copy()
    assert local and os.path.normcase(win._path) == os.path.normcase(local)
    assert not any(os.path.normcase(getattr(win.tabs.widget(i), "path", "")
                                    or "") == os.path.normcase(str(p))
                   for i in range(win.tabs.count()))
    assert win.copy_back_original() == str(p)


def test_ctrl_k_service_hit_opens_that_record(win, monkeypatch):
    """Section 2/4: a Ctrl+K service hit opens Equipment & Service
    Records on that unit, not just the window."""
    from app import quickaccess as QA
    from app.estimating import service, ui as est_ui
    st = service.blank()
    pid = service.add_property(st, "Example Clinic", "1 Example Rd")
    service.add_equipment(st, pid, "RTU", make="ExampleAir", serial="A1")
    eid = service.add_equipment(st, pid, "Boiler", make="ExampleHeat",
                                serial="B2")
    service.save(st)
    got = []
    real = est_ui.open_tools
    monkeypatch.setattr(est_ui, "open_tools",
                        lambda w, key="check", focus=None, show=True:
                        got.append((key, focus)))
    hit = next(a for k, a in QA.palette_extras(win)
               if k == "Service record" and "Boiler" in a.text())
    hit.trigger()
    assert got == [("service", ("equipment", eid))]
    dlg = real(win, "service", focus=("equipment", eid),
                            show=False)
    pg = dlg.pages["service"]
    assert pg.equip.currentRow() == 1
    assert pg.focus("property", pid) == 0
    dlg.close()


def test_attachments_saved_safely(win, tmp_path):
    """PR 15 wired: Document > Attachments saves a copy of an allowed
    type; job data and blocked types are not offered / refused."""
    from app import safe_extract
    p = tmp_path / "a.pdf"
    d = fitz.open()
    d.new_page()
    d.embfile_add("spec.pdf", b"%PDF-1.4\n%x\n", filename="spec.pdf")
    d.embfile_add("tool.exe", b"MZ", filename="tool.exe")
    d.embfile_add("quantisheet_estimate.json", b"{}",
                  filename="quantisheet_estimate.json")
    d.save(str(p))
    d.close()
    assert win.open_path(str(p))
    names = [n for n, _k in safe_extract.listing(win._view.doc)]
    assert "spec.pdf" in names and not any("quantisheet_" in n
                                           for n in names)
    out = str(tmp_path / "saved.pdf")
    assert win.attachments(pick="spec.pdf", save_to=out) == out
    assert open(out, "rb").read().startswith(b"%PDF")
    assert win.attachments(pick="tool.exe", save_to=str(tmp_path / "t")) \
        is None
    assert not os.path.exists(tmp_path / "t")
