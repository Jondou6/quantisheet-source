"""QuantiSheet 1.2 phase 1 (Nov 5): the 2026 refrigerant rules - 40 CFR
84.106 for HFCs (GWP > 53) at 15 lb and up, 82.157 for ozone-depleting
refrigerants at 50 lb and up - repair clocks, migration of 1.1.1 units,
owner records, recovery and cylinders. Made-up data only."""
import json

import fitz
import pytest

from app.service import recovery, refrigerant as R, refrigerant_rules as RR
from r111_support import isolate, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _pdf_text(path, page=0):
    with fitz.open(path) as d:
        return d[page].get_text()


def _pdf_fields(path, page=0):
    with fitz.open(path) as d:
        return {w.field_name: w.field_value for w in d[page].widgets() or []}


def _eq(rec, prop, n):
    from app.estimating import service
    return service.add_equipment(rec, prop, "RTU", make="TestCo",
                                 model=f"M{n}", serial=f"SN-{n}")


def _u(st, rec, eq, gas, charge, cls, gwp=None, res=False,
       cat="comfort_cooling"):
    return R.add_unit(st, rec, eq, gas, charge, cat, ref_class=cls,
                      gwp_over_53=gwp, residential_ac=res)


def test_which_rule_applies_at_the_edges():
    rec, prop, _e = records()
    st = R.blank()
    cases = [("R-410A", "14.999", "hfc", True, False, None),
             ("R-410A", "15", "hfc", True, False, "84.106"),
             ("R-410A", "200", "hfc", True, True, None),      # residential
             ("R-1234YF", "40", "hfc", False, False, None),   # GWP <= 53
             ("R-22", "49.999", "ods", None, False, None),
             ("R-22", "50", "ods", None, False, "82.157"),
             ("R-290", "60", "other", None, False, None)]
    for n, (gas, charge, cls, gwp, res, want) in enumerate(cases):
        uid = _u(st, rec, _eq(rec, prop, n), gas, charge, cls, gwp, res)
        got = R.applicability(st, uid)
        assert got["rule"] == want, (gas, charge, got)
        assert not got["needs_review"]
    uid = _u(st, rec, _eq(rec, prop, 99), "R-410A", "30", "hfc", None)
    assert R.applicability(st, uid)["needs_review"]       # GWP not known
    blend = R.add_unit(st, rec, _eq(rec, prop, 98), "R-999X", "30",
                       "comfort_cooling")
    u = R._unit(st, blend)
    assert u["needs_review"] and u["suggested"]["ref_class"] == "unknown"


def test_1_1_1_units_are_flagged_for_review_never_reclassified(tmp_path):
    rec, prop, eq = records()
    old = {"kind": R.KIND, "version": 1, "log": [],
           "units": [{"id": "u1", "equipment_id": eq, "property_id": prop,
                      "unit": "Furnace", "refrigerant": "R-22",
                      "full_charge": "60.000", "category": "comfort_cooling",
                      "charge_date": ""}],
           "visits": [{"id": "v1", "unit_id": "u1", "date": "2026-02-01",
                       "lbs_added": "9.000", "lbs_recovered": "0.000",
                       "cylinder": "C1", "cert_no": "608-1", "tech": "T",
                       "notes": ""}]}
    p = tmp_path / "old.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    st = R.load(str(p))
    u = st["units"][0]
    assert u["ref_class"] == "unknown" and u["needs_review"]
    assert u["suggested"]["ref_class"] == "ods"           # a suggestion only
    info = R.leak_rate(st, "u1")
    assert info["rule"] is None and info["needs_review"]
    assert any("Confirm the refrigerant class" in d[2] for d in R.due(st))
    R.confirm_class(st, "u1", "ods", why="R-22 per nameplate")
    assert R.applicability(st, "u1")["rule"] == "82.157"
    assert R.history(st, "u1")[-1]["action"] == "confirm class"
    R.confirm_class(st, "u1", "hfc", gwp_over_53=True, why="retrofit")
    assert "keep the rule they were logged under" in \
        R._unit(st, "u1")["reclassified_note"]


def test_repair_clock_opens_once_and_closes_after_both_tests():
    rec, prop, eq = records()
    st = R.blank()
    uid = R.add_unit(st, rec, eq, "R-410A", "100", "comfort_cooling",
                     charge_date="2026-01-01", ref_class="hfc",
                     gwp_over_53=True)
    R.add_visit(st, uid, "2026-04-01", lbs_added="10", cylinder="C",
                cert_no="608-1", tech_type="Universal")
    c = R.open_clock(st, uid)
    assert c and c["rule"] == "84.106" and c["repair_by"] == "2026-05-01"
    assert st["visits"][0]["rule"] == "84.106"
    R.add_visit(st, uid, "2026-04-10", lbs_added="3", cylinder="C",
                cert_no="608-1")
    assert len(st["clocks"]) == 1 and len(c["additions"]) == 2  # no restart
    assert R.due(st, "2026-05-02")[0][3] is True                 # late
    with pytest.raises(R.RefError):
        R.set_shutdown(st, c["id"])         # not industrial
    R.record_repair(st, c["id"], "2026-04-20", "2026-04-20")
    assert c["followup_due"] == "2026-04-30"
    assert "Follow-up" in R.due(st, "2026-04-25")[0][2]
    R.record_followup(st, c["id"], "2026-04-28")
    assert c["status"] == "repaired" and R.open_clock(st, uid) is None
    # a unit under its limit, or not covered, opens nothing
    st2 = R.blank()
    small = R.add_unit(st2, rec, eq, "R-410A", "10", "comfort_cooling",
                       ref_class="hfc", gwp_over_53=True)
    R.add_visit(st2, small, "2026-04-01", lbs_added="5", cylinder="C",
                cert_no="608-1")
    assert R.leak_rate(st2, small)["over"] and not st2["clocks"]


def test_industrial_window_extension_retrofit_chronic_and_reports():
    rec, prop, eq = records()
    st = R.blank()
    uid = R.add_unit(st, rec, eq, "R-404A", "1600", "industrial_process",
                     charge_date="2026-01-01", ref_class="hfc",
                     gwp_over_53=True)
    assert "84.108" in R.auto_leak_detection_note(st, uid)
    R.add_visit(st, uid, "2026-02-01", lbs_added="1000", cylinder="C",
                cert_no="608-1")
    c = R.open_clock(st, uid)
    R.set_shutdown(st, c["id"])
    assert c["repair_by"] == "2026-06-01"                    # 120 days
    R.request_extension(st, c["id"], "2026-08-01", "compressor on order")
    assert R.due(st, "2026-07-01")[0][0] == "2026-08-01"
    R.add_visit(st, uid, "2026-03-01", lbs_added="1100", cylinder="C",
                cert_no="608-1", lbs_purged="2")
    R.retrofit_plan(st, c["id"], "replace with low-GWP rack", retire=False)
    kinds = [k for k, _u, _t in R.reportable(st, 2026)]
    assert set(kinds) == {"extension", "retrofit", "chronic leaker",
                          "purged"}
    ch = R.chronic_leakers(st, 2026)[0]
    assert ch["report_by"] == "2027-03-01" and ch["pct"] >= 125


def test_thresholds_are_editable_and_the_note_follows():
    rules = RR.load()
    assert rules["decision"] == "Refrigerant rule change approved by Jon " \
                                "on Nov 5, 2026."
    assert "NOT YET REVIEWED" in R.rule_note()
    rules["rules"]["84.106"]["min_lbs"] = "20"
    rules["reviewed"], rules["reviewer"], rules["review_date"] = \
        True, "A Tech", "2026-11-20"
    RR.save(rules)
    assert RR.load()["rules"]["84.106"]["min_lbs"] == "20"
    note = R.rule_note()
    assert "NOT YET REVIEWED" not in note and "A Tech" in note
    assert "20 lb" in note
    rec, prop, eq = records()
    st = R.blank()
    uid = R.add_unit(st, rec, eq, "R-410A", "18", "comfort_cooling",
                     ref_class="hfc", gwp_over_53=True)
    assert R.applicability(st, uid)["rule"] is None          # now 20 lb


def test_owner_record_has_the_84_106_fields(tmp_path, monkeypatch):
    use_company(monkeypatch)
    rec, prop, eq = records()
    st = R.blank()
    uid = R.add_unit(st, rec, eq, "R-410A", "30", "comfort_cooling",
                     ref_class="hfc", gwp_over_53=True, location="Roof")
    vid = R.add_visit(st, uid, "2026-05-02", lbs_added="2",
                      lbs_recovered="0.5", cylinder="CYL-7",
                      cert_no="608-55", tech="A Tester", tech_type="Type II",
                      parts="Schrader core", work_done="Leak search, fixed")
    path = R.owner_record_pdf(st, rec, vid, str(tmp_path / "o.pdf"))
    text = _pdf_text(path)
    for want in ("Roof", "2026-05-02", "Schrader core", "Leak search",
                 "A Tester", "Type II", "608-55", "2.000 lb", "0.500 lb",
                 "Test Plumbing Co"):
        assert want in text, want


def test_recovery_disposals_totals_transfers_cylinders(tmp_path,
                                                       monkeypatch):
    use_company(monkeypatch)
    st = recovery.blank()
    with pytest.raises(recovery.RecoveryError):
        recovery.add_disposal(st, "2026-05-01", "1 Test St", "R-22", "3",
                              full_charge="60")
    recovery.add_disposal(st, "2026-05-01", "1 Test St", "r-22", "3.5",
                          full_charge="8", appliance="Window AC")
    recovery.add_disposal(st, "2026-05-09", "2 Test St", "R-410A", "4",
                          full_charge="10")
    recovery.add_disposal(st, "2026-06-01", "3 Test St", "R-410A", "1")
    assert recovery.monthly_totals(st, 2026, 5) == {"R-22": "3.500",
                                                    "R-410A": "4.000"}
    recovery.add_transfer(st, "2026-05-20", "Test Reclaim Co", "R-22", "3.5",
                          "RC-1")
    cid = recovery.add_cylinder(st, "DC-1", "R-410A", "disposable",
                                "Truck 1")
    recovery.add_cylinder(st, "RC-1", "R-22", "recovery", "Truck 1")
    assert len(recovery.on_truck(st, "Truck 1")) == 2
    with pytest.raises(recovery.RecoveryError):
        recovery.add_cylinder(st, "DC-1", "R-410A")
    sid = recovery.empty_statement(st, cid, "2028-01-05", "vacuum",
                                   "A Tester", "608-55")
    assert recovery.statement_required("2028-01-05")
    assert not recovery.statement_required("2027-12-31")
    text = _pdf_text(recovery.statement_pdf(st, sid, str(tmp_path / "s.pdf")))
    assert "15 in-Hg" in text and "DC-1" in text and "signature" in text
    text = _pdf_text(recovery.disposal_log_pdf(st, 2026, 5,
                                               str(tmp_path / "m.pdf")))
    assert "Window AC" in text and "Test Reclaim Co" in text
    assert "3 Test St" not in text                         # June


def test_window_confirms_a_suggested_class_and_edits_rules(qapp, tmp_path):
    from app.estimating import service
    from app.service.refrigerant_ui import RefrigerantWindow
    rec, _p, _eq = records()
    service.save(rec)
    w = RefrigerantWindow()
    w.gas.setText("R-22")
    w.charge.setText("60")
    w.category.setCurrentIndex(w.category.findData("comfort_cooling"))
    w.add_unit_clicked()
    assert "Needs review" in w.table.item(0, 7).text()
    assert "Confirm the refrigerant class" in w.due_label.text()
    asked = []
    res = w.confirm_clicked(ask=lambda t: asked.append(t) or True)
    assert res["rule"] == "82.157" and "Ozone-depleting" in asked[0]
    assert w.due_label.text() == "Nothing due."
    w.added.setText("9")
    w.cylinder.setText("C1")
    w.cert.setText("608-1")
    w.when.setText("2026-06-01")
    w.add_visit_clicked()
    assert "Repair clock running" in w.msg.text()
    cd = w.clock_clicked()
    cd.repaired.setText("2026-06-10")
    cd.initial.setText("2026-06-10")
    assert cd.repair() and "Follow-up test due 2026-06-20" in cd.head.text()
    cd.followup.setText("bad")
    assert not cd.follow() and cd.err.text()
    cd.followup.setText("2026-06-18")
    assert cd.follow() and "repaired" in cd.head.text()
    cd.close()
    out = w.year_clicked(path=str(tmp_path / "y.pdf"), year=2026)
    assert "Nothing found for 2026" in _pdf_text(out)
    dlg = w.rules_clicked()
    dlg.fields[("repair_days",)].setText("x")
    assert dlg.save() is None and "isn't a number" in dlg.err.text()
    dlg.fields[("repair_days",)].setText("45")
    assert dlg.save()
    assert RR.load()["repair_days"] == 45
    rw = w.recovery_clicked()
    assert rw.windowTitle() == "Refrigerant Recovery & Cylinders"
    rw.close()
    w.close()
