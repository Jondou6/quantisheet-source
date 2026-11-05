"""A Job Cost Report with several jobs in one file (Nov 4): each job's
codes stay with that job, a dash-numbered address on a later page never
starts a job, and importing stores one import per job. Made-up data."""
import os

import pytest

from quantisheet_backoffice import jobs
from quantisheet_backoffice.r111 import sagejc

from .test_r111_sagejc_layout import EDGES, HEAD1, HEAD2, _row


def _head(page, y0, number, name, street, city):
    w = _row(page, y0, f"{number} {name}", {})
    w += _row(page, y0 + 12, street, {})
    w += _row(page, y0 + 24, city, {})
    for k, t in enumerate(HEAD1):
        w.append({"page": page, "x0": EDGES[k] - 6 * len(t), "y0": y0 + 40,
                  "x1": EDGES[k], "y1": y0 + 48, "t": t})
    for k, t in enumerate(HEAD2):
        w.append({"page": page, "x0": EDGES[k] - 6 * len(t), "y0": y0 + 52,
                  "x1": EDGES[k], "y1": y0 + 60, "t": t})
    return w


SEVEN = {0: "100", 1: "0", 2: "100", 3: "0", 4: "100", 5: "40", 6: "60"}


def _code(page, y, code):
    w = _row(page, y, f"{code} Sample item", {})
    w += _row(page, y + 12, "Labor", SEVEN)
    w += _row(page, y + 24, "Cost Code Totals", SEVEN, star=True)
    return w


def _three_jobs():
    w = _head(0, 20, "99-T-001", "Example Hall", "123 Example St",
              "Example City EX 00000")
    w += _code(0, 100, "01-100") + _code(0, 140, "01-101")
    # page 2: same job; its street has a dash number
    w += _head(1, 20, "99-T-001", "Example Hall", "10-12 Main St",
               "Example City EX 00000")
    w += _code(1, 100, "01-102")
    w += _row(1, 140, "Job Totals", {0: "300"}, star=True)
    # job 2 starts mid-page right after Job Totals
    w += _row(1, 160, "99-T-002 Example Annex", {})
    w += _row(1, 172, "45 Sample Rd", {})
    w += _code(1, 190, "02-100")
    w += _row(1, 230, "Job Totals", {0: "100"}, star=True)
    # job 3 on its own page
    w += _head(2, 20, "99-T-003", "Example Shop", "9 Test Ave",
               "Example City EX 00000")
    w += _code(2, 100, "03-100") + _code(2, 140, "03-101")
    w += _row(2, 180, "Job Totals", {0: "200"}, star=True)
    w += _row(2, 200, "Report Totals", {0: "600"}, star=True)
    return w


def test_each_job_keeps_its_own_codes():
    r = sagejc.parse_words(_three_jobs())
    got = [(j["job_number"], [c["code"] for c in j["codes"]])
           for j in r["jobs"]]
    assert got == [("99-T-001", ["01-100", "01-101", "01-102"]),
                   ("99-T-002", ["02-100"]),
                   ("99-T-003", ["03-100", "03-101"])]
    assert [j["address"] for j in r["jobs"]] == [
        "123 Example St", "45 Sample Rd", "9 Test Ave"]
    assert r["job_number"] == "99-T-001" and len(r["codes"]) == 3
    for j in r["jobs"]:
        for c in j["codes"]:
            assert [ln["category"] for ln in c["lines"]] == ["Labor", ""]


def test_one_job_report_is_unchanged():
    from .test_r111_sagejc_layout import _report
    r = sagejc.parse_words(_report())
    assert len(r["jobs"]) == 1 and r["job_number"] == "99-X-123"


def test_import_stores_one_import_per_job(office, tmp_path, monkeypatch):
    words = _three_jobs()
    monkeypatch.setattr(sagejc.pdfutil, "words", lambda p: words)
    pdf = tmp_path / "jc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%made up\n")
    first = sagejc.import_pdf(office, str(pdf))
    rows = office.db.rows("SELECT job_number FROM sage_imports WHERE "
                          "deleted = 0 ORDER BY id")
    assert [r["job_number"] for r in rows] == ["99-T-001", "99-T-002",
                                              "99-T-003"]
    assert sagejc.get_import(office, first)["job_number"] == "99-T-001"
    for n in ("99-T-001", "99-T-002", "99-T-003"):
        assert jobs.job_by_number(office, n)


def test_import_onto_a_picked_job_takes_only_its_section(office, tmp_path,
                                                         monkeypatch):
    words = _three_jobs()
    monkeypatch.setattr(sagejc.pdfutil, "words", lambda p: words)
    pdf = tmp_path / "jc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%made up\n")
    jid = office.db.insert("jobs", number="99-T-002", name="Example Annex",
                           project={}, retainage_work="0",
                           retainage_stored="0", state="",
                           last_snapshot_at="", source={})
    iid = sagejc.import_pdf(office, str(pdf), job_id=jid)
    codes = {ln["cost_code"] for ln in sagejc.lines(office, iid)}
    assert codes == {"02-100"}
    other = office.db.insert("jobs", number="77-Z-9", name="Not In File",
                             project={}, retainage_work="0",
                             retainage_stored="0", state="",
                             last_snapshot_at="", source={})
    with pytest.raises(sagejc.SageError, match="3 jobs"):
        sagejc.import_pdf(office, str(pdf), job_id=other)


SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests", "sample_data")


@pytest.mark.skipif(not os.path.isfile(os.path.join(
    SAMPLE, "job_cost_report.pdf")), reason="sample data not present")
def test_the_sample_report_reads_as_three_jobs():
    r = sagejc.read_pdf(os.path.join(SAMPLE, "job_cost_report.pdf"))
    nums = [j["job_number"] for j in r["jobs"]]
    assert nums == ["99-T-001", "99-T-002", "99-T-003"], nums
    assert sum(len(j["codes"]) for j in r["jobs"]) == 25
    for j in r["jobs"]:
        assert j["address"] == "123 Example St", j
        for c in j["codes"]:
            assert any(ln["is_total"] for ln in c["lines"]), c["code"]
            assert all(ln["category"] in ("", "Labor", "Material",
                                          "Subcontractor", "Other",
                                          "Equipment")
                       for ln in c["lines"]), c


def test_report_page_defaults_to_each_job_by_number(office, tmp_path,
                                                    monkeypatch, qapp):
    from quantisheet_backoffice.r111.ui import BY_NUMBER, ReportPage
    office.db.insert("jobs", number="55-A-1", name="Some Other Job",
                     project={}, retainage_work="0", retainage_stored="0",
                     state="", last_snapshot_at="", source={})
    words = _three_jobs()
    monkeypatch.setattr(sagejc.pdfutil, "words", lambda p: words)
    pdf = tmp_path / "jc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%made up\n")
    page = ReportPage(office, pick_file=lambda: str(pdf),
                      confirm=lambda text, dup: True)
    assert page.job.currentText() == BY_NUMBER and page._job_id() is None
    assert page.import_report()
    n = office.db.scalar("SELECT COUNT(*) FROM sage_imports WHERE "
                         "deleted = 0")
    assert n == 3                      # nothing went onto 55-A-1


@pytest.mark.skipif(not os.path.isfile(os.path.join(
    SAMPLE, "job_cost_report.pdf")), reason="sample data not present")
def test_one_line_headings_put_amounts_in_their_columns():
    """The sample has all seven headings on one line, close together
    ('Total Committed Remaining to Commit'); amounts must still land under
    the right one, blank cells included."""
    r = sagejc.read_pdf(os.path.join(SAMPLE, "job_cost_report.pdf"))
    labor, material = r["jobs"][0]["codes"][0]["lines"][:2]
    assert (labor["original"], labor["changes_amt"], labor["total_estimate"],
            labor["committed"], labor["remaining"], labor["jtd"],
            labor["variance"]) == (1000, -500, 500, 400, 100, 2000, -1500)
    assert (material["original"], material["committed"],
            material["jtd"], material["variance"]) == (800, 0, 200, 600)


def test_publish_follows_the_job_picked_after_a_multi_job_import(
        office, tmp_path, monkeypatch, qapp):
    from quantisheet_backoffice.r111.ui import ReportPage
    words = _three_jobs()
    monkeypatch.setattr(sagejc.pdfutil, "words", lambda p: words)
    pdf = tmp_path / "jc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%made up\n")
    page = ReportPage(office, pick_file=lambda: str(pdf),
                      confirm=lambda text, dup: True)
    first = page.import_report()
    assert "3 jobs" in page.status.text()
    # the picker now lists the new jobs and shows the first one
    j2 = jobs.job_by_number(office, "99-T-002")["id"]
    assert page._job_id() == jobs.job_by_number(office, "99-T-001")["id"]
    page.job.setCurrentIndex(page.job.findData(j2))
    published = page.publish()
    assert published != first
    assert sagejc.get_import(office, published)["job_number"] == "99-T-002"



def test_preview_before_import_and_no_silent_duplicate(office, tmp_path,
                                                       monkeypatch, qapp):
    from quantisheet_backoffice.r111.ui import ReportPage
    words = _three_jobs()
    monkeypatch.setattr(sagejc.pdfutil, "words", lambda p: words)
    pdf = tmp_path / "jc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%made up\n")
    pv = sagejc.preview(office, str(pdf))
    assert [j["job_number"] for j in pv["jobs"]] == ["99-T-001", "99-T-002",
                                                    "99-T-003"]
    assert pv["new_jobs"] == 3 and not pv["duplicate_of"]
    assert office.db.scalar("SELECT COUNT(*) FROM sage_imports") == 0
    seen = []
    page = ReportPage(office, pick_file=lambda: str(pdf),
                      confirm=lambda text, dup: seen.append((text, dup)) or
                      False)
    assert page.import_report() is None                # cancelled
    assert "NEW job" in seen[0][0] and seen[0][1] is False
    assert office.db.scalar("SELECT COUNT(*) FROM sage_imports") == 0
    page.confirm = lambda text, dup: True
    assert page.import_report()
    # the same file again: refused by the model, asked about on the page
    with pytest.raises(sagejc.SageError, match="already imported"):
        sagejc.import_pdf(office, str(pdf))
    page.confirm = lambda text, dup: seen.append((text, dup)) or False
    assert page.import_report() is None
    assert seen[-1][1] is True and "already imported" in seen[-1][0]


def test_totals_that_do_not_add_up_are_shown():
    words = _three_jobs()
    r = sagejc.parse_words(words)
    j1 = r["jobs"][0]
    # the made-up report says 300 for job 1; its codes add to 300
    assert sagejc.mismatches(j1) == []
    j1["stated"]["original"] = 999900
    got = sagejc.mismatches(j1)
    assert got and got[0][0] == "Original Estimate"
