"""Made-up fixtures (brief section 6): Example Clinic, job 2611."""
import copy

from quantisheet_backoffice import interface, jobs, security
from quantisheet_backoffice.office import Office

USERS = [("Ann Admin", "admin@bo.test", "Admin", ""),
         ("Carl Controller", "ctl@bo.test", "Controller", ""),
         ("Alice Clerk", "ap@bo.test", "AP Clerk", ""),
         ("Bea Billing", "bill@bo.test", "Billing", ""),
         ("Pat Morgan", "pm@bo.test", "Approver", "PM"),
         ("R. Silva", "fm@bo.test", "Approver", "Foreman"),
         ("Dana Ortiz", "viewer@bo.test", "Viewer", "")]
PW = "correct horse 7"


def make_office(folder):
    o = Office(folder)
    for name, email, role, title in USERS:
        security.add_user(o.db, name, email, role, PW, title)
    o.act_as("admin@bo.test")
    o.set_company(name="Example Builders LLC",
                  address="100 Main St\nSpringfield, OR 97477")
    return o


def summary(**v):
    return {k: f"{x}.00" for k, x in v.items()}


APP1 = {"number": "1", "period_to": "2026-08-31", "status": "certified",
        "lines": [{"item": "1", "previous": "0.00", "this_period": "60000.00",
                   "stored": "0.00"}],
        "summary": {"1": "500000.00", "2": "25000.00", "3": "525000.00",
                    "4": "60000.00", "5a": "6000.00", "5b": "0.00",
                    "5": "6000.00", "6": "54000.00", "7": "0.00",
                    "8": "54000.00", "9": "471000.00"}}
APP2 = {"number": "2", "period_to": "2026-09-30", "status": "certified",
        "lines": [{"item": "1", "previous": "60000.00", "this_period": "40000.00",
                   "stored": "0.00"},
                  {"item": "2", "previous": "0.00", "this_period": "40000.00",
                   "stored": "0.00"},
                  {"item": "3", "previous": "0.00", "this_period": "0.00",
                   "stored": "10000.00"}],
        "summary": {"1": "500000.00", "2": "25000.00", "3": "525000.00",
                    "4": "150000.00", "5a": "14000.00", "5b": "1000.00",
                    "5": "15000.00", "6": "135000.00", "7": "54000.00",
                    "8": "81000.00", "9": "390000.00"}}
APP3 = {"number": "3", "period_to": "2026-10-31", "status": "draft",
        "lines": [{"item": "1", "previous": "100000.00", "this_period": "0.00",
                   "stored": "0.00"},
                  {"item": "2", "previous": "40000.00", "this_period": "50000.00",
                   "stored": "0.00"},
                  {"item": "CO-001", "previous": "0.00",
                   "this_period": "20000.00", "stored": "0.00"},
                  {"item": "3", "previous": "0.00", "this_period": "0.00",
                   "stored": "15000.00"}],
        "summary": {"1": "500000.00", "2": "25000.00", "3": "525000.00",
                    "4": "225000.00", "5a": "21000.00", "5b": "1500.00",
                    "5": "22500.00", "6": "202500.00", "7": "135000.00",
                    "8": "67500.00", "9": "322500.00"}}

BASE = {
    "interface_version": 1,
    "source": {"app": "QuantiSheet 0.13.1", "file": "Example Clinic.pdf",
               "taken_at": "2026-10-20T09:00"},
    "project": {"name": "Example Clinic", "number": "2611",
                "address": "4200 Example Clinic Rd, Springfield, OR",
                "owner": "Example Health District",
                "contractor": "Example Builders LLC",
                "architect": "Studio Fern Architects",
                "contract_no": "MRC-01", "contract_date": "2026-06-01",
                "state": "OR"},
    "cost_codes": [
        {"code": "01-5000", "description": "General conditions", "category": "O"},
        {"code": "02-2000", "description": "Sitework", "category": "S"},
        {"code": "03-3000", "description": "Concrete", "category": "M"},
        {"code": "06-1000", "description": "Framing", "category": "S"}],
    "budget": [
        {"code": "01-5000", "description": "General conditions", "category": "O",
         "original": "30000.00", "revised": "30000.00"},
        {"code": "02-2000", "description": "Sitework", "category": "S",
         "original": "90000.00", "revised": "90000.00"},
        {"code": "03-3000", "description": "Concrete", "category": "M",
         "original": "48000.00", "revised": "48000.00"},
        {"code": "06-1000", "description": "Framing", "category": "S",
         "original": "140000.00", "revised": "150000.00"}],
    "estimate": [
        {"code": "03-3000", "description": "Concrete crew hours", "category": "L",
         "quantity": "160", "unit": "HR", "amount": "9280.00"}],
    "activities": [
        {"id": "A100", "name": "Foundations", "cost_code": "03-3000",
         "start": "2026-09-01", "finish": "2026-11-15", "percent": "40"}],
    "contract": {"retainage_work": "10", "retainage_stored": "10",
                 "sov": [{"item": "1", "cost_code": "02-2000",
                          "description": "Sitework", "scheduled": "100000.00"},
                         {"item": "2", "cost_code": "03-3000",
                          "description": "Concrete", "scheduled": "250000.00"},
                         {"item": "3", "cost_code": "06-1000",
                          "description": "Framing", "scheduled": "150000.00"}]},
    "changes": [
        {"id": "c1", "pco": "PCO-001", "cor": "COR-001", "co": "CO-001",
         "title": "Added exam rooms", "stage": "co", "amount": "25000.00",
         "approved_amount": "25000.00", "days": "5", "executed": "2026-08-15"},
        {"id": "c2", "pco": "PCO-002", "cor": "COR-002", "co": "",
         "title": "Upgraded roof drains", "stage": "cor", "amount": "8500.00",
         "days": "2"}],
    "payapps": [APP1, APP2, APP3],
    "commitments": [
        {"number": "SC-004", "vendor": "Example Framing", "type": "Subcontract",
         "lines": [{"cost_code": "06-1000", "description": "Framing",
                    "amount": "120000.00"}],
         "retainage": "10", "insurance_expires": "2026-09-30",
         "license_expires": "2027-06-30", "w9": "Yes"},
        {"number": "PO-002", "vendor": "Example Ready-Mix",
         "type": "Purchase Order",
         "lines": [{"cost_code": "03-3000", "description": "Ready-mix",
                    "amount": "30000.00"}],
         "retainage": "0", "insurance_expires": "2027-12-31",
         "license_expires": "", "w9": "Yes"}],
    "direct_costs": [
        {"id": "DC-001", "date": "2026-10-05", "vendor": "Example Pump Rental",
         "cost_code": "03-3000", "category": "E", "amount": "1850.00",
         "invoice": "VP-311", "status": "Approved"},
        {"id": "DC-002", "date": "2026-09-25", "vendor": "Example Framing",
         "cost_code": "06-1000", "category": "S", "amount": "96000.00",
         "invoice": "AF-2", "status": "Paid", "commitment": "SC-004"}],
    "timecards": [
        {"id": "TC-019", "date": "2026-10-19", "foreman": "R. Silva",
         "crew": [{"name": "M. Chen", "class": "LAB", "hours": "8"},
                  {"name": "J. Ruiz", "class": "LAB", "hours": "8"},
                  {"name": "T. Okafor", "class": "OPR", "hours": "8"},
                  {"name": "L. Novak", "class": "FMN", "hours": "8"}],
         "equipment": [],
         "production": [{"cost_code": "03-3000", "qty": "42", "unit": "CY",
                         "hours": "32"}]}],
    "directory": [
        {"name": "Dana Ortiz", "company": "Example Health District",
         "email": "dana@example.test", "phone": "", "role": "Owner"},
        {"name": "Sam Apex", "company": "Example Framing",
         "email": "ap@apex.example", "phone": "", "role": "Subcontractor"}],
}


def stage(n=1):
    """1: apps 1-2 certified; 2: app 3 certified; 3: COR-002 executed."""
    s = copy.deepcopy(BASE)
    if n >= 2:
        s["payapps"][2]["status"] = "certified"
        s["source"]["taken_at"] = "2026-10-31T16:00"
    if n >= 3:
        c2 = s["changes"][1]
        c2.update(stage="co", co="CO-002", approved_amount="8500.00",
                  executed="2026-11-05")
        s["source"]["taken_at"] = "2026-11-06T08:00"
    return s


def import_stage(office, n):
    return jobs.import_snapshot(office, interface.load_snapshot(stage(n)))


STEP_USER = {"jobrole:PM": "pm@bo.test", "role:Controller": "ctl@bo.test",
             "role:Admin": "admin@bo.test", "jobrole:Foreman": "fm@bo.test"}


def approve_ap(office, iid, override_reason="", gl_date=None):
    """Walk an AP invoice through every approval step."""
    from quantisheet_backoffice import ap, approvals
    who = office.user
    if ap.invoice(office, iid)["status"] in ("Draft", "Rejected"):
        office.act_as("ap@bo.test")
        ap.submit(office, iid)
    while True:
        req = approvals.request(office, "ap_invoice", iid)
        if req["status"] != "pending":
            break
        p = req["steps"][req["step"]]["principals"][0]
        office.act_as(STEP_USER[p])
        ap.approve(office, iid, override_reason=override_reason,
                   gl_date=gl_date)
    office.act_as(who["id"])
    return ap.invoice(office, iid)


def ap_invoice(office, vendor, no, date, amount, job_id=None, code="03-3000",
               cat="M", **kw):
    from quantisheet_backoffice import ap
    who = office.user
    office.act_as("ap@bo.test")
    v = ap.vendor_by_name(office, vendor)
    vid = v["id"] if v else ap.add_vendor(office, vendor)
    iid = ap.create_invoice(office, vid, no, date, amount, job_id=job_id,
                            lines=kw.pop("lines", None) or
                            [{"cost_code": code if job_id else "",
                              "category": cat, "amount": amount}], **kw)
    office.act_as(who["id"])
    return iid
