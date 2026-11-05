"""Screenshots of Project Center with a realistic sample job.

    python tools/pm_screens.py [OUTDIR]
"""
import os
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def sample(store):
    team = [("Pat Morgan", "Example Builders", "General Contractor",
             "jon@example.com"),
            ("Sam Rivera", "Example Builders", "General Contractor",
             "lee@example.com"),
            ("Ann Ross", "Ross Architects", "Architect", "ann@example.com"),
            ("Sam Pike", "Pike Concrete", "Subcontractor", "sam@example.com"),
            ("Lee Volt", "Volt Electric", "Subcontractor", "lee@example.com"),
            ("Kim Ash", "Aiken County", "Owner", "kim@example.com")]
    for n, c, r, e in team:
        store.save_record("member", {"name": n, "company": c, "role": r,
                                     "email": e})
    rfis = [("Kennel drain slope", "Plans show 1/8 in/ft at kennel trench "
             "drains; civil C-301 shows 1/4 in/ft. Which governs?",
             "Ann Ross", "Open", d(3), "Plan/Spec Discrepancy", "Yes"),
            ("Surgery suite door hardware", "Hardware set 7 calls for a "
             "storeroom lock at 118; the owner wants access control. "
             "Please confirm.", "Ann Ross", "Open", d(-2), "Clarification",
             "Undetermined"),
            ("Footing depth at grid C", "Geotech recommends 24 in below "
             "grade; S-101 shows 18 in.", "Ann Ross", "Closed", d(-9),
             "Engineering Conflict", "No"),
            ("FRP panel color in exam rooms", "Finish schedule omits FRP "
             "color for exam 1-4.", "Ann Ross", "Draft", d(7), "Finish "
             "Schedule", "No"),
            ("Generator pad location", "Pad conflicts with the storm "
             "inlet at the NE corner.", "Ann Ross", "Open", d(5),
             "Existing Conditions Conflict", "Yes")]
    for subj, q, to, st, due, why, cost in rfis:
        r = {"subject": subj, "question": q, "to": to, "status": st,
             "due": due, "reason": why, "cost_impact": cost,
             "from": "Pat Morgan", "cc": ["Sam Rivera", "Kim Ash"],
             "drawing": "A-101"}
        if st == "Closed":
            r["answer"] = "Use 24 in below grade per geotech."
            r["answered_by"] = "Ann Ross"
        store.save_record("rfi", r)
    subs = [("Concrete mix designs", "03 30 00", "Product Data", "Sam Pike",
             "In Review", d(40)),
            ("Reinforcing shop drawings", "03 20 00", "Shop Drawings",
             "Sam Pike", "Approved as Noted", d(30)),
            ("Hollow metal frames", "08 11 13", "Shop Drawings", "",
             "Not Submitted", d(70)),
            ("Lighting fixtures", "26 51 00", "Product Data", "Lee Volt",
             "Revise and Resubmit", d(60)),
            ("Epoxy floor in surgery", "09 67 23", "Samples", "",
             "Not Submitted", d(90))]
    for title, spec, typ, resp, st, need in subs:
        r = {"title": title, "spec": spec, "type": typ, "responsible": resp,
             "status": st, "required_on_site": need, "lead_days": 21,
             "review_days": 10,
             "workflow": [{"reviewer": "Pat Morgan", "days": 3,
                           "sent": d(-6), "returned": d(-4),
                           "result": "Approved"},
                          {"reviewer": "Ann Ross", "days": 10,
                           "sent": d(-4), "due": d(6)}]}
        from app.pm import schema
        r["submit_by"] = schema.submit_by(r)
        store.save_record("submittal", r)
    punch = [("Touch up paint at door frame", "Exam 2", "Sam Pike",
              "Work Required"),
             ("Ceiling tile stained", "Corridor 110", "Lee Volt",
              "Ready for Review"),
             ("Missing outlet cover plate", "Surgery 118", "Lee Volt",
              "Not Accepted"),
             ("Caulk joint at countertop", "Lab 104", "Sam Pike", "Closed"),
             ("Kennel gate latch sticks", "Kennel 12", "Sam Pike",
              "Work Required")]
    for t, loc, who, st in punch:
        store.save_record("punch", {"title": t, "location": loc,
                                    "assignee": who, "status": st,
                                    "due": d(4), "manager": "Pat Morgan",
                                    "priority": "Normal"})
    store.save_record("daily", {
        "date": d(0), "status": "Draft", "author": "Sam Rivera",
        "weather": {"high": "74", "low": "55", "sky": "Partly cloudy",
                    "precip": "0.00", "wind": "8"},
        "manpower": [{"company": "Pike Concrete", "trade": "Concrete",
                      "workers": 6, "hours": 8, "location": "Grid A-C",
                      "notes": "Formed and poured footings"},
                     {"company": "Volt Electric", "trade": "Electrical",
                      "workers": 3, "hours": 8, "location": "Slab",
                      "notes": "Underslab conduit"}],
        "work": "Footings grid A-C poured, 38 CY. Underslab electrical "
                "inspected and passed.",
        "deliveries": [{"time": "7:30", "supplier": "Aiken Ready Mix",
                        "contents": "38 CY 4000 psi", "received_by":
                        "Lee"}]})
    store.save_record("daily", {"date": d(-1), "status": "Submitted",
                                "author": "Sam Rivera",
                                "weather": {"high": "71", "low": "52",
                                            "sky": "Clear"},
                                "manpower": [{"company": "Pike Concrete",
                                              "workers": 5, "hours": 8}]})
    store.save_record("meeting", {
        "title": "OAC Meeting #4", "type": "OAC", "date": d(-1),
        "time": "10:00", "status": "Minutes",
        "attendees": [{"name": "Pat Morgan", "present": "Yes"},
                      {"name": "Ann Ross", "present": "Yes"},
                      {"name": "Kim Ash", "present": "Yes"}],
        "topics": [{"no": "4.1", "topic": "Generator pad conflict",
                    "owner": "Ann Ross", "due": d(5), "status": "Open"},
                   {"no": "4.2", "topic": "Schedule update",
                    "discussion": "On track for slab pour", "status":
                    "Info"}]})
    store.save_record("issue", {"title": "Storm inlet grate missing",
                                "assignee": "Sam Pike", "due": d(-1),
                                "status": "Open"})
    for code, desc, cat, amt in (
            ("01 50 00", "Temporary facilities", "Other", 42000),
            ("03 30 00", "Cast-in-place concrete", "Subcontractor", 186000),
            ("08 11 13", "Hollow metal doors and frames", "Material",
             38000),
            ("09 67 23", "Epoxy flooring", "Subcontractor", 54000),
            ("22 00 00", "Plumbing", "Subcontractor", 148000),
            ("26 00 00", "Electrical", "Subcontractor", 212000),
            ("01 31 00", "Project management", "Labor", 96000)):
        store.save_record("budget", {"cost_code": code, "description": desc,
                                     "category": cat, "original": amt})
    for i, (desc, amt) in enumerate((("General conditions", 138000),
                                     ("Sitework and concrete", 236000),
                                     ("Doors, frames and hardware", 52000),
                                     ("Finishes", 118000),
                                     ("Plumbing", 171000),
                                     ("Electrical", 244000)), 1):
        store.save_record("contract", {"item": str(i), "description": desc,
                                       "scheduled": amt})
    c1 = store.save_record("commitment", {
        "title": "Concrete", "vendor": "Sam Pike", "status": "Executed",
        "lines": [{"cost_code": "03 30 00", "description": "Footings, "
                   "slab, walks", "amount": 179500}]})
    store.save_record("commitment", {
        "title": "Electrical", "vendor": "Lee Volt", "status": "Executed",
        "lines": [{"cost_code": "26 00 00", "description": "Complete "
                   "electrical", "amount": 219800}]})
    store.save_record("commitment", {
        "title": "Plumbing", "vendor": "Gray Plumbing",
        "status": "Out for Signature",
        "lines": [{"cost_code": "22 00 00", "amount": 141250}]})
    store.save_record("event", {
        "title": "Add kennel trench drains", "status": "Approved",
        "approved": d(-5), "co_no": "CO-001", "reason": "Owner Request",
        "lines": [{"cost_code": "03 30 00", "vendor": "Sam Pike",
                   "cost": 8400, "markup": 12}]})
    store.save_record("event", {
        "title": "Relocate generator pad", "status": "Pending",
        "reason": "Unforeseen Condition", "submitted": d(-2),
        "lines": [{"cost_code": "26 00 00", "vendor": "Lee Volt",
                   "cost": 6200, "markup": 12}]})
    store.save_record("cost", {"date": d(-12), "vendor": "Sam Pike",
                               "cost_code": "03 30 00", "amount": 64000,
                               "commitment": c1["_id"], "retainage": 6400,
                               "status": "Paid"})
    store.save_record("cost", {"date": d(-3), "vendor": "United Rentals",
                               "cost_code": "01 50 00", "amount": 6850,
                               "category": "Equipment"})
    store.save_record("cost", {"date": d(-1), "vendor": "Payroll",
                               "cost_code": "01 31 00", "amount": 18400,
                               "category": "Labor"})
    store.save_record("observation", {"title": "Open edge at mezzanine",
                                      "type": "Safety",
                                      "assignee": "Sam Pike",
                                      "priority": "High",
                                      "status": "Initiated", "due": d(1)})


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "pmshots")
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="quantisheet-pm-")
    from app import settings, mail
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = {"author": "Pat Morgan"}
    mail.OUTBOX = []
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from app import theme
    from app.pm.store import ProjectStore
    from app.pm import center
    store = ProjectStore(os.path.join(tmp, "Aiken Spay-Neuter Clinic"))
    store.data["name"] = "Aiken County Spay-Neuter Clinic"
    sample(store)
    shots = []
    for mode in ("light", "dark"):
        theme.apply(app, mode)
        w = center.ProjectCenter(store)
        w.resize(1500, 900)
        w.show()
        app.processEvents()

        def grab(name):
            app.processEvents()
            p = os.path.join(out, f"{mode}-{name}.png")
            w.grab().save(p)
            shots.append(p)
        w.home.refresh()
        grab("home")
        page = w.show_tool("rfi", "All")
        app.processEvents()
        page.select(store.find("rfi", subject="Kennel drain slope")[0]
                    ["_id"])
        grab("rfis")
        page = w.show_tool("submittal", "All")
        page.select(store.find("submittal", title="Concrete mix designs")[0]
                    ["_id"])
        grab("submittals")
        page = w.show_tool("punch", "Open")
        page.select(store.find("punch", title="Missing outlet cover plate")
                    [0]["_id"])
        grab("punch")
        page = w.show_tool("daily", "All")
        page.select(store.find("daily", date=d(0))[0]["_id"])
        grab("daily")
        page = w.show_tool("meeting", "All")
        page.select(store.list("meeting")[0]["_id"])
        grab("meeting")
        for key in ("cost_summary", "forecast"):
            w.show_tool(key)
            for i in range(w.nav.count()):
                if w.nav.item(i).data(0x0100) == key:
                    w.nav.setCurrentRow(i)
            grab(key)
        page = w.show_tool("commitment", "All")
        page.select(store.list("commitment")[0]["_id"])
        grab("commitments")
        if mode == "light":
            dlg = center.CreateDialog(w, "rfi")
            dlg.show()
            app.processEvents()
            p = os.path.join(out, "light-new-rfi.png")
            dlg.grab().save(p)
            shots.append(p)
            dlg.close()
            j = center.JumpDialog(w)
            j.q.setText("rfi 2")
            j.show()
            app.processEvents()
            p = os.path.join(out, "light-jump.png")
            j.grab().save(p)
            shots.append(p)
            j.close()
        w.close()
    from app.pm import report
    p = os.path.join(out, "rfi-001.pdf")
    report.record_pdf(store, "rfi", store.list("rfi")[0], p)
    shots.append(p)
    p = os.path.join(out, "daily-log.pdf")
    report.record_pdf(store, "daily", store.find("daily", date=d(0))[0], p)
    shots.append(p)
    print("\n".join(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
