"""Master Schedule: lockable baseline in the schedule history."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import schedule, schedule_record                    # noqa: E402
from app.pm.master import baseline                              # noqa: E402
from r39_master_fixtures import act, make_store                 # noqa: E402
from test_pm import qapp_pm                                     # noqa: E402,F401


def test_lock_takes_a_baseline_snapshot(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    e = baseline.lock(s, "Contract baseline")
    st = baseline.status(s)
    assert st["locked"] and st["snapshot_n"] == e["n"] == 1
    assert st["hash"] == e["hash"] and st["reason"] == "Contract baseline"
    log = schedule_record.updates(s)
    assert log[-1]["kind"] == "baseline"
    assert schedule_record.verify(s) == []
    # the display copy was filled first (it was blank)
    assert act(s, "A0002")["baseline_finish"]
    with pytest.raises(ValueError):
        baseline.lock(s, "again")                    # already locked


def test_lock_requires_reason(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        baseline.lock(s, "  ")
    assert baseline.status(s) is None


def test_set_baseline_refuses_while_locked(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    baseline.lock(s, "Contract")
    before = s.list("activity")
    a = act(s, "A0003")
    a["duration"] = 9
    s.save_record("activity", a)
    with pytest.raises(schedule.BaselineLocked) as ei:
        schedule.set_baseline(s)
    assert "Re-baseline" in str(ei.value)
    assert [x.get("baseline_finish") for x in s.list("activity")] == \
        [x.get("baseline_finish") for x in before]


def test_set_baseline_unchanged_without_lock(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    assert schedule.set_baseline(s) == 6
    assert schedule.set_baseline(s) == 0


def test_drift_and_restore(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    baseline.lock(s, "Contract")
    assert baseline.drift(s) == []
    a = act(s, "A0005")
    good = a["baseline_finish"]
    a["baseline_finish"] = "2027-01-01"        # typed in the grid / _merge
    s.save_record("activity", a)
    d = baseline.drift(s)
    assert [(x["_no"], x["field"], x["shown"], x["locked"]) for x in d] == \
        [("A0005", "baseline_finish", "2027-01-01", good)]
    assert baseline.restore(s) == 1
    assert act(s, "A0005")["baseline_finish"] == good
    assert baseline.drift(s) == []


def test_tampered_locked_entry_is_reported(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    baseline.lock(s, "Contract")
    log = s.setting("schedule_updates")
    log[0]["activities"][0]["baseline_finish"] = "2030-01-01"
    s.set_setting("schedule_updates", log)
    with pytest.raises(ValueError):
        baseline.locked_entry(s)
    assert baseline.problems(s)


def test_rebaseline_keeps_the_old_entry(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    first = baseline.lock(s, "Contract")
    a = act(s, "A0005")
    a["duration"] = 6
    s.save_record("activity", a)
    with pytest.raises(PermissionError):
        baseline.rebaseline(s, "Owner change 3")        # needs confirm
    with pytest.raises(ValueError):
        baseline.rebaseline(s, "", confirm=True)        # needs a reason
    e = baseline.rebaseline(s, "Owner change 3", confirm=True)
    log = schedule_record.updates(s)
    assert [x["kind"] for x in log] == ["baseline", "baseline"]
    assert log[0]["hash"] == first["hash"]              # old one intact
    st = baseline.status(s)
    assert st["snapshot_n"] == e["n"] == 2 and st["locked"]
    h = st["history"]
    assert h[0]["snapshot_n"] == 1 and h[-1]["reason"] == "Owner change 3"
    assert h[-1]["compare"]["durations"][0]["_no"] == "A0005"
    assert schedule_record.verify(s) == []
    assert baseline.drift(s) == []
    with pytest.raises(schedule.BaselineLocked):
        schedule.set_baseline(s)


@pytest.mark.parametrize("which", ["scheduler", "gantt_page"])
def test_set_baseline_buttons_explain_lock(tmp_path, monkeypatch, qapp_pm,
                                           which):
    s = make_store(tmp_path, monkeypatch)
    baseline.lock(s, "Contract")
    n_log = len(schedule_record.updates(s))
    if which == "scheduler":
        from app.pm.scheduler import Scheduler
        w = Scheduler(s)
        w._quiet = True
        assert w.baseline() == 0
        msg = w.last_baseline_message
        w.close()
    else:
        from app.pm import scheduleui
        page = scheduleui.GanttPage.__new__(scheduleui.GanttPage)
        page.store = s
        toasts = []
        page.center = type("C", (), {"toast": lambda self, t:
                                     toasts.append(t)})()
        page.refresh = lambda: None
        assert page.baseline() == 0
        msg = page.last_baseline_message
        assert toasts == [msg]
    assert "locked" in msg.lower() and "Re-baseline" in msg
    # no new baseline entry was written
    assert len(schedule_record.updates(s)) == n_log
