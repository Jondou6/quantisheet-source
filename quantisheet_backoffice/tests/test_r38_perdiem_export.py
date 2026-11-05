"""r38 G2.2: approved per diem goes out in the accounting exports as its own
file type (CSV / Excel), batch-numbered like the others: never twice, and a
voided batch frees the lines again. IIF / Sage are refused for it. The time
export's columns are unchanged (per diem is not time). File exports only."""
import csv
import os

import pytest

from quantisheet_backoffice import exports, jobcost, perdiem, timeentry


def _approved(office, job, wid, d, amt):
    pid = perdiem.add(office, wid, d, job, "03-3000", amt)
    perdiem.submit(office, [pid])
    office.act_as("pm@bo.test")
    perdiem.decide(office, [pid], "approve")
    office.act_as("admin@bo.test")
    return pid


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def test_r38_perdiem_is_an_export_type():
    assert "perdiem" in exports.TYPES


def test_r38_perdiem_csv_and_batch_rules(office, job, tmp_path):
    wid = timeentry.add_worker(office, "M. Chen", "LAB", employee_no="E-1")
    p1 = _approved(office, job, wid, "2026-10-20", "45.50")
    _approved(office, job, wid, "2026-10-21", "45.50")
    perdiem.add(office, wid, "2026-10-22", job, "03-3000", "45.50")     # Draft
    res = exports.export(office, "perdiem", "2026-10-19", "2026-10-25", "csv",
                         folder=str(tmp_path))
    assert (res["count"], res["total"]) == (2, 9100)
    rows = _read(res["path"])
    assert rows[0] == ["Batch", "Date", "Employee", "Employee no.", "Class",
                       "Job", "Cost code", "Kind", "Amount"]
    assert rows[1][1:] == ["2026-10-20", "M. Chen", "E-1", "LAB", "2611",
                           "03-3000", "Per diem", "45.50"]
    assert len(rows) == 3
    again = exports.export(office, "perdiem", "2026-10-19", "2026-10-25", "csv",
                           folder=str(tmp_path))
    assert again["count"] == 0
    exports.void_batch(office, res["batch_id"], "wrong week")
    assert [r["id"] for r in exports.preview(
        office, "perdiem", "2026-10-19", "2026-10-25")["records"]][0] == p1


def test_r38_perdiem_xlsx(office, job, tmp_path):
    from openpyxl import load_workbook
    wid = timeentry.add_worker(office, "M. Chen", "LAB")
    _approved(office, job, wid, "2026-10-20", "10")
    res = exports.export(office, "perdiem", "2026-10-19", "2026-10-25", "xlsx",
                         folder=str(tmp_path))
    ws = load_workbook(res["path"]).active
    assert [c.value for c in ws[1]][-2:] == ["Kind", "Amount"]
    assert ws.max_row == 2


def test_r38_perdiem_iif_and_sage_refused(office, job, tmp_path):
    with pytest.raises(exports.ExportError, match="IIF"):
        exports.preview(office, "perdiem", "2026-10-19", "2026-10-25", "iif")
    wid = timeentry.add_worker(office, "M. Chen", "LAB")
    _approved(office, job, wid, "2026-10-20", "10")
    with pytest.raises(exports.ExportError, match="Sage"):
        exports.export(office, "perdiem", "2026-10-19", "2026-10-25", "sage",
                       folder=str(tmp_path))


def test_r38_time_export_columns_unchanged(office, job, tmp_path):
    wid = timeentry.add_worker(office, "M. Chen", "LAB")
    lid = timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8")
    timeentry.submit(office, [lid])
    office.act_as("pm@bo.test")
    timeentry.decide(office, [lid], "approve")
    office.act_as("admin@bo.test")
    _approved(office, job, wid, "2026-10-20", "10")
    res = exports.export(office, "time", "2026-10-19", "2026-10-25", "csv",
                         folder=str(tmp_path))
    rows = _read(res["path"])
    assert rows[0] == ["Batch", "Date", "Employee", "Employee no.", "Class",
                       "Job", "Cost code", "Pay type", "Hours", "Equipment",
                       "Equipment hours"]
    assert len(rows) == 2


def test_r38_job_cost_csv_has_per_diem_column(office, job, tmp_path):
    wid = timeentry.add_worker(office, "M. Chen", "LAB")
    _approved(office, job, wid, "2026-10-20", "45.50")
    path = exports.job_cost_csv(office, job, str(tmp_path / "jc.csv"))
    rows = _read(path)
    assert rows[0][:10] == ["Cost code", "Description", "Category", "Original",
                            "Revised", "Committed", "Actual", "Remaining",
                            "% spent", "Variance"]
    assert rows[0][10] == "Per diem"
    (r,) = [r for r in rows[1:] if r[0] == "03-3000"]
    assert r[10] == "45.50"
    assert r[6] == "%.2f" % (jobcost.by_code(office, job)["03-3000"]["actual"] / 100)


def test_r38_exports_page_offers_and_exports_per_diem(office, job, qapp):
    from PySide6.QtCore import QDate
    from quantisheet_backoffice.ui.exports_page import ExportsPage
    wid = timeentry.add_worker(office, "M. Chen", "LAB")
    _approved(office, job, wid, "2026-10-20", "10")
    pg = ExportsPage(office)
    pg.kind.setCurrentIndex(pg.kind.findData("perdiem"))
    assert pg.kind.currentText() == "Approved per diem"
    pg.d_from.setDate(QDate(2026, 10, 19))
    pg.d_to.setDate(QDate(2026, 10, 25))
    r = pg.export()
    assert r["count"] == 1 and os.path.exists(r["path"])
    assert pg.history.item(0, 1).text() == "perdiem"
