"""Recovery schedule: where the job stands, crash / fast-track /
resequence on a what-if copy, Suggest Steps, the AI helper loop (with a
scripted model), apply, the owner's PDF, and the dialog."""
import datetime as dt
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                      # noqa: E402
from app.pm import recovery as rc, recovery_ai as ra, schedule  # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402
from test_pm import qapp_pm                                   # noqa: E402,F401

D = dt.date
TARGET = D(2026, 12, 1)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "Job"))
    s.set_setting("data_date", "2026-10-01")
    add = lambda **r: s.save_record("activity", r)           # noqa: E731
    add(name="Mobilize", duration=2, start="2026-11-02")
    add(name="Excavate", duration=10, preds=[{"id": "A0001"}])
    add(name="Footings", duration=8, preds=[{"id": "A0002"}],
        responsible="ABC Concrete")
    add(name="Walls", duration=10, preds=[{"id": "A0003"}])
    add(name="Site lighting", duration=3, preds=[{"id": "A0001"}])
    add(name="Substantial Completion", duration=0,
        preds=[{"id": "A0004"}, {"id": "A0005"}])
    return s


def act(s, name):
    return s.find("activity", name=name)[0]


def test_where_the_job_stands(store):
    st = rc.standing(store, TARGET)
    assert st["forecast"] == D(2026, 12, 11)
    assert st["behind"] == 8 and st["calendar_days"] == 10
    assert [r["name"] for r in st["critical"]] == \
        ["Mobilize", "Excavate", "Footings", "Walls"]
    # the target defaults to the milestone's baseline finish
    sc = act(store, "Substantial Completion")
    sc["baseline_finish"] = "2026-12-04"
    store.save_record("activity", sc)
    assert rc.default_target(store) == D(2026, 12, 4)


def test_techniques_on_a_copy(store):
    plan = rc.new_plan(TARGET)
    plan["steps"] = [{"id": act(store, "Excavate")["_id"],
                      "technique": "crash", "duration": 7, "was": 10}]
    ev = rc.evaluate(store, plan)
    assert ev["recovered"] == 3 and ev["behind"] == 5 and not ev["on_time"]
    assert act(store, "Excavate")["duration"] == 10      # live untouched
    plan["steps"].append({"id": act(store, "Walls")["_id"],
                          "technique": "fast_track",
                          "pred": act(store, "Footings")["_id"],
                          "overlap": 3})
    ev = rc.evaluate(store, plan)
    assert ev["behind"] == 2
    w = next(a for a in rc.changed_acts(store, plan) if a["name"] == "Walls")
    # SS + FF 0: the walls can start early but not finish before footings
    assert w["preds"] == [{"id": "A0003", "type": "SS", "lag": 5},
                          {"id": "A0003", "type": "FF", "lag": 0}]
    plan["steps"].append({"id": act(store, "Footings")["_id"],
                          "technique": "resequence",
                          "pred": act(store, "Excavate")["_id"]})
    ev = rc.evaluate(store, plan)
    assert ev["on_time"] and ev["forecast"] < TARGET


def test_suggest_meets_the_target(store):
    plan = rc.suggest(store, TARGET)
    assert plan["steps"] and all(s["suggested"] for s in plan["steps"])
    assert rc.evaluate(store, plan)["on_time"]
    # nothing to do when the job is on time
    assert rc.suggest(store, D(2027, 1, 15))["steps"] == []


def test_apply_and_history(store):
    plan = rc.suggest(store, TARGET)
    plan["cause"] = "weather"
    n = rc.apply(store, plan, D(2026, 10, 21))
    assert n >= 1
    ex = act(store, "Excavate")
    assert ex["duration"] < 10
    assert "Recovery plan Oct 21, 2026: Crash: 10 -> " in ex["notes"]
    assert rc.standing(store, TARGET)["behind"] <= 0
    assert store.setting("recovery_plan")["status"] == "Applied"
    assert len(store.setting("recovery_history")) == 1


def test_owner_report(store, tmp_path):
    plan = rc.suggest(store, TARGET)
    plan["cause"], plan["cause_note"] = "weather", "11 rain days in Nov."
    plan["steps"][0].update(cost=4500, agreed=True)
    p = rc.export_pdf(store, str(tmp_path / "rec.pdf"), plan,
                      D(2026, 10, 21))
    doc = fitz.open(p)
    t = "".join(pg.get_text() for pg in doc)
    assert "WHERE THE JOB STANDS" in t           # headings print in caps
    for w in ("Recovery Schedule", "8 workday(s)",
              "Weather beyond normal", "time-extension", "Crash",
              "$4,500", "Revised completion", "On time", "Revised schedule (recovery plan)",
              "DRAFT - not yet in the schedule"):
        assert w in t, w
    assert doc.page_count >= 2                       # + the Gantt
    assert "Sub agreed" in t and "Added cost" in t   # headers not clipped
    # the footer counts the Gantt pages too (was "Page 1 of 1")
    n = doc.page_count
    assert f"Page 1 of {n}" in doc[0].get_text()
    assert f"Page {n} of {n}" in doc[n - 1].get_text()


SCRIPT = [
    '{"steps":[{"activity":"A0002","technique":"crash","new_duration":2},'
    '{"activity":"A0004","technique":"crash","new_duration":7,'
    '"how":"second wall crew","why":"longest critical","risk":"cost"},'
    '{"activity":"A0099","technique":"crash","new_duration":3}],'
    '"summary":"Crash the walls."}',
    'Sure! {"steps":[{"activity":"A0004","technique":"fast_track",'
    '"predecessor":"A0003","overlap":3,"how":"start walls at first pour"}]'
    ',"summary":"Overlap walls."}',
    '{"steps":[{"activity":"Excavate","technique":"crash",'
    '"new_duration":7,"how":"second excavator"}]}',
]


def test_ai_loop_checks_every_step(store):
    prompts = []
    answers = iter(SCRIPT)

    def ask(p):
        prompts.append(p)
        return next(answers)
    plan = rc.new_plan(TARGET)
    plan["cause"] = "weather"
    out = ra.run(store, plan, "No second crew on footings.", ask=ask)
    assert out["rounds"] == 3 and out["result"]["on_time"]
    assert [s["technique"] for s in out["steps"]] == \
        ["crash", "fast_track", "crash"]
    assert any("cuts more than half" in r for r in out["rejected"])
    assert any("no activity 'A0099'" in r for r in out["rejected"])
    assert "No second crew on footings." in prompts[0]
    assert "Behind: 8 workdays" in prompts[0]
    assert "Weather beyond normal" in prompts[0]
    assert "still 5 workday(s) late" in prompts[1]        # feedback
    assert plan["steps"] == []                    # proposals only
    # a broken answer is reported and retried, not a crash
    junk = iter(["no json here", SCRIPT[1]])
    out = ra.run(store, rc.new_plan(TARGET), ask=lambda p: next(junk),
                 rounds=2)
    assert "could not be read" in out["log"][0] or \
        "didn't answer" in out["log"][0]


def test_dialog(qapp_pm, store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.pm import center
    from app.pm.recovery_ui import RecoveryDialog
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    w = center.ProjectCenter(store)
    page = w.show_tool("gantt")
    d = page.recovery()
    from PySide6.QtCore import QDate
    d.target.setDate(QDate(2026, 12, 1))
    QApplication.processEvents()
    assert "8 workday(s)" in d.stand.text()
    assert d.crit.count() == 4
    d.suggest()
    assert d.table.rowCount() >= 1 and "meets the target" in \
        d.result.text()
    d.cause.setCurrentIndex(d.cause.findData("weather"))
    assert d.report(str(tmp_path / "r.pdf"))
    d.save()
    assert store.setting("recovery_plan")["cause"] == "weather"
    # the AI helper with a scripted model, picking every proposal
    script = iter(SCRIPT)
    d2 = RecoveryDialog(store, None, None, ask=lambda p: next(script))
    d2.plan["steps"] = []
    d2.plan["target"] = TARGET.isoformat()
    d2._fill_table()
    d2.ai_help(wait=True, accept=lambda out: out["steps"])
    QApplication.processEvents()
    assert d2.table.rowCount() == 3
    assert d2.apply(confirm=False) >= 1
    assert schedule.compute(store)["finish"] <= TARGET
    w.close()


# ------------------------------------------------ review 0.12.32 fixes
def _acts(s):
    """The activities as stored, without the bookkeeping fields."""
    return {a["_id"]: {k: v for k, v in a.items() if not k.startswith("_")}
            for a in s.list("activity")}


def test_criticality_is_toward_the_milestone(store):
    # a long activity that doesn't lead to Substantial Completion is
    # "critical" to CPM (it finishes last) but can't win any time back
    store.save_record("activity", {"name": "Landscaping", "duration": 62,
                                   "start": "2026-11-02"})
    land = act(store, "Landscaping")["_id"]
    cpm = schedule.compute(store, schedule.data_date(store))
    assert land in cpm["critical"]                 # CPM's longest path
    st = rc.standing(store, TARGET)
    assert st["milestone"] == "Substantial Completion"
    assert [r["name"] for r in st["critical"]] == \
        ["Mobilize", "Excavate", "Footings", "Walls"]
    fl = rc.driving(st["cpm"])
    assert land not in fl and fl[act(store, "Site lighting")["_id"]] > 0
    plan = rc.suggest(store, TARGET)
    assert plan["steps"] and all(s["id"] != land for s in plan["steps"])
    assert rc.evaluate(store, plan)["on_time"]
    assert "Landscaping" not in ra.brief(store, rc.new_plan(TARGET))


def test_fast_track_keeps_finish_after_predecessor(store):
    store.save_record("activity", {"name": "Cure check", "duration": 2,
                                   "preds": [{"id": "A0003"}]})
    cc = act(store, "Cure check")["_id"]
    foot = act(store, "Footings")["_id"]
    plan = rc.new_plan(TARGET)
    plan["steps"] = [{"id": cc, "technique": "fast_track", "pred": foot,
                      "overlap": 7}]
    rows = {r["name"]: r for r in rc.evaluate(store, plan)["cpm"]["rows"]}
    assert rows["Cure check"]["es"] < rows["Footings"]["ef"]   # overlaps
    assert rows["Cure check"]["ef"] >= rows["Footings"]["ef"]  # FF 0
    # an overlap as long as the predecessor is not made SS 0: it's
    # ignored, with a note
    plan["steps"][0]["overlap"] = 8
    ev = rc.evaluate(store, plan)
    c = next(a for a in rc.changed_acts(store, plan) if a["_id"] == cc)
    assert c["preds"] == [{"id": "A0003"}]
    assert any("fast-track ignored" in n and "not shorter" in n
               for n in ev["notes"])
    assert ev["recovered"] == 0


def _one(store, raw, plan=None, limits=""):
    return ra.check(store, plan or rc.new_plan(TARGET), raw, limits)


def test_ai_check_rejects_fake_recovery(store):
    # the three shapes llama3.2 got through: a fast-track on the
    # milestone, two steps on one link, and a resequence
    ok, bad = _one(store, [{"activity": "A0006", "technique": "fast_track",
                            "predecessor": "A0004", "overlap": 2}])
    assert ok == [] and "milestone" in bad[0]
    ok, bad = _one(store, [{"activity": "A0006", "technique": "crash",
                            "new_duration": 1}])
    assert ok == [] and "milestone" in bad[0] and "-1" not in bad[0]
    ok, bad = _one(store, [{"activity": "A0006", "technique": "resequence",
                            "predecessor": "A0005"}])
    assert ok == [] and "milestone" in bad[0]
    two = [{"activity": "A0004", "technique": "fast_track",
            "predecessor": "A0003", "overlap": 3},
           {"activity": "A0004", "technique": "fast_track",
            "predecessor": "A0003", "overlap": 4}]
    ok, bad = _one(store, two)
    assert len(ok) == 1 and "one step per link" in bad[0]
    ok, bad = _one(store, [{"activity": "A0004", "technique": "resequence",
                            "predecessor": "A0003"}])
    assert len(ok) == 1 and ok[0]["needs_ok"] and bad == []
    ok, _bad = _one(store, [{"activity": "A0004", "technique": "resequence",
                             "predecessor": "A0003"}],
                    limits="Saturdays OK. Resequencing is allowed.")
    assert not ok[0].get("needs_ok")
    ok, _bad = _one(store, [{"activity": "A0004", "technique": "resequence",
                             "predecessor": "A0003"}],
                    limits="No resequencing.")
    assert ok[0]["needs_ok"]
    # a step already in the plan counts: one crash per activity, one
    # step per link
    plan = rc.new_plan(TARGET)
    plan["steps"] = [{"id": act(store, "Walls")["_id"],
                      "technique": "crash", "duration": 8, "was": 10},
                     {"id": act(store, "Walls")["_id"],
                      "technique": "fast_track", "overlap": 2,
                      "pred": act(store, "Footings")["_id"]}]
    ok, bad = _one(store, [{"activity": "A0004", "technique": "crash",
                            "new_duration": 7},
                           {"activity": "A0004", "technique": "resequence",
                            "predecessor": "A0003"}], plan)
    assert ok == [] and "one crash per activity" in bad[0]
    assert "one step per link" in bad[1]
    # overlap: under the predecessor and at most half of it (Footings 8)
    ok, bad = _one(store, [{"activity": "A0004", "technique": "fast_track",
                            "predecessor": "A0003", "overlap": 5}])
    assert ok == [] and "1 to 4 workdays" in bad[0]
    ok, bad = _one(store, [{"activity": "A0004", "technique": "fast_track",
                            "predecessor": "A0003", "overlap": 4}])
    assert ok[0]["overlap"] == 4


def test_ai_resequence_needs_ok_and_does_not_count(store):
    answer = ('{"steps":[{"activity":"A0004","technique":"resequence",'
              '"predecessor":"A0003","how":"walls on spread footings"}]}')
    out = ra.run(store, rc.new_plan(TARGET), ask=lambda p: answer,
                 rounds=2)
    assert len(out["steps"]) == 1 and out["steps"][0]["needs_ok"]
    assert not out["result"]["on_time"]           # not counted
    assert any("one step per link" in r for r in out["rejected"])


def test_ai_error_keeps_earlier_rounds(store):
    from app.ai.review import AIError
    calls = []

    def ask(p):
        calls.append(p)
        if len(calls) == 1:
            return SCRIPT[0]
        raise AIError("Ollama error 500: unexpected EOF")
    out = ra.run(store, rc.new_plan(TARGET), ask=ask)
    assert [s["technique"] for s in out["steps"]] == ["crash"]
    assert "AI stopped at round 2: Ollama error 500: unexpected EOF" in \
        out["log"]
    assert out["failed_round"] == 2 and out["result"]["recovered"] == 3

    def down(p):
        raise ConnectionError("Ollama isn't running")
    out = ra.run(store, rc.new_plan(TARGET), ask=down)
    assert out["steps"] == [] and out["failed_round"] == 1
    assert out["log"] == ["AI stopped at round 1: Ollama isn't running"]


def _fast_track_plan(store):
    plan = rc.new_plan(TARGET)
    plan["steps"] = [{"id": act(store, "Excavate")["_id"],
                      "technique": "crash", "duration": 7, "was": 10},
                     {"id": act(store, "Walls")["_id"],
                      "technique": "fast_track",
                      "pred": act(store, "Footings")["_id"],
                      "overlap": 3}]
    return plan


def test_apply_then_revert_restores_exactly(store):
    sc = act(store, "Walls")
    sc["preds"] = [{"id": "A0003", "type": "FS", "lag": 1}]
    sc["notes"] = "Walls by XYZ Masonry"
    store.save_record("activity", sc)
    before = _acts(store)
    assert rc.revert_last(store) is None          # nothing applied yet
    n = rc.apply(store, _fast_track_plan(store), D(2026, 10, 21))
    assert n == 2
    assert "notes" not in act(store, "Mobilize")      # untouched
    h = store.setting("recovery_history")[-1]
    walls = next(b for b in h["before"] if b["_id"] == sc["_id"])
    assert walls["preds"] == [{"id": "A0003", "type": "FS", "lag": 1}]
    assert walls["duration"] == 10 and walls["notes"] == \
        "Walls by XYZ Masonry"
    ex = next(b for b in h["before"] if b["_id"] ==
              act(store, "Excavate")["_id"])
    assert "notes" in ex["_absent"]
    assert _acts(store) != before
    assert rc.last_applied(store) is not None
    assert rc.revert_last(store, D(2026, 10, 22)) == 2
    assert _acts(store) == before                 # exactly as it was
    assert store.setting("recovery_history")[-1]["reverted"] == \
        "2026-10-22"
    assert store.setting("recovery_plan")["status"] == "Draft"
    assert rc.last_applied(store) is None and rc.revert_last(store) is None


def test_revert_after_reopen(store):
    before = _acts(store)
    rc.apply(store, _fast_track_plan(store), D(2026, 10, 21))
    store.flush(force=True)
    again = ProjectStore(store.folder)
    assert rc.revert_last(again) == 2
    again.flush(force=True)
    assert _acts(ProjectStore(store.folder)) == before


def test_dialog_revert_and_ai_fallback(qapp_pm, store, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.pm.recovery_ui import AIDialog, RecoveryDialog
    before = _acts(store)
    d = RecoveryDialog(store, None, None)
    d.plan = _fast_track_plan(store)
    d._fill_table()
    d.recalc()
    assert not d.revert_btn.isEnabled()
    assert d.apply(confirm=False) == 2
    assert d.revert_btn.isEnabled()
    assert d.revert(confirm=False) == 2
    assert _acts(store) == before and not d.revert_btn.isEnabled()
    # the AI is down in round 1: offer Suggest Steps instead
    d.plan["steps"] = []
    d._fill_table()

    def down(p):
        raise ConnectionError("Ollama isn't running")
    d.ask = down
    seen = []

    def pick(box):
        seen.append(box.text())
        return next(b for b in box.buttons() if b.text().replace("&", "")
                    == "Use Suggest Steps instead")
    monkeypatch.setattr(d, "_ask_box", pick)
    d.ai_help(wait=True, accept=lambda out: out["steps"])
    QApplication.processEvents()
    assert "Ollama isn't running" in seen[0]
    assert d.table.rowCount() >= 1 and "meets the target" in \
        d.result.text()
    # a resequence that needs the PM's OK shows unticked
    res = rc.evaluate(store, rc.new_plan(TARGET))
    out = {"summary": "", "result": res, "rejected": [], "error": "",
           "steps": [{"id": act(store, "Walls")["_id"],
                      "technique": "resequence", "needs_ok": True,
                      "pred": act(store, "Footings")["_id"]},
                     {"id": act(store, "Walls")["_id"],
                      "technique": "crash", "duration": 8, "was": 10}]}
    a = AIDialog(None, store, out)
    from PySide6.QtCore import Qt
    assert a.list.item(0).checkState() == Qt.Unchecked
    assert "needs PM OK" in a.list.item(0).text()
    assert a.list.item(1).checkState() == Qt.Checked
    assert [s["technique"] for s in a.chosen()] == ["crash"]
    a.list.item(0).setCheckState(Qt.Checked)
    assert "needs_ok" not in a.chosen()[0]
    d.close_dialog()


def test_closing_the_dialog_stops_the_ai(qapp_pm, store):
    import threading
    from PySide6.QtWidgets import QApplication
    from app.pm.recovery_ui import RecoveryDialog
    gate, calls = threading.Event(), []

    def ask(p):
        calls.append(p)
        gate.wait(10)
        return SCRIPT[1]
    d = RecoveryDialog(store, None, None, ask=ask)
    d.plan["steps"], d.plan["target"] = [], TARGET.isoformat()
    picked = []
    w = d.ai_help(accept=lambda out: picked.append(out) or out["steps"])
    d.close_dialog()
    gate.set()
    assert w.wait(10000)
    for _ in range(5):
        QApplication.processEvents()
    assert picked == [] and d.plan["steps"] == []
    assert len(calls) <= 1                         # no second round
