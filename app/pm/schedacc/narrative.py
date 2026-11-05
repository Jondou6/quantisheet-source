"""Basis-of-schedule narrative, written from the schedule data.

Every sentence comes from a field on the draft: dates, calendars, the
critical path, float, long-lead release dates, exclusions, and the
completeness and health results. Nothing is filled in by a model.
"""


def render(doc):
    p = doc.get("project") or {}
    lines = []
    state = "finished" if doc.get("status") == "finished" else "not finished"
    lines.append(
        f"Basis of schedule for {p.get('name') or 'the project'}. "
        f"Completeness result: {state} "
        f"({(doc.get('rubric') or {}).get('score', 0)}).")
    lines.append(
        f"Project type: {p.get('type_label') or p.get('type') or 'unspecified'}. "
        f"Data date {p.get('data_date') or 'not set'}. "
        f"Planned start {p.get('start') or 'not set'}. "
        f"Early finish {p.get('early_finish') or 'not set'}.")
    if p.get("must_finish"):
        lines.append(f"Contract finish date used for float: {p['must_finish']}.")
    lines.append(_calendars(doc))
    lines.append(_durations(doc))
    lines.append(_long_lead(doc))
    lines.append(_critical(doc))
    lines.append(_exclusions(doc))
    lines.append(_risks(doc))
    lines.append(_health(doc))
    opt = doc.get("options") or {}
    lines.append(
        "Schedule options: out-of-sequence handling "
        f"{opt.get('out_of_sequence')}, total float uses "
        f"{opt.get('total_float')}, lag calendar is the "
        f"{opt.get('lag_calendar')} calendar, critical activities are "
        f"those with total float at or under "
        f"{p.get('critical_hours', 0)} hours"
        + (" or on the longest path." if opt.get("critical") == "longest"
           else "."))
    text = "\n\n".join(lines)
    doc["narrative"] = text
    return text


def _calendars(doc):
    bits = []
    for spec in (doc.get("calendars") or {}).values():
        days = spec.get("weekdays") or []
        hol = spec.get("holidays") or []
        months = spec.get("months_off") or []
        desc = (f"{spec.get('name')} ({spec.get('hours_per_day')} hours a "
                f"workday, {len(days)} days a week, {len(hol)} holidays")
        if months:
            desc += ", no work in months " + ", ".join(str(m) for m in months)
        desc += ")"
        bits.append(desc)
    return "Calendars: " + "; ".join(bits) + "." if bits else "No calendars."


def _durations(doc):
    comp = est = 0
    for a in doc.get("activities") or ():
        if a.get("type") in ("start_ms", "finish_ms", "loe", "wbs_summary"):
            continue
        if a.get("duration_kind") == "computed":
            comp += 1
        else:
            est += 1
    return (f"Durations: {comp} computed from a quantity, a production rate "
            f"or a figure stated in the spec; {est} estimated from the "
            f"company template. The model did not author a duration.")


def _long_lead(doc):
    rows = []
    for fact in doc.get("facts") or []:
        if fact.get("kind") != "long_lead":
            continue
        when = fact.get("release_date") or "not scheduled"
        val = fact.get("value")
        rows.append(f"{fact.get('item')} (lead {val} {fact.get('unit') or 'days'}, "
                    f"release {when}, {fact.get('basis') or 'unspecified'})")
    if not rows:
        return "No long-lead items were found in the spec."
    return "Long-lead items: " + "; ".join(rows) + "."


def _critical(doc):
    path = [a for a in doc.get("activities") or () if a.get("longest_path")]
    path.sort(key=lambda a: (a.get("es") or "", a.get("float_path_order") or 0))
    names = [a.get("name") or a.get("code") for a in path]
    near = [a.get("name") for a in doc.get("activities") or ()
            if a.get("near_critical")]
    text = "Longest path: " + (" -> ".join(names) if names else "none") + "."
    if near:
        text += " Near-critical: " + "; ".join(near[:12]) + "."
    return text


def _exclusions(doc):
    rows = [a.get("name") for a in doc.get("activities") or () if a.get("by_others")]
    if not rows:
        return "No scope was marked by others or not in contract."
    return "Exclusions: " + "; ".join(rows) + "."


def _risks(doc):
    gaps = (doc.get("rubric") or {}).get("gaps") or []
    conflicts = [f for f in doc.get("facts") or [] if f.get("conflict")]
    bits = []
    if gaps:
        bits.append("Completeness gaps: " + "; ".join(gaps[:8]))
    if conflicts:
        bits.append("Conflicts (not resolved): " + "; ".join(
            f"{f.get('item')}" for f in conflicts[:6]))
    blanks = (doc.get("ingest") or {}).get("blank_pages") or []
    if blanks:
        bits.append(
            f"{len(blanks)} page(s) had no extractable text"
            + (" and were not recovered." if any(
                b.get("ocr") != "used" for b in blanks) else "."))
    if not bits:
        return "No open completeness gaps."
    return "Risks: " + " ".join(bits)


def _health(doc):
    h = doc.get("health") or {}
    if not h:
        return "Schedule health was not run."
    failed = [i["name"] for i in h.get("items") or [] if i.get("passed") is False]
    text = (f"Schedule health {h.get('score')} "
            f"({h.get('passed')} of {h.get('graded')} graded points passed).")
    if failed:
        text += " Look at: " + ", ".join(failed) + "."
    return text
