"""Schedule quality check: the DCMA 14-Point Assessment."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import schedule, schedule_check as sc            # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402
from test_schedule import _store                             # noqa: E402


def _blank(tmp_path, monkeypatch, name="job", start="2026-11-02",
           dd="2026-11-02"):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / name))
    s.set_setting("project_start", start)
    s.set_setting("data_date", dd)
    return s


def _add(s, **r):
    return s.save_record("activity", r)


def _by_no(s, no):
    return s.find("activity", _no=no)[0]


def _clean(tmp_path, monkeypatch):
    """A tidy FS network, baselined, statused at Oct 19 with the first
    three activities done on time and Footings under way."""
    s = _blank(tmp_path, monkeypatch, "clean", "2026-10-05", "2026-10-01")
    _add(s, name="Notice to Proceed", duration=0)
    _add(s, name="Mobilize", duration=3, preds=[{"id": "A0001"}])
    _add(s, name="Excavate", duration=5, preds=[{"id": "A0002"}])
    _add(s, name="Footings", duration=5, preds=[{"id": "A0003"}])
    _add(s, name="Walls", duration=10, preds=[{"id": "A0004"}])
    _add(s, name="Utilities", duration=4, preds=[{"id": "A0004"}])
    _add(s, name="Roof", duration=10, preds=[{"id": "A0005"},
                                             {"id": "A0006"}])
    _add(s, name="Finishes", duration=15, preds=[{"id": "A0007"}])
    _add(s, name="Substantial Completion", duration=0,
         preds=[{"id": "A0008"}])
    assert schedule.set_baseline(s) == 9
    for no, a_s, a_f in (("A0001", "2026-10-05", "2026-10-05"),
                         ("A0002", "2026-10-05", "2026-10-07"),
                         ("A0003", "2026-10-08", "2026-10-14")):
        r = _by_no(s, no)
        r.update(actual_start=a_s, actual_finish=a_f, status="Complete",
                 percent=100)
        s.save_record("activity", r)
    r = _by_no(s, "A0004")
    r.update(actual_start="2026-10-15", status="In Progress", percent=60)
    s.save_record("activity", r)
    s.set_setting("data_date", "2026-10-19")
    s.set_setting("contract_completion", "2026-12-11")
    return s


def _messy(tmp_path, monkeypatch):
    s = _blank(tmp_path, monkeypatch, "messy", "2026-11-02", "2026-11-16")
    done = dict(status="Complete", percent=100)
    _add(s, name="Start", duration=0, actual_start="2026-11-02",
         actual_finish="2026-11-02", baseline_finish="2026-11-02", **done)
    _add(s, name="Mobilize", duration=2, preds=[{"id": "A0001"}],
         actual_start="2026-11-02", actual_finish="2026-11-03",
         baseline_finish="2026-11-03", **done)
    _add(s, name="Excavate", duration=5, preds=[{"id": "A0002"}],
         baseline_finish="2026-11-10")                  # missed, not begun
    _add(s, name="Footings", duration=4,
         preds=[{"id": "A0003", "lag": -2}],            # a lead
         baseline_finish="2026-11-13")
    _add(s, name="Rebar", duration=3, preds=[{"id": "A0004", "type": "FF"}])
    _add(s, name="Framing", duration=60, preds=[{"id": "A0005"}])
    _add(s, name="Fence", duration=3, preds=[{"id": "A0002"}])  # dangling
    _add(s, name="Inspection", duration=1,
         preds=[{"id": "A0004", "lag": 3}],             # a lag
         actual_start="2026-12-01", status="In Progress")   # future actual
    _add(s, name="Permit", duration=2, start="2026-11-20",
         preds=[{"id": "A0002"}])
    _add(s, name="Close-out", duration=0,
         preds=[{"id": "A0006"}, {"id": "A0008"}, {"id": "A0009"}])
    s.set_setting("contract_completion", "2027-01-29")
    return s


def _items(res):
    return {it["key"]: it for it in res["items"]}


def _nos(item):
    return sorted(o["no"] for o in item["offenders"])


def test_shape_and_clean_schedule(tmp_path, monkeypatch):
    s = _clean(tmp_path, monkeypatch)
    res = sc.check(s)
    assert [it["key"] for it in res["items"]] == [k for k, _n in sc.POINTS]
    for it in res["items"]:
        assert set(it) >= {"key", "name", "metric", "threshold", "passed",
                           "offenders", "why"}
        assert it["why"] and it["passed"] in (True, False, None)
    it = _items(res)
    assert it["resources"]["passed"] is None
    for k in it:
        if k != "resources":
            assert it[k]["passed"] is True, (k, it[k])
    assert res["score"] == "13 of 13"
    assert "13 of 13" in res["summary"] and "1 n/a" in res["summary"]
    assert it["logic"]["metric"] == "0 of 6 (0.0%)"   # NTP + SC exempt
    assert it["bei"]["metric"].startswith("1.00 (3 done / 3 due)")
    assert it["neg_float"]["passed"] and "contract" in it["neg_float"]["note"]
    assert 0.95 <= res["cpli"] < 1.1
    text = sc.text_summary(res)
    assert "DCMA" in text and "Critical Path Test" in text


def test_target_missing_is_na(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)       # no baseline, no contract date
    it = _items(sc.check(s))
    for k in ("neg_float", "cpli", "bei", "missed", "resources"):
        assert it[k]["passed"] is None, k
    assert "target" in it["neg_float"]["note"].lower()
    # the sample schedule: open ends, an SS link and lags, an SNET date
    assert it["logic"]["passed"] is False
    assert _nos(it["logic"]) == ["A0001", "A0005", "A0007"]
    assert _nos(it["lags"]) == ["A0003", "A0005"]
    assert _nos(it["rel_types"]) == ["A0005"]
    assert it["rel_types"]["metric"] == "6 of 7 FS (85.7%)"
    # its only constraint is "start no earlier than": soft, listed apart
    assert it["constraints"]["passed"] is True
    assert _nos(it["constraints"]) == []
    assert [o["no"] for o in it["constraints"]["soft"]] == ["A0001"]
    assert "Soft: 1" in it["constraints"]["metric"]
    assert "soft" in it["constraints"]["note"]
    assert it["cp_test"]["passed"] is True
    # a contract date earlier than the forecast makes negative float
    s.set_setting("contract_completion", "2026-11-16")
    it = _items(sc.check(s))
    assert it["neg_float"]["passed"] is False
    assert "A0007" in _nos(it["neg_float"])           # Slab, critical
    assert "A0004" not in _nos(it["neg_float"])       # Survey has float
    assert it["cpli"]["passed"] is False


def test_messy_schedule(tmp_path, monkeypatch):
    s = _messy(tmp_path, monkeypatch)
    res = sc.check(s)
    it = _items(res)
    failed = {k for k, v in it.items() if v["passed"] is False}
    assert failed == {"logic", "leads", "lags", "high_float",
                      "neg_float", "high_duration", "invalid_dates",
                      "missed", "cpli", "bei"}
    logic = {o["no"]: o["detail"] for o in it["logic"]["offenders"]}
    assert set(logic) == {"A0005", "A0007"}
    assert logic["A0007"] == "No successor"                 # Fence
    assert logic["A0005"].startswith("Dangling start")      # Rebar: FF only
    assert _nos(it["leads"]) == ["A0004"]
    assert "-2" in it["leads"]["offenders"][0]["detail"]
    assert _nos(it["lags"]) == ["A0008"]
    assert it["rel_types"]["passed"] is True                # 9 of 10 = 90%
    assert it["rel_types"]["metric"] == "9 of 10 FS (90.0%)"
    assert _nos(it["rel_types"]) == ["A0005"]
    assert _nos(it["constraints"]) == []                    # SNET is soft
    assert [o["no"] for o in it["constraints"]["soft"]] == ["A0009"]
    assert _nos(it["high_float"]) == ["A0007", "A0008", "A0009"]
    assert _nos(it["high_duration"]) == ["A0006"]          # not milestones
    assert _nos(it["neg_float"]) == ["A0003", "A0004", "A0005", "A0006",
                                     "A0010"]
    inv = {o["no"]: o["detail"] for o in it["invalid_dates"]["offenders"]}
    assert set(inv) == {"A0003", "A0007", "A0008"}
    assert "after the data date" in inv["A0008"]
    assert "Not started" in inv["A0003"]
    assert _nos(it["missed"]) == ["A0003", "A0004"]
    assert it["missed"]["metric"] == "2 of 4 (50.0%)"
    assert res["bei"] == 0.5
    assert it["bei"]["metric"].startswith("0.50 (2 done / 4 due)")
    assert res["cpli"] < 0.95
    text = sc.text_summary(res)
    assert "Fence" in text and "FAIL" in text


def test_critical_path_test(tmp_path, monkeypatch):
    s = _blank(tmp_path, monkeypatch)
    _add(s, name="Start", duration=0)
    _add(s, name="Layout", duration=2, preds=[{"id": "A0001"}])
    _add(s, name="Install", duration=10,
         preds=[{"id": "A0002", "type": "SS"}])
    _add(s, name="Done", duration=0, preds=[{"id": "A0003"}])
    # Layout is "critical" only through a start-to-start link: making it
    # longer doesn't drive the finish one for one - a broken path
    cp = sc.cp_test(s)
    assert cp["activity"]["name"] == "Layout"
    assert cp["passed"] is False
    assert (cp["act_shift"], cp["finish_shift"]) == (600, 592)
    it = _items(sc.check(s))["cp_test"]
    assert it["passed"] is False and _nos(it) == ["A0002"]
    assert "592" in it["offenders"][0]["detail"]
    # Install drives the finish
    inst = s.find("activity", name="Install")[0]["_id"]
    assert sc.cp_test(s, act_id=inst)["passed"] is True
    # linked finish-to-start instead, the test passes; nothing is saved
    lay = s.find("activity", name="Install")[0]
    lay["preds"] = [{"id": "A0002"}]
    s.save_record("activity", lay)
    assert sc.cp_test(s)["passed"] is True
    assert s.find("activity", name="Layout")[0]["duration"] == 2
    # nothing critical left to test -> n/a
    s2 = _blank(tmp_path, monkeypatch, "empty")
    assert sc.cp_test(s2)["passed"] is None


def test_bei_numbers(tmp_path, monkeypatch):
    s = _blank(tmp_path, monkeypatch, dd="2026-11-20")
    for i in range(20):
        _add(s, name=f"Task {i + 1}", duration=1,
             baseline_finish="2026-11-10" if i < 10 else "2026-12-10")
    for i in range(9):                   # 9 of the 10 due are done
        r = _by_no(s, f"A{i + 1:04d}")
        r.update(actual_start="2026-11-05", actual_finish="2026-11-06",
                 status="Complete")
        s.save_record("activity", r)
    res = sc.check(s)
    it = _items(res)
    assert res["bei"] == 0.9 and it["bei"]["passed"] is False
    assert _nos(it["bei"]) == ["A0010"]
    assert it["missed"]["metric"] == "1 of 10 (10.0%)"
    # one more finished (early, ahead of its baseline) brings it to 1.0
    r = _by_no(s, "A0015")
    r.update(actual_start="2026-11-09", actual_finish="2026-11-09",
             status="Complete")
    s.save_record("activity", r)
    assert sc.check(s)["bei"] == 1.0
    assert _items(sc.check(s))["bei"]["passed"] is True
    # finished, but after the baseline finish: missed, still counts in BEI
    r = _by_no(s, "A0010")
    r.update(actual_start="2026-11-12", actual_finish="2026-11-13",
             status="Complete")
    s.save_record("activity", r)
    res = sc.check(s)
    assert res["bei"] == 1.1
    m = _items(res)["missed"]
    assert _nos(m) == ["A0010"] and "finished 2026-11-13" in \
        m["offenders"][0]["detail"]


def test_offenders_capped(tmp_path, monkeypatch):
    s = _blank(tmp_path, monkeypatch)
    for i in range(60):
        _add(s, name=f"Loose {i}", duration=3)
    it = _items(sc.check(s))["logic"]
    assert it["passed"] is False and it["count"] == 60
    assert len(it["offenders"]) == 50


def test_export_pdf(tmp_path, monkeypatch):
    s = _messy(tmp_path, monkeypatch)
    p = sc.export_pdf(s, str(tmp_path / "dcma.pdf"), today="2026-11-16")
    d = fitz.open(p)
    assert d[0].rect.width == 612 and d[0].rect.height == 792    # Letter
    text = " ".join(" ".join(pg.get_text().split()) for pg in d)
    assert "DCMA" in text and "Schedule Quality Check" in text
    for _k, name in sc.POINTS:
        assert name in text, name
    assert "Fence" in text and "FAIL" in text
    assert "Start no earlier than 2026-11-20" in text
    d.close()
    s2 = _clean(tmp_path, monkeypatch)
    p2 = sc.export_pdf(s2, str(tmp_path / "clean.pdf"))
    assert "DCMA" in fitz.open(p2)[0].get_text()


def _ten(tmp_path, monkeypatch, name="ten"):
    """A made-up 10-activity network: one critical chain and a short
    parallel branch, all finish-to-start."""
    s = _blank(tmp_path, monkeypatch, name, "2026-11-02", "2026-11-02")
    _add(s, name="Notice to Proceed", duration=0)                   # A0001
    _add(s, name="Mobilize", duration=3, preds=[{"id": "A0001"}])   # A0002
    _add(s, name="Excavate", duration=5, preds=[{"id": "A0002"}])   # A0003
    _add(s, name="Footings", duration=5, preds=[{"id": "A0003"}])   # A0004
    _add(s, name="Walls", duration=8, preds=[{"id": "A0004"}])      # A0005
    _add(s, name="Underground", duration=3,
         preds=[{"id": "A0004"}])                                   # A0006
    _add(s, name="Slab", duration=4, preds=[{"id": "A0005"},
                                            {"id": "A0006"}])       # A0007
    _add(s, name="Roof", duration=6, preds=[{"id": "A0007"}])       # A0008
    _add(s, name="Finishes", duration=10, preds=[{"id": "A0008"}])  # A0009
    _add(s, name="Substantial Completion", duration=0,
         preds=[{"id": "A0009"}])                                   # A0010
    return s


def test_hard_and_soft_constraints(tmp_path, monkeypatch):
    """Review 0.12.34 #16: only MSO / MFO / SNLT / FNLT count in point 5;
    start / finish no earlier than are soft and listed as 'Soft: n'."""
    s = _ten(tmp_path, monkeypatch)
    for no, when in (("A0006", "2026-11-16"), ("A0008", "2026-11-30")):
        a = _by_no(s, no)
        a["start"] = when                         # start no earlier than
        s.save_record("activity", a)
    it = _items(sc.check(s))["constraints"]
    assert it["passed"] is True and it["count"] == 0
    assert "Soft: 2" in it["metric"]
    assert sorted(o["no"] for o in it["soft"]) == ["A0006", "A0008"]
    # a typed / imported hard constraint does count
    a = _by_no(s, "A0005")
    a.update(constraint="Must Finish On", constraint_date="2026-12-01")
    s.save_record("activity", a)
    a = _by_no(s, "A0009")
    a.update(constraint="FNET", constraint_date="2027-01-04")
    s.save_record("activity", a)
    it = _items(sc.check(s))["constraints"]
    assert _nos(it) == ["A0005"] and "Must finish on" in \
        it["offenders"][0]["detail"]
    assert "Soft: 3" in it["metric"]
    assert it["passed"] is False                  # 1 of 10 > 5%
    for text, code in (("MSO", "MSO"), ("mfo", "MFO"), ("CS_MSOB", "SNLT"),
                       ("Finish No Later Than", "FNLT"), ("SNET", "SNET"),
                       ("ASAP", ""), ("", ""), (None, "")):
        assert sc.constraint_code(text) == code, text


def test_dangling_starts_and_finishes(tmp_path, monkeypatch):
    """Review 0.12.34 #16: an activity whose only successor is
    start-to-start (dangling finish) and one whose only predecessor is
    finish-to-finish (dangling start) count in the Logic point."""
    s = _ten(tmp_path, monkeypatch)
    assert _items(sc.check(s))["logic"]["count"] == 0
    # Underground's only successor becomes start-to-start
    a = _by_no(s, "A0007")
    a["preds"] = [{"id": "A0005"}, {"id": "A0006", "type": "SS"}]
    s.save_record("activity", a)
    lg = _items(sc.check(s))["logic"]
    assert _nos(lg) == ["A0006"]
    assert lg["offenders"][0]["detail"].startswith("Dangling finish")
    # Roof's only predecessor becomes finish-to-finish
    a = _by_no(s, "A0008")
    a["preds"] = [{"id": "A0007", "type": "FF"}]
    s.save_record("activity", a)
    lg = _items(sc.check(s))["logic"]
    assert _nos(lg) == ["A0006", "A0008"]
    det = {o["no"]: o["detail"] for o in lg["offenders"]}
    assert det["A0008"].startswith("Dangling start")
    # SS plus FF (a fast-track) ties both ends: not dangling
    a["preds"] = [{"id": "A0007", "type": "SS", "lag": 2},
                  {"id": "A0007", "type": "FF"}]
    s.save_record("activity", a)
    assert _nos(_items(sc.check(s))["logic"]) == ["A0006"]


def test_critical_path_test_moves_the_whole_path(tmp_path, monkeypatch):
    """Review 0.12.34 #16: the first critical activity delayed by a big
    amount moves the project finish - and every activity on its driving
    path - by the same amount."""
    s = _ten(tmp_path, monkeypatch)
    cp = sc.cp_test(s)
    assert cp["activity"]["name"] == "Mobilize"   # first unstarted, not a
    assert cp["passed"] is True                   # milestone
    assert cp["act_shift"] == sc.CP_ADD == cp["finish_shift"]
    path = {p["no"]: p["shift"] for p in cp["path"]}
    # the driving path: Excavate .. Substantial Completion, not the
    # Underground branch (it has float)
    assert set(path) == {"A0003", "A0004", "A0005", "A0007", "A0008",
                         "A0009", "A0010"}
    assert set(path.values()) == {sc.CP_ADD}
    assert "7 activities on its driving path" in cp["detail"]
    # the delay as a what-if: nothing saved
    assert _by_no(s, "A0002")["duration"] == 3
    # break the path: Walls follows Footings start-to-start only, so
    # Footings is "critical" through that link alone. Made 600 longer, its
    # finish runs on by itself - the finish moves less than 600, and the
    # detail says where the path breaks
    a = _by_no(s, "A0005")
    a.update(preds=[{"id": "A0004", "type": "SS"}], duration=5)
    s.save_record("activity", a)
    a = _by_no(s, "A0006")
    a["preds"] = [{"id": "A0003"}]
    s.save_record("activity", a)
    foot = _by_no(s, "A0004")["_id"]
    cp = sc.cp_test(s, act_id=foot)
    assert cp["passed"] is False
    assert cp["act_shift"] == sc.CP_ADD and cp["finish_shift"] < sc.CP_ADD
    assert {p["no"]: p["shift"] for p in cp["path"]}["A0005"] == 0
    assert "path breaks at A0005 Walls moves 0" in cp["detail"]
    # ... and the Logic point names Footings' dangling finish
    lg = _items(sc.check(s))["logic"]
    assert "A0004" in _nos(lg)
