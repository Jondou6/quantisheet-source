"""Backflow assembly test report.

A fillable letter PDF. The header is the company from proposal.company().
Customer, site and device are filled from the service record. The next
test is one year after the test date.

The layout is this program's own: a slate band, copper section marks and
a results grid. It is not a water-system form, and it carries no outside
organization's name, mark, address or phone.
"""
import datetime as dt

from ..estimating import service as records_api
from . import files

FILE = "service_backflow.json"
KIND = "service_backflow"

APPLICATIONS = ("", "Domestic", "Fire Line", "Irrigation", "Other")
CATEGORIES = ("", "General", "Limited", "Inspector")
METHODS = ("", "Direction of flow", "Differential")
KITS = ("", "Vertical tube", "Differential gauge")

# point id, label, "pair" (leaked / tight / psi), "valve" (leaked / tight)
# or "psi" (opened-at psi only)
POINTS = (
    ("c1", "Check 1", "pair"),
    ("c2", "Check 2", "pair"),
    ("rv", "Air inlet / relief valve", "psi"),
    ("so1", "Shutoff valve 1", "valve"),
    ("so2", "Shutoff valve 2", "valve"),
)
PHASES = (
    ("before", "Before repairs"),
    ("repair", "Repairs & materials"),
    ("after", "After repairs"),
)


class BackflowError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "next": 1, "reports": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _choice(value, choices, what):
    value = " ".join(str(value or "").split())
    if value not in choices:
        raise BackflowError(f"{what} must be one of: " +
                            ", ".join(c for c in choices if c) + ".")
    return value


def empty_report():
    data = {
        "acct_name": "", "acct_address": "", "acct_no": "", "meter_no": "",
        "dev_name": "", "dev_model": "", "dev_serial": "", "dev_size": "",
        "dev_application": "", "dev_location": "",
        "test_date": "", "next_due": "", "repair_materials": "",
        "tester": "", "cert_no": "", "cert_company": "", "cert_phone": "",
        "category": "", "method": "", "kit": "", "signature": "",
        "comments": "", "property_id": "", "equipment_id": "",
    }
    for pid, _label, kind in POINTS:
        data[f"{pid}_repair_note"] = ""      # what was repaired / replaced
        for phase, _plab in PHASES:
            if kind != "psi":
                data[f"{pid}_{phase}_leaked"] = False
                data[f"{pid}_{phase}_tight"] = False
            if kind != "valve":
                data[f"{pid}_{phase}_psi"] = ""
    return data


def apply_due(report):
    """Next test is one year after the test date."""
    if not report.get("test_date"):
        report["next_due"] = ""
        return report
    d = dt.date.fromisoformat(report["test_date"])
    report["next_due"] = records_api.add_interval(d, 1, "years").isoformat()
    return report


def from_service(records, property_id, equipment_id="", comp=None,
                 test_date=""):
    """A report filled from the service record. Company and phone on the
    certification come from proposal.company() when `comp` is omitted."""
    prop = records_api.find(records, property_id) if records else None
    if not prop or "customer" not in prop:
        raise BackflowError("That site isn't in the service records.")
    report = empty_report()
    report["property_id"] = property_id
    report["acct_name"] = prop.get("customer") or prop.get("name") or ""
    report["acct_address"] = prop.get("address") or ""
    if equipment_id:
        eq = records_api.find(records, equipment_id)
        if not eq or "kind" not in eq:
            raise BackflowError("That device isn't in the service records.")
        if eq.get("property") != property_id:
            raise BackflowError("That device is not at this site.")
        report["equipment_id"] = equipment_id
        report["dev_name"] = eq.get("kind") or ""
        report["dev_model"] = eq.get("model") or ""
        report["dev_serial"] = eq.get("serial") or ""
    if comp is None:
        from .. import proposal
        comp = proposal.company()
    comp = comp or {}
    report["cert_company"] = str(comp.get("name") or "")
    report["cert_phone"] = str(comp.get("phone") or "")
    if test_date:
        try:
            report["test_date"] = files.iso_date(test_date, "Test date",
                                                 blank_ok=False)
        except files.FileError as e:
            raise BackflowError(str(e)) from e
        apply_due(report)
    return report


def _clean(report):
    base = empty_report()
    out = dict(base)
    src = report or {}
    for key in ("acct_name", "acct_address", "acct_no", "meter_no",
                "dev_name", "dev_model", "dev_serial", "dev_size",
                "dev_location", "repair_materials", "tester", "cert_no",
                "cert_company", "cert_phone", "signature", "comments",
                "property_id", "equipment_id"):
        out[key] = files.txt(src.get(key), 400 if "address" in key or
                             key in ("comments", "repair_materials") else 120)
    out["dev_application"] = _choice(src.get("dev_application"), APPLICATIONS,
                                     "Application")
    out["category"] = _choice(src.get("category"), CATEGORIES, "Category")
    out["method"] = _choice(src.get("method"), METHODS, "Method")
    out["kit"] = _choice(src.get("kit"), KITS, "Test kit")
    try:
        out["test_date"] = files.iso_date(src.get("test_date"), "Test date")
    except files.FileError as e:
        raise BackflowError(str(e)) from e
    for pid, _label, kind in POINTS:
        out[f"{pid}_repair_note"] = files.txt(src.get(f"{pid}_repair_note"),
                                              120)
        for phase, _plab in PHASES:
            if kind != "psi":
                out[f"{pid}_{phase}_leaked"] = bool(src.get(
                    f"{pid}_{phase}_leaked"))
                out[f"{pid}_{phase}_tight"] = bool(src.get(
                    f"{pid}_{phase}_tight"))
            if kind != "valve":
                out[f"{pid}_{phase}_psi"] = files.txt(
                    src.get(f"{pid}_{phase}_psi"), 20)
    apply_due(out)
    return out


def add(store, report):
    data = _clean(report)
    if not data["acct_name"]:
        raise BackflowError("Name the account.")
    if not data["dev_name"]:
        raise BackflowError("Name the device.")
    n = int(store.get("next") or 1)
    store["next"] = n + 1
    data["id"] = files.new_id()
    data["number"] = f"BF-{n:04d}"
    store["reports"].append(data)
    return data["id"]


def get(store, rid):
    for r in store["reports"]:
        if r["id"] == rid:
            return r
    raise BackflowError("That report isn't on file.")


def _on(value):
    return bool(value) and str(value).lower() not in ("0", "false", "off", "")


def write_pdf(report, path, comp=None):
    """Fillable PDF. Header company is proposal.company() when omitted.
    Field values are the report. Next test due is read-only."""
    from .pdfdoc import LEFT, RIGHT, Sheet
    number = str((report or {}).get("number") or "")
    data = _clean(report)
    if comp is None:
        from .. import proposal
        comp = proposal.company()
    sheet = Sheet("Backflow Assembly Test Report", comp, subtitle=number)
    sheet.section("01", "Customer & Site")
    y = sheet.y + 2
    fields = (
        ("acct_name", "Account name", data["acct_name"], LEFT, 300),
        ("acct_no", "Account no.", data["acct_no"], 316, RIGHT),
        ("acct_address", "Account address", data["acct_address"], LEFT, 300),
        ("meter_no", "Meter no.", data["meter_no"], 316, RIGHT),
    )
    for i, (name, label, value, x0, x1) in enumerate(fields):
        top = y + (i // 2) * 26
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x1, top + 16), value)
    sheet.y = y + 58
    sheet.section("02", "Device")
    y = sheet.y + 2
    device = (
        ("dev_name", "Device", data["dev_name"], LEFT, 200),
        ("dev_model", "Model", data["dev_model"], 214, 360),
        ("dev_serial", "Serial", data["dev_serial"], 374, RIGHT),
        ("dev_size", "Size", data["dev_size"], LEFT, 120),
        ("dev_location", "Location", data["dev_location"], 134, RIGHT),
    )
    for i, (name, label, value, x0, x1) in enumerate(device):
        top = y + (0 if i < 3 else 26)
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x1, top + 16), value)
    sheet.label(LEFT, y + 52, "Application")
    sheet.combo("dev_application", (LEFT, y + 54, 220, y + 68),
                APPLICATIONS, data["dev_application"])
    sheet.y = y + 80
    sheet.section("03", "Test Results")
    # column headers
    col_x = {"before": 230, "repair": 360, "after": 490}
    sheet.y += 12
    for phase, label in PHASES:
        sheet.text(col_x[phase], sheet.y, label, 7.5, True,
                   color=(0.38, 0.40, 0.42))
    for pid, label, kind in POINTS:
        row_h = 40 if kind == "pair" else 20
        sheet.need(row_h + 6)
        sheet.y += 12
        sheet.text(LEFT, sheet.y, label, 8, True)
        for phase, _plab in PHASES:
            x = col_x[phase]
            if phase == "repair":
                # what was done to this part, not a pass / fail (Nov 4)
                sheet.text_field(
                    f"{pid}_repair_note",
                    (x, sheet.y - 8, x + 112, sheet.y + (22 if kind == "pair"
                                                         else 6)),
                    data.get(f"{pid}_repair_note") or "",
                    multiline=kind == "pair")
                continue
            if kind == "psi":
                sheet.text(x, sheet.y - 10, "Opened at", 6.5,
                           color=(0.38, 0.40, 0.42))
                sheet.text_field(
                    f"{pid}_{phase}_psi",
                    (x + 36, sheet.y - 8, x + 84, sheet.y + 6),
                    data.get(f"{pid}_{phase}_psi") or "")
                sheet.text(x + 87, sheet.y, "psi", 6.5)
                continue
            sheet.checkbox(f"{pid}_{phase}_leaked",
                           (x, sheet.y - 8, x + 9, sheet.y + 1),
                           _on(data.get(f"{pid}_{phase}_leaked")))
            sheet.text(x + 11, sheet.y, "Leaked", 6.5)
            sheet.checkbox(f"{pid}_{phase}_tight",
                           (x + 48, sheet.y - 8, x + 57, sheet.y + 1),
                           _on(data.get(f"{pid}_{phase}_tight")))
            sheet.text(x + 59, sheet.y, "Closed tight", 6.5)
            if kind == "pair":
                sheet.text(x, sheet.y + 18, "Diff.", 6.5,
                           color=(0.38, 0.40, 0.42))
                sheet.text_field(
                    f"{pid}_{phase}_psi",
                    (x + 20, sheet.y + 8, x + 72, sheet.y + 22),
                    data.get(f"{pid}_{phase}_psi") or "")
                sheet.text(x + 75, sheet.y + 18, "psi", 6.5)
        sheet.y += row_h
    sheet.need(36)
    sheet.y += 8
    sheet.label(LEFT, sheet.y, "Repairs and materials")
    sheet.text_field("repair_materials", (LEFT, sheet.y + 4, RIGHT, sheet.y + 28),
                     data.get("repair_materials") or "", multiline=True)
    sheet.y += 40
    sheet.section("04", "Certification")
    y = sheet.y + 2
    cert = (
        ("tester", "Tester", data["tester"]),
        ("cert_no", "Certification no.", data["cert_no"]),
        ("cert_company", "Company", data["cert_company"]),
        ("cert_phone", "Phone", data["cert_phone"]),
        ("signature", "Signature", data["signature"]),
        ("test_date", "Test date", data["test_date"]),
    )
    for i, (name, label, value) in enumerate(cert):
        col = i % 2
        row = i // 2
        x0 = LEFT if col == 0 else 320
        x1 = 300 if col == 0 else RIGHT
        top = y + row * 26
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x1, top + 16), value)
    y = y + 3 * 26 + 4
    sheet.label(LEFT, y, "Category")
    sheet.combo("category", (LEFT, y + 2, 160, y + 16), CATEGORIES,
                data["category"])
    sheet.label(176, y, "Method")
    sheet.combo("method", (176, y + 2, 340, y + 16), METHODS, data["method"])
    sheet.label(356, y, "Test kit")
    sheet.combo("kit", (356, y + 2, RIGHT, y + 16), KITS, data["kit"])
    sheet.y = y + 28
    sheet.label(LEFT, sheet.y, "Comments")
    sheet.text_field("comments", (LEFT, sheet.y + 4, RIGHT, sheet.y + 32),
                     data.get("comments") or "", multiline=True)
    sheet.y += 44
    sheet.label(LEFT, sheet.y, "Next test due")
    sheet.text_field("next_due", (LEFT + 80, sheet.y - 8, LEFT + 180, sheet.y + 6),
                     data.get("next_due") or "", readonly=True)
    return sheet.save(path)


# ---- the data for a district's own form (review 2, Nov 4) -----------------

SHEET_LABELS = (
    ("Device", (("dev_name", "Make"), ("dev_model", "Model"),
                ("dev_serial", "Serial no."), ("dev_size", "Size"),
                ("dev_application", "Application / use"),
                ("dev_location", "Location of assembly"))),
    ("Site", (("acct_name", "Customer / site name"),
              ("acct_address", "Service address"))),
    ("Test", (("test_date", "Test date"), ("next_due", "Next test due"),
              ("method", "Test method"), ("kit", "Test kit"))),
    ("Tester", (("tester", "Tester"), ("cert_no", "Certification no."),
                ("cert_company", "Company"), ("cert_phone", "Phone"),
                ("category", "Certification category"))),
)


def data_sheet_lines(report):
    """[(section, label, value)] of everything a district's own form
    usually asks for, in plain words - for copying onto that form or its
    web portal. Many districts accept only their own form."""
    data = _clean(report)
    out = []
    for sec, items in SHEET_LABELS:
        for key, label in items:
            out.append((sec, label, str(data.get(key) or "")))
    for pid, plabel, kind in POINTS:
        for phase, phlabel in PHASES:
            bits = []
            if kind != "psi":
                if data.get(f"{pid}_{phase}_tight"):
                    bits.append("closed tight")
                if data.get(f"{pid}_{phase}_leaked"):
                    bits.append("leaked")
            if kind != "valve" and data.get(f"{pid}_{phase}_psi"):
                bits.append(f"{data[f'{pid}_{phase}_psi']} psi")
            if bits:
                out.append(("Results", f"{plabel} - {phlabel}",
                            ", ".join(bits)))
        if data.get(f"{pid}_repair_note"):
            out.append(("Repairs", plabel, data[f"{pid}_repair_note"]))
    if data.get("repair_materials"):
        out.append(("Repairs", "Materials", data["repair_materials"]))
    if data.get("comments"):
        out.append(("Notes", "Comments", data["comments"]))
    return out


def write_data_sheet(report, path):
    """One page: every value above, labelled, to copy onto the district's
    form. Not a test report form itself."""
    import fitz
    d = fitz.open()
    pg = d.new_page(width=612, height=792)
    y = 60
    pg.insert_text((50, y), "Backflow test - data for the district's form",
                   fontsize=15)
    y += 18
    pg.insert_text((50, y), "Copy these onto the water district's own form "
                   "or portal. This sheet is not that form.", fontsize=9,
                   color=(0.35, 0.35, 0.35))
    y += 22
    last = None
    for sec, label, value in data_sheet_lines(report):
        if y > 750:
            pg = d.new_page(width=612, height=792)
            y = 60
        if sec != last:
            y += 6
            pg.insert_text((50, y), sec.upper(), fontsize=9,
                           color=(0.55, 0.35, 0.2))
            y += 14
            last = sec
        pg.insert_text((60, y), f"{label}:", fontsize=10)
        pg.insert_text((250, y), value or "-", fontsize=10)
        y += 15
    d.save(path)
    d.close()
    return path
