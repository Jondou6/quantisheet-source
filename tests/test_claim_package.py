"""Schedule claim package: the record (updates, fingerprints), delay
events with their time impact, concurrency, late notice, recovery plans,
the quality check and planned vs actual - in one PDF; plus the Gantt
page's menu entries and the delay event's Time Impact Analysis action."""
import datetime as dt
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import actions, claim_package as cp                # noqa: E402
from app.pm import schedule_record as sr                       # noqa: E402
from test_pm import qapp_pm                                    # noqa: E402,F401
from test_schedule import _store                               # noqa: E402

TODAY = dt.date(2026, 11, 20)
NOW = "2026-10-01T09:00:00"


def _job(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    sr.snapshot(s, "baseline", "Baseline", now=NOW)
    ft = s.find("activity", name="Footings")[0]
    ft["duration"] = 6
    s.save_record("activity", ft)
    sr.snapshot(s, "update", "November update", now="2026-11-02T09:00:00")
    s.save_record("delay", {
        "title": "Footing redesign", "status": "Notice Given",
        "responsibility": "Owner", "cause": "Design error / RFI response",
        "event_start": "2026-11-05", "event_end": "2026-11-12",
        "notice_date": "2026-11-20",                 # 15 days later
        "fragnet": [{"name": "Redesign footings", "duration": 3,
                     "pred": "A0002", "succ": "A0003"}],
        "days_requested": 3})
    s.save_record("delay", {
        "title": "Rebar crew short", "status": "Open",
        "responsibility": "Contractor", "cause": "Labor / crew shortage",
        "event_start": "2026-11-10", "event_end": "2026-11-11",
        "notice_date": "2026-11-10",
        "affected": [{"id": "A0005", "days": 1}]})
    return s


def test_gather_holds_the_whole_record(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    g = cp.gather(s, TODAY)
    assert [u["kind"] for u in g["updates"]] == ["baseline", "update"]
    assert g["intact"] == []
    assert len(g["changes"]) == 1 and g["changes"][0]["durations"]
    assert [r["title"] for r in g["delays"]] == ["Footing redesign",
                                                 "Rebar crew short"]
    tia = g["tia"][g["delays"][0]["_id"]]
    assert tia["impact_workdays"] is not None and "error" not in tia
    assert g["notice"][g["delays"][0]["_id"]]["late"]
    assert not g["notice"][g["delays"][1]["_id"]]["late"]
    assert g["concurrency"]                      # owner vs contractor
    assert len(g["windows"]) == 1
    assert len(g["quality"]["items"]) == 14


def test_package_pdf(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    p = cp.export_pdf(s, str(tmp_path / "claim.pdf"), TODAY)
    doc = fitz.open(p)
    t = "".join(pg.get_text() for pg in doc)
    for w in ("Schedule Claim Package", "1. WHERE THE JOB STANDS",
              "Intact", "2. SCHEDULE UPDATES", "November update",
              "3. DELAY EVENTS AND TIME IMPACT", "Footing redesign",
              "LATE", "notice clause governs", "4. CONCURRENT DELAYS",
              "5. WINDOWS ANALYSIS", "6. RECOVERY PLANS",
              "7. SCHEDULE QUALITY (DCMA 14-POINT)",
              "8. PLANNED VS ACTUAL", "9. UPDATE FINGERPRINTS",
              sr.updates(s)[0]["hash"], "decided under the contract",
              "Completion date used", "Notice period", "Recorded head",
              sr.anchor(s)["head"]):
        assert w in t, w


def test_a_changed_update_shows_in_the_package(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    log = s.setting("schedule_updates")
    log[0]["finish"] = "2026-12-31"                 # edited after the fact
    s.set_setting("schedule_updates", log)
    t = fitz.open(cp.export_pdf(s, str(tmp_path / "c.pdf"), TODAY))[0] \
        .get_text()
    assert "CHECK:" in t and "Update 1" in t


def test_empty_job_still_builds(tmp_path, monkeypatch):
    from app import settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    s = ProjectStore(str(tmp_path / "empty"))
    t = "".join(pg.get_text() for pg in fitz.open(
        cp.export_pdf(s, str(tmp_path / "e.pdf"), TODAY)))
    assert "No schedule updates saved yet" in t
    assert "No delay events" in t


def test_gantt_menu_entries_and_tia_action(qapp_pm, tmp_path, monkeypatch):
    from app.pm import center
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = _job(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    page = w.show_tool("gantt")
    n0 = len(sr.updates(s))
    assert page.save_update("December update")["n"] == n0 + 1
    page.baseline()                             # snapshots too
    assert sr.updates(s)[-1]["kind"] == "baseline"
    assert sr.verify(s) == []
    assert page.quality_check(str(tmp_path / "q.pdf"))
    assert page.claim_package(str(tmp_path / "c.pdf"))
    assert "DCMA" in fitz.open(str(tmp_path / "q.pdf"))[0].get_text()
    rec = s.find("delay", title="Footing redesign")[0]
    said = []
    ctx = actions.Ctx(s, ask=lambda *a: None, notify=said.append)
    out = actions.run(ctx, "delay", rec, "Time Impact Analysis")
    assert out["status"] == "Analyzed"
    assert said and "workdays" in said[0]
    w.show_tool("delay")                         # the Delay Log page opens
    w.close()


def test_scheduler_window_has_the_claim_tools(qapp_pm, tmp_path,
                                              monkeypatch):
    """The claim tools are in the Scheduler (Gantt) window too, and its
    Set Baseline saves an update like the Gantt Chart page's (Oct 21)."""
    from app.pm import scheduler as sch
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = _job(tmp_path, monkeypatch)
    w = sch.Scheduler(s, None)
    for t in ("Save Schedule Update…", "Delay Log", "Recovery Schedule…",
              "Schedule Quality Check (PDF)…", "Claim Package (PDF)…"):
        assert t in w.acts_by_name, t
    n0 = len(sr.updates(s))
    assert w.save_update("Nov 30 update")["n"] == n0 + 1
    w.baseline()
    assert sr.updates(s)[-1]["kind"] == "baseline" and sr.verify(s) == []
    p = w.claim_package(str(tmp_path / "w.pdf"))
    assert "Schedule Claim Package" in fitz.open(p)[0].get_text()
    assert w.quality_check(str(tmp_path / "wq.pdf"))
    d = w.recovery()
    d.close()
    w.close()


def _dates_job(tmp_path, monkeypatch):
    """Made-up job: the finish activity (Slab) baselined to finish Dec 25."""
    s = _store(tmp_path, monkeypatch)
    slab = s.find("activity", name="Slab")[0]
    slab["baseline_finish"] = "2026-12-25"
    s.save_record("activity", slab)
    sr.snapshot(s, "baseline", now=NOW)
    return s


def test_one_completion_date_everywhere(tmp_path, monkeypatch):
    """Review 0.12.34 #2: section 1, the DCMA CPLI and recovery.standing()
    use the contract completion date when set, else the baseline finish,
    and say which."""
    from app.pm import recovery
    s = _dates_job(tmp_path, monkeypatch)
    g = cp.gather(s, TODAY)
    assert g["completion"] == dt.date(2026, 12, 25)
    assert g["completion_source"] == "baseline"
    assert cp.completion_text(g) == "12/25/2026 (baseline)"
    q = g["quality"]
    assert q["target"] == dt.date(2026, 12, 25)
    assert q["target_kind"] == "baseline"
    cpli = next(it for it in q["items"] if it["key"] == "cpli")
    assert "baseline" in cpli["note"]
    assert "12/25/2026" in cp.quality_measure(q, cpli) and \
        "baseline" in cp.quality_measure(q, cpli)
    st = recovery.standing(s)
    assert (st["target"], st["target_source"]) == \
        (dt.date(2026, 12, 25), "baseline")
    # the contract completion date wins once it is set
    s.set_setting("contract_completion", "2026-12-31")
    g = cp.gather(s, TODAY)
    assert (g["completion"], g["completion_source"]) == \
        (dt.date(2026, 12, 31), "contract")
    assert cp.completion_text(g) == "12/31/2026 (contract)"
    q = g["quality"]
    assert (q["target"], q["target_kind"]) == (dt.date(2026, 12, 31),
                                               "contract")
    cpli = next(it for it in q["items"] if it["key"] == "cpli")
    assert "contract" in cpli["note"] and "Dec 31, 2026" in cpli["note"]
    m = cp.quality_measure(q, cpli)
    assert "12/31/2026" in m and "contract" in m
    st = recovery.standing(s)
    assert (st["target"], st["target_source"]) == \
        (dt.date(2026, 12, 31), "contract")
    assert g["standing"]["behind"] == st["behind"] < 0     # ahead
    # a date typed in the Recovery dialog is still used there
    assert recovery.standing(s, dt.date(2026, 11, 20))["target_source"] == \
        "given"


def test_contract_terms_are_checked_and_saved(tmp_path, monkeypatch):
    from app.pm import recovery
    s = _store(tmp_path, monkeypatch)
    assert recovery.contract_terms(s) == {"completion": None,
                                          "notice_days": 7}
    assert recovery.parse_terms("", "") == ("", 7)
    assert recovery.parse_terms("12/31/2026", "21") == ("2026-12-31", 21)
    assert recovery.parse_terms(" 2026-12-31 ", "0") == ("2026-12-31", 0)
    for bad in (("Dec 31", "7"), ("2026-12-31", "-1"),
                ("2026-12-31", "two weeks"), ("2026-12-31", "2.5")):
        try:
            recovery.parse_terms(*bad)
            assert False, bad
        except ValueError as e:
            assert str(e), bad
    recovery.set_terms(s, "2026-12-31", "21")
    assert s.setting("contract_completion") == "2026-12-31"
    assert s.setting("notice_days") == 21
    assert recovery.contract_terms(s) == {
        "completion": dt.date(2026, 12, 31), "notice_days": 21}
    # day 15 notice is on time with 21 days
    rec = s.save_record("delay", {"title": "Hold", "status": "Open",
                                  "event_start": "2026-11-02",
                                  "notice_date": "2026-11-17"})
    assert not sr.notice_late(s, rec)["late"]


def test_anchor_in_the_package(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    g = cp.gather(s, TODAY)
    assert g["anchor"]["count"] == 2
    assert g["anchor"]["head"] == sr.updates(s)[-1]["hash"]
    assert cp.record_text(g).startswith("Intact")
    # the last update dropped: section 1 says so
    s.set_setting(sr.SETTING, sr.updates(s)[:-1])
    g = cp.gather(s, TODAY)
    assert "chain shorter than recorded (1 vs 2)" in \
        cp.record_text(g).lower()


def test_project_settings_dialog_has_the_contract_terms(qapp_pm, tmp_path,
                                                        monkeypatch):
    """Project settings: 'Contract completion date' (blank) and 'Notice
    period (days)' (7), saved as the settings the package reads."""
    from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit
    from app.pm import center
    s = _store(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    seen = {}

    def fill(dlg, *a):
        f = dlg.layout()
        for row in range(f.rowCount()):
            lab = f.itemAt(row, QFormLayout.ItemRole.LabelRole)
            fld = f.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if lab is None or fld is None or not isinstance(
                    fld.widget(), QLineEdit):
                continue
            seen[lab.widget().text()] = fld.widget()
        seen["_before"] = {k: e.text() for k, e in seen.items()}
        seen["Contract completion date"].setText("2026-12-31")
        seen["Notice period (days)"].setText("21")
        return 1
    monkeypatch.setattr(QDialog, "exec", fill)
    w.project_settings()
    assert seen["_before"]["Contract completion date"] == ""
    assert seen["_before"]["Notice period (days)"] == "7"
    assert s.setting("contract_completion") == "2026-12-31"
    assert s.setting("notice_days") == 21
    w.close()


class _Grab:
    """Collects the log records of one logger (no pytest caplog needed)."""

    def __init__(self, name):
        import logging
        self.records, self.log = [], logging.getLogger(name)
        self.h = logging.Handler()
        self.h.emit = self.records.append

    def __enter__(self):
        self.log.addHandler(self.h)
        return self.records

    def __exit__(self, *a):
        self.log.removeHandler(self.h)


def test_set_baseline_reports_a_failed_snapshot(qapp_pm, tmp_path,
                                                monkeypatch):
    """Review 0.12.38 #10 (made-up job): the schedule-record snapshot after
    Set Baseline fails -> the baseline is still saved, the person is told
    the record wasn't updated (with the reason), and the log has it - in
    the Scheduler window and on the Gantt Chart page."""
    from app.pm import center, scheduler as sch
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = _job(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise OSError("disk full (made up)")
    monkeypatch.setattr(sr, "snapshot", boom)
    n0 = len(sr.updates(s))
    want = ("Baseline saved, but the schedule record could not be updated:"
            " disk full (made up)")
    w = sch.Scheduler(s, None)
    w._quiet = True
    with _Grab("app.pm.scheduler") as recs:
        n = w.baseline()
    assert n and w.last_baseline_message == want
    assert w.statusBar().currentMessage() == want
    assert any("snapshot failed" in r.getMessage() and r.exc_info
               for r in recs)
    assert any(a.get("baseline_finish") for a in s.list("activity"))
    w.close()
    c = center.ProjectCenter(s)
    page = c.show_tool("gantt")
    with _Grab("app.pm.scheduleui") as recs:
        page.baseline()
    assert page.last_baseline_message == want
    assert c.toast_lbl.text() == want
    assert any(r.exc_info for r in recs)
    assert len(sr.updates(s)) == n0             # nothing was recorded
    c.close()
