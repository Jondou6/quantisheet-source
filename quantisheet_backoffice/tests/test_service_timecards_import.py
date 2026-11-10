"""Service tech hours arrive as time cards (Nov 5). The snapshot below is
the shape app/service/timecards.py writes (interface v1, the "Service
Department" job, one card per logged entry, ids "svc:<entry>"). Back
Office imports each entry once, however often it is sent."""
from quantisheet_backoffice import interface, jobs, timeentry


def _snap(extra=()):
    cards = [{"id": "svc:e1", "date": "2026-11-02", "foreman": "A Tester",
              "crew": [{"name": "A Tester", "class": "Service Tech",
                        "hours": "2"}], "equipment": [],
              "production": [{"cost_code": "SV-100", "qty": "1", "unit": "ea",
                              "hours": "2"}]},
             {"id": "svc:e2", "date": "2026-11-03", "foreman": "B Tester",
              "crew": [{"name": "B Tester", "class": "Service Tech",
                        "hours": "1.25"}], "equipment": [],
              "production": [{"cost_code": "SV-100", "qty": "1", "unit": "ea",
                              "hours": "1.25"}]}] + list(extra)
    return {"interface_version": 1,
            "source": {"app": "QuantiSheet test", "file": "service work "
                       "orders", "folder": "", "taken_at": "2026-11-05T09:00"},
            "project": {"name": "Service Department", "number": "SERVICE",
                        "address": "", "owner": "", "contractor": "",
                        "architect": "", "contract_no": "",
                        "contract_date": "", "state": ""},
            "cost_codes": [], "budget": [], "estimate": [], "activities": [],
            "contract": {"retainage_work": "0", "retainage_stored": "0",
                         "sov": []},
            "changes": [], "payapps": [], "commitments": [],
            "direct_costs": [], "timecards": cards, "directory": [],
            "daily_logs": []}


def test_each_entry_once(office):
    office.act_as("ap@bo.test")
    snap = interface.load_snapshot(_snap())
    assert not snap.rejected
    job = jobs.import_snapshot(office, snap).job_id
    ids = timeentry.import_timecards(office, job)
    rows = [office.db.get("time_lines", i) for i in ids]
    assert sorted((r["date"], r["hours"]) for r in rows) == \
        [("2026-11-02", 200), ("2026-11-03", 125)]
    assert timeentry.import_timecards(office, job) == []     # never twice
    more = {"id": "svc:e3", "date": "2026-11-04", "foreman": "A Tester",
            "crew": [{"name": "A Tester", "class": "Service Tech",
                      "hours": "1"}], "equipment": [], "production": []}
    job2 = jobs.import_snapshot(office, interface.load_snapshot(
        _snap([more]))).job_id
    assert job2 == job                                       # same job
    new = timeentry.import_timecards(office, job)
    assert len(new) == 1
