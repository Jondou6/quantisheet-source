"""Load the made-up 1.1.1 sample files. No network."""
import json

import pytest
import os
import re

import pymupdf

from cryptography.fernet import Fernet


HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_data")

PHONE = re.compile(r"(?<!\d)(?:\d{3}[-.\s]\d{3}[-.\s]\d{4}|\d{10})(?!\d)")
LOCAL = re.compile(r"(?<!\d)\d{3}-\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
MONEY = re.compile(r"^[\d,]+\.\d{2}-?\*?$")
JOB_NO = re.compile(r"^\d{2}-[A-Z]-\d{3}$")
CODE = re.compile(r"\b\d{2}-\d{3}\b")
BANNED = ("rsmeans", "bluebeam", "planswift", "xactimate", "accubid")


def _read(name):
    with open(os.path.join(SAMPLE, name), encoding="utf-8") as fh:
        return fh.read()


def _json(name):
    return json.loads(_read(name))


def _lines(page):
    rows = []
    for word in page.get_text("words"):
        placed = False
        for row in rows:
            if abs(row[0][1] - word[1]) <= 2:
                row.append(word)
                placed = True
                break
        if not placed:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w[0])
    return rows


def test_backflow_reports_cover_the_cases():
    store = _json("service_backflow.json")
    assert store["kind"] == "service_backflow"
    reports = store["reports"]
    assert len(reports) == 5
    devices = {r["dev_name"] for r in reports}
    assert devices == {"RP", "DC"}
    assert any(r["dev_serial"] == "" for r in reports)
    assert any(r["c1_before_leaked"] and r["c1_after_tight"] for r in reports)
    assert any(r["c1_before_tight"] and not r["c1_before_leaked"]
               for r in reports)
    notes = [r["c1_repair_note"] for r in reports]
    assert any(notes)
    psi = " ".join(r["c1_before_psi"] for r in reports)
    relief = " ".join(r["rv_before_psi"] + r["rv_after_psi"] for r in reports)
    assert "Diff." in psi and "psi" in psi
    assert "Opened at" in relief and "psi" in relief
    for report in reports:
        for pid in ("c1", "c2", "rv", "so1", "so2"):
            assert f"{pid}_repair_note" in report
        assert report["acct_no"] == "" and report["meter_no"] == ""
        assert report["cert_company"] == ""
        assert report["cert_phone"] == "555-0100"
        assert report["acct_address"] == "123 Example St"
    blob = json.dumps(store).lower()
    for word in ("utility", "district", "municipal"):
        assert word not in blob


def test_service_calls_and_agreements_load():
    orders = _json("service_work_orders.json")
    agreements = _json("service_agreements.json")
    assert orders["kind"] == "service_work_orders"
    assert agreements["kind"] == "service_agreements"
    assert len(orders["orders"]) == 10
    assert len(agreements["agreements"]) == 3
    need = {"id", "number", "customer", "site", "address", "complaint",
            "billing", "call_type", "status", "time", "parts"}
    assert all(need <= set(wo) for wo in orders["orders"])
    agr_need = {"id", "number", "customer", "site", "price",
                "visits_per_year", "start", "renewal", "status"}
    assert all(agr_need <= set(a) for a in agreements["agreements"])
    linked = {wo["agreement_id"] for wo in orders["orders"] if wo["agreement_id"]}
    assert linked <= {a["id"] for a in agreements["agreements"]}
    assert all(wo["address"] == "123 Example St" for wo in orders["orders"])


def test_job_cost_pdf_matches_the_column_layout():
    path = os.path.join(SAMPLE, "job_cost_report.pdf")
    doc = pymupdf.open(path)
    assert doc.page_count >= 2
    text = "\n".join(page.get_text("text") for page in doc)
    assert "99-T-001" in text and "99-T-002" in text and "99-T-003" in text
    assert "EX 00000" in text
    assert "Job Totals*" in text and "Extra Totals*" in text
    assert "Report Totals*" in text
    assert "15.00-" in text or "5.00-" in text
    assert len(set(CODE.findall(text))) >= 25
    seen = {}
    found_job_line = False
    found_short = False
    for page in doc:
        rows = _lines(page)
        heading = next((row for row in rows if any(w[4] == "Variance" for w in row)),
                       None)
        assert heading is not None
        edges = [w[2] for w in heading]
        for row in rows:
            words = [w[4] for w in row]
            if words and JOB_NO.match(words[0]):
                found_job_line = True
                assert "Job" not in words
                seen.setdefault(words[0], 0)
                seen[words[0]] += 1
            amounts = [w for w in row if MONEY.match(w[4])]
            if any(w[4] == "Material" for w in row) and 0 < len(amounts) < 7:
                found_short = True
            for amount in amounts:
                assert any(abs(amount[2] - edge) <= 3 for edge in edges)
    assert found_job_line and found_short
    assert any(count >= 2 for count in seen.values())
    doc.close()


@pytest.mark.skipif(not os.path.isfile(os.path.join(
    SAMPLE, "job_cost_report.prn")), reason="the .prn sample isn't copied "
    "to every PC")
def test_prn_is_text_and_unchecked_against_this_branch():
    prn = _read("job_cost_report.prn")
    assert "\f" in prn
    assert "99-T-001" in prn and "99-T-003" in prn
    assert "EX 00000" in prn
    assert "Report Totals*" in prn
    assert "15.00-" in prn or "5.00-" in prn
    readme = _read("README.md")
    assert "The .PRN cannot be checked against this branch's parser." in readme


def test_payroll_company_uses_the_old_key_file():
    """Only looks at the files. Opening it moves the key, so that is done
    on a copy: quantisheet_backoffice/tests/test_r111_qs025_sample.py."""
    folder = os.path.join(SAMPLE, "payroll_company")
    blob = open(os.path.join(folder, "datakey.bin"), "rb").read()
    assert blob.startswith(b"plain:")
    assert not blob.startswith(b"qskey1:")
    Fernet(blob[len(b"plain:"):])
    raw = open(os.path.join(folder, "backoffice.sqlite"), "rb").read()
    assert b"555-0100" not in raw
    assert b"worker-one@example.com" not in raw


def test_samples_have_no_real_looking_contact_data():
    chunks = []
    for name in os.listdir(SAMPLE):
        path = os.path.join(SAMPLE, name)
        if os.path.isdir(path) or name == "datakey.bin":
            continue
        if name.endswith(".pdf"):
            doc = pymupdf.open(path)
            chunks.append("\n".join(page.get_text("text") for page in doc))
            doc.close()
        else:
            chunks.append(open(path, encoding="utf-8", errors="ignore").read())
    pay_db = os.path.join(SAMPLE, "payroll_company", "backoffice.sqlite")
    chunks.append(open(pay_db, encoding="utf-8", errors="ignore").read())
    text = "\n".join(chunks)
    for match in PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        assert digits.startswith("55501") and len(digits) == 10, match.group(0)
    for match in LOCAL.finditer(text):
        assert match.group(0).startswith("555-01"), match.group(0)
    for match in EMAIL.finditer(text):
        assert match.group(0).endswith("@example.com"), match.group(0)
    low = text.lower()
    for word in BANNED:
        assert word not in low
    assert re.search(r"\bsage\b", low) is None
