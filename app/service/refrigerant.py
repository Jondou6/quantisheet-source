"""Refrigerant log for EPA Section 608 recordkeeping.

Each unit has a refrigerant and a full charge. Each visit records pounds
added, pounds recovered, the cylinder number and the technician's 608
certificate number.

Leak rate uses the annualizing method. The repair limits below are the
published thresholds for appliances with a full charge of 50 pounds or
more. Units under 50 pounds are still rated and marked when they pass the
same percentages; the repair rule itself does not apply to them.

40 CFR 82.152 (definitions) — annualizing method:

    leak rate (% per year) =
        (pounds of refrigerant added / pounds in the full charge)
        x (365 / days in the period)
        x 100

    The period is the shorter of 365 days and the days since the previous
    addition (or since the date the full charge was recorded). When that
    start date was never recorded, the period is 365 days so a missing
    date cannot inflate the rate.

40 CFR 82.157(c) — leak repair for appliances containing 50 or more
pounds of refrigerant (40 CFR Part 82, Subpart F, Clean Air Act
Section 608). Repair is required when the leak rate exceeds:

    * 30%  industrial process refrigeration
    * 20%  commercial refrigeration
    * 10%  comfort cooling
    * 10%  all other appliances

QuantiSheet 1.2 (Nov 5): which rule applies now depends on the
refrigerant's class - 40 CFR 84.106 for HFCs with GWP above 53 at 15 lb
and up, 40 CFR 82.157 for ozone-depleting refrigerants at 50 lb and up
(refrigerant_rules.py has the numbers, all editable). A covered unit
over its limit opens a repair clock; verification tests, chronic
leakers and the owner's service record are kept here too.

No network calls. Amounts are Decimal.
"""
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from .. import dmoney
from . import files
from ..dmoney import c2 as _c2

FILE = "service_refrigerant.json"
KIND = "service_refrigerant"

# 40 CFR 82.157(c) thresholds, percent per year. See the module docstring.
THRESHOLDS = {
    "industrial_process": Decimal("30"),
    "commercial_refrigeration": Decimal("20"),
    "comfort_cooling": Decimal("10"),
    "other": Decimal("10"),
}
CATEGORY_LABELS = {
    "industrial_process": "industrial process refrigeration",
    "commercial_refrigeration": "commercial refrigeration",
    "comfort_cooling": "comfort cooling",
    "other": "other appliances",
}
# 40 CFR 82.157 applies at a full charge of 50 pounds or more.
REGULATORY_MIN_LBS = Decimal("50")


# shown in the window and on printouts: built from the rules in force
# (refrigerant_rules.note); stays NOT YET REVIEWED until the licensed tech
# signs off in the rules file (Jon, Nov 4-5).
REVIEWED = False


def rule_note():
    from . import refrigerant_rules
    return refrigerant_rules.note()


RULE_NOTE = ("NOT YET REVIEWED - see the rule note in the log window. "
             "Not legal advice.")
TECH_TYPES = ("", "Type I", "Type II", "Type III", "Universal")


class RefError(ValueError):
    pass


def _who():
    import getpass
    try:
        return getpass.getuser()
    except Exception:                                     # noqa: BLE001
        return ""


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _log(store, action, rid, before=None, after=None, why=""):
    """Every change is kept: who, when, what - entries are never edited
    or removed in place (review 2, Nov 4)."""
    store.setdefault("log", []).append({
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "by": _who(), "action": action, "id": rid,
        "before": before, "after": after, "why": why})


def correct_visit(store, visit_id, field, value, why):
    """Fix a typed mistake on a visit. The old value stays in the log with
    the reason; the visit is marked corrected."""
    if not files.txt(why):
        raise RefError("Say why the entry is being corrected.")
    allowed = ("lbs_added", "lbs_recovered", "cylinder", "cert_no", "tech",
               "notes", "date")
    if field not in allowed:
        raise RefError("That part of a visit can't be corrected.")
    v = next((v for v in store["visits"] if v["id"] == visit_id), None)
    if v is None:
        raise RefError("That visit isn't in the log.")
    try:
        if field in ("lbs_added", "lbs_recovered"):
            new = files.lbs(value, "Pounds")
        elif field == "date":
            new = files.iso_date(value, "Visit date", blank_ok=False)
        else:
            new = files.txt(value, 500 if field == "notes" else 40)
    except files.FileError as e:
        _err(e)
    old = v.get(field)
    v[field] = new
    v["corrected"] = True
    _log(store, "correct visit", visit_id, {field: old}, {field: new},
         files.txt(why, 300))
    return v


def history(store, rid=None):
    """The change log, oldest first (for one unit or visit when given)."""
    return [r for r in store.get("log", [])
            if rid is None or r.get("id") == rid]


def blank():
    return {"kind": KIND, "version": 1, "units": [], "visits": [], "log": [],
            "clocks": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return migrate(files.read(path or default_path(), KIND, blank))


def migrate(store):
    """Units from before 1.2 have no refrigerant class: mark each "needs
    review" with a suggested class (never applied silently, Nov 5)."""
    from . import refrigerant_rules
    store.setdefault("clocks", [])
    for u in store.get("units", []):
        if "ref_class" not in u:
            cls, gwp, why = refrigerant_rules.suggest(u.get("refrigerant"))
            u.update(ref_class="unknown", gwp_over_53=None,
                     residential_ac=False, needs_review=True,
                     suggested={"ref_class": cls, "gwp_over_53": gwp,
                                "why": why},
                     location=u.get("location", ""))
    return store


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(exc):
    if isinstance(exc, files.FileError):
        raise RefError(str(exc)) from exc
    raise exc


def add_unit(store, records, equipment_id, refrigerant, full_charge,
             category, charge_date="", ref_class=None, gwp_over_53=None,
             residential_ac=False, location=""):
    """ref_class None (or "unknown"): the unit is logged "needs review"
    with a suggested class, like a unit from before 1.2."""
    from ..estimating import service
    eq = service.find(records, equipment_id) if records is not None else None
    if not eq or "kind" not in eq:
        raise RefError("That unit isn't in the service records.")
    if category not in THRESHOLDS:
        raise RefError("Pick industrial process, commercial refrigeration, "
                       "comfort cooling, or other.")
    if not files.txt(refrigerant):
        raise RefError("Name the refrigerant.")
    try:
        charge = files.lbs(full_charge, "Full charge", allow_zero=False)
        charged = files.iso_date(charge_date, "Charge date")
    except files.FileError as e:
        _err(e)
    if any(u["equipment_id"] == equipment_id for u in store["units"]):
        raise RefError("That unit already has a refrigerant record.")
    row = {"id": files.new_id(), "equipment_id": equipment_id,
           "property_id": eq.get("property") or "",
           "unit": " ".join(p for p in (eq.get("kind"), eq.get("make"),
                                        eq.get("model"), eq.get("serial"))
                            if p),
           "refrigerant": files.txt(refrigerant, 80),
           "full_charge": charge, "category": category,
           "charge_date": charged, "location": files.txt(location, 120)}
    from . import refrigerant_rules
    if ref_class in (None, "", "unknown"):
        cls, gwp, why = refrigerant_rules.suggest(row["refrigerant"])
        row.update(ref_class="unknown", gwp_over_53=None,
                   residential_ac=bool(residential_ac), needs_review=True,
                   suggested={"ref_class": cls, "gwp_over_53": gwp,
                              "why": why})
    else:
        if ref_class not in refrigerant_rules.CLASSES:
            raise RefError("Pick ozone-depleting, HFC, other, or not known.")
        row.update(ref_class=ref_class,
                   gwp_over_53=None if gwp_over_53 is None
                   else bool(gwp_over_53),
                   residential_ac=bool(residential_ac), needs_review=False,
                   confirmed={"by": _who(), "at": _now()})
    store.setdefault("clocks", [])
    store["units"].append(row)
    _log(store, "add unit", row["id"], None, dict(row))
    return row["id"]


def _unit(store, uid):
    for u in store["units"]:
        if u["id"] == uid:
            return u
    raise RefError("That unit isn't in the refrigerant log.")


def confirm_class(store, unit_id, ref_class, gwp_over_53=None,
                  residential_ac=None, why=""):
    """A person confirms (or changes) a unit's refrigerant class. Logged.
    Entries already logged keep the rule they were logged under."""
    from . import refrigerant_rules
    if ref_class not in refrigerant_rules.CLASSES or ref_class == "unknown":
        raise RefError("Pick ozone-depleting, HFC, or other.")
    u = _unit(store, unit_id)
    before = {k: u.get(k) for k in ("ref_class", "gwp_over_53",
                                    "residential_ac", "needs_review")}
    u["ref_class"] = ref_class
    if ref_class == "hfc":
        if gwp_over_53 is None:
            raise RefError("Say whether this HFC's GWP is above 53.")
        u["gwp_over_53"] = bool(gwp_over_53)
    else:
        u["gwp_over_53"] = None if gwp_over_53 is None else bool(gwp_over_53)
    if residential_ac is not None:
        u["residential_ac"] = bool(residential_ac)
    u["needs_review"] = False
    u["confirmed"] = {"by": _who(), "at": _now()}
    earlier = sum(1 for v in store["visits"] if v["unit_id"] == unit_id)
    if earlier and before["ref_class"] not in (None, "unknown") and \
            before["ref_class"] != ref_class:
        u["reclassified_note"] = (
            f"Class changed after {earlier} entr{'y' if earlier == 1 else 'ies'}"
            " - those keep the rule they were logged under.")
    after = {k: u.get(k) for k in before}
    _log(store, "confirm class", unit_id, before, after,
         files.txt(why, 300))
    return applicability(store, unit_id)


def applicability(store, unit_id):
    from . import refrigerant_rules
    return refrigerant_rules.applies(_unit(store, unit_id))


def add_visit(store, unit_id, when, lbs_added="0", lbs_recovered="0",
              cylinder="", cert_no="", tech="", notes="", tech_type="",
              parts="", work_done="", lbs_purged="0"):
    unit = _unit(store, unit_id)
    try:
        added = files.lbs(lbs_added, "Pounds added")
        recovered = files.lbs(lbs_recovered, "Pounds recovered")
        purged = files.lbs(lbs_purged or "0", "Pounds purged")
        when_s = files.iso_date(when, "Visit date", blank_ok=False)
    except files.FileError as e:
        _err(e)
    if dmoney.D(added) == 0 and dmoney.D(recovered) == 0:
        raise RefError("Enter pounds added or pounds recovered.")
    if dmoney.D(added) > 0 or dmoney.D(recovered) > 0:
        if not files.txt(cylinder):
            raise RefError("Enter the cylinder number.")
        if not files.txt(cert_no):
            raise RefError("Enter the technician's 608 certificate number.")
    if tech_type and tech_type not in TECH_TYPES:
        raise RefError("Pick the tech's 608 type (I, II, III or Universal).")
    rule = applicability(store, unit_id)
    row = {"id": files.new_id(), "unit_id": unit_id, "date": when_s,
           "lbs_added": added, "lbs_recovered": recovered,
           "lbs_purged": purged,
           "cylinder": files.txt(cylinder, 40),
           "cert_no": files.txt(cert_no, 40),
           "tech": files.txt(tech), "tech_type": tech_type or "",
           "parts": files.txt(parts, 300),
           "work_done": files.txt(work_done, 500),
           "notes": files.txt(notes, 500),
           # the rule in force when this entry was made (Nov 5)
           "rule": rule["rule"] or "",
           "ref_class": unit.get("ref_class", "unknown")}
    store["visits"].append(row)
    _log(store, "add visit", row["id"], None, dict(row))
    if dmoney.D(added) > 0:
        _clock_after_addition(store, unit, row)
    return row["id"]


# ---- repair clocks (84.106(f)/(g), 82.157(d)/(e)) -----------------------

def _add_days(iso, days):
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=int(days))
            ).isoformat()


def open_clock(store, unit_id):
    for c in store.setdefault("clocks", []):
        if c["unit_id"] == unit_id and c["status"] == "open":
            return c
    return None


def _clock_after_addition(store, unit, visit):
    """Refrigerant added to a covered unit over its limit starts the
    repair clock; another addition while it is open is logged against the
    same clock and does not restart it."""
    from . import refrigerant_rules
    c = open_clock(store, unit["id"])
    if c is not None:
        c["additions"].append(visit["id"])
        _log(store, "addition on open clock", c["id"], None,
             {"visit": visit["id"]})
        return c
    info = leak_rate(store, unit["id"])
    if not (info["over"] and info["rule"]):
        return None
    rules = refrigerant_rules.load()
    c = {"id": files.new_id(), "unit_id": unit["id"], "rule": info["rule"],
         "opened": visit["date"], "rate": str(info["rate"]),
         "repair_by": _add_days(visit["date"], rules["repair_days"]),
         "shutdown": False, "additions": [visit["id"]],
         "repaired_on": "", "initial_test": None, "followup_due": "",
         "followup_test": None, "extension": None, "retrofit_plan": None,
         "status": "open"}
    store["clocks"].append(c)
    _log(store, "open repair clock", c["id"], None, dict(c))
    return c


def _clock(store, clock_id):
    for c in store.get("clocks", []):
        if c["id"] == clock_id:
            return c
    raise RefError("That repair clock isn't in the log.")


def set_shutdown(store, clock_id, shutdown=True):
    """Industrial process refrigeration that must shut down to repair:
    the repair window is the longer one (120 days by default)."""
    from . import refrigerant_rules
    rules = refrigerant_rules.load()
    c = _clock(store, clock_id)
    unit = _unit(store, c["unit_id"])
    if shutdown and unit["category"] != "industrial_process":
        raise RefError("The longer window is for industrial process "
                       "refrigeration only.")
    before = c["repair_by"]
    days = rules["repair_days_industrial_shutdown"] if shutdown else \
        rules["repair_days"]
    c["shutdown"] = bool(shutdown)
    c["repair_by"] = _add_days(c["opened"], days)
    _log(store, "repair window", clock_id, {"repair_by": before},
         {"repair_by": c["repair_by"]})
    return c


def record_repair(store, clock_id, repaired_on, initial_test_on, passed=True,
                  notes=""):
    """The repair and its initial verification test. A passed test sets
    the follow-up test due date (10 days by default)."""
    from . import refrigerant_rules
    rules = refrigerant_rules.load()
    c = _clock(store, clock_id)
    try:
        rep = files.iso_date(repaired_on, "Repair date", blank_ok=False)
        tst = files.iso_date(initial_test_on, "Initial test date",
                             blank_ok=False)
    except files.FileError as e:
        _err(e)
    c["repaired_on"] = rep
    c["initial_test"] = {"date": tst, "passed": bool(passed),
                         "notes": files.txt(notes, 300)}
    c["followup_due"] = _add_days(tst, rules["followup_test_days"]) \
        if passed else ""
    _log(store, "repair", clock_id, None, {"repaired_on": rep,
                                           "initial_test": c["initial_test"]})
    return c


def record_followup(store, clock_id, when, passed=True, notes=""):
    c = _clock(store, clock_id)
    try:
        d = files.iso_date(when, "Follow-up test date", blank_ok=False)
    except files.FileError as e:
        _err(e)
    c["followup_test"] = {"date": d, "passed": bool(passed),
                          "notes": files.txt(notes, 300)}
    if passed and c.get("initial_test", {}) and c["initial_test"]["passed"]:
        c["status"] = "repaired"
    _log(store, "follow-up test", clock_id, None, c["followup_test"])
    return c


def request_extension(store, clock_id, until, why):
    """An extension (parts not available, and so on). Reportable under
    84.106(m): the owner files it - QuantiSheet only records it."""
    c = _clock(store, clock_id)
    if not files.txt(why):
        raise RefError("Say why more time is needed.")
    try:
        u = files.iso_date(until, "Extended to", blank_ok=False)
    except files.FileError as e:
        _err(e)
    c["extension"] = {"until": u, "why": files.txt(why, 300), "at": _now()}
    _log(store, "extension", clock_id, None, c["extension"])
    return c


def retrofit_plan(store, clock_id, plan, retire=False):
    """Repair failed: a retrofit or retire plan (reportable)."""
    c = _clock(store, clock_id)
    if not files.txt(plan):
        raise RefError("Describe the retrofit or retirement plan.")
    c["retrofit_plan"] = {"plan": files.txt(plan, 500), "retire": bool(retire),
                          "at": _now()}
    c["status"] = "retire" if retire else "retrofit"
    _log(store, "retrofit plan", clock_id, None, c["retrofit_plan"])
    return c


def _additions(store, unit_id):
    rows = [v for v in store["visits"]
            if v["unit_id"] == unit_id and dmoney.D(v["lbs_added"]) > 0]
    rows.sort(key=lambda v: v["date"])
    return rows


def _limits():
    from . import refrigerant_rules
    return {k: dmoney.D(v) for k, v in
            refrigerant_rules.load()["limits"].items()}


def leak_rate(store, unit_id):
    """The annualizing-method leak rate for the latest addition.

    Returns rate (percent per year, 2 decimals), the pounds added, the
    days used, the category threshold, whether the rate is over it, and
    which rule applies ("rule", with "regulatory" True when one does).
    See the module docstring.
    """
    unit = _unit(store, unit_id)
    charge = dmoney.D(unit["full_charge"])
    threshold = _limits().get(unit["category"], THRESHOLDS["other"])
    app = applicability(store, unit_id)
    base = {"full_charge": charge, "threshold": threshold,
            "regulatory": app["rule"] is not None, "rule": app["rule"],
            "why": app["why"], "needs_review": app["needs_review"],
            "category": unit["category"]}
    additions = _additions(store, unit_id)
    if not additions or charge <= 0:
        return dict(base, rate=Decimal("0.00"), added=Decimal("0"), days=0,
                    over=False)
    latest = additions[-1]
    if len(additions) >= 2:
        ref = dt.date.fromisoformat(additions[-2]["date"])
    elif unit.get("charge_date"):
        ref = dt.date.fromisoformat(unit["charge_date"])
    else:
        ref = None
    if ref is None:
        days = 365
    else:
        days = (dt.date.fromisoformat(latest["date"]) - ref).days
        if days < 1:
            days = 1
    window = min(days, 365)
    added = dmoney.D(latest["lbs_added"])
    # 40 CFR 82.152 annualizing method. See the module docstring.
    rate = (added / charge) * (Decimal(365) / Decimal(window)) * Decimal(100)
    rate = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return dict(base, rate=rate, added=added, days=window,
                over=rate > threshold, as_of=latest["date"])


def _pct(d):
    if d == d.to_integral():
        return str(int(d))
    return f"{_c2(d):.2f}"


def flag_text(info):
    """A short sentence when the unit is over its limit or needs review,
    else ''."""
    if not info.get("over"):
        return "Needs review: confirm the refrigerant class." \
            if info.get("needs_review") else ""
    label = CATEGORY_LABELS.get(info["category"], "this equipment")
    text = (f"Leak rate {_pct(info['rate'])}% per year. Over the "
            f"{_pct(info['threshold'])}% leak-rate limit for {label}.")
    if info.get("rule"):
        text += f" {info['why']} Repair clock running."
    else:
        text += f" {info.get('why', '')}".rstrip()
    return text


def flagged(store):
    out = []
    for unit in store["units"]:
        info = leak_rate(store, unit["id"])
        if info["over"]:
            out.append(dict(info, unit_id=unit["id"], unit=unit["unit"],
                            text=flag_text(info)))
    return out


def chronic_leakers(store, year):
    """Covered units that lost 125% (default) or more of their full charge
    in a calendar year - the owner reports them by March 1 next year."""
    from . import refrigerant_rules
    rules = refrigerant_rules.load()
    pct = dmoney.D(rules["chronic_leak_pct"])
    out = []
    for u in store["units"]:
        if applicability(store, u["id"])["rule"] != "84.106":
            continue
        charge = dmoney.D(u["full_charge"])
        if charge <= 0:
            continue
        added = sum((dmoney.D(v["lbs_added"]) for v in store["visits"]
                     if v["unit_id"] == u["id"] and
                     v["date"].startswith(str(year))), Decimal(0))
        share = (added / charge * 100).quantize(Decimal("0.1"))
        if share >= pct:
            out.append({"unit_id": u["id"], "unit": u["unit"],
                        "added": added, "pct": share,
                        "report_by": f"{int(year) + 1}-"
                                     f"{rules['chronic_report_by']}"})
    return out


def auto_leak_detection_note(store, unit_id):
    """84.108: refrigeration (commercial or industrial) at 1,500 lb or
    more - automatic leak detection is expected. A note, not a check."""
    from . import refrigerant_rules
    u = _unit(store, unit_id)
    lim = dmoney.D(refrigerant_rules.load()["auto_leak_detection_lbs"])
    if u["category"] in ("commercial_refrigeration", "industrial_process") \
            and dmoney.D(u["full_charge"]) >= lim and \
            applicability(store, unit_id)["rule"] == "84.106":
        return (f"Full charge {u['full_charge']} lb: 40 CFR 84.108 "
                "automatic leak detection applies to refrigeration this "
                "size - check it is installed.")
    return ""


def reportable(store, year):
    """84.106(m) cases for the owner to file: extensions, retrofit /
    retire plans, chronic leakers, purged refrigerant."""
    out = []
    for c in store.get("clocks", []):
        if not c["opened"].startswith(str(year)):
            continue
        u = _unit(store, c["unit_id"])
        if c.get("extension"):
            out.append(("extension", u["unit"],
                        f"Repair extended to {c['extension']['until']}: "
                        f"{c['extension']['why']}"))
        if c.get("retrofit_plan"):
            kind = "retire" if c["retrofit_plan"]["retire"] else "retrofit"
            out.append((kind, u["unit"], c["retrofit_plan"]["plan"]))
    for ch in chronic_leakers(store, year):
        out.append(("chronic leaker", ch["unit"],
                    f"{ch['pct']}% of full charge added in {year}; report "
                    f"by {ch['report_by']}"))
    for v in store["visits"]:
        if v["date"].startswith(str(year)) and \
                dmoney.D(v.get("lbs_purged") or 0) > 0 and \
                v.get("rule") == "84.106":
            u = _unit(store, v["unit_id"])
            out.append(("purged", u["unit"],
                        f"{v['lbs_purged']} lb purged on {v['date']}"))
    return out


def due(store, today=None):
    """What needs doing: units to review, repairs and follow-up tests due
    or late. [(date, unit, what, late)]"""
    today = (today or dt.date.today())
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    t = today.isoformat()
    out = []
    for u in store["units"]:
        if u.get("needs_review"):
            out.append(("", u["unit"], "Confirm the refrigerant class "
                        f"(suggested: {u.get('suggested', {}).get('why', '')})",
                        False))
    for c in store.get("clocks", []):
        if c["status"] != "open":
            continue
        u = _unit(store, c["unit_id"])
        by = (c.get("extension") or {}).get("until") or c["repair_by"]
        if not c["repaired_on"]:
            out.append((by, u["unit"], f"Repair leak ({c['rule']}) by {by}",
                        by < t))
        elif c.get("initial_test") and not c["initial_test"]["passed"]:
            out.append((by, u["unit"], "Initial verification test failed - "
                        "repair again or make a retrofit / retire plan",
                        by < t))
        elif c["followup_due"] and not c.get("followup_test"):
            out.append((c["followup_due"], u["unit"],
                        f"Follow-up verification test by {c['followup_due']}",
                        c["followup_due"] < t))
    out.sort(key=lambda r: (r[0] == "", r[0]))
    return out


def year_report_pdf(store, year, path, comp=None):
    """The 84.106(m) cases of one year for the owner to file - extensions,
    retrofit / retire plans, chronic leakers, purged refrigerant. A list
    to act on, not a filing."""
    from .pdfdoc import Sheet, fit
    sheet = Sheet("Refrigerant year-end list", comp, subtitle=str(year))
    sheet.section("01", "Cases the owner may need to report")
    rows = reportable(store, year)
    if not rows:
        sheet.y += 14
        sheet.text(36, sheet.y, f"Nothing found for {year}.", 9)
    for kind, unit, text in rows:
        sheet.need(14)
        sheet.y += 14
        sheet.text(36, sheet.y, kind.capitalize(), 9, True)
        sheet.text(140, sheet.y, fit(f"{unit}: {text}", 420, 9), 9)
    sheet.y += 24
    sheet.text(36, sheet.y, fit("40 CFR 84.106(m). QuantiSheet lists "
                                "possible cases; the owner and the licensed "
                                "tech decide what is filed. Not legal "
                                "advice.", 540, 8), 8)
    return sheet.save(path)


def owner_record_pdf(store, records, visit_id, path, comp=None):
    """One page per visit for the owner (84.106(l)(2)(i)-(vi); given to
    the owner under 84.106(l)(4)): unit and location, date, parts, work
    done, technician, refrigerant added and removed."""
    from ..estimating import service
    from .pdfdoc import Sheet
    v = next((x for x in store["visits"] if x["id"] == visit_id), None)
    if v is None:
        raise RefError("That visit isn't in the log.")
    u = _unit(store, v["unit_id"])
    prop = service.find(records, u["property_id"]) if records else None
    sheet = Sheet("Refrigerant service record", comp,
                  subtitle=(prop or {}).get("name") or "")
    rows = [("Unit", u["unit"] or "Unit"),
            ("Location", u.get("location") or ""),
            ("Site", " ".join(p for p in ((prop or {}).get("customer"),
                                          (prop or {}).get("address")) if p)),
            ("Refrigerant", f"{u['refrigerant']}, full charge "
                            f"{u['full_charge']} lb"),
            ("Date of service", v["date"]),
            ("Parts", v.get("parts") or "None"),
            ("Work done", v.get("work_done") or v.get("notes") or ""),
            ("Technician", " ".join(p for p in (
                v.get("tech"), v.get("tech_type"),
                f"608 cert {v['cert_no']}" if v.get("cert_no") else "")
                if p)),
            ("Refrigerant added", f"{v['lbs_added']} lb"),
            ("Refrigerant removed", f"{v['lbs_recovered']} lb (cylinder "
                                    f"{v['cylinder']})"),
            ("Rule", (applicability(store, u["id"])["why"]))]
    sheet.section("01", "Service record")
    from .pdfdoc import fit
    for label, val in rows:
        sheet.need(14)
        sheet.y += 14
        sheet.text(36, sheet.y, label, 9, True)
        sheet.text(160, sheet.y, fit(val, 400, 9), 9)
    sheet.y += 24
    from . import refrigerant_rules
    yrs = refrigerant_rules.load()["records_years"]
    sheet.text(36, sheet.y, fit("Keep this record. The owner keeps "
                                f"refrigerant records at least {yrs} years.",
                                540, 8), 8)
    return sheet.save(path)


def site_log_pdf(store, records, property_id, path, comp=None):
    """A printable refrigerant log for one site."""
    from ..estimating import service
    from .pdfdoc import Sheet
    prop = service.find(records, property_id) if records is not None else None
    if not prop or "customer" not in prop:
        raise RefError("That site isn't in the service records.")
    units = [u for u in store["units"] if u["property_id"] == property_id]
    sheet = Sheet("Refrigerant log", comp, subtitle=prop.get("name") or "")
    sheet.section("01", prop.get("name") or "Site")
    sheet.y += 12
    sheet.text(36, sheet.y, prop.get("customer") or "", 10, True)
    sheet.y += 12
    sheet.text(36, sheet.y, prop.get("address") or "", 8)
    if not units:
        sheet.y += 20
        sheet.text(36, sheet.y, "No refrigerant records at this site.", 9)
        return sheet.save(path)
    for unit in units:
        info = leak_rate(store, unit["id"])
        sheet.section("Unit", unit["unit"] or "Unit")
        sheet.y += 12
        sheet.text(36, sheet.y,
                   f"{unit['refrigerant']}    full charge "
                   f"{unit['full_charge']} lb    "
                   f"{CATEGORY_LABELS[unit['category']]}", 9)
        sheet.y += 12
        rate = (f"Leak rate {info['rate']}% per year"
                if info["days"] else "No refrigerant added yet")
        mark = flag_text(info)
        sheet.text(36, sheet.y, rate + ("    " + mark if mark else ""), 9, True)
        sheet.y += 12
        from .pdfdoc import fit
        sheet.text(36, sheet.y, fit(info["why"], 540, 8), 8)
        visits = [v for v in store["visits"] if v["unit_id"] == unit["id"]]
        visits.sort(key=lambda v: v["date"])
        for v in visits:
            sheet.need(14)
            sheet.y += 12
            sheet.text(36, sheet.y,
                       f"{v['date']}  added {v['lbs_added']} lb  "
                       f"recovered {v['lbs_recovered']} lb  "
                       f"cylinder {v['cylinder']}  cert {v['cert_no']}  "
                       f"{v['tech']}", 8)
    return sheet.save(path)
