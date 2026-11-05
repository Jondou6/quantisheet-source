"""Made-up fixtures for the Phase 2 people, payroll and field items (M3)."""
import copy

from quantisheet_backoffice import interface, jobs, security, timeentry

from .helpers import PW

HR = ("Hana Reyes", "hr@bo.test", "Payroll/HR", "")

WEEK = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
        "2026-10-23"]                      # Mon-Fri; pay week 10-19..10-25


def add_hr(office):
    if not office.db.one("SELECT id FROM users WHERE email = ?", (HR[1],)):
        security.add_user(office.db, HR[0], HR[1], HR[2], PW, HR[3])


def second_job(office, number="2702", name="Example Warehouse"):
    """A plain (not prevailing-wage) job with the same cost codes."""
    snap = {"interface_version": 1,
            "source": {"app": "QuantiSheet 0.13.1", "file": f"{name}.pdf",
                       "taken_at": "2026-10-18T09:00"},
            "project": {"name": name, "number": number, "state": "OR"},
            "cost_codes": [
                {"code": "03-3000", "description": "Concrete",
                 "category": "M"},
                {"code": "06-1000", "description": "Framing",
                 "category": "S"}]}
    return jobs.import_snapshot(office, interface.load_snapshot(snap)).job_id


def approve_time(office, ids):
    """Submit and approve time lines on the default PM path."""
    who = office.user
    office.act_as("admin@bo.test")
    timeentry.submit(office, ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, ids, "approve")
    office.act_as(who["id"])


def snapshot_with(base, **sections):
    s = copy.deepcopy(base)
    s.update(sections)
    return s
