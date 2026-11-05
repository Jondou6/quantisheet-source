"""r39 characterization (golden) tests, written BEFORE any master-schedule
code: they pin 0.13.9's existing schedule import path - _merge(),
import_msproject(), import_xer(), set_baseline() with no lock, and the
Scheduler's Import button - so the new Master Schedule module can be
proven not to change them. Golden files were generated on the pristine
0.13.9 tree (R39_WRITE_GOLDEN=1) and are only compared afterwards."""
import hashlib
import inspect
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import schedule                                  # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402
from test_pm import qapp_pm                                  # noqa: E402,F401

DATA = os.path.join(os.path.dirname(__file__), "data", "r39")
VOLATILE = {"_id", "_created", "_updated", "_by", "_upd_by", "_dirty"}

MSP = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
 <Name>Sub job</Name><CalendarUID>1</CalendarUID>
 <Calendars><Calendar><UID>1</UID><Name>Standard</Name>
  <IsBaseCalendar>1</IsBaseCalendar>
  <Exceptions><Exception><DayWorking>0</DayWorking>
   <TimePeriod><FromDate>2026-11-26T00:00:00</FromDate>
   <ToDate>2026-11-27T23:59:00</ToDate></TimePeriod></Exception>
  </Exceptions></Calendar></Calendars>
 <Tasks>
  <Task><UID>0</UID><Name>Sub job</Name><OutlineLevel>0</OutlineLevel>
   <Summary>1</Summary></Task>
  <Task><UID>1</UID><Name>Electrical</Name><OutlineLevel>1</OutlineLevel>
   <Summary>1</Summary></Task>
  <Task><UID>2</UID><Name>Rough-in</Name><OutlineLevel>2</OutlineLevel>
   <Duration>PT40H0M0S</Duration><Start>2026-11-02T08:00:00</Start>
   <PercentComplete>25</PercentComplete>
   <ActualStart>2026-11-02T08:00:00</ActualStart>
   <Notes>Level 1 first</Notes>
   <Baseline><Number>0</Number><Start>2026-11-02T08:00:00</Start>
    <Finish>2026-11-06T17:00:00</Finish></Baseline></Task>
  <Task><UID>3</UID><Name>Trim</Name><OutlineLevel>2</OutlineLevel>
   <Duration>PT20H0M0S</Duration><Start>2026-11-09T08:00:00</Start>
   <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type>
    <LinkLag>4800</LinkLag></PredecessorLink></Task>
  <Task><UID>4</UID><Name>Power on</Name><OutlineLevel>2</OutlineLevel>
   <Duration>PT0H0M0S</Duration><Milestone>1</Milestone>
   <Start>2026-11-12T08:00:00</Start>
   <PredecessorLink><PredecessorUID>3</PredecessorUID><Type>3</Type>
   </PredecessorLink></Task>
 </Tasks></Project>
"""

XER = "\n".join([
    "ERMHDR\t19.12",
    "%T\tPROJWBS", "%F\twbs_id\twbs_name", "%R\t10\tSite", "%R\t11\tShell",
    "%T\tTASK",
    "%F\ttask_id\ttask_code\ttask_name\twbs_id\ttarget_drtn_hr_cnt\t"
    "target_start_date\tact_start_date\tact_end_date\tphys_complete_pct\t"
    "task_type",
    "%R\t500\tA1000\tClear site\t10\t24\t2026-11-02 08:00\t"
    "2026-11-02 08:00\t2026-11-04 17:00\t100\tTT_Task",
    "%R\t501\tA1010\tGrade\t10\t36\t2026-11-05 08:00\t\t\t0\tTT_Task",
    "%R\t502\tA1020\tPads ready\t11\t0\t2026-11-12 08:00\t\t\t0\tTT_Mile",
    "%T\tTASKPRED",
    "%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt",
    "%R\t1\t501\t500\tPR_FS\t8",
    "%R\t2\t502\t501\tPR_SS\t0",
    "%E", ""])


def _store(tmp_path, monkeypatch, name="job"):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / name))
    s.set_setting("data_date", "2026-10-01")
    return s


def _state(s):
    acts = []
    for a in s.list("activity", deleted=True):
        acts.append({k: v for k, v in sorted(a.items())
                     if k not in VOLATILE})
    return {"activities": acts,
            "settings": {k: s.setting(k) for k in ("holidays",
                                                   "data_date")},
            "pending": len(s.data["pending"]), "next": s.data["next"]}


def _golden(name, got):
    path = os.path.join(DATA, name + ".json")
    got = json.loads(json.dumps(got, sort_keys=True, default=str))
    if os.environ.get("R39_WRITE_GOLDEN") == "1":
        os.makedirs(DATA, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(got, f, indent=1, sort_keys=True)
    with open(path, encoding="utf-8") as f:
        want = json.load(f)
    assert got == want


def _files(tmp_path):
    x = tmp_path / "sub.xml"
    x.write_text(MSP, encoding="utf-8")
    e = tmp_path / "sub.xer"
    e.write_bytes(XER.encode("cp1252"))
    return str(x), str(e)


def _seed(s):
    s.save_record("activity", {"name": "GC mobilize", "duration": 2,
                               "start": "2026-11-02"})


def test_import_msproject_golden(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    _seed(s)
    x, _e = _files(tmp_path)
    n = schedule.import_msproject(s, x)
    _golden("msp_first", {"n": n, "state": _state(s)})
    # the same file again updates in place (keyed by _ext)
    n2 = schedule.import_msproject(s, x)
    _golden("msp_again", {"n": n2, "state": _state(s)})


def test_import_msproject_keeps_existing_holidays(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    s.set_setting("holidays", ["2026-12-25"])
    x, _e = _files(tmp_path)
    schedule.import_msproject(s, x)
    _golden("msp_holidays_kept", _state(s))


def test_import_xer_golden(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    _seed(s)
    _x, e = _files(tmp_path)
    n = schedule.import_xer(s, e)
    _golden("xer_first", {"n": n, "state": _state(s)})


def test_merge_overwrites_and_keys_on_submitter_ids(tmp_path, monkeypatch):
    """The documented reason _merge is unsafe for sub submissions: it
    overwrites straight away and keys on the file's own ids (a second
    source creates duplicates). Pinned so nobody 'fixes' it in place."""
    s = _store(tmp_path, monkeypatch)
    items = [{"uid": "1", "name": "Pour", "duration": 3,
              "start": "2026-11-02", "links": []},
             {"uid": "2", "name": "Cure", "duration": 2.5,
              "start": "2026-11-05", "notes": "n",
              "links": [{"uid": "1", "type": "FS", "lag": 1}]}]
    schedule._merge(s, items, "msp")
    items[0]["duration"] = 9
    schedule._merge(s, items, "msp")
    schedule._merge(s, items, "p6")                  # other source: dupes
    _golden("merge_direct", _state(s))


def test_set_baseline_unlocked_golden(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    _seed(s)
    x, _e = _files(tmp_path)
    schedule.import_msproject(s, x)
    n = schedule.set_baseline(s)
    n2 = schedule.set_baseline(s)          # nothing moved: 0 the second time
    _golden("set_baseline", {"n": n, "n2": n2, "state": _state(s)})


def test_importer_sources_unchanged():
    """_merge, import_msproject, import_xer and the Scheduler's
    import_file are byte-identical to 0.13.9 (source hash)."""
    from app.pm import scheduler
    got = {}
    for name, fn in (("_merge", schedule._merge),
                     ("import_msproject", schedule.import_msproject),
                     ("import_xer", schedule.import_xer),
                     ("msproject_holidays", schedule.msproject_holidays),
                     ("Scheduler.import_file",
                      scheduler.Scheduler.import_file)):
        got[name] = hashlib.sha256(
            inspect.getsource(fn).encode("utf-8")).hexdigest()
    _golden("importer_sources", got)


def test_scheduler_import_button_golden(tmp_path, monkeypatch, qapp_pm):
    from app.pm.scheduler import Scheduler
    s = _store(tmp_path, monkeypatch)
    _seed(s)
    x, e = _files(tmp_path)
    w = Scheduler(s)
    w._quiet = True
    n1 = w.import_file(x)
    n2 = w.import_file(e)
    undo = len(w.undo_stack)
    st = _state(s)
    w.close()
    _golden("scheduler_import", {"n": [n1, n2], "undo": undo, "state": st})
