"""Master Schedule M5/M6 remainder: XML/XER through the watched folder,
the hook's background poll while a project is open, the monthly Thursday
cycle panel, closed-cycle flag, combined impact of a cycle's pending
submissions (4.7) and Edit and approve (GC overrides, 3.7)."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import master_hook, settings                           # noqa: E402
from app.pm.master import apply, cycle, diff, intake, model     # noqa: E402
from app.pm.master.formats import excel                         # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,  # noqa: E402
                                 make_store, msp_xml, xer_text)


@pytest.fixture
def job(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    inbox = tmp_path / "Schedule Inbox"
    for c in (ACME, BEST):
        (inbox / c).mkdir(parents=True)
    model.set_config(s, inbox=str(inbox), cycle={"nth": 1},
                     review_msp_xer=False)   # Q6 review: test_master_decisions
    return s, inbox


# ------------------------------------------------ watched folder: xml/xer
def test_folder_takes_msp_and_xer(job):
    s, inbox = job
    msp_xml(inbox / ACME / "acme.xml",
            [{"uid": 1, "name": "Rough-in electrical", "hours": 40,
              "pct": 60, "astart": "2026-11-04", "text30": "A0002"}])
    xer_text(inbox / BEST / "best.xer",
             [{"id": 3, "code": "A0003", "name": "Rough-in plumbing",
               "hours": 24, "pct": 10, "astart": "2026-11-05"}])
    st = intake.state_for(s)
    assert intake.scan(s, st)["picked"] == []          # first sight: wait
    r = intake.scan(s, st)
    got = {x["format"]: x["status"] for x in r["picked"]}
    assert got == {"msp": "Auto-accepted", "xer": "Auto-accepted"}
    assert os.path.exists(inbox / ACME / "Processed" / "acme.xml")
    assert act(s, "A0003")["percent"] == 10


def test_state_is_shared_per_project(job):
    s, _inbox = job
    assert intake.state_for(s) is intake.state_for(s)


# ------------------------------------------------ hook background polling
def _win(s):
    pdf = os.path.join(s.folder, "plan.pdf")
    open(pdf, "wb").close()
    return type("W", (), {"_path": pdf})()


def test_background_poll_picks_up_while_project_open(job):
    s, inbox = job
    p = excel.generate(s, ACME, str(inbox / ACME / "u.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 60}})
    w = _win(s)
    assert master_hook.background_poll(w)["picked"] == []
    r = master_hook.background_poll(w)
    assert [x["status"] for x in r["picked"]] == ["Auto-accepted"]


def test_background_poll_does_nothing_without_setup(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)            # no master_schedule
    s.flush()
    raw = open(s.path, "rb").read()
    assert master_hook.background_poll(_win(s)) is None
    assert master_hook.background_poll(type("W", (), {"_path": None})()) \
        is None
    s.flush()
    assert open(s.path, "rb").read() == raw
    assert s.setting(model.SETTING) is None


def test_background_poll_off_when_module_off(job):
    s, inbox = job
    settings.set("master_schedule_module", False)
    assert master_hook.background_poll(_win(s)) is None
    model.set_config(s, enabled=False)
    settings.set("master_schedule_module", True)
    assert master_hook.background_poll(_win(s)) is None


def test_background_poll_errors_are_contained(job, monkeypatch):
    s, _inbox = job
    monkeypatch.setattr(intake, "scan", lambda *a, **k: 1 / 0)
    assert master_hook.background_poll(_win(s)) is None


# ------------------------------------------------------------- cycle panel
def test_cycle_status_and_reminder_due(job):
    s, _inbox = job
    st = cycle.status(s, today=dt.date(2026, 10, 31))
    assert st["next"] == "2026-11-05" and st["previous"] == "2026-10-01"
    assert st["remind_on"] == "2026-10-31" and st["remind_due"] is True
    st = cycle.status(s, today=dt.date(2026, 10, 20))
    assert st["remind_due"] is False


def test_cycle_status_holiday_warning(job):
    s, _inbox = job
    s.set_setting("holidays", ["2026-11-26", "2026-11-05"])
    st = cycle.status(s, today=dt.date(2026, 11, 1))
    assert any("holiday" in w for w in st["warnings"])


def test_last_thursday_for_24_months():
    for k in range(24):
        y, m = 2026 + (k // 12), k % 12 + 1
        d = cycle.data_date({"nth": "last"}, y, m)
        assert d.weekday() == 3 and (d + dt.timedelta(days=7)).month != m


def test_closed_cycle_template_flagged_not_auto(job, tmp_path):
    s, _inbox = job
    # "closed" = the next cycle's packet already went to this sub (not the
    # wall clock, so the suite doesn't change meaning as time passes)
    p = excel.generate(s, ACME, str(tmp_path / "old.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 60}})
    excel.generate(s, ACME, str(tmp_path / "dec.xlsx"), cycle="2026-12-03")
    sub = apply.receive(s, p, ACME)
    assert sub["status"] == "Pending review"
    assert any("closed" in w["text"] for w in sub["warnings"])


# ------------------------------------------------------ combined impact
def test_combined_impact_of_cycle(job, tmp_path):
    s, _inbox = job
    pa = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(pa, {"A0002": {"Duration (workdays)": 7}})
    a = apply.receive(s, pa, ACME)
    pb = excel.generate(s, BEST, str(tmp_path / "b.xlsx"), cycle=CYCLE)
    fill(pb, {"A0003": {"Duration (workdays)": 9}})
    b = apply.receive(s, pb, BEST)
    assert a["status"] == b["status"] == "Pending review"
    c = diff.combined(s, CYCLE)
    assert sorted(c["submissions"]) == sorted([model.label(a),
                                               model.label(b)])
    one = max(x["workdays"] for x in a["impact"]["later"])
    both = max(x["workdays"] for x in c["later"])
    assert both > one
    assert diff.combined(s, "2027-01-07")["submissions"] == []


# ------------------------------------------------------- edit and approve
def test_edit_and_approve_records_gc_override(job, tmp_path):
    s, _inbox = job
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"Duration (workdays)": 8}})
    sub = apply.receive(s, p, ACME)
    out = apply.approve(s, sub["_id"], edits={"A0002": {"duration": 6}})
    assert out["status"] == "Approved"
    assert act(s, "A0002")["duration"] == 6
    assert out["gc_overrides"] == [{"_no": "A0002", "field": "duration",
                                    "sub": 8, "gc": 6}]


def test_edit_and_approve_checks_values_and_slice(job, tmp_path):
    s, _inbox = job
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"Duration (workdays)": 8}})
    sub = apply.receive(s, p, ACME)
    with pytest.raises(ValueError):
        apply.approve(s, sub["_id"], edits={"A0002": {"percent": 150}})
    with pytest.raises(ValueError):
        apply.approve(s, sub["_id"], edits={"A0003": {"duration": 1}})
    with pytest.raises(ValueError):
        apply.approve(s, sub["_id"], edits={"A0002": {"name": "x"}})
    assert s.get(model.SUBS, sub["_id"])["status"] == "Pending review"
    assert act(s, "A0002")["duration"] == 5
