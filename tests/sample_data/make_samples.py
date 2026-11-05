"""Write the made-up 1.1.1 sample files in this folder.

Standard library, PyMuPDF, and the back-office packages already in the
tree. No network. Re-running replaces the payroll key, so commit
payroll_company/backoffice.sqlite and datakey.bin together.

    python tests/sample_data/make_samples.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402

from quantisheet_backoffice.crypto import FieldCrypto, _OwnerOnlyFile  # noqa: E402
from quantisheet_backoffice.store import DB  # noqa: E402

PAGE_W, PAGE_H = 792, 612
LEFT = 36
SIZE = 7
LEADING = 15
BOTTOM = 540
LABEL_CHARS = 28
# wide enough for "Remaining to Commit" so heading words do not touch
COL_CHARS = 20
HEADINGS = (
    "Original Estimate",
    "Approved Changes",
    "Total Estimate",
    "Total Committed",
    "Remaining to Commit",
    "JTD Cost",
    "Budget Variance",
)

POINTS = (
    ("c1", "pair"),
    ("c2", "pair"),
    ("rv", "psi"),
    ("so1", "valve"),
    ("so2", "valve"),
)
PHASES = ("before", "repair", "after")


def money(cents, star=False):
    """Cents as a report amount. Negatives use a trailing minus."""
    if cents is None:
        return None
    neg = cents < 0
    cents = abs(int(cents))
    whole, frac = divmod(cents, 100)
    text = f"{whole:,}.{frac:02d}"
    if neg:
        text += "-"
    if star:
        text += "*"
    return text


class Report:
    def __init__(self):
        self.doc = pymupdf.open()
        self.page = None
        self.y = 0
        self.pages = []
        self._lines = []
        gap = pymupdf.get_text_length(" ", fontname="cour", fontsize=SIZE)
        widest = max(pymupdf.get_text_length(h, fontname="cour", fontsize=SIZE)
                     for h in HEADINGS)
        col_w = widest + gap
        label_w = pymupdf.get_text_length("M" * LABEL_CHARS, fontname="cour",
                                          fontsize=SIZE)
        self.rights = []
        x = LEFT + label_w
        for _ in HEADINGS:
            x += col_w
            self.rights.append(x)
        # keep the last heading on the page
        if self.rights[-1] + LEFT > PAGE_W:
            raise RuntimeError("headings do not fit the page")

    def new_page(self):
        if self._lines:
            self.pages.append(self._lines)
        self._lines = []
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = 40

    def _overflow(self, rows):
        return self.page is None or self.y + rows * LEADING > BOTTOM

    def left(self, text):
        self.page.insert_text((LEFT, self.y), text, fontname="cour",
                              fontsize=SIZE)
        self._lines.append(text)
        self.y += LEADING

    def row(self, label, cells):
        self.page.insert_text((LEFT, self.y), label, fontname="cour",
                              fontsize=SIZE)
        for i, cell in enumerate(cells):
            if not cell:
                continue
            width = pymupdf.get_text_length(cell, fontname="cour",
                                            fontsize=SIZE)
            self.page.insert_text((self.rights[i] - width, self.y), cell,
                                  fontname="cour", fontsize=SIZE)
        parts = [label[:LABEL_CHARS].ljust(LABEL_CHARS)]
        for cell in cells:
            parts.append((cell or "").rjust(COL_CHARS))
        self._lines.append("".join(parts).rstrip())
        self.y += LEADING

    def header(self, job):
        """Job number, name, and two address lines. No Job label."""
        self.left("Job Cost Report")
        self.left(f"{job['number']}  {job['name']}")
        self.left(job["addr1"])
        self.left(job["addr2"])
        self.left("")
        self.row("Cost code", HEADINGS)
        self.left("")

    def ensure(self, job, rows=1):
        if self._overflow(rows):
            self.new_page()
            self.header(job)

    def finish(self, pdf_path, prn_path):
        if self._lines:
            self.pages.append(self._lines)
        self.doc.set_metadata({
            "title": "Job Cost Report",
            "author": "",
            "subject": "",
            "keywords": "",
            "creator": "",
            "producer": "",
        })
        self.doc.save(pdf_path)
        self.doc.close()
        body = "\f".join("\r\n".join(page) + "\r\n" for page in self.pages)
        with open(prn_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
        return len(self.pages)


def _jobs():
    specs = (
        ("99-T-001", "Example Hall", "Example City EX 00000", 9),
        ("99-T-002", "Example Warehouse", "Example City EX 00001", 8),
        ("99-T-003", "Example School", "Example City EX 00002", 8),
    )
    jobs = []
    start = 0
    for number, name, addr2, count in specs:
        codes = []
        for n in range(start, start + count):
            group = 1 + n // 10
            labor = [1000, -500, 500, 400, 100, 2000, -1500] if n % 5 == 0 \
                else [1000, 0, 1000, 400, 600, 300, 700]
            material = [800, None, 800, None, None, 200, 600] if n % 3 == 0 \
                else None
            codes.append({
                "code": f"{group:02d}-{100 + n:03d}",
                "desc": f"Sample item {n + 1:02d}",
                "labor": labor,
                "material": material,
            })
        jobs.append({
            "number": number,
            "name": name,
            "addr1": "123 Example St",
            "addr2": addr2,
            "codes": codes,
        })
        start += count
    return jobs


def write_job_cost():
    report = Report()
    jobs = _jobs()
    assert sum(len(j["codes"]) for j in jobs) == 25
    for job in jobs:
        if report.page is None or report._overflow(8):
            report.new_page()
        report.header(job)
        for code in job["codes"]:
            report.ensure(job)
            report.left(f"{code['code']}  {code['desc']}")
            report.ensure(job)
            report.row("Labor", [money(c) for c in code["labor"]])
            if code["material"] is not None:
                report.ensure(job)
                report.row("Material", [money(c) for c in code["material"]])
            report.ensure(job)
            report.row("Cost Code Totals*", [
                money(1000), money(0), money(1000), money(400),
                money(600), money(300), money(700, star=True),
            ])
        for label, last in (("Job Totals*", 900), ("Extra Totals*", 100)):
            report.ensure(job)
            report.row(label, [
                money(last), money(0), money(last), money(0),
                money(0), money(0), money(last, star=True),
            ])
    report.ensure(jobs[-1])
    report.row("Report Totals*", [
        money(120000), money(0), money(120000), money(0),
        money(0), money(0), money(120000, star=True),
    ])
    pages = report.finish(
        os.path.join(HERE, "job_cost_report.pdf"),
        os.path.join(HERE, "job_cost_report.prn"),
    )
    print(f"job cost report: {pages} pages, 25 cost codes, 3 jobs")


def _blank_report():
    data = {
        "acct_name": "", "acct_address": "", "acct_no": "", "meter_no": "",
        "dev_name": "", "dev_model": "", "dev_serial": "", "dev_size": "",
        "dev_application": "", "dev_location": "",
        "test_date": "", "next_due": "", "repair_materials": "",
        "tester": "", "cert_no": "", "cert_company": "", "cert_phone": "",
        "category": "", "method": "", "kit": "", "signature": "",
        "comments": "", "property_id": "", "equipment_id": "",
    }
    for pid, kind in POINTS:
        data[f"{pid}_repair_note"] = ""
        for phase in PHASES:
            if kind != "psi":
                data[f"{pid}_{phase}_leaked"] = False
                data[f"{pid}_{phase}_tight"] = False
            if kind != "valve":
                data[f"{pid}_{phase}_psi"] = ""
    return data


def _checks(report, phase, leaked, psi):
    for pid in ("c1", "c2"):
        report[f"{pid}_{phase}_leaked"] = leaked
        report[f"{pid}_{phase}_tight"] = not leaked
        report[f"{pid}_{phase}_psi"] = psi
    report[f"so1_{phase}_tight"] = not leaked
    report[f"so1_{phase}_leaked"] = leaked
    report[f"so2_{phase}_tight"] = not leaked
    report[f"so2_{phase}_leaked"] = leaked


def write_backflow():
    common = {
        "acct_address": "123 Example St",
        "tester": "Example Tester",
        "cert_no": "EX-0000",
        "cert_company": "",
        "cert_phone": "555-0100",
        "category": "General",
        "method": "Differential",
        "kit": "Differential gauge",
        "test_date": "2026-04-01",
        "next_due": "2027-04-01",
        "dev_size": "3/4",
        "dev_location": "Mechanical room",
        "dev_application": "Domestic",
    }
    specs = (
        ("BF-0001", "Example Resident", "RP", "EX-100", "RP-EX-0001", "pass"),
        ("BF-0002", "Example Tenant", "DC", "EX-200", "DC-EX-0002", "repair"),
        ("BF-0003", "Example Owner", "RP", "EX-100", "", "pass"),
        ("BF-0004", "Example Resident", "DC", "EX-200", "DC-EX-0004", "pass"),
        ("BF-0005", "Example Tenant", "RP", "EX-100", "RP-EX-0005", "relief"),
    )
    reports = []
    for number, name, device, model, serial, kind in specs:
        report = _blank_report()
        report.update(common)
        report["id"] = "bf-sample-" + number[-1]
        report["number"] = number
        report["acct_name"] = name
        report["dev_name"] = device
        report["dev_model"] = model
        report["dev_serial"] = serial
        if kind == "pass":
            _checks(report, "before", False, "Diff. 5.0 psi")
            report["rv_before_psi"] = "Opened at 2.0 psi"
        elif kind == "repair":
            _checks(report, "before", True, "Diff. 0.1 psi")
            _checks(report, "after", False, "Diff. 5.2 psi")
            report["c1_repair_note"] = "Replaced the check disc."
            report["c2_repair_note"] = "Replaced the second check disc."
            report["repair_materials"] = "Sample disc"
        else:
            _checks(report, "before", False, "Diff. 4.4 psi")
            _checks(report, "after", False, "Diff. 5.1 psi")
            report["rv_before_psi"] = "Opened at 0.3 psi"
            report["rv_after_psi"] = "Opened at 2.2 psi"
            report["rv_repair_note"] = "Cleaned the relief seat."
            report["c1_before_leaked"] = True
            report["c1_before_tight"] = False
            report["c1_after_leaked"] = False
            report["c1_after_tight"] = True
            report["c1_repair_note"] = "Reset the first check."
            report["repair_materials"] = "Sample seat"
        reports.append(report)
    store = {"kind": "service_backflow", "version": 1, "next": 6,
             "reports": reports}
    _dump("service_backflow.json", store)
    print("backflow: 5 reports")


def write_agreements_and_calls():
    agreements = []
    specs = (
        ("sa-sample-1", "SA-0001", "Example Resident", "Example Hall",
         "120.00", 2, "2026-01-01", "2027-01-01"),
        ("sa-sample-2", "SA-0002", "Example Tenant", "Example Warehouse",
         "80.00", 4, "2026-03-01", "2027-03-01"),
        ("sa-sample-3", "SA-0003", "Example Owner", "Example School",
         "90.00", 1, "2025-11-01", "2026-11-01"),
    )
    for aid, number, customer, site, price, visits, start, renewal in specs:
        agreements.append({
            "id": aid, "number": number, "customer": customer, "site": site,
            "property_id": "", "price": price, "visits_per_year": visits,
            "start": start, "renewal": renewal, "notes": "Sample agreement.",
            "status": "active",
        })
    _dump("service_agreements.json", {
        "kind": "service_agreements", "version": 1, "next": 4,
        "agreements": agreements,
    })

    calls = (
        ("Example Resident", "Example Hall", "Fan is noisy", "tm", "call",
         "", "open"),
        ("Example Tenant", "Example Warehouse", "Unit not cooling", "tm",
         "call", "", "open"),
        ("Example Owner", "Example School", "Filter check", "tm", "call",
         "", "closed"),
        ("Example Resident", "Example Hall", "Thermostat blank", "tm",
         "call", "", "closed"),
        ("Example Tenant", "Example Warehouse", "Drain pan full", "tm",
         "call", "", "open"),
        ("Example Owner", "Example School", "Belt worn", "flat", "call",
         "", "closed"),
        ("Example Resident", "Example Hall", "Odd smell", "tm", "call",
         "", "open"),
        ("Example Tenant", "Example Warehouse", "No heat", "tm", "call",
         "", "open"),
        ("Example Resident", "Example Hall", "Planned maintenance visit",
         "agreement", "pm", "sa-sample-1", "closed"),
        ("Example Tenant", "Example Warehouse", "Planned maintenance visit",
         "agreement", "pm", "sa-sample-2", "open"),
    )
    orders = []
    for n, (customer, site, complaint, billing, call_type, agr, status) \
            in enumerate(calls, start=1):
        opened = f"2026-02-{n:02d}"
        closed = status == "closed"
        time_rows = []
        parts = []
        if closed or call_type == "pm":
            time_rows.append({
                "id": f"time-{n}", "tech": "Example Tech", "hours": "1.00",
                "date": opened, "note": "Sample time", "bill": "10.00",
                "cost": "4.00",
            })
        if closed and billing != "agreement":
            parts.append({
                "id": f"part-{n}", "sku": "EX-1", "desc": "Sample filter",
                "qty": "1", "unit": "ea", "cost": "2.00", "price": "3.00",
                "truck_id": "", "part_id": "", "issue_id": "",
            })
        orders.append({
            "id": f"wo-sample-{n:02d}",
            "number": f"WO-{n:04d}",
            "opened": opened,
            "status": status,
            "customer": customer,
            "site": site,
            "address": "123 Example St",
            "property_id": "",
            "equipment_id": "",
            "unit": "",
            "complaint": complaint,
            "tech": "Example Tech",
            "billing": billing,
            "agreement_id": agr,
            "scheduled": opened,
            "pm_visit": opened if call_type == "pm" else "",
            "call_type": call_type,
            "flat_price": "15.00" if billing == "flat" else "",
            "task_id": "task-sample" if billing == "flat" else "",
            "task_name": "Sample flat task" if billing == "flat" else "",
            "member": False,
            "book": None,
            "time": time_rows,
            "parts": parts,
            "parts_recorded": closed,
            "photos": [],
            "notes": "Sample notes." if closed else "",
            "closed": opened if closed else "",
            "invoice_id": "",
        })
    _dump("service_work_orders.json", {
        "kind": "service_work_orders", "version": 1, "next": 11,
        "invoice_next": 1,
        "settings": {"labor_bill": "10.00", "labor_cost": "4.00"},
        "techs": ["Example Tech"],
        "orders": orders,
        "invoices": [],
    })
    print(f"agreements: {len(agreements)}; service calls: {len(orders)}")


def write_payroll():
    """Company database with the pre-move key: datakey.bin beside the db.

    crypto.FieldCrypto on a non-Windows host writes plain:<fernet key>
    (crypto._OwnerOnlyFile). Windows DPAPI wrapping is not produced here.
    """
    folder = os.path.join(HERE, "payroll_company")
    os.makedirs(folder, exist_ok=True)
    db_path = os.path.join(folder, "backoffice.sqlite")
    key_path = os.path.join(folder, "datakey.bin")
    for path in (db_path, key_path):
        if os.path.exists(path):
            os.remove(path)
    # build in a temp folder so a failed run cannot leave a half file
    tmp = tempfile.mkdtemp(prefix="qs-sample-pay-")
    try:
        db = DB(os.path.join(tmp, "backoffice.sqlite"))
        crypto = FieldCrypto(tmp, _OwnerOnlyFile())
        db.crypto = crypto
        with db.tx():
            db.insert("company", name="", address="", logo="",
                      fiscal_year_start="01-01",
                      invoice_format="INV-{n:04d}", net_terms=30,
                      accounting_mode="export", state="")
            people = (
                ("Example Worker One", "E-001", "555-0100",
                 "worker-one@example.com", 2500),
                ("Example Worker Two", "E-002", "555-0101",
                 "worker-two@example.com", 3000),
                ("Example Worker Three", "E-003", "555-0102",
                 "worker-three@example.com", 1850),
            )
            first_worker = None
            for name, eno, phone, email, rate in people:
                wid = db.insert("workers", name=name, employee_no=eno,
                                labor_class="Helper", active=1)
                first_worker = first_worker or wid
                db.insert("employees", worker_id=wid, name=name,
                          employee_no=eno, address="123 Example St",
                          phone=phone, email=email, hire_date="2026-01-05",
                          status="Active", labor_class="Helper",
                          pay_rate=rate)
            db.insert("payroll_lines", period_id=0, worker_id=first_worker,
                      job_id=0,
                      cost_code="99-000", date="2026-01-06",
                      pay_type="regular", hours=800, rate=2500, base=20000,
                      gross=20000, fringe_cash=0, fringe_plan=0,
                      fringes="[]", rate_source="sample", rule="",
                      time_line_id=0, prevailing=0)
        db.close()
        os.replace(os.path.join(tmp, "backoffice.sqlite"), db_path)
        os.replace(os.path.join(tmp, "datakey.bin"), key_path)
    finally:
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    try:
        os.chmod(db_path, 0o600)
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    blob = open(key_path, "rb").read()
    if not blob.startswith(b"plain:"):
        raise SystemExit("expected the off-Windows plain: key wrapping")
    print("payroll company: 3 employees, datakey.bin beside the database")


def _dump(name, data):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main():
    write_backflow()
    write_agreements_and_calls()
    write_job_cost()
    write_payroll()


if __name__ == "__main__":
    main()
