"""Tags vs schedule (Nov 4, takeoff list #14): every door (window,
fixture, equipment) tag on the plans against the schedule that lists
them - which tags are drawn but not scheduled, scheduled but never drawn,
and how many times each one is drawn.

Tags are found with Count by Label's search (label_search.search): a
pattern with wildcards ("D-#", "1##", "W*"), each hit marked as on the
plan or in a schedule / legend / notes / title block. Nothing is changed
in the drawing; the report can be copied to Excel, saved as CSV, or each
gap turned into an RFI.
"""
import csv
import re

from . import label_search


def _nat(s):
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r"(\d+)", s)]


def check(doc, pattern, pages=None, use_ocr=True):
    """{"plan_only": [tag], "schedule_only": [tag], "both": [tag],
    "drawn": {tag: times on the plans}, "where": {tag: [page numbers]},
    "pattern": pattern}."""
    hits = label_search.search(doc, pattern, pages=pages, use_ocr=use_ocr)
    drawn, listed, where = {}, set(), {}
    for h in hits:
        t = h["text"].strip()
        if not t:
            continue
        if h["in_plan"]:
            drawn[t] = drawn.get(t, 0) + 1
            where.setdefault(t, set()).add(h["page"] + 1)
        else:
            listed.add(t)
    plan = set(drawn)
    return {"pattern": pattern,
            "plan_only": sorted(plan - listed, key=_nat),
            "schedule_only": sorted(listed - plan, key=_nat),
            "both": sorted(plan & listed, key=_nat),
            "drawn": drawn,
            "where": {k: sorted(v) for k, v in where.items()}}


def rows(rep):
    """[(tag, status, times drawn, sheets)] for a table or CSV."""
    out = []
    for t in rep["schedule_only"]:
        out.append((t, "In the schedule, not on the plans", 0, ""))
    for t in rep["plan_only"]:
        out.append((t, "On the plans, not in the schedule", rep["drawn"][t],
                    ", ".join(str(p) for p in rep["where"].get(t, []))))
    for t in rep["both"]:
        out.append((t, "OK", rep["drawn"][t],
                    ", ".join(str(p) for p in rep["where"].get(t, []))))
    return out


def export_csv(rep, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Tag", "Check", "Times drawn", "Sheets (page numbers)"])
        w.writerows(rows(rep))
    return path


def rfi_text(rep):
    """One RFI's question listing the gaps, or '' when there are none."""
    parts = []
    if rep["schedule_only"]:
        parts.append("Scheduled but not shown on the plans: " +
                     ", ".join(rep["schedule_only"]) + ".")
    if rep["plan_only"]:
        parts.append("Shown on the plans but not in the schedule: " +
                     ", ".join(rep["plan_only"]) + ".")
    if not parts:
        return ""
    return (f"Tag check ({rep['pattern']}): " + " ".join(parts) +
            " Please confirm which is correct.")
