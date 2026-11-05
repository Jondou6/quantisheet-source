"""Nov 3 (Jon): on a shared computer the all-users copy can't update
without an administrator - it installs the person's own copy instead, and
once they have one, starting the shared copy opens their own."""
import os

from app import owncopy, settings


def _setup(tmp_path):
    pf = tmp_path / "Program Files"
    shared = pf / "QuantiSheet" / "QuantiSheet.exe"
    own = tmp_path / "Users" / "me" / "AppData" / "Local" / "Programs" / \
        "QuantiSheet" / "QuantiSheet.exe"
    for p in (shared, own):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"MZ")
    return [os.path.normcase(str(pf))], str(shared), str(own)


def test_shared_copy_is_the_one_in_program_files(tmp_path):
    dirs, shared, own = _setup(tmp_path)
    assert owncopy.shared_copy(shared, dirs)
    assert not owncopy.shared_copy(own, dirs)
    assert not owncopy.shared_copy("", dirs)            # a source run
    assert owncopy.own_copy(shared, dirs, own) == own
    assert owncopy.own_copy(shared, dirs, shared) is None
    assert owncopy.own_copy(shared, dirs, own + ".missing") is None


def test_shared_copy_opens_your_own_with_the_files(tmp_path, monkeypatch):
    dirs, shared, own = _setup(tmp_path)
    pdf = tmp_path / "plan.pdf"
    pdf.write_bytes(b"%PDF")
    ran = []
    assert owncopy.redirect([shared, str(pdf), "-x"], shared, ran.append,
                            dirs, own)
    assert ran == [[own, str(pdf)]]
    ran.clear()                         # your own copy never redirects
    assert not owncopy.redirect([own], own, ran.append, dirs, own)
    assert not owncopy.redirect([shared], shared, ran.append, dirs,
                                own + ".none")           # no own copy yet
    monkeypatch.setattr(settings, "get", lambda k, d=None: False
                        if k == owncopy.S_OPEN_OWN else d)
    assert not owncopy.redirect([shared], shared, ran.append, dirs, own)
    assert ran == []


def test_shared_copy_offers_your_own_copy(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QWidget
    from app import updatecheck, updatecheck_ui
    monkeypatch.setattr(owncopy, "shared_copy", lambda *a, **k: True)
    monkeypatch.setattr(updatecheck, "ready_download", lambda i: None)
    w = QMainWindow()
    w.setCentralWidget(QWidget())
    qtbot.addWidget(w)
    n = updatecheck_ui.UpdateNotice(w, {"version": "9.0.0", "url": "x",
                                        "sha256": "0" * 64, "size": 1,
                                        "notes": ""})
    assert n.b1.text() == "Install my own copy"
    assert "administrator" in n.title.text()
