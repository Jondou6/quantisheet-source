"""Backflow tester and gauge checks (QuantiSheet 1.2, QW3), and the
report's submission to the water district.

- Each tester's certificate number and expiry date (South Carolina
  certificates run 3 years - the date on the card is what counts).
- Each test kit / gauge: serial, last calibration, and its accuracy (the
  usual figure: within 2% of full scale or 0.3 psid). Calibration is due
  every service_gauge_calibration_months (12 unless set otherwise - set
  it to your district's rule).
- Before a report prints: a warning when the certificate or the gauge
  calibration has run out (or runs out within 30 days), and a "retest
  after repair" warning when repairs are listed with no after-repair
  results (SC R.61-58.7: test at install, at least yearly, and right
  after any repair).
- Submission: method, where to and days to submit are settings
  (service_backflow_submit_method / _to / _days); there is no built-in
  deadline. QuantiSheet never sends anything - it records when a report
  was submitted.
"""
import datetime as dt

from . import files

FILE = "service_backflow_testers.json"
KIND = "service_backflow_testers"
METHODS = ("mail", "fax", "email", "hand-delivered", "other")
# Jon / Chief, Nov 5: the certificate and calibration rules wait for the
# licensed tech, like the refrigerant numbers
REVIEWED = False
RULE_NOTE = (("NOT YET REVIEWED - the tester-certificate and gauge-"
              "calibration rules haven't been checked by the licensed tech. ")
             if not REVIEWED else "") + (
    "Certificates: the expiry on the card (SC: 3 years). Gauges: "
    "calibrated every {months} months; accuracy within 2% of full scale or "
    "0.3 psid. Not legal advice.")


def rule_note():
    return RULE_NOTE.format(months=calibration_months())
WARN_DAYS = 30


class TesterError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "testers": [], "gauges": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _date(v, what):
    try:
        return files.iso_date(v, what, blank_ok=False)
    except files.FileError as e:
        raise TesterError(str(e)) from e


def set_tester(store, name, cert_no, cert_expires):
    name = files.txt(name)
    if not name or not files.txt(cert_no):
        raise TesterError("Name the tester and the certificate number.")
    row = next((t for t in store["testers"] if t["name"] == name), None)
    if row is None:
        row = {"id": files.new_id(), "name": name}
        store["testers"].append(row)
    row.update(cert_no=files.txt(cert_no, 40),
               cert_expires=_date(cert_expires, "Certificate expires"))
    return row


def set_gauge(store, serial, calibrated, make="", accuracy=""):
    serial = files.txt(serial, 60)
    if not serial:
        raise TesterError("Enter the gauge serial.")
    row = next((g for g in store["gauges"] if g["serial"] == serial), None)
    if row is None:
        row = {"id": files.new_id(), "serial": serial}
        store["gauges"].append(row)
    row.update(calibrated=_date(calibrated, "Last calibration"),
               make=files.txt(make, 80),
               accuracy=files.txt(accuracy, 60) or
               "within 2% of full scale or 0.3 psid")
    return row


def calibration_months():
    from .. import settings
    try:
        return max(1, int(settings.get("service_gauge_calibration_months")
                          or 12))
    except (TypeError, ValueError):
        return 12


def _add_months(d, m):
    from ..estimating import service as records_api
    return records_api.add_interval(d, m, "months")


def _repairs_listed(report):
    if (report.get("repair_materials") or "").strip():
        return True
    return any(report.get(k) for k in report
               if "_repair_" in k and not k.endswith("_note")) or \
        any((report.get(k) or "").strip() for k in report
            if k.endswith("_repair_note"))


def _after_results(report):
    return any(report.get(k) for k in report
               if "_after_" in k and (k.endswith("_leaked") or
                                      k.endswith("_tight") or
                                      k.endswith("_psi")))


def check(report, store, today=None):
    """[(kind, text)] warnings to show before printing. kind is "stop"
    for something expired, "warn" for soon or missing."""
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    out = []
    t = next((x for x in store["testers"]
              if x["name"] == (report.get("tester") or "").strip()), None)
    if t is None:
        out.append(("warn", "This tester isn't on file - add the "
                            "certificate number and expiry (Testers & "
                            "gauges)."))
    else:
        exp = dt.date.fromisoformat(t["cert_expires"])
        if report.get("cert_no") and report["cert_no"] != t["cert_no"]:
            out.append(("warn", f"The certificate number on the report "
                                f"({report['cert_no']}) isn't the one on "
                                f"file ({t['cert_no']})."))
        if exp < today:
            out.append(("stop", f"{t['name']}'s tester certificate expired "
                                f"on {exp}."))
        elif (exp - today).days <= WARN_DAYS:
            out.append(("warn", f"{t['name']}'s tester certificate expires "
                                f"on {exp}."))
    serial = (report.get("gauge_serial") or "").strip()
    g = next((x for x in store["gauges"] if x["serial"] == serial), None)
    if not serial:
        out.append(("warn", "No gauge picked for this test."))
    elif g is None:
        out.append(("warn", f"Gauge {serial} isn't on file."))
    else:
        due = _add_months(dt.date.fromisoformat(g["calibrated"]),
                          calibration_months())
        if due < today:
            out.append(("stop", f"Gauge {serial} was due for calibration on "
                                f"{due} (last {g['calibrated']})."))
        elif (due - today).days <= WARN_DAYS:
            out.append(("warn", f"Gauge {serial} is due for calibration on "
                                f"{due}."))
    if _repairs_listed(report) and not _after_results(report):
        out.append(("warn", "Repairs are listed but there are no "
                            "after-repair results - retest the assembly "
                            "after the repair."))
    return out


def submission():
    """{"method", "to", "days"} from settings (days None: not set)."""
    from .. import settings
    days = settings.get("service_backflow_submit_days")
    try:
        days = int(days) if days not in (None, "") else None
    except (TypeError, ValueError):
        days = None
    method = settings.get("service_backflow_submit_method") or ""
    return {"method": method if method in METHODS else "",
            "to": settings.get("service_backflow_submit_to") or "",
            "days": days}


def submit_by(report):
    """The date the report is due at the district, or "" (not set)."""
    s = submission()
    if s["days"] is None or not report.get("test_date"):
        return ""
    d = dt.date.fromisoformat(report["test_date"])
    return (d + dt.timedelta(days=s["days"])).isoformat()


def submit_line(report):
    s = submission()
    if not s["method"]:
        return "Submission: set the method in the backflow settings."
    by = submit_by(report)
    return (f"Submit by {s['method']}" + (f" to {s['to']}" if s["to"]
                                         else "") +
            (f", by {by}" if by else "") + ".")


def mark_submitted(report, how="", when=None):
    s = submission()
    how = how or s["method"]
    if how not in METHODS:
        raise TesterError("Mail, fax, email, hand-delivered or other.")
    report["submitted"] = {"how": how, "on": _date(when or dt.date.today(),
                                                   "Submitted on")}
    return report["submitted"]


def unsubmitted(store_reports, today=None):
    """Reports not yet submitted, with their due date (when set)."""
    out = []
    for r in store_reports:
        if r.get("submitted"):
            continue
        out.append((r.get("number", ""), r.get("acct_name", ""),
                    submit_by(r)))
    return out
