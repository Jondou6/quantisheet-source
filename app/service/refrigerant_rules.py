"""Which refrigerant rule applies to a unit, and the numbers each rule
uses (QuantiSheet 1.2, Nov 5). Jon approved the rule change on Nov 5,
2026; a licensed tech reviews the numbers. QuantiSheet flags possible
issues - it does not decide compliance.

Since Jan 1, 2026:
- 40 CFR 84.106 (AIM Act, Emissions Reduction and Reclamation) covers
  HFCs and other substitutes with a GWP above 53 at a full charge of
  15 lb or more. Residential and light-commercial air conditioning and
  heat pumps are exempt.
- 40 CFR 82.157 (Section 608) covers ozone-depleting refrigerants (R-22
  and the like) at 50 lb or more - the 1.1.1 rule, now for those only.
Leak-rate limits, repair days, verification tests, chronic leakers and
the rest are below. Every number is editable: the defaults here are
copied into service_refrigerant_rules.json in the data folder the first
time they are changed, and that file wins from then on.

Units logged before 1.2 have no refrigerant class: they are marked
"needs review" with a suggested class, and nothing is rated under a rule
until a person confirms the class (Jon, Nov 5).
"""
import copy
import json
import os
from decimal import Decimal

from . import files

FILE = "service_refrigerant_rules.json"
DECISION = "Refrigerant rule change approved by Jon on Nov 5, 2026."

CLASSES = {"ods": "Ozone-depleting (R-22 and the like)",
           "hfc": "HFC or other substitute",
           "other": "Other / natural (not covered)",
           "unknown": "Not known - needs review"}

DEFAULTS = {
    "reviewed": False, "reviewer": "", "review_date": "",
    "decision": DECISION,
    "rules": {
        "84.106": {
            "label": "40 CFR 84.106 (AIM Act leak repair)",
            "classes": ["hfc"], "gwp_over": 53, "min_lbs": "15",
            "residential_exempt": True,
        },
        "82.157": {
            "label": "40 CFR 82.157 (Section 608 leak repair)",
            "classes": ["ods"], "gwp_over": None, "min_lbs": "50",
            "residential_exempt": False,
        },
    },
    # percent of full charge a year (both rules use the same limits)
    "limits": {"industrial_process": "30", "commercial_refrigeration": "20",
               "comfort_cooling": "10", "other": "10"},
    "repair_days": 30,
    "repair_days_industrial_shutdown": 120,
    "followup_test_days": 10,
    "chronic_leak_pct": "125",           # of full charge in a calendar year
    "chronic_report_by": "03-01",        # month-day of the next year
    "auto_leak_detection_lbs": "1500",   # 84.108, refrigeration only
    "records_years": 3,
    "disposal_min_lbs": "5",             # 82.156(a)(3): 5 to 50 lb
    "disposal_max_lbs": "50",
    "disposable_cylinder_from": "2028-01-01",   # 84.116
    "disposable_cylinder_vacuum_inhg": "15",
}

# Suggestions only: a person confirms each one with a click (Nov 5).
# The GWP numbers themselves are the tech's to check against Table 1 of
# 40 CFR 84.64(b) - this list only sorts common names into a class.
_ODS = {"R-11", "R-12", "R-13", "R-22", "R-113", "R-114", "R-115",
        "R-123", "R-124", "R-141B", "R-142B", "R-401A", "R-401B", "R-402A",
        "R-402B", "R-403B", "R-408A", "R-409A", "R-411B", "R-414B",
        "R-500", "R-502", "R-503"}
_HFC_OVER_53 = {"R-32", "R-125", "R-134A", "R-143A", "R-152A", "R-227EA",
                "R-404A", "R-407A", "R-407C", "R-407F", "R-410A", "R-417A",
                "R-421A", "R-422A", "R-422B", "R-422D", "R-427A", "R-437A",
                "R-438A", "R-448A", "R-449A", "R-452A", "R-452B", "R-454B",
                "R-454C", "R-507A", "R-513A"}
_OTHER = {"R-290", "R-600A", "R-717", "R-744", "R-1234YF", "R-1234ZE",
          "R-1233ZD", "R-718"}


def _norm(name):
    t = str(name or "").upper().replace(" ", "").replace("_", "-")
    if t.startswith("R") and not t.startswith("R-"):
        t = "R-" + t[1:]
    return t


def suggest(refrigerant):
    """(class, gwp_over_53 or None, why) - a suggestion to confirm."""
    n = _norm(refrigerant)
    if n in _ODS:
        return "ods", None, f"{n} is an ozone-depleting refrigerant"
    if n in _HFC_OVER_53:
        return "hfc", True, f"{n} is an HFC (GWP above 53)"
    if n in _OTHER:
        return "other", False, f"{n} is a low-GWP / natural refrigerant"
    return "unknown", None, (f"{refrigerant or 'This refrigerant'} isn't in "
                             "the list - check it (blends and new names "
                             "need the tech)")


def path():
    return files.path_for(FILE)


def load():
    """The rules in force: the saved file over the defaults."""
    out = copy.deepcopy(DEFAULTS)
    p = path()
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                for k2, v2 in v.items():
                    if isinstance(v2, dict) and isinstance(out[k].get(k2),
                                                           dict):
                        out[k][k2].update(v2)
                    else:
                        out[k][k2] = v2
            else:
                out[k] = v
    return out


def save(rules):
    files.write(path(), rules)
    return path()


def D(v):
    return Decimal(str(v))


def applies(unit, rules=None):
    """{"rule": "84.106" | "82.157" | None, "label", "why",
    "needs_review"} for one unit."""
    rules = rules or load()
    cls = unit.get("ref_class") or "unknown"
    charge = D(unit.get("full_charge") or 0)
    if cls == "unknown" or unit.get("needs_review"):
        return {"rule": None, "label": "", "needs_review": True,
                "why": "Refrigerant class not confirmed - needs review "
                       "before any rule is applied."}
    for key, r in rules["rules"].items():
        if cls not in r["classes"]:
            continue
        if r.get("gwp_over") is not None:
            gwp = unit.get("gwp_over_53")
            if gwp is None:
                return {"rule": None, "label": r["label"],
                        "needs_review": True,
                        "why": f"GWP not confirmed - needs review "
                               f"({r['label']} covers GWP above "
                               f"{r['gwp_over']})."}
            if not gwp:
                return {"rule": None, "label": r["label"],
                        "needs_review": False,
                        "why": f"GWP {r['gwp_over']} or less - not covered "
                               f"by {r['label']}."}
        if r.get("residential_exempt") and unit.get("residential_ac"):
            return {"rule": None, "label": r["label"], "needs_review": False,
                    "why": "Residential / light-commercial AC or heat pump - "
                           f"exempt from {r['label']} (still logged)."}
        if charge < D(r["min_lbs"]):
            return {"rule": None, "label": r["label"], "needs_review": False,
                    "why": f"Full charge under {r['min_lbs']} lb - "
                           f"{r['label']} applies at {r['min_lbs']} lb and "
                           "up."}
        return {"rule": key, "label": r["label"], "needs_review": False,
                "why": f"{r['label']}, {r['min_lbs']} lb and up."}
    return {"rule": None, "label": "", "needs_review": False,
            "why": "Not covered by a leak-repair rule (still logged)."}


def note(rules=None):
    """The line shown at the top of the log window and on printouts."""
    rules = rules or load()
    head = "" if rules.get("reviewed") else (
        "NOT YET REVIEWED - these thresholds haven't been checked by the "
        "licensed tech. ")
    who = (f"Reviewed by {rules['reviewer']} on {rules['review_date']}. "
           if rules.get("reviewed") and rules.get("reviewer") else "")
    r1, r2 = rules["rules"]["84.106"], rules["rules"]["82.157"]
    lim = rules["limits"]
    return (head + who +
            f"{r1['label']}: HFCs / substitutes with GWP above "
            f"{r1['gwp_over']} at {r1['min_lbs']} lb and up (residential and "
            f"light-commercial AC / heat pumps exempt). {r2['label']}: "
            f"ozone-depleting refrigerants at {r2['min_lbs']} lb and up. "
            f"Leak-rate limits: industrial {lim['industrial_process']}%, "
            f"commercial refrigeration {lim['commercial_refrigeration']}%, "
            f"comfort cooling and others {lim['comfort_cooling']}% a year. "
            f"Repair within {rules['repair_days']} days of adding "
            "refrigerant to a unit over its limit. QuantiSheet flags "
            "possible issues; it does not decide compliance. Not legal "
            "advice.")
