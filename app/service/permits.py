"""Permits and inspections on service work orders (QuantiSheet 1.2,
#10 / QW5).

Which office applies depends on whether the job is inside city limits,
never on the mailing address: the jurisdiction is picked on each work
order (remembered per site, never chosen automatically). The offices and
how each takes inspection requests are data (Chief's research, Nov 5,
2026, from the offices' own pages; anything not confirmed is marked
UNVERIFIED). Other towns (Surfside Beach, Loris, Aynor, Atlantic Beach
and others) are "Other" with details for the office to fill in.

Which kinds of job need a permit is a setting (service_permit_types);
the starting list is what the shop pulls permits for today (Jon, Nov 5):
HVAC changeouts, new HVAC installs, gas line work and backflow device
installs. Closing a ticket that needs a permit warns until the final
inspection has passed.
"""
import datetime as dt
import os

from . import files

OFFICES = {
    "horry": {
        "name": "Horry County (unincorporated)",
        "phone": "843-915-5090",
        "how": "Mechanical and plumbing: call the inspection request line "
               "843-915-5090 (residential permits use the online portal).",
        "page": "https://horrycountysc.gov/departments/code-enforcement/",
        "portal": "", "unverified": "Portal address UNVERIFIED; no "
                                    "cut-off time found."},
    "myrtle_beach": {
        "name": "City of Myrtle Beach",
        "phone": "843-918-1111",
        "how": "Call 843-918-1111: by 4:00 PM the day before for a morning "
               "inspection, by 9:00 AM the same day for an afternoon one. "
               "Trade permits: permittech@cityofmyrtlebeach.com.",
        "page": "https://cityofmyrtlebeach.com/departments/"
                "construction_services_department.php",
        "portal": "", "unverified": "No online portal found (UNVERIFIED)."},
    "north_myrtle_beach": {
        "name": "City of North Myrtle Beach",
        "phone": "843-280-5560",
        "how": "Applications through the OpenGov portal; call Building "
               "843-280-5560.",
        "page": "https://www.nmb.us/177/Planning-Development",
        "portal": "https://northmyrtlebeachsc.portal.opengov.com/"
                  "categories/1071",
        "unverified": "Scheduling inspections in OpenGov is UNVERIFIED."},
    "conway": {
        "name": "City of Conway",
        "phone": "843-488-9888",
        "how": "Inspections only through the BS&A online portal; a total "
               "rough-in means scheduling each inspection separately.",
        "page": "https://www.conwaysc.gov/departments/building/index.php",
        "portal": "https://bsaonline.com/Home/Index?uid=2754",
        "unverified": "No cut-off time found."},
    "georgetown": {
        "name": "Georgetown County (unincorporated)",
        "phone": "843-545-3261",
        "how": "Inspection request line 843-545-3261 (office 843-545-3116).",
        "page": "https://gtcountysc.gov/176/Building-Department",
        "portal": "", "unverified": "No online portal found (UNVERIFIED); "
                                    "no cut-off time found."},
    "other": {"name": "Other (Surfside Beach, Loris, Aynor, Atlantic Beach "
                      "...)", "phone": "", "how": "Fill in the office's "
              "details on the ticket.", "page": "", "portal": "",
              "unverified": "Not researched."},
}
TYPES = {"hvac_changeout": "HVAC equipment changeout",
         "hvac_new": "New HVAC install", "gas_line": "Gas line work",
         "backflow_install": "Backflow device install",
         "water_heater": "Water heater replacement", "repipe": "Repipe"}
DEFAULT_NEEDS = ["hvac_changeout", "hvac_new", "gas_line",
                 "backflow_install"]
RESULTS = ("", "scheduled", "passed", "failed", "partial")
INSPECTIONS = ("rough", "final")


class PermitError(ValueError):
    pass


def needs_types():
    from .. import settings
    v = settings.get("service_permit_types")
    return [t for t in (v if isinstance(v, list) else DEFAULT_NEEDS)
            if t in TYPES]


def needs_permit(job_type):
    return job_type in needs_types()


def remembered(store, wo):
    """The jurisdiction last picked for this site (a suggestion only)."""
    key = wo.get("property_id") or wo.get("site")
    for o in reversed(store.get("orders", [])):
        if o is wo or not o.get("permit"):
            continue
        if (o.get("property_id") or o.get("site")) == key:
            return o["permit"].get("jurisdiction", "")
    return ""


def set_permit(store, wo_id, job_type="", jurisdiction="", number="",
               other_office="", pdf="", needed=None):
    from . import workorder
    wo = workorder.get(store, wo_id)
    if job_type and job_type not in TYPES:
        raise PermitError("Pick the kind of job.")
    if jurisdiction and jurisdiction not in OFFICES:
        raise PermitError("Pick the permit office.")
    if pdf and not os.path.isfile(pdf):
        raise PermitError("That permit PDF isn't there.")
    p = wo.setdefault("permit", {"inspections": []})
    p["job_type"] = job_type or p.get("job_type", "")
    p["needed"] = needs_permit(p["job_type"]) if needed is None \
        else bool(needed)
    if jurisdiction:
        p["jurisdiction"] = jurisdiction
    if p["needed"] and not p.get("jurisdiction"):
        raise PermitError("Pick the permit office - inside or outside city "
                          "limits decides it, not the mailing address.")
    p["number"] = files.txt(number, 60) or p.get("number", "")
    p["other_office"] = files.txt(other_office, 200) or \
        p.get("other_office", "")
    if pdf:
        p["pdf"] = os.path.abspath(pdf)
    wo["permit_no"] = p["number"]
    return p


def add_inspection(store, wo_id, kind, when, result="scheduled", notes=""):
    from . import workorder
    wo = workorder.get(store, wo_id)
    p = wo.get("permit")
    if not p:
        raise PermitError("Add the permit first.")
    if kind not in INSPECTIONS:
        raise PermitError("Rough or final inspection.")
    if result not in RESULTS:
        raise PermitError("Scheduled, passed, failed or partial.")
    try:
        d = files.iso_date(when, "Inspection date", blank_ok=False)
    except files.FileError as e:
        raise PermitError(str(e)) from e
    row = {"kind": kind, "date": d, "result": result,
           "notes": files.txt(notes, 300)}
    p["inspections"].append(row)
    return row


def final_passed(wo):
    p = wo.get("permit") or {}
    return any(i["kind"] == "final" and i["result"] == "passed"
               for i in p.get("inspections", []))


def close_warning(wo):
    """Text when the ticket needs a permit and the final hasn't passed."""
    p = wo.get("permit") or {}
    if not p.get("needed"):
        return ""
    if not p.get("number"):
        return "This job needs a permit and no permit number is on the " \
               "ticket."
    if not final_passed(wo):
        office = OFFICES.get(p.get("jurisdiction"), {})
        return ("The final inspection hasn't passed yet"
                + (f" ({office['name']}: {office['how']})" if office.get(
                    "how") else "") + ".")
    return ""


def summary(wo):
    p = wo.get("permit") or {}
    if not p:
        return "No permit on this ticket."
    office = OFFICES.get(p.get("jurisdiction"), {}).get("name", "-")
    last = p.get("inspections", [])[-1:] or [{}]
    return (f"{TYPES.get(p.get('job_type'), 'Job')}: permit "
            f"{p.get('number') or '(none yet)'}, {office}"
            + (f", {last[0].get('kind')} inspection {last[0].get('date')} "
               f"{last[0].get('result')}" if last[0] else "") +
            ("" if p.get("needed") else " (permit not required by the "
                                       "settings)"))


def open_permits(store, today=None):
    """Tickets with a permit whose final hasn't passed."""
    out = []
    for o in store.get("orders", []):
        p = o.get("permit")
        if p and p.get("needed") and not final_passed(o):
            out.append((o["number"], o["customer"], summary(o)))
    return out
