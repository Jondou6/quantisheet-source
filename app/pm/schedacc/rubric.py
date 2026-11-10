"""Completeness gate. A draft that fails is not finished.

The checks are the ones a scheduler would refuse to issue without:
every spec division is in the schedule or marked by others, every long-lead
item has a procurement chain and a release date, every submittal has a
submit / review / return / fabricate path (or an explicit "no fabrication"
marker), every named inspection is a hold point, the contract milestones
are present, general conditions the project type requires are present,
logic is closed, negative float is acknowledged, and every activity has a
calendar. Conflicts are not resolved in silence, so an open conflict fails
the gate too.
"""

_REQUIRED = {
    "ground_up_commercial": (
        "mobilization", "demobilization", "temp_facilities", "temp_utilities",
        "swppp", "closeout", "commissioning", "punch", "substantial", "final",
        "ntp"),
    "tenant_improvement": (
        "mobilization", "demobilization", "temp_facilities", "temp_utilities",
        "closeout", "commissioning", "punch", "substantial", "final", "ntp"),
    "mep_retrofit": (
        "mobilization", "demobilization", "temp_facilities", "closeout",
        "commissioning", "punch", "substantial", "final", "ntp"),
    "plumbing_hvac_service": (
        "mobilization", "demobilization", "closeout", "startup", "turnover",
        "substantial", "final", "ntp"),
}

_CHAIN = ("submittal_submit", "submittal_review", "submittal_return")


def evaluate(doc):
    gaps = []
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})
        if not ok:
            gaps.append(detail)

    divisions = set((doc.get("ingest") or {}).get("divisions") or ())
    acts = doc.get("activities") or []
    rels = doc.get("relationships") or []
    by = {a["code"]: a for a in acts}
    ptype = (doc.get("project") or {}).get("type") or "ground_up_commercial"

    covered = {a.get("division") for a in acts if a.get("division")
               and not a.get("by_others")}
    marked = {a.get("division") for a in acts if a.get("by_others") and a.get("division")}
    # A by-others fact that names no division still counts as a marker when
    # the item text names the division.
    missing = []
    for div in sorted(divisions):
        if div in ("00",):
            continue
        if div not in covered and div not in marked:
            if div == "01" and any(a.get("cls") == "ntp" for a in acts):
                continue
            missing.append(div)
    add("divisions", not missing,
        "Spec divisions with no activity and no by-others marker: "
        + ", ".join(missing) if missing else "Every spec division is covered.")

    chains = {}
    for a in acts:
        cid = a.get("chain_id") or ""
        if cid:
            chains.setdefault(cid, []).append(a)
    lead_gaps = []
    for fact in doc.get("facts") or []:
        if fact.get("kind") != "long_lead":
            continue
        item = (fact.get("item") or "").lower()
        group = None
        for cid, rows in chains.items():
            if cid == "general":
                continue
            if any(item and item in (r.get("item") or "").lower() for r in rows):
                group = rows
                break
        if not group:
            lead_gaps.append(f"{fact.get('item')} has no procurement chain")
            continue
        classes = {r.get("cls") for r in group}
        release = next((r for r in group if r.get("cls") == "release"), None)
        if "fabrication" not in classes and not any(r.get("fabrication_na") for r in group):
            lead_gaps.append(f"{fact.get('item')} has no fabrication activity")
        if release is None or not release.get("es"):
            lead_gaps.append(f"{fact.get('item')} has no release date")
        else:
            fact["release_date"] = release.get("es")
    add("long_lead", not lead_gaps,
        "; ".join(lead_gaps) if lead_gaps else "Long-lead items have a release date.")

    sub_gaps = []
    if not chains:
        sub_gaps.append("no submittal chain")
    for cid, rows in chains.items():
        classes = {r.get("cls") for r in rows}
        if not set(_CHAIN) <= classes:
            sub_gaps.append(f"{cid} is missing a submit, review or return step")
        if "fabrication" not in classes and not any(r.get("fabrication_na") for r in rows):
            sub_gaps.append(f"{cid} has no fabricate step and no marker that fabrication does not apply")
    add("submittals", not sub_gaps,
        "; ".join(sub_gaps) if sub_gaps else "Submittal chains are complete.")

    named = [f for f in doc.get("facts") or [] if f.get("kind") in ("inspection", "test")]
    gate_cls = {"rough_in_inspection", "footing_inspection", "final_inspection",
                "pressure_test", "inspection", "test_gate", "tab"}
    gates = [a for a in acts if a.get("cls") in gate_cls]
    insp_gaps = []
    if named and not gates:
        insp_gaps.append("named inspections or tests have no hold point")
    # Each named item should be reflected by an activity whose name contains
    # a distinctive slice of the fact, or by a hold point of the right class.
    for fact in named:
        token = " ".join((fact.get("item") or "").lower().split())[:40]
        if token and not any(token[:24] in (a.get("name") or "").lower()
                             for a in acts):
            insp_gaps.append(f"no hold point for {fact.get('item')}")
    add("inspections", not insp_gaps,
        "; ".join(insp_gaps[:8]) if insp_gaps else "Inspections and tests are hold points.")

    classes = {a.get("cls") for a in acts}
    need = list(_REQUIRED.get(ptype, _REQUIRED["ground_up_commercial"]))
    if doc.get("scope"):
        # bid-set job: commissioning / temporary utilities only when the
        # scope has the equipment or the temporary service in it
        need = [c for c in need if c not in ("commissioning",
                                             "temp_utilities")]
    blob = " ".join(f.get("item") or "" for f in doc.get("facts") or [])
    if ptype != "ground_up_commercial" and (
            "31" in divisions or "SWPPP" in blob.upper()):
        if "swppp" not in need:
            need.append("swppp")
    absent = [c for c in need if c not in classes]
    add("general_conditions", not absent,
        "Missing required activities: " + ", ".join(absent) if absent
        else "Required general conditions are in the schedule.")

    preds = {}
    succs = {}
    for r in rels:
        preds.setdefault(r["succ"], []).append(r["pred"])
        succs.setdefault(r["pred"], []).append(r["succ"])
    orphans = []
    for a in acts:
        if a.get("type") in ("loe", "wbs_summary"):
            continue
        code = a["code"]
        if a.get("cls") != "ntp" and not preds.get(code):
            orphans.append(f"{code} {a.get('name')} has no predecessor")
        if a.get("cls") != "final" and not succs.get(code):
            orphans.append(f"{code} {a.get('name')} has no successor")
    add("logic", not orphans,
        "; ".join(orphans[:8]) if orphans else "Every activity is tied in.")

    leads = [r for r in rels if float(r.get("lag_hours") or 0) < 0]
    add("leads", not leads,
        f"{len(leads)} relationship(s) have a lead (negative lag)." if leads
        else "No leads.")

    neg = [a for a in acts if (a.get("total_float_days") or 0) < 0
           and a.get("type") not in ("loe", "wbs_summary")]
    acked = bool((doc.get("project") or {}).get("negative_float_ack"))
    if neg and not acked:
        add("negative_float", False,
            "Negative float is not acknowledged: " + ", ".join(
                a.get("code") or "" for a in neg[:8]))
    else:
        add("negative_float", True,
            "Negative float is acknowledged." if neg else "No negative float.")

    calendars = set((doc.get("calendars") or {}))
    bare = [a.get("code") for a in acts if (a.get("calendar") or "") not in calendars]
    add("calendars", not bare,
        "Activities with no calendar: " + ", ".join(bare) if bare
        else "Every activity has a calendar.")

    conflicts = [f for f in doc.get("facts") or [] if f.get("conflict")]
    add("conflicts", not conflicts,
        "Unresolved conflicts: " + "; ".join(
            f"{f.get('kind')} {f.get('item')}" for f in conflicts[:6])
        if conflicts else "No unresolved conflicts.")

    known = {}
    for sec in (doc.get("ingest") or {}).get("sections") or []:
        known[sec.get("number") or ""] = set(sec.get("pages") or [])
    bad_cites = []
    for a in acts:
        for c in a.get("citations") or []:
            if c.get("document"):
                continue                       # a bid document, not the spec
            sec = c.get("spec_section") or ""
            page = c.get("page")
            if not sec and page is None:
                bad_cites.append(a.get("code"))
                continue
            if sec and sec not in known:
                bad_cites.append(f"{a.get('code')} cites {sec}, which is not in the spec")
            elif sec and page is not None and known.get(sec) and page not in known[sec]:
                bad_cites.append(f"{a.get('code')} cites page {page}, not in {sec}")
    add("citations", not bad_cites,
        "; ".join(bad_cites[:6]) if bad_cites else "Citations point at the spec.")

    if doc.get("scope"):
        _bid_checks(doc, acts, add)

    passed = sum(1 for c in checks if c["passed"])
    score = round(100.0 * passed / len(checks), 1) if checks else 0
    result = {"checks": checks, "gaps": gaps, "passed": not gaps,
              "score": score, "passed_checks": passed, "total": len(checks)}
    doc["rubric"] = result
    doc["status"] = "finished" if result["passed"] else "incomplete"
    return result


_FIELD_OK = {"ntp", "substantial", "final", "mobilization",
             "demobilization", "temp_facilities", "punch", "closeout",
             "margin", "training"}


def _bid_checks(doc, acts, add):
    """Two-way scope check, removed scope, holds and workdays (bid set)."""
    import datetime as _dt
    from . import bidset
    scope = doc["scope"]
    keys = {a.get("scope_key") for a in acts if a.get("scope_key")}
    lost = [f"{x['source']}: {x['text'][:60]}" for x in scope["lines"]
            if x["key"] not in keys]
    add("scope_to_activity", not lost,
        "Live scope with no activity: " + "; ".join(lost[:8]) if lost
        else f"All {len(scope['lines'])} live scope lines have an activity.")
    bare = [f"{a['code']} {a.get('name')}" for a in acts
            if a.get("type") not in ("loe", "wbs_summary")
            and a.get("cls") not in _FIELD_OK and not a.get("chain_id")
            and not a.get("citations")]
    add("activity_to_source", not bare,
        "Activities with no source: " + "; ".join(bare[:8]) if bare
        else "Every activity cites a bid document, a stated rule or the "
             "company template.")
    gone = {x["key"] for x in scope["removed"]}
    back = [f"{a['code']} {a.get('name')}" for a in acts
            if a.get("scope_key") in gone]
    add("removed_scope", not back,
        "Removed scope still scheduled: " + "; ".join(back) if back
        else f"{len(gone)} removed item(s) kept off the schedule.")
    finals = [a for a in acts if a.get("cls") == "final_inspection"]
    subst = next((a for a in acts if a.get("cls") == "substantial"), None)
    hold = []
    if len(finals) != 1:
        hold.append(f"{len(finals)} final inspections (one expected)")
    elif subst and finals[0].get("ef") and subst.get("es") and \
            finals[0]["ef"] > subst["es"]:
        hold.append("final inspection is after Substantial Completion")
    rough = [a for a in acts if a.get("cls") in bidset.ROUGH]
    rinsp = [a for a in acts if a.get("cls") == "rough_in_inspection"]
    cover = [a for a in acts if a.get("cls") == "cover"]
    if rough and not rinsp:
        hold.append("rough-in work with no rough-in inspection")
    elif rinsp and cover:
        last = max((a.get("ef") or "") for a in rinsp)
        early = [c["code"] for c in cover if (c.get("es") or "") <= last]
        if early:
            hold.append("close-in starts before the rough-in inspection: "
                        + ", ".join(early))
    add("hold_points", not hold, "; ".join(hold) if hold else
        "Rough-in inspection before close-in; one final inspection before "
        "Substantial Completion.")
    hol = set(((doc.get("calendars") or {}).get("5day") or {})
              .get("holidays") or [])
    bad = []
    for a in acts:
        if a.get("calendar") not in ("5day", "weather"):
            continue
        for k in ("es", "ef"):
            d = a.get(k)
            if not d:
                continue
            day = _dt.date.fromisoformat(d[:10])
            if day.weekday() >= 5 or d[:10] in hol:
                bad.append(f"{a['code']} {k} {d[:10]}")
    add("workdays", not bad, "Work starts or finishes on a weekend or "
        "holiday: " + ", ".join(bad[:8]) if bad else
        "No field work starts or finishes on a weekend or holiday.")


def acknowledge_negative_float(doc, note):
    """A person has read the negative float and said why it is there.

    The float stays visible. The completeness gate no longer blocks on it.
    """
    doc.setdefault("project", {})["negative_float_ack"] = (note or "").strip()
    return evaluate(doc)
