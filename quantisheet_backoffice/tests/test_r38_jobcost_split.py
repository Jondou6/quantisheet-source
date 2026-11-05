"""r38 G2.5: job cost shows regular labor, overtime labor (OT and DT) and
per diem separately, by cost code, with hours. Regular + overtime = labor;
labor + AP + direct + per diem = actual. Made-up EXAMPLE rates only."""
from quantisheet_backoffice import exports, jobcost, perdiem, timeentry


def _approve_time(office, ids):
    timeentry.submit(office, ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, ids, "approve")
    office.act_as("admin@bo.test")


def _setup(office, job):
    timeentry.add_labor_class(office, "EXL", "Laborer EXAMPLE", "10.00", "0")
    wid = timeentry.add_worker(office, "W. Example", "EXL")
    ids = [timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8"),
           timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "2", pay_type="OT"),
           timeentry.add_line(office, wid, "2026-10-21", job, "03-3000", "1", pay_type="DT"),
           timeentry.add_line(office, wid, "2026-10-22", job, "03-3000", "8", pay_type="PTO")]
    _approve_time(office, ids)
    pid = perdiem.add(office, wid, "2026-10-20", job, "03-3000", "45.50")
    perdiem.submit(office, [pid])
    office.act_as("pm@bo.test")
    perdiem.decide(office, [pid], "approve")
    office.act_as("admin@bo.test")
    return wid


def test_r38_split_by_pay_type(office, job):
    base = jobcost.by_code(office, job)["03-3000"]
    _setup(office, job)
    r = jobcost.by_code(office, job)["03-3000"]
    # loaded rate 10.00: REG 8h 80.00 + PTO 8h 80.00 = 160.00; OT 2h x1.5 = 30.00; DT 1h x2 = 20.00
    assert r["labor_regular"] - base["labor_regular"] == 16000
    assert r["labor_overtime"] - base["labor_overtime"] == 5000
    assert r["hours_regular"] - base["hours_regular"] == 1600
    assert r["hours_overtime"] - base["hours_overtime"] == 300
    assert r["labor_regular"] + r["labor_overtime"] == r["labor"]
    assert r["hours_regular"] + r["hours_overtime"] == r["hours"]
    assert r["per_diem"] == 4550
    assert r["actual"] == r["labor"] + r["ap"] + r["direct"] + r["per_diem"]
    t = jobcost.totals(office, job)
    assert t["labor_regular"] + t["labor_overtime"] == t["labor"]


def test_r38_job_cost_page_columns(office, job, qapp):
    from quantisheet_backoffice.ui.main_window import JobCostPage
    _setup(office, job)
    pg = JobCostPage(office)
    pg.job.setCurrentIndex(pg.job.findData(job))
    pg.refresh()
    hdr = [pg.grid.horizontalHeaderItem(i).text() for i in range(pg.grid.columnCount())]
    assert hdr == ["Code", "Description", "Revised budget", "Committed",
                   "Regular labor", "Overtime labor", "Per diem", "AP + other",
                   "Actual", "Remaining", "% spent", "Forecast", "Variance"]
    r = jobcost.by_code(office, job)["03-3000"]
    (row,) = [i for i in range(pg.grid.rowCount()) if pg.grid.item(i, 0).text() == "03-3000"]
    vals = [pg.grid.item(row, c).text() for c in (4, 5, 6, 7, 8)]
    from quantisheet_backoffice import cents
    assert vals == [cents.fmt(r["labor_regular"]), cents.fmt(r["labor_overtime"]),
                    cents.fmt(r["per_diem"]), cents.fmt(r["ap"] + r["direct"]),
                    cents.fmt(r["actual"])]


def test_r38_job_cost_csv_split_columns_added_last(office, job, tmp_path):
    _setup(office, job)
    import csv
    path = exports.job_cost_csv(office, job, str(tmp_path / "jc.csv"))
    rows = list(csv.reader(open(path, newline="")))
    assert rows[0][10:] == ["Per diem", "Regular labor", "Overtime labor",
                            "Regular hours", "Overtime hours"]
    (r,) = [x for x in rows[1:] if x[0] == "03-3000"]
    jc = jobcost.by_code(office, job)["03-3000"]
    assert r[11:] == ["%.2f" % (jc["labor_regular"] / 100), "%.2f" % (jc["labor_overtime"] / 100),
                      "%.2f" % (jc["hours_regular"] / 100), "%.2f" % (jc["hours_overtime"] / 100)]
