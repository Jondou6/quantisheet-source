"""Offscreen smoke run: make a temp company, sign in, open the Back Office
window, visit every page, grab a screenshot, quit."""
import os, sys, tempfile
home = tempfile.mkdtemp(prefix="qsbo-smoke-")
os.environ.update(HOME=home, USERPROFILE=home, APPDATA=home, LOCALAPPDATA=home,
                  QS_BACKOFFICE_HOME=os.path.join(home, "bo"), QT_QPA_PLATFORM="offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from quantisheet_backoffice import office as officemod, jobs, security
from quantisheet_backoffice.ui.main_window import NAV, BackOfficeWindow
o = officemod.Office(os.path.join(home, "bo"))
security.add_user(o.db, "Smoke Admin", "admin@smoke.test", "Admin", "Sm0ke-pass!x-long", "Owner")
snap = os.path.join(os.path.dirname(officemod.__file__), "tests", "data", "golden_snapshot.json")
o.sign_in("admin@smoke.test", "Sm0ke-pass!x-long")
job = jobs.import_file(o, snap).job_id
print("import:", job)
# M3 data: full books, one employee, a week of approved time, final payroll
from quantisheet_backoffice import hr, payroll, timeentry
o.set_company(accounting_mode="full")
eid = hr.add_employee(o, "M. Chen", "E101", "2026-03-02", labor_class="LAB",
                      ssn="900-00-1234")
wid = hr.employee(o, eid)["worker_id"]
payroll.pay_setup(o, wid, pay_rate="42.00")
ids = [timeentry.add_line(o, wid, d, job, "03-3000", "10")
       for d in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22")]
timeentry.submit(o, ids)
security.add_user(o.db, "Smoke PM", "pm@smoke.test", "Approver", "Sm0ke-pass!x-long", "PM")
o.act_as("pm@smoke.test"); timeentry.decide(o, ids, "approve")
o.act_as("admin@smoke.test")
pid = payroll.add_period(o, "2026-10-19", "2026-10-25", "2026-10-30")
pv = payroll.preview(o, pid)
print("payroll preview:", [(x["name"], x["gross"]) for x in pv["workers"]])
payroll.finalize(o, pid)
print("employee ssn shown as:", hr.employee(o, eid)["ssn"])
w = BackOfficeWindow(o); w.resize(1280, 800); w.show()
for i, n in enumerate(NAV):
    w.nav.setCurrentRow(i); app.processEvents()
    print("page ok:", n, type(w.pages[n]).__name__)
w.nav.setCurrentRow(NAV.index("Billing")); app.processEvents()
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(home, "smoke.png")
w.grab().save(out)
from quantisheet_backoffice import assistant
a = assistant.ask(o, "Which lien waivers are missing?")
assert a["tool"] == "unavailable" and "AI is unavailable" in a["text"], a
print("ask (no model, decision 6.3 = A):", a["text"][:60], "| plain search hits:",
      len(a.get("search") or []))
for n in ("Payroll", "People", "Assistant", "Sync Center", "Books & Reports"):
    w.nav.setCurrentRow(NAV.index(n)); app.processEvents()
    extra = out[:-4] + "_" + n.split()[0].lower() + ".png"
    w.grab().save(extra); print("shot:", extra)
print("status:", w.statusBar().currentMessage()); print("shot:", out)
w.close(); app.quit()
