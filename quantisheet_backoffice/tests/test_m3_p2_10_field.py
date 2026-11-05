"""P2-10 field reports link (10.1-10.2): QuantiSheet's Daily Log manpower and
Time Card production quantities, read from the snapshot (no new daily log)."""
from quantisheet_backoffice import field, interface, jobs, timeentry

from .helpers import stage
from .m3_helpers import approve_time
from .test_p1_07_jobcost import seed_7_1


def _snap():
    s = stage(1)
    s["daily_logs"] = [
        {"id": "DL-031", "date": "2026-10-20", "status": "Submitted",
         "manpower": [{"company": "Example Builders", "trade": "Concrete",
                       "workers": "6", "hours": "8"},
                      {"company": "Example Framing", "trade": "Framing",
                       "workers": "4", "hours": "8"}]},
        {"id": "DL-032", "date": "2026-10-21", "status": "Submitted",
         "manpower": [{"company": "Example Builders", "trade": "Concrete",
                       "workers": "5", "hours": "8"}]}]
    s["timecards"].append(
        {"id": "TC-020", "date": "2026-10-16", "foreman": "R. Silva",
         "crew": [], "equipment": [],
         "production": [{"cost_code": "03-3000", "qty": "78", "unit": "CY",
                         "hours": "40"}]})
    return s


def test_snapshot_reads_daily_logs_and_rejects_bad_counts():
    s = _snap()
    s["daily_logs"].append({"id": "DL-033", "date": "2026-10-22",
                            "manpower": [{"company": "X", "workers": 2.5,
                                          "hours": "8"}]})
    snap = interface.load_snapshot(s)
    assert len(snap.sections["daily_logs"]) == 2
    assert snap.rejected[-1][0] == "daily_logs" and \
        "not a decimal string" in snap.rejected[-1][2]


def test_10_1_manpower_vs_approved_hours(office, job):
    jobs.import_snapshot(office, interface.load_snapshot(_snap()))
    seed_7_1(office, job)
    ids = []
    for n in range(5):
        wid = timeentry.add_worker(office, f"C{n}", "LAB")
        ids.append(timeentry.add_line(office, wid, "2026-10-20", job,
                                      "03-3000", "8"))
        ids.append(timeentry.add_line(office, wid, "2026-10-21", job,
                                      "03-3000", "8"))
    approve_time(office, ids)
    rows = {r["date"]: r for r in field.manpower(office, job)}
    d = rows["2026-10-20"]
    assert (d["log_workers"], d["log_hours"], d["approved_hours"]) == \
        (6, 4_800, 4_000)
    assert d["flag"] == "8.00 h difference"
    assert d["others"] == [{"company": "Example Framing", "workers": 4,
                            "hours": 3_200}]
    assert rows["2026-10-21"]["flag"] == ""


def test_10_2_unit_cost_by_code(office, job):
    jobs.import_snapshot(office, interface.load_snapshot(_snap()))
    seed_7_1(office, job)
    (u,) = [r for r in field.unit_costs(office, job) if r["code"] == "03-3000"]
    assert (u["qty"], u["unit"], u["actual"]) == ("120", "CY", 3_121_000)
    assert u["text"] == "$260.08 per CY"
