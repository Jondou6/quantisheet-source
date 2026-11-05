"""Master Schedule window: MS Project / P6 files, Map rows…, Edit and
approve…, cycle panel and combined impact."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm.master import apply, model                          # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store, msp_xml)
from test_pm import qapp_pm                                     # noqa: E402,F401


def _window(s):
    from app.pm.master.ui import MasterScheduleWindow
    w = MasterScheduleWindow(s)
    w.timer.stop()
    return w


def _store(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    model.set_config(s, cycle={"nth": 1}, review_msp_xer=False)
    return s


def test_add_msp_and_map_rows(qapp_pm, tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    p = msp_xml(tmp_path / "a.xml", [{"uid": 4, "name": "Rough-in",
                                      "hours": 40, "pct": 60,
                                      "astart": "2026-11-04"}])
    w = _window(s)
    sub = w.add_submission(p, ACME)
    assert sub["status"] == "Pending review"
    w.select(sub["_id"])
    assert w.btn_map.isEnabled()
    assert "msp:4" in w.detail.toPlainText()
    new = w.map_rows({"msp:4": act(s, "A0002")["_id"]})
    assert new["status"] == "Auto-accepted"
    assert act(s, "A0002")["percent"] == 60
    w.close()


def test_map_dialog_lists_own_activities(qapp_pm, tmp_path, monkeypatch):
    from app.pm.master.ui import MapDialog
    s = _store(tmp_path, monkeypatch)
    d = MapDialog(s, ACME, [{"ref": "msp:4", "name": "Rough-in",
                             "where": "Task UID 4"}])
    items = d.choices(0)
    assert "A0002 Rough-in electrical" in items and "Ignore" in items
    assert not any("A0003" in x for x in items)
    d.choose(0, "A0002 Rough-in electrical")
    assert d.pairs() == {"msp:4": act(s, "A0002")["_id"]}
    d.choose(0, "Ignore")
    assert d.pairs() == {"msp:4": "ignore"}
    d.close()


def test_edit_and_approve_from_window(qapp_pm, tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"Duration (workdays)": 8}})
    sub = apply.receive(s, p, ACME)
    w = _window(s)
    w.select(sub["_id"])
    assert w.btn_edit.isEnabled()
    out = w.edit_and_approve({"A0002": {"duration": 6}})
    assert out["status"] == "Approved" and act(s, "A0002")["duration"] == 6
    assert "GC override" in w.detail.toPlainText()
    w.close()


def test_cycle_and_combined_labels(qapp_pm, tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    for co, no, n in ((ACME, "A0002", 7), (BEST, "A0003", 9)):
        p = excel.generate(s, co, str(tmp_path / f"{no}.xlsx"), cycle=CYCLE)
        fill(p, {no: {"Duration (workdays)": n}})
        apply.receive(s, p, co)
    w = _window(s)
    assert "Next data date" in w.cycle_label.text()
    w.refresh()
    assert "2 pending" in w.combined_label.text()
    w.close()
