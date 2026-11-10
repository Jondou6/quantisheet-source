"""Plumbing test certificates (QuantiSheet 1.2, #16 / QW8): a gas piping
pressure test and a drain camera inspection, as fillable PDFs - filled
from a work order, or blank in the Form Library (category "Plumbing").

The forms record what the tech did and saw. They state no code test
pressure or duration: those come from the local code and the permit, and
the tech writes them in. QuantiSheet doesn't decide pass or fail.
"""
import datetime as dt
import os
import tempfile

KINDS = {
    "gas_test": "Gas Piping Pressure Test",
    "drain_camera": "Drain Camera Inspection",
}
OBSERVATIONS = ("", "Clear", "Roots", "Grease / buildup", "Belly / sag",
                "Offset joint", "Crack", "Break / collapse",
                "Separated joint", "Debris", "Other")
FINDING_ROWS = 8


class CertError(ValueError):
    pass


def _head(sheet, wo):
    rows = (("c_customer", "Customer", (wo or {}).get("customer", ""),
             36, 300),
            ("c_date", "Date", dt.date.today().isoformat() if wo else "",
             320, 440),
            ("c_wo", "Work order", (wo or {}).get("number", ""), 460, 576),
            ("c_address", "Address", " ".join(p for p in (
                (wo or {}).get("site", ""), (wo or {}).get("address", ""))
                if p), 36, 440),
            ("c_permit", "Permit no.", (wo or {}).get("permit_no", ""),
             460, 576))
    y = sheet.y + 8
    for i, (name, label, value, x0, x1) in enumerate(rows):
        top = y + (0 if i < 3 else 28)
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x1, top + 16), value)
    sheet.y = y + 60


def _sign(sheet, wo):
    sheet.need(80)
    sheet.section("", "Tested by")
    y = sheet.y + 8
    for name, label, value, x0, x1 in (
            ("c_tech", "Technician", (wo or {}).get("tech", ""), 36, 220),
            ("c_license", "License no.", "", 240, 380),
            ("c_signature", "Signature (type or sign)", "", 400, 576)):
        sheet.label(x0, y, label)
        sheet.text_field(name, (x0, y + 2, x1, y + 16), value)
    sheet.y = y + 30
    sheet.text(36, sheet.y, "Records the test as performed. Test pressure "
                            "and time per the local code and permit; "
                            "not a code determination.", 7.5)


def gas_test(sheet, wo):
    sheet.section("01", "System tested")
    y = sheet.y + 8
    for name, label, x0, x1 in (("g_scope", "Piping tested (new / "
                                 "altered section, appliances)", 36, 576),):
        sheet.label(x0, y, label)
        sheet.text_field(name, (x0, y + 2, x1, y + 30), multiline=True)
    y += 40
    sheet.label(36, y, "Pipe material")
    sheet.combo("g_material", (36, y + 2, 200, y + 16),
                ["", "Black steel", "CSST", "Copper", "PE (buried)",
                 "Other"])
    sheet.label(220, y, "Test medium")
    sheet.combo("g_medium", (220, y + 2, 340, y + 16),
                ["", "Air", "Nitrogen", "Other inert gas"])
    sheet.label(360, y, "Appliances isolated")
    sheet.checkbox("g_isolated", (360, y + 3, 372, y + 15))
    sheet.y = y + 30
    sheet.section("02", "Test")
    y = sheet.y + 8
    for i, (name, label) in enumerate((
            ("g_req_pressure", "Required test pressure (code / permit)"),
            ("g_req_minutes", "Required duration, minutes"),
            ("g_gauge", "Gauge (type, range, increments)"),
            ("g_start", "Start: time and pressure"),
            ("g_end", "End: time and pressure"),
            ("g_drop", "Pressure drop observed"))):
        top = y + (i // 2) * 28
        x0 = 36 if i % 2 == 0 else 320
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x0 + 250, top + 16))
    y += 3 * 28 + 6
    sheet.label(36, y, "Result")
    sheet.combo("g_result", (36, y + 2, 200, y + 16),
                ["", "Held - no drop", "Did not hold", "Retest needed"])
    sheet.label(220, y, "Leaks found / repaired")
    sheet.text_field("g_leaks", (220, y + 2, 576, y + 16))
    sheet.y = y + 30


def drain_camera(sheet, wo):
    sheet.section("01", "Line inspected")
    y = sheet.y + 8
    for i, (name, label) in enumerate((
            ("d_line", "Line (main / branch / lateral)"),
            ("d_access", "Access point (cleanout, roof vent...)"),
            ("d_material", "Pipe material"), ("d_size", "Diameter"),
            ("d_length", "Length inspected, ft"),
            ("d_recording", "Recording file name"))):
        top = y + (i // 2) * 28
        x0 = 36 if i % 2 == 0 else 320
        sheet.label(x0, top, label)
        sheet.text_field(name, (x0, top + 2, x0 + 250, top + 16))
    sheet.y = y + 3 * 28 + 6
    sheet.section("02", "Findings (distance from the access point)")
    y = sheet.y + 6
    sheet.label(36, y, "Distance, ft")
    sheet.label(120, y, "Observation")
    sheet.label(290, y, "Notes")
    for i in range(1, FINDING_ROWS + 1):
        top = y + 4 + (i - 1) * 22
        sheet.text_field(f"d_dist{i}", (36, top, 110, top + 15))
        sheet.combo(f"d_obs{i}", (120, top, 280, top + 15), OBSERVATIONS)
        sheet.text_field(f"d_note{i}", (290, top, 576, top + 15))
    y += 4 + FINDING_ROWS * 22 + 10
    sheet.label(36, y, "Recommendation")
    sheet.text_field("d_recommend", (36, y + 2, 576, y + 40), multiline=True)
    sheet.y = y + 50


def pdf(kind, path, wo=None, comp=None):
    """The certificate, filled from `wo` (a work order dict) when given."""
    from .pdfdoc import Sheet
    if kind not in KINDS:
        raise CertError("Pick a gas pressure test or a drain camera "
                        "inspection.")
    sheet = Sheet(KINDS[kind], comp, subtitle=(wo or {}).get("number", ""))
    sheet.section("", "Job")
    _head(sheet, wo)
    (gas_test if kind == "gas_test" else drain_camera)(sheet, wo)
    _sign(sheet, wo)
    return sheet.save(path)


def install_templates(comp=None):
    """Put the blank certificates in the Form Library (once). Returns the
    entries added."""
    from .. import formlib
    have = {(e["category"], e["name"]) for e in formlib.entries()}
    added = []
    for kind, name in KINDS.items():
        if ("Plumbing", name) in have:
            continue
        tmp = os.path.join(tempfile.mkdtemp(prefix="qs_cert_"),
                           f"{name}.pdf")
        pdf(kind, tmp, comp=comp)
        added.append(formlib.add(tmp, category="Plumbing", name=name,
                                 notes="QuantiSheet certificate (1.2)"))
    return added
