"""Master Schedule: the hook (Module menu) and the review window."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import mail, master_hook, settings                     # noqa: E402
from app.pm.master import apply, baseline, model                # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store)
from test_pm import qapp_pm                                     # noqa: E402,F401
from test_gui import qapp, win                                  # noqa: E402,F401


def _menu_texts(win):
    from PySide6.QtWidgets import QMenu
    return [a.text() for m in win.menuBar().findChildren(QMenu)
            for a in m.actions()]


def test_hook_adds_module_item(qapp_pm, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    make_store(tmp_path, monkeypatch)
    m = QMenu()
    act_ = master_hook.add_menu_item(object(), m)
    assert act_ is not None and act_.text() == master_hook.MENU_TEXT
    settings.set("master_schedule_module", False)          # switched off
    m2 = QMenu()
    assert master_hook.add_menu_item(object(), m2) is None
    assert m2.actions() == []


def test_hook_failure_leaves_menu_unchanged(qapp_pm, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    make_store(tmp_path, monkeypatch)
    monkeypatch.setattr(master_hook, "enabled",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))
    m = QMenu()
    assert master_hook.add_menu_item(object(), m) is None
    assert m.actions() == []


def test_main_window_module_menu(win):
    texts = _menu_texts(win)
    assert master_hook.MENU_TEXT in texts
    assert texts.index(master_hook.MENU_TEXT) > texts.index(
        "Read the Energy Code Online…")


def test_store_for_window_finds_project(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    pdf = os.path.join(s.folder, "Drawings", "plan.pdf")
    os.makedirs(os.path.dirname(pdf))
    open(pdf, "wb").close()
    w = type("W", (), {"_path": pdf})()
    got = master_hook.store_for(w)
    assert got is not None and os.path.samefile(got.folder, s.folder)
    assert master_hook.store_for(type("W", (), {"_path": None})()) is None


def _window(s):
    from app.pm.master.ui import MasterScheduleWindow
    w = MasterScheduleWindow(s)
    w.timer.stop()
    return w


def _pending(s, tmp_path, edits, company=ACME, name="p.xlsx"):
    p = excel.generate(s, company, str(tmp_path / name), cycle=CYCLE)
    fill(p, edits)
    return apply.receive(s, p, company)


def test_window_with_zero_one_many(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    w = _window(s)
    assert w.queue.rowCount() == 0
    assert not w.btn_approve.isEnabled()
    _pending(s, tmp_path, {"A0002": {"% complete": 0}})
    w.refresh()
    assert w.queue.rowCount() == 1
    for k in range(5):
        _pending(s, tmp_path, {"A0003": {"Duration (workdays)": 4 + k}},
                 company=BEST, name=f"b{k}.xlsx")
    w.refresh()
    assert w.queue.rowCount() == 6
    w.close()


def test_window_approve_decline_revert(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a = _pending(s, tmp_path, {"A0002": {"% complete": 0}})
    b = _pending(s, tmp_path, {"A0003": {"Duration (workdays)": 4}},
                 company=BEST, name="b.xlsx")
    w = _window(s)
    w.select(a["_id"])
    assert "finish later" in w.detail.toPlainText()
    assert w.btn_approve.isEnabled()
    w.approve_selected()
    assert s.get(model.SUBS, a["_id"])["status"] == "Approved"
    w.select(b["_id"])
    w.decline_selected("Not now")
    assert s.get(model.SUBS, b["_id"])["status"] == "Declined"
    c = _pending(s, tmp_path, {"A0005": {"Note": "on track"}}, name="c.xlsx")
    assert c["status"] == "Auto-accepted"
    w.refresh()
    w.select(c["_id"])
    assert w.btn_revert.isEnabled()
    w.revert_selected()
    assert s.get(model.SUBS, c["_id"])["status"] == "Reverted"
    w.close()


def test_window_add_submission_and_entry(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 60}})
    w = _window(s)
    sub = w.add_submission(p, ACME)
    assert sub["status"] == "Auto-accepted"
    e = w.enter_update(ACME, CYCLE, [{"no": "A0005", "duration": 5}])
    assert e["status"] == "Pending review" and e["channel"] == "gc-entry"
    assert w.queue.rowCount() == 2
    w.close()


def test_entry_form_builds_entries(qapp_pm, tmp_path, monkeypatch):
    from app.pm.master.ui import EntryDialog
    s = make_store(tmp_path, monkeypatch)
    d = EntryDialog(s, ACME, CYCLE)
    assert d.table.rowCount() == 2
    d.set_cell("A0005", "% complete", "10")
    d.set_cell("A0002", "Note", "short crew")
    assert d.entries() == [{"no": "A0002", "note": "short crew"},
                           {"no": "A0005", "percent": "10"}]
    d.close()


def test_window_baseline_lock_and_settings(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    w = _window(s)
    w.lock_baseline("Contract")
    assert baseline.status(s)["locked"]
    assert "Locked" in w.base_label.text()
    w.rebaseline("Change 2", confirm=True)
    assert baseline.status(s)["snapshot_n"] == 2
    w.inbox_edit.setText(str(tmp_path / "in"))
    w.nth.setCurrentIndex(0)                       # 1st Thursday
    w.auto_box.setChecked(False)
    w.save_settings()
    c = model.config(s)
    assert c["inbox"] == str(tmp_path / "in") and c["cycle"]["nth"] == 1
    assert c["auto_accept"]["progress_only"] is False
    w.close()


def test_window_assign_subs_needs_confirm(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a = act(s, "A0003")
    a["owner_co"] = ""
    s.save_record("activity", a)
    w = _window(s)
    assert w.assign_subs(confirm=False) == 0
    assert act(s, "A0003")["owner_co"] == ""
    assert w.assign_subs(confirm=True) == 1
    assert act(s, "A0003")["owner_co"] == BEST
    w.close()


def test_window_open_draft_needs_click(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    got = []
    monkeypatch.setattr(mail, "send", lambda *a, **k: got.append(k) or "x")
    _pending(s, tmp_path, {"A0002": {"% complete": 0}})
    w = _window(s)
    assert got == [] and w.drafts_list.count() >= 1
    assert w.open_draft(0, confirm=False) is None and got == []
    w.open_draft(0, confirm=True)
    assert got[0]["display"] is True
    w.close()


def test_window_check_inbox(qapp_pm, tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    inbox = tmp_path / "in"
    (inbox / ACME).mkdir(parents=True)
    model.set_config(s, inbox=str(inbox))
    p = excel.generate(s, ACME, str(inbox / ACME / "u.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 60}})
    w = _window(s)                     # first poll at open
    r = w.check_inbox()
    assert len(r["picked"]) == 1 and w.queue.rowCount() == 1
    w.close()


def test_opening_window_writes_nothing(qapp_pm, tmp_path, monkeypatch):
    """Opening (and closing) the window never changes the project file:
    two QuantiSheets with the window open can't overwrite each other."""
    from app.pm import store as store_mod
    s = make_store(tmp_path, monkeypatch)
    raw = open(s.path, "rb").read()
    v = s.version
    w = _window(s)
    w.refresh()
    w.close()
    assert s.version == v and s.path not in store_mod._DIRTY
    s.flush()
    assert open(s.path, "rb").read() == raw
