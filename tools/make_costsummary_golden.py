"""Run ONCE with QuantiSheet's own code (not part of either test suite):
builds a made-up Project Center project in a temp folder, then writes
  golden_costsummary.json - QuantiSheet's pm/cost.by_code numbers per code
  golden_snapshot.json    - what app/backoffice_hook.py hands Back Office
into quantisheet_backoffice/tests/data/ (brief test 7.3).

usage: python make_costsummary_golden.py <QuantiSheet root> <out folder>
Never touches ~/.quantisheet: run it with a temp HOME."""
import json
import os
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

root, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
for _name in (".quantisheet",):
    real = os.path.realpath(os.path.join(os.path.expanduser("~"), _name))
    assert not os.path.isdir(real), "run with a temp HOME"

from app import backoffice_hook                       # noqa: E402
from app.pm import cost                               # noqa: E402
from app.pm.store import ProjectStore                 # noqa: E402

folder = tempfile.mkdtemp(prefix="quantisheet-golden-")
s = ProjectStore(folder)
s.data["name"] = "Example Clinic"
s.set_setting("number", "2611")
s.set_setting("state", "OR")
for code, desc, cat, amt in (
        ("03-3000", "Cast-in-place concrete", "Labor", "48000"),
        ("06-1000", "Rough carpentry", "Subcontractor", "135000"),
        ("09-2000", "Gypsum board", "Subcontractor", "62000"),
        ("26-0500", "Electrical", "Subcontractor", "88000"),
        ("01-5000", "Temporary facilities", "Other", "12500.50")):
    s.save_record("budget", {"cost_code": code, "description": desc,
                             "category": cat, "original": amt})
apex = s.save_record("commitment", {
    "title": "Framing", "vendor": "Example Framing", "type": "Subcontract",
    "status": "Executed", "retainage": 10,
    "insurance_expires": "2026-09-30",
    "lines": [{"cost_code": "06-1000", "description": "Framing",
               "amount": 120000}]})
s.save_record("commitment", {
    "title": "Concrete supply", "vendor": "Example Ready-Mix",
    "type": "Purchase Order", "status": "Executed",
    "lines": [{"cost_code": "03-3000", "description": "Ready-mix",
               "amount": 30000},
              {"cost_code": "03-3000", "description": "Pump",
               "amount": 2750.25}]})
s.save_record("commitment", {
    "title": "Cancelled", "vendor": "Nobody", "status": "Void",
    "lines": [{"cost_code": "09-2000", "amount": 5000}]})
s.save_record("event", {   # approved, with Apex: budget and committed
    "title": "Added header beams", "status": "Approved",
    "approved": "2026-08-15",
    "lines": [{"cost_code": "06-1000", "vendor": "Example Framing",
               "cost": 8500, "markup": 10}]})
s.save_record("event", {   # approved, no vendor: budget only
    "title": "Owner upgrade", "status": "Approved", "approved": "2026-09-02",
    "lines": [{"cost_code": "09-2000", "cost": 3100.75, "markup": 15}]})
s.save_record("event", {   # pending: neither
    "title": "Extra outlets", "status": "Pending",
    "lines": [{"cost_code": "26-0500", "cost": 1800, "markup": 15}]})
for d, code, cat, amt, comm in (
        ("2026-10-05", "03-3000", "Material", 1850, None),
        ("2026-09-25", "06-1000", "Subcontractor", 96000, apex["_id"]),
        ("2026-10-12", "01-5000", "Other", 412.37, None),
        ("2026-10-14", "26-0500", "Material", 2200.10, None)):
    s.save_record("cost", {"date": d, "cost_code": code, "category": cat,
                           "amount": amt, "commitment": comm,
                           "vendor": "Test vendor", "status": "Approved"})
s.flush(force=True)

rows = cost.by_code(s)
C = Decimal("0.01")


def m(v):
    return str(Decimal(repr(v)).quantize(C, rounding=ROUND_HALF_UP))


golden = {"made_by": "app/pm/cost.by_code (QuantiSheet "
                     f"{backoffice_hook.__version__})",
          "rows": {k: {"revised": m(r["revised"]),
                       "committed": m(r["committed"]),
                       "actual": m(r["actual"])} for k, r in rows.items()}}
snap = backoffice_hook.snapshot(None, s)
snap["source"]["folder"] = ""
snap["source"]["taken_at"] = "2026-10-22T10:00"
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "golden_costsummary.json"), "w") as fh:
    json.dump(golden, fh, indent=1, sort_keys=True)
with open(os.path.join(out, "golden_snapshot.json"), "w") as fh:
    json.dump(snap, fh, indent=1)
print(json.dumps(golden["rows"], indent=1))
