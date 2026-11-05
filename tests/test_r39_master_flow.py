"""Master Schedule: receive -> validate (whole file) -> match/slice ->
diff + impact on a what-if copy -> classify -> auto-accept / review ->
all-or-nothing apply, revert, stale three-way, supersede, hub guard."""
import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import schedule_record                               # noqa: E402
from app.pm.master import apply, model                           # noqa: E402
from app.pm.master.formats import excel                          # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act, fill,   # noqa: E402
                                 make_store)


def _sub(s, tmp_path, edits=None, new=None, company=ACME, name=None,
         as_company=None):
    name = name or f"{company[:4]}_{len(os.listdir(tmp_path))}.xlsx"
    p = excel.generate(s, company, str(tmp_path / name), cycle=CYCLE)
    fill(p, edits, new)
    return apply.receive(s, p, as_company or company, channel="manual")


def _acts(s):
    return [{k: v for k, v in a.items() if k not in ("_updated",)}
            for a in s.list("activity")]


def test_progress_only_no_slip_auto_accepts(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60}})
    assert sub["status"] == "Auto-accepted", sub.get("why")
    assert sub["decided_by"] == "auto-rule"
    assert act(s, "A0002")["percent"] == 60
    assert sub["impact"]["later"] == []
    assert model.config(s)["rev"] == 1
    log = schedule_record.updates(s)
    assert log[-1]["kind"] == "update" and model.label(sub) in \
        log[-1]["note"]
    assert schedule_record.verify(s) == []


def test_less_progress_slips_goes_to_review(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    before = _acts(s)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 0}})
    assert sub["status"] == "Pending review"
    assert _acts(s) == before                  # nothing applied
    later = {x["_no"] for x in sub["impact"]["later"]}
    assert {"A0002", "A0004", "A0005", "A0006"} <= later
    assert sub["impact"]["finish_workdays"] > 0
    assert any("later" in w for w in sub["why"])


def test_float_absorbed_duration_still_reviews(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0003": {"Duration (workdays)": 4}},
               company=BEST)
    assert sub["status"] == "Pending review"
    assert sub["impact"]["finish_workdays"] == 0     # float absorbed it
    assert [x["_no"] for x in sub["impact"]["later"]] == ["A0003"]


def test_expected_finish_becomes_duration(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0003": {"Expected finish": "2026-11-11"}},
               company=BEST)
    ch = {(c["_no"], c["field"]): c for c in sub["changes"]}
    assert ch[("A0003", "duration")]["after"] == 5
    assert sub["status"] == "Pending review"
    assert apply.approve(s, sub["_id"], by="Jon")["status"] == "Approved"
    from app.pm import schedule
    row = next(r for r in schedule.compute(s, schedule.data_date(s))["rows"]
               if r["_no"] == "A0003")
    assert row["ef"].isoformat() == "2026-11-11"


def test_whole_file_rejected_with_every_reason(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    before, log = _acts(s), schedule_record.updates(s)
    sub = _sub(s, tmp_path, {
        "A0002": {"% complete": 120, "Actual finish": "2026-11-01"},
        "A0005": {"Duration (workdays)": -1, "Actual start": "next week"}},
        new=[("", 2, "A0002", ""), ("Wire", 1, "A0003", "")])
    assert sub["status"] == "Rejected"
    texts = " | ".join(r["text"] for r in sub["reasons"])
    for want in ("0 to 100", "before", "below 0", "date", "name",
                 "isn't yours"):
        assert want in texts, want
    assert len(sub["reasons"]) >= 6
    assert all(r["where"] for r in sub["reasons"])
    assert _acts(s) == before and schedule_record.updates(s) == log
    assert sub["changes"] == []                # never partly applied


@pytest.mark.parametrize("edits,needle", [
    ({"A0002": {"Actual finish": "2026-11-04", "Actual start": None,
                "% complete": 100}}, "without an actual start"),
    ({"A0002": {"Actual start": "2026-11-20"}}, "after the data date"),
    ({"A0002": {"% complete": 100}}, "100 %"),
    ({"A0002": {"Actual finish": "2026-11-05"}}, "100 %"),
    ({"A0005": {"Duration (workdays)": 0}}, "milestone"),
    ({"A0005": {"Duration (workdays)": "abc"}}, "number"),
    ({"A0005": {"Duration (workdays)": 4, "Expected finish": "2027-03-01"}},
     "disagree"),
])
def test_hard_rejects(tmp_path, monkeypatch, edits, needle):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, edits)
    assert sub["status"] == "Rejected"
    assert any(needle in r["text"] for r in sub["reasons"]), sub["reasons"]


def test_company_mismatch_rejected(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60}}, as_company=BEST)
    assert sub["status"] == "Rejected"
    assert any("Acme" in r["text"] for r in sub["reasons"])
    assert act(s, "A0002")["percent"] == 20


def test_context_row_edits_ignored_and_flagged(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60},
                             "A0004": {"Duration (workdays)": 9}})
    assert sub["status"] == "Pending review"     # a flag stops auto
    assert any(i["_no"] == "A0004" for i in sub["ignored"])
    assert all(c["_no"] != "A0004" for c in sub["changes"])
    apply.approve(s, sub["_id"], by="Jon")
    assert act(s, "A0004")["duration"] == 1


def test_fractional_duration_rounds_up_with_warning(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0005": {"Duration (workdays)": 3.2}})
    ch = {(c["_no"], c["field"]): c for c in sub["changes"]}
    assert ch[("A0005", "duration")]["after"] == 4       # up, never down
    assert sub["warnings"] and sub["status"] == "Pending review"


def test_retroactive_actual_is_red_flag(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"Actual start": "2026-11-03",
                                       "% complete": 60}})
    assert sub["status"] == "Pending review"
    assert sub["impact"]["red_flags"]


def test_new_internal_activities_rolled_up(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    n_before = len(s.list("activity"))
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60}},
               new=[("Pull wire L1", 4, "A0002", ""),
                    ("Pull wire L2", 3, "A0002", "")])
    assert [n["name"] for n in sub["new"]] == ["Pull wire L1",
                                              "Pull wire L2"]
    assert any("longer than" in w["text"] for w in sub["warnings"])
    assert sub["status"] == "Pending review"
    apply.approve(s, sub["_id"], by="Jon")
    assert len(s.list("activity")) == n_before        # one line per sub


def test_absent_row_is_not_deletion(tmp_path, monkeypatch):
    import openpyxl
    s = make_store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    wb = openpyxl.load_workbook(p)
    wb["Update"].delete_rows(3)                     # A0005 row gone
    wb.save(p)
    fill(p, {"A0002": {"% complete": 60}})
    sub = apply.receive(s, p, ACME)
    assert sub["status"] == "Auto-accepted"
    assert "A0005" in sub["not_reported"]
    assert act(s, "A0005")["duration"] == 3


def test_duplicate_file_skipped(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 0}})
    first = apply.receive(s, p, ACME)
    again = apply.receive(s, p, ACME)
    assert again["duplicate_of"] == first["_id"]
    assert len(model.submissions(s)) == 1
    q = os.path.join(s.folder, ".quantisheet", "master", "received")
    assert os.listdir(q) == [first["sha256"] + ".xlsx"]


def test_stale_three_way(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "a.xlsx"), cycle=CYCLE)
    a5 = act(s, "A0005")
    a5["duration"] = 4                         # GC changed it since issue
    s.save_record("activity", a5)
    fill(p, {"A0002": {"% complete": 60}})     # sub left A0005 alone
    sub = apply.receive(s, p, ACME)
    assert sub["status"] == "Auto-accepted"
    assert act(s, "A0005")["duration"] == 4    # GC value kept
    p2 = excel.generate(s, ACME, str(tmp_path / "b.xlsx"), cycle=CYCLE)
    a5 = act(s, "A0005")
    a5["duration"] = 6
    s.save_record("activity", a5)
    fill(p2, {"A0005": {"Duration (workdays)": 2}})
    sub2 = apply.receive(s, p2, ACME)
    assert sub2["status"] == "Pending review"
    assert [(c["_no"], c["field"], c["base"], c["current"], c["sub"])
            for c in sub2["conflicts"]] == [("A0005", "duration", 4, 6, 2)]


def test_newer_submission_supersedes(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a = _sub(s, tmp_path, {"A0002": {"% complete": 0}}, name="a1.xlsx")
    b = _sub(s, tmp_path, {"A0002": {"% complete": 10}}, name="a2.xlsx")
    assert s.get(model.SUBS, a["_id"])["status"] == "Superseded"
    assert b["status"] == "Pending review"


def test_decline_keeps_master_and_drafts_reply(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    before = _acts(s)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 0}})
    d = apply.decline(s, sub["_id"], "Talk to me first", by="Jon")
    assert d["status"] == "Declined" and d["decision"] == "Talk to me first"
    assert _acts(s) == before
    assert d["drafts"][-1]["kind"] == "declined"
    assert "Talk to me first" in d["drafts"][-1]["body"]


def test_apply_is_all_or_nothing(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 0},
                             "A0005": {"Duration (workdays)": 4}})
    before = _acts(s)
    real = s.save_record
    calls = []

    def boom(coll, rec):
        if coll == "activity":
            calls.append(rec.get("_no"))
            if len(calls) == 2:
                raise OSError("disk full")
        return real(coll, rec)
    monkeypatch.setattr(s, "save_record", boom)
    out = apply.approve(s, sub["_id"], by="Jon")
    monkeypatch.setattr(s, "save_record", real)
    assert out["status"] == "Apply failed" and "disk full" in out["error"]
    assert [{k: v for k, v in a.items() if not k.startswith("_")}
            for a in s.list("activity")] == \
        [{k: v for k, v in a.items() if not k.startswith("_")}
         for a in before]
    assert model.config(s)["rev"] == 0
    assert [e["kind"] for e in schedule_record.updates(s)] == []


def test_revert_auto_accepted(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60,
                                       "Note": "half way"}})
    assert sub["status"] == "Auto-accepted"
    r = apply.revert(s, sub["_id"], by="Jon")
    assert r["status"] == "Reverted"
    a = act(s, "A0002")
    assert a["percent"] == 20 and "half way" not in (a.get("notes") or "")
    assert schedule_record.updates(s)[-1]["note"].startswith("Revert")
    assert schedule_record.verify(s) == []


def test_revert_refused_after_later_edit(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60}})
    a = act(s, "A0002")
    a["percent"] = 70
    s.save_record("activity", a)
    with pytest.raises(ValueError) as ei:
        apply.revert(s, sub["_id"], by="Jon")
    assert "A0002" in str(ei.value)
    assert act(s, "A0002")["percent"] == 70


def test_approve_rechecks_against_current_master(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    a = _sub(s, tmp_path, {"A0002": {"% complete": 0}}, name="a.xlsx")
    b = _sub(s, tmp_path, {"A0003": {"Duration (workdays)": 4}},
             company=BEST, name="b.xlsx")
    imp_b = copy.deepcopy(b["impact"])
    apply.approve(s, a["_id"], by="Jon")
    b2 = s.get(model.SUBS, b["_id"])
    assert b2["status"] == "Pending review" and b2["rechecked"]
    assert b2["impact"] != imp_b               # recomputed on the new master


def test_hub_pending_ops_block_apply(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 0}})
    s.data["hub"] = {"url": "http://hub.invalid", "project": "p",
                     "key": "k", "role": "admin"}
    with pytest.raises(apply.ApplyRefused) as ei:
        apply.approve(s, sub["_id"], by="Jon")
    assert "Sync" in str(ei.value)
    s.data["pending"] = []
    s.data["hub"]["role"] = "estimator"
    with pytest.raises((apply.ApplyRefused, PermissionError)):  # Q7: PM only
        apply.approve(s, sub["_id"], by="Jon")
    s.data["hub"]["role"] = "pm"
    assert apply.approve(s, sub["_id"], by="Jon")["status"] == "Approved"
    s.data["hub"] = None


def test_manual_entry_goes_through_same_queue(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    sub = apply.receive_manual(s, ACME, CYCLE,
                               [{"no": "A0002", "percent": 0}], by="Jon")
    assert sub["channel"] == "gc-entry" and sub["format"] == "form"
    assert sub["status"] == "Pending review"
    bad = apply.receive_manual(s, ACME, CYCLE,
                               [{"no": "A0003", "percent": 50},
                                {"no": "A0002", "percent": 500}], by="Jon")
    assert bad["status"] == "Rejected" and len(bad["reasons"]) == 2


def test_web_seam_uses_same_receive(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    p = excel.generate(s, ACME, str(tmp_path / "w.xlsx"), cycle=CYCLE)
    fill(p, {"A0002": {"% complete": 60}})
    sub = apply.receive(s, p, ACME, channel="web")
    assert sub["channel"] == "web" and sub["status"] == "Auto-accepted"
    assert "web" in apply.CHANNELS


def test_auto_accept_switch_off_sends_all_to_review(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    model.set_config(s, auto_accept={"progress_only": False,
                                     "max_slip_workdays": 0})
    sub = _sub(s, tmp_path, {"A0002": {"% complete": 60}})
    assert sub["status"] == "Pending review"


def test_project_without_module_is_unchanged(tmp_path, monkeypatch):
    """No master_schedule setting: compute() and the saved project.json
    are identical after open / save (regression)."""
    from app.pm import schedule
    from app.pm.store import ProjectStore
    s = make_store(tmp_path, monkeypatch)
    raw = open(s.path, "rb").read()
    cpm = schedule.compute(s, schedule.data_date(s))
    s2 = ProjectStore(s.folder)
    s2.flush(force=True)
    assert open(s.path, "rb").read() == raw
    assert schedule.compute(s2, schedule.data_date(s2))["rows"] == \
        cpm["rows"]
    assert model.config(s2)["rev"] == 0 and s2.setting(model.SETTING) \
        is None
