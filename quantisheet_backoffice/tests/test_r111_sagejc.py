"""Job Cost Report PDF import (release 1.1.1). Made-up jobs only."""
import os

import pytest

from quantisheet_backoffice import cents, jobcost, security
from quantisheet_backoffice.r111 import sagejc, schema


def _words(lines):
    """One visual line -> word dicts sharing a y."""
    out = []
    y = 0
    for page, tokens in lines:
        x = 0
        for token in tokens:
            out.append({"page": page, "x0": x, "y0": y, "x1": x + 8,
                        "y1": y + 8, "t": token})
            x += 12
        y += 20
    return out


def test_trailing_minus_and_parentheses():
    assert sagejc.parse_money_token("16,121-") == -1_612_100
    assert sagejc.parse_money_token("700.00-") == -70_000
    assert sagejc.parse_money_token("(500.00)") == -50_000
    assert sagejc.parse_money_token("1,200.00") == 120_000
    assert sagejc.parse_money_token("Labor") is None
    words = _words([
        (0, ["Job", "4401", "Riverside", "Pavilion"]),
        (0, ["88", "River", "Rd"]),
        (0, ["01-042", "Scheduling", "Expense"]),
        (0, ["Labor", "12000.00", "1500.00", "13500.00", "13500.00",
             "0.00", "14200.00", "700.00-"]),
        (0, ["Other", "0.00", "0.00", "0.00", "0.00", "0.00", "0.00",
             "16,121", "-"]),
        (0, ["Cost", "Code", "Totals", "*", "14000.00", "1500.00",
             "13500.00", "13500.00", "0.00", "14200.00", "400.00-"]),
    ])
    report = sagejc.parse_words(words)
    assert report["job_number"] == "4401"
    assert report["job_name"] == "Riverside Pavilion"
    assert report["address"] == "88 River Rd"
    code = report["codes"][0]
    labor = code["lines"][0]
    other = code["lines"][1]
    totals = code["lines"][2]
    assert labor["category"] == "Labor" and labor["overrun"] == 1
    assert labor["variance"] == -70_000
    assert other["variance"] == -1_612_100
    assert totals["is_total"] == 1 and totals["variance"] == -40_000


def write_report(path):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    rows = [
        "JOB COST REPORT",
        "Job 4401 Riverside Pavilion",
        "88 River Rd, Springfield, OR",
        "Category  Original  Approved  TotalEst  Committed  Remaining  JTD  Variance",
        "01-042 Scheduling Expense",
        "Labor  12000.00  1500.00  13500.00  13500.00  0.00  14200.00  700.00-",
        "Material  2000.00  0.00  2000.00  1200.00  800.00  900.00  1100.00",
        "Subcontractor  0.00  0.00  16121.00  0.00  0.00  0.00  16,121-",
        "Cost Code Totals *  14000.00  1500.00  31621.00  14700.00  800.00  16000.00  100.00-",
        "02-100 Site Concrete",
        "Labor  8000.00  0.00  8000.00  8000.00  0.00  6400.00  1600.00",
    ]
    y = 40
    for row in rows:
        page.insert_text((36, y), row, fontsize=10, fontname="cour")
        y += 16
    page2 = doc.new_page(width=792, height=612)
    page2.insert_text((36, 40), "03-050 Temp Power", fontsize=10, fontname="cour")
    page2.insert_text((36, 56),
                      "Material  500.00  0.00  500.00  500.00  0.00  800.00  300.00-",
                      fontsize=10, fontname="cour")
    doc.save(path)
    doc.close()


def test_pdf_words_and_prn_is_not_opened(office, tmp_path, monkeypatch):
    import fitz
    opened = []
    real = fitz.open

    def spy(*a, **k):
        if a and isinstance(a[0], (str, bytes, os.PathLike)):
            opened.append(os.fspath(a[0]))
        return real(*a, **k)

    monkeypatch.setattr(fitz, "open", spy)
    pdf = str(tmp_path / "job-cost.pdf")
    write_report(pdf)
    report = sagejc.read_pdf(pdf)
    assert any(str(pdf) == p or p.endswith("job-cost.pdf") for p in opened)
    assert report["job_number"] == "4401"
    assert report["job_name"] == "Riverside Pavilion"
    assert "Springfield" in report["address"]
    assert report["page_count"] == 2
    codes = {c["code"]: c for c in report["codes"]}
    assert set(codes) == {"01-042", "02-100", "03-050"}
    assert codes["01-042"]["lines"][-1]["is_total"] == 1
    sub = [ln for ln in codes["01-042"]["lines"]
           if ln["category"] == "Subcontractor"][0]
    assert sub["variance"] == -1_612_100
    calls = []
    real_page = fitz.Page.get_text

    def page_spy(self, *a, **k):
        calls.append(a[0] if a else k.get("option"))
        return real_page(self, *a, **k)

    monkeypatch.setattr(fitz.Page, "get_text", page_spy)
    sagejc.read_pdf(pdf)
    assert "words" in calls
    prn = str(tmp_path / "job-cost.PRN")
    open(prn, "w", encoding="utf-8").write("not a pdf\n")
    before = len(opened)
    with pytest.raises(sagejc.SageError, match="PRN"):
        sagejc.import_pdf(office, prn)
    assert len(opened) == before


def test_publish_feeds_job_cost_and_unpublish_restores(office, job, tmp_path):
    pdf = str(tmp_path / "report.pdf")
    write_report(pdf)
    before = jobcost.by_code(office, job)["03-3000"]["original"]
    iid = sagejc.import_pdf(office, pdf, job_id=job)
    assert sagejc.get_import(office, iid)["status"] == "stored"
    rows = {r["code"]: r for r in sagejc.comparison(office, import_id=iid)}
    assert rows["01-042"]["jtd"] == 1_600_000          # totals line, not the sum
    assert rows["01-042"]["committed"] == 1_470_000
    assert rows["01-042"]["total_estimate"] == 3_162_100
    assert rows["01-042"]["overrun"] is True
    labor = [c for c in rows["01-042"]["categories"]
             if c["category"] == "Labor"][0]
    material = [c for c in rows["01-042"]["categories"]
                if c["category"] == "Material"][0]
    assert labor["overrun"] is True and material["overrun"] is False
    assert rows["02-100"]["overrun"] is False
    assert rows["02-100"]["jtd"] == 640_000            # no totals line: sum
    assert rows["03-050"]["overrun"] is True
    assert jobcost.by_code(office, job)["03-3000"]["original"] == before
    assert "01-042" not in jobcost.by_code(office, job)
    sagejc.publish(office, iid)
    view = jobcost.by_code(office, job)
    hit = view["01-042"]
    assert hit["original"] == 1_400_000
    assert hit["revised"] == 3_162_100
    assert hit["committed"] == 1_470_000
    assert hit["actual"] == 1_600_000
    assert hit["variance"] == -10_000
    assert hit["overrun"] is True
    assert hit["actual_from_report"] is True
    assert "sage_jtd" in {s["type"] for s in hit["sources"]}
    assert view["03-3000"]["original"] == before
    assert "overrun" not in view["03-3000"]
    assert cents.fmt(hit["actual"]) == "$16,000.00"
    sagejc.unpublish(office, iid)
    restored = jobcost.by_code(office, job)
    assert "01-042" not in restored
    assert restored["03-3000"]["original"] == before
    assert restored["03-3000"]["revised"] == 4_800_000


def test_new_job_from_the_header_and_viewer_cannot(office, tmp_path):
    pdf = str(tmp_path / "report.pdf")
    write_report(pdf)
    iid = sagejc.import_pdf(office, pdf)
    imp = sagejc.get_import(office, iid)
    assert imp["job_number"] == "4401"
    from quantisheet_backoffice import jobs
    assert jobs.job(office, imp["job_id"])["name"] == "Riverside Pavilion"
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        sagejc.import_pdf(office, pdf)


def test_added_column_keeps_existing_rows(office):
    cols = ", ".join(
        f"{name} {typ}" for name, typ in schema.TABLES["sage_imports"]
        if name != "note")
    office.db.conn.execute(
        f"CREATE TABLE sage_imports ({schema.store.STD}, {cols})")
    office.db.conn.execute(
        "INSERT INTO sage_imports (job_number, status, deleted) "
        "VALUES ('4401', 'stored', 0)")
    schema.ensure(office.db)
    have = {r[1] for r in office.db.conn.execute(
        "PRAGMA table_info(sage_imports)")}
    assert "note" in have
    assert office.db.scalar(
        "SELECT COUNT(*) FROM sage_imports WHERE job_number = '4401'") == 1
