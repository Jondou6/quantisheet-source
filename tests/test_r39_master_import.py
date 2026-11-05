"""Master Schedule: the NEW MS Project XML / P6 XER path (design 3.4,
4.1, 4.10, 4.11, 4.14). Read -> match -> neutral rows -> the same
validate / diff / review / apply as Excel. The Scheduler's Import button
(schedule.import_msproject / import_xer / _merge) is never called."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import schedule                                      # noqa: E402
from app.pm.master import apply, match, model                    # noqa: E402
from app.pm.master.formats import msp, xer                       # noqa: E402
from r39_master_fixtures import (ACME, BEST, CYCLE, act,         # noqa: E402
                                 make_store, msp_xml, xer_text)


@pytest.fixture
def s(tmp_path, monkeypatch):
    st = make_store(tmp_path, monkeypatch)
    model.set_config(st, cycle={"nth": 1})       # Nov 5 2026 = 1st Thursday
    # the readers' own auto-accept rule; Q6's always-review is tested in
    # test_master_decisions.py
    model.set_config(st, review_msp_xer=False)

    def boom(*a, **k):
        raise AssertionError("the Scheduler importer must not be used")
    for f in ("import_msproject", "import_xer", "_merge"):
        monkeypatch.setattr(schedule, f, boom)
    return st


def _acts(s):
    return {a["_no"]: {k: v for k, v in a.items() if k != "_updated"}
            for a in s.list("activity")}


ACME_TASKS = [{"uid": 1, "name": "Rough-in electrical", "hours": 40,
               "pct": 20, "astart": "2026-11-04", "text30": "A0002"},
              {"uid": 2, "name": "Trim electrical", "hours": 24,
               "text30": "A0005"}]


def _msp(s, tmp_path, tasks, name="acme.xml", company=ACME, **kw):
    p = msp_xml(tmp_path / name, tasks, **kw)
    return apply.receive(s, p, company, channel="manual")


def _t(**over):
    out = [dict(t) for t in ACME_TASKS]
    for uid, ch in over.items():
        out[int(uid[1:]) - 1].update(ch)
    return out


# ------------------------------------------------------------------ MSP
def test_msp_text30_progress_only_auto_accepts(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"pct": 60}))
    assert sub["format"] == "msp"
    assert sub["status"] == "Auto-accepted", sub.get("why")
    assert act(s, "A0002")["percent"] == 60
    assert sub["based_on"] == "unknown"
    assert {r["matched_by"] for r in sub["rows"]} == {"Text30"}


def test_msp_hours_duration_slip_goes_to_review(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"hours": 56}))
    assert sub["status"] == "Pending review"
    ch = [c for c in sub["changes"] if c["field"] == "duration"]
    assert ch and ch[0]["after"] == 7
    assert act(s, "A0002")["duration"] == 5


def test_msp_minutes_per_day_used_for_hours(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"hours": 37.5, "pct": 30},
                               u2={"hours": 22.5}),
               minutes_per_day=450)
    assert sub["status"] == "Auto-accepted", sub.get("why")
    assert act(s, "A0002")["duration"] == 5


def test_msp_fractional_rounds_up_with_warning(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"hours": 44}))
    assert sub["status"] == "Pending review"
    d = [c for c in sub["changes"] if c["field"] == "duration"]
    assert d[0]["after"] == 6
    assert any("rounded up" in w["text"] for w in sub["warnings"])


def test_msp_doctype_rejected_before_parsing(s, tmp_path):
    before = _acts(s)
    sub = _msp(s, tmp_path, _t(u1={"pct": 60}), doctype=True)
    assert sub["status"] == "Rejected"
    assert any("DOCTYPE" in r["text"] for r in sub["reasons"])
    assert _acts(s) == before


def test_msp_not_a_project_file_rejected(s, tmp_path):
    sub = _msp(s, tmp_path, [], tasks_el=False)
    assert sub["status"] == "Rejected"
    assert any("Microsoft Project" in r["text"] for r in sub["reasons"])


def test_msp_every_error_reported_and_store_unchanged(s, tmp_path):
    before = _acts(s)
    sub = _msp(s, tmp_path, _t(u1={"pct": 150},
                               u2={"afinish": "2026-11-04", "pct": 100}))
    assert sub["status"] == "Rejected"
    texts = " | ".join(r["text"] for r in sub["reasons"])
    assert "0 to 100" in texts and "without an actual start" in texts
    assert _acts(s) == before


def test_msp_unmatched_rows_listed_then_mapped_and_remembered(s, tmp_path):
    tasks = _t(u1={"text30": "", "pct": 60})
    sub = _msp(s, tmp_path, tasks)
    assert sub["status"] == "Pending review"
    assert [u["ref"] for u in sub["unmatched"]] == ["msp:1"]
    assert act(s, "A0002")["percent"] == 20
    a2 = act(s, "A0002")["_id"]
    new = apply.remap(s, sub["_id"], {"msp:1": a2})
    assert s.get(model.SUBS, sub["_id"])["status"] == "Superseded"
    assert new["remapped_from"] == sub["_id"]
    assert new["status"] == "Auto-accepted", new.get("why")
    assert act(s, "A0002")["percent"] == 60
    assert model.config(s)["mappings"][ACME] == {"msp:1": a2}
    # next cycle's file: same UID, still no Text30 -> matched by the table
    nxt = _msp(s, tmp_path, _t(u1={"text30": "", "pct": 70}),
               name="acme2.xml")
    assert nxt["status"] == "Auto-accepted", nxt.get("why")
    assert [r["matched_by"] for r in nxt["rows"]
            if r["no"] == "A0002"] == ["mapping"]


def test_remap_refuses_another_trades_activity(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"text30": ""}))
    with pytest.raises(ValueError):
        apply.remap(s, sub["_id"], {"msp:1": act(s, "A0003")["_id"]})
    assert model.config(s).get("mappings", {}).get(ACME) in (None, {})


def test_remap_ignore_drops_the_row(s, tmp_path):
    tasks = _t() + [{"uid": 9, "name": "Our own detail", "hours": 8}]
    sub = _msp(s, tmp_path, tasks)
    assert [u["ref"] for u in sub["unmatched"]] == ["msp:9"]
    new = apply.remap(s, sub["_id"], {"msp:9": "ignore"})
    assert new["unmatched"] == []
    assert new["status"] == "Auto-accepted", new.get("why")


def test_msp_other_trades_row_ignored_and_flagged(s, tmp_path):
    tasks = _t() + [{"uid": 3, "name": "Rough-in plumbing", "hours": 80,
                     "text30": "A0003"}]
    sub = _msp(s, tmp_path, tasks)
    assert any(i["_no"] == "A0003" for i in sub["ignored"])
    assert act(s, "A0003")["duration"] == 3
    assert sub["status"] == "Pending review"


def test_msp_company_mismatch_rejected(s, tmp_path):
    tasks = [{"uid": 3, "name": "Rough-in plumbing", "hours": 24,
              "pct": 10, "astart": "2026-11-04", "text30": "A0003"}]
    sub = _msp(s, tmp_path, tasks, company=ACME)
    assert sub["status"] == "Rejected"
    assert any(BEST in r["text"] for r in sub["reasons"])


def test_msp_holiday_mismatch_warns_and_never_writes_holidays(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"pct": 60}),
               holidays=["2026-11-26", "2026-11-27"])
    assert sub["status"] == "Pending review"
    assert any("2026-11-27" in w["text"] for w in sub["warnings"])
    assert s.setting("holidays") == ["2026-11-26"]


def test_msp_progress_going_backwards_keeps_master_and_warns(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"pct": 10}))
    assert act(s, "A0002")["percent"] == 20
    assert not [c for c in sub["changes"] if c["field"] == "percent"]
    assert any("kept" in w["text"] for w in sub["warnings"])
    assert sub["status"] == "Pending review"


def test_msp_status_date_not_a_cycle_date_warns(s, tmp_path):
    sub = _msp(s, tmp_path, _t(u1={"pct": 60}), status_date="2026-11-06")
    assert sub["cycle"] == "2026-11-06"
    assert any("cycle date" in w["text"] for w in sub["warnings"])
    assert sub["status"] == "Pending review"


def test_msp_missing_status_date_uses_previous_cycle_with_warning(s,
                                                                   tmp_path):
    import datetime as dt
    p = msp_xml(tmp_path / "nostat.xml", _t(u1={"pct": 60}),
                status_date=None)
    sub = apply.receive(s, p, ACME, channel="manual",
                        now=dt.datetime(2026, 11, 9, 10))
    assert sub["cycle"] == CYCLE
    assert any("status date" in w["text"].lower() for w in sub["warnings"])


def test_msp_logic_differences_listed_as_requests_not_applied(s, tmp_path):
    tasks = _t(u2={"preds": [1]})
    sub = _msp(s, tmp_path, tasks)
    assert act(s, "A0005")["preds"] == [{"id": "A0004"}]
    assert sub["logic_requests"]
    assert sub["logic_requests"][0]["_no"] == "A0005"


def test_msp_reader_is_pure(s, tmp_path):
    p = msp_xml(tmp_path / "pure.xml", _t(u1={"pct": 60}))
    s.flush()
    raw = open(s.path, "rb").read()
    out = msp.read(s, p, ACME)
    assert not out["errors"] and out["meta"]["cycle"] == CYCLE
    s.flush()
    assert open(s.path, "rb").read() == raw


# ------------------------------------------------------------------ XER
def _xer(s, tmp_path, tasks, name="acme.xer", company=ACME, **kw):
    p = xer_text(tmp_path / name, tasks, **kw)
    return apply.receive(s, p, company, channel="manual")


def test_xer_task_code_progress_auto_accepts(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 1, "code": "A0002", "name":
                              "Rough-in electrical", "hours": 40, "pct": 60,
                              "astart": "2026-11-04"}])
    assert sub["format"] == "xer"
    assert sub["status"] == "Auto-accepted", sub.get("why")
    assert act(s, "A0002")["percent"] == 60


def test_xer_activity_code_match_and_hours(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 7, "code": "E-100", "name": "Trim",
                              "hours": 56, "actv": "A0005"}])
    assert [r["matched_by"] for r in sub["rows"]] == ["activity code"]
    d = [c for c in sub["changes"] if c["field"] == "duration"]
    assert d and d[0]["after"] == 7 and d[0]["_no"] == "A0005"
    assert sub["status"] == "Pending review"


def test_xer_task_code_with_other_name_warns(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 1, "code": "A0002", "name":
                              "Something else", "hours": 40, "pct": 60,
                              "astart": "2026-11-04"}])
    assert any("name" in w["text"] for w in sub["warnings"])
    assert sub["status"] == "Pending review"


def test_xer_actual_finish_means_complete(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 1, "code": "A0002", "name":
                              "Rough-in electrical", "hours": 16, "pct": 80,
                              "astart": "2026-11-04",
                              "afinish": "2026-11-05"}])
    assert sub["status"] in ("Auto-accepted", "Pending review")
    pc = [r for r in sub["rows"] if r["no"] == "A0002"][0]["values"]
    assert pc["percent"] == 100


def test_xer_unmatched_mapping(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 7, "code": "E-200", "name": "Trim",
                              "hours": 24, "pct": 0}])
    assert [u["ref"] for u in sub["unmatched"]] == ["p6:E-200"]
    new = apply.remap(s, sub["_id"], {"p6:E-200": act(s, "A0005")["_id"]})
    assert new["unmatched"] == []
    assert model.config(s)["mappings"][ACME]["p6:E-200"] == \
        act(s, "A0005")["_id"]


def test_xer_not_an_xer_rejected(s, tmp_path):
    sub = _xer(s, tmp_path, [{"id": 1, "code": "A0002"}], header=False)
    assert sub["status"] == "Rejected"
    assert any("XER" in r["text"] for r in sub["reasons"])


def test_xer_entity_text_rejected(s, tmp_path):
    p = tmp_path / "evil.xer"
    xer_text(p, [{"id": 1, "code": "A0002"}])
    with open(p, "a", encoding="cp1252") as f:
        f.write("<!ENTITY x 'y'>\n")
    sub = apply.receive(s, str(p), ACME, channel="manual")
    assert sub["status"] == "Rejected"


# ---------------------------------------------------------------- match
def test_match_order_mapping_then_id_then_ext(s):
    a2 = act(s, "A0002")
    a5 = act(s, "A0005")
    model.set_config(s, mappings={ACME: {"msp:5": a5["_id"]}})
    got = match.find(s, ACME, {"ref": "msp:5", "ids": ["A0002"],
                               "ext": "msp:5", "name": "x"})
    assert got[0]["_id"] == a5["_id"] and got[1] == "mapping"
    got = match.find(s, ACME, {"ref": "msp:6", "ids": [a2["_id"]],
                               "ext": "msp:6", "name": "x"})
    assert got[0]["_id"] == a2["_id"]
    # _ext is set only when the Scheduler import CREATES a record
    imp = s.save_record("activity", {"_ext": "msp:77", "name": "Imported",
                                     "owner_co": ACME, "duration": 1})
    got = match.find(s, ACME, {"ref": "msp:77", "ids": [], "ext": "msp:77",
                               "name": "x"})
    assert got[0]["_id"] == imp["_id"] and got[1] == "earlier import"
    assert match.find(s, ACME, {"ref": "msp:99", "ids": [], "ext":
                                "msp:99", "name": "x"}) == (None, None)
