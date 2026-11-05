"""Turn facts, the template and the rule table into a network.

The model is not called from here. Every division in the spec or the
takeoff becomes an activity or an explicit "by others / not in scope"
marker. Long-lead items get a procurement chain: submit, review, return,
release, fabricate (in pieces short enough to stay under a 44-workday
health limit), deliver, then the install that consumes them.
"""
import re

from . import rules as rules_mod
from . import templates as tmpl
from .calendar import standard_specs
from .durations import apply as apply_durations
from .durations import set_hours
from .merge import of_kind
from .model import (
    FINISH_MS, LOE, START_MS, blank_activity, new_schedule,
)

# Division -> (name, class, wbs, default days, role) for a division the
# template did not already cover.
_FILL = {
    "02": ("Demolition", "demolition", "1.3", 8, "Laborer"),
    "03": ("Concrete", "foundations", "1.4", 10, "Concrete crew"),
    "04": ("Masonry", "structure", "1.4", 10, "Mason"),
    "05": ("Metals", "structure", "1.4", 12, "Ironworker"),
    "06": ("Carpentry", "structure", "1.4", 8, "Carpenter"),
    "07": ("Thermal and moisture protection", "roofing", "1.5", 10, "Roofer"),
    "08": ("Openings", "envelope", "1.5", 8, "Carpenter"),
    "09": ("Finishes", "finishes", "1.6", 10, "Finishes crew"),
    "10": ("Specialties", "finishes", "1.6", 5, "Carpenter"),
    "11": ("Equipment", "trim", "1.6", 5, "Laborer"),
    "12": ("Furnishings", "finishes", "1.6", 5, "Laborer"),
    "13": ("Special construction", "structure", "1.4", 8, "Laborer"),
    "14": ("Conveying equipment", "structure", "1.4", 10, "Elevator crew"),
    "21": ("Fire suppression", "fire_rough", "1.7", 8, "Sprinkler fitter"),
    "22": ("Plumbing", "plumb_rough", "1.7", 10, "Plumber"),
    "23": ("Heating, ventilating and air conditioning", "hvac_rough", "1.7",
           10, "HVAC technician"),
    "25": ("Integrated automation", "elec_rough", "1.7", 5, "Electrician"),
    "26": ("Electrical", "elec_rough", "1.7", 10, "Electrician"),
    "27": ("Communications", "elec_rough", "1.7", 5, "Electrician"),
    "28": ("Electronic safety", "elec_rough", "1.7", 5, "Electrician"),
    "31": ("Earthwork", "underground", "1.3", 8, "Operator"),
    "32": ("Exterior improvements", "underground", "1.3", 6, "Laborer"),
    "33": ("Utilities", "underground", "1.3", 8, "Operator"),
}

_TYPE_MAP = {
    "new_building": "ground_up_commercial",
    "renovation": "tenant_improvement",
    "hvac_replacement": "mep_retrofit",
    "ground_up": "ground_up_commercial",
    "ti": "tenant_improvement",
    "tenant": "tenant_improvement",
    "service": "plumbing_hvac_service",
}

_WBS = (
    ("1", "", "Project"),
    ("1.1", "1", "General conditions"),
    ("1.2", "1", "Procurement"),
    ("1.3", "1", "Site"),
    ("1.4", "1", "Structure"),
    ("1.5", "1", "Envelope"),
    ("1.6", "1", "Interiors"),
    ("1.7", "1", "MEP"),
    ("1.8", "1", "Commissioning and closeout"),
    ("1.9", "1", "By others"),
)

_FIELD = {
    "demolition", "underground", "foundations", "slab", "cure", "structure",
    "roofing", "envelope", "openings", "plumb_rough", "hvac_rough",
    "elec_rough", "fire_rough", "cover", "finishes", "service_repair",
}


def detect_type(text, divisions, explicit=None):
    if explicit:
        key = _TYPE_MAP.get(explicit, explicit)
        if key in tmpl.LABELS:
            return key
    blob = (text or "").lower()
    if re.search(r"tenant improvement|tenant fit|fit[- ]?out", blob):
        return "tenant_improvement"
    if re.search(r"\bretrofit\b|equipment replacement|replace the existing|"
                 r"replace existing", blob):
        return "mep_retrofit"
    if re.search(r"service call|service work|plumbing service|hvac service",
                 blob):
        return "plumbing_hvac_service"
    if re.search(r"ground[- ]up|new building|new construction", blob):
        return "ground_up_commercial"
    core = set(divisions or ()) - {"01", "00"}
    if core and core <= {"21", "22", "23", "25", "26", "27", "28"}:
        return "mep_retrofit"
    if "02" in core and "03" not in core and "31" not in core:
        return "tenant_improvement"
    return "ground_up_commercial"


def _hpd(calendar):
    return 24 if calendar == "24hour" else 8


def _make(code, name, **kw):
    days = kw.pop("days", 0)
    calendar = kw.get("calendar") or "5day"
    kind = kw.pop("milestone_type", None)
    if days == 0 and kind is None and kw.get("cls") in (
            "ntp", "release"):
        kind = START_MS
    if days == 0 and kw.get("cls") in ("substantial", "final"):
        kind = FINISH_MS
    act = blank_activity(
        code, name,
        type=kind or ("task"),
        calendar=calendar,
        cls=kw.get("cls") or "",
        division=kw.get("division") or "",
        wbs=kw.get("wbs") or "1",
        roles=kw.get("roles") or (),
        template_slot=kw.get("template_slot") or "",
        duration_kind=kw.get("duration_kind") or "estimated",
        basis=kw.get("basis") or "",
        chain_id=kw.get("chain_id") or "",
        by_others=kw.get("by_others") or False,
        fabrication_na=kw.get("fabrication_na") or False,
        citations=kw.get("citations") or (),
        cost_code=kw.get("cost_code") or "",
    )
    act["phase"] = kw.get("phase") or ""
    set_hours(act, 0 if kind in (START_MS, FINISH_MS) else days,
              {"calendars": standard_specs()})
    if kind in (START_MS, FINISH_MS):
        act["type"] = kind
    if kw.get("constraint"):
        act["constraint"] = kw["constraint"]
        act["constraint_date"] = kw.get("constraint_date") or ""
    return act


def _cite(fact):
    return [{"spec_section": c.get("spec_section") or "",
             "page": c.get("page"), "source": c.get("source") or ""}
            for c in (fact.get("citations") or []) if c.get("page")]


def _slug(text):
    chars = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (chars or "item")[:24]


def assemble(facts, ct, ingest, project_type=None, takeoff=None,
             cost_book=None, productivity=None, actuals=None,
             ntp=None, data_date=None, holidays=None, name="Project",
             template_dir=None, area_sf=None, stories=1,
             weather_months=None):
    text = "\n".join((s.get("text") or "") for s in
                     ingest.get("spec_sections") or [])
    text += "\n" + "\n".join((d.get("text") or "") + " " +
                             (d.get("title") or "")
                             for d in ingest.get("drawings") or ())
    divisions = set(ingest.get("divisions") or ())
    for it in takeoff or ():
        if isinstance(it, dict) and str(it.get("division") or "")[:2].isdigit():
            divisions.add(str(it["division"])[:2])
    ptype = detect_type(text, divisions, project_type)
    library = tmpl.load(template_dir)
    assumptions = library.get("assumptions") or {}
    if weather_months is None:
        weather_months = assumptions.get("weather_months") or []
    swppp = bool(re.search(r"\bSWPPP\b|erosion and sediment", text, re.I))
    slots = tmpl.slots_for(library, ptype, divisions, swppp=swppp)
    doc = new_schedule(name, start=ntp, data_date=data_date or ntp)
    doc["calendars"] = standard_specs(holidays or [], weather_months)
    doc["project"]["type"] = ptype
    doc["project"]["type_label"] = tmpl.LABELS.get(ptype, ptype)
    doc["facts"] = facts
    doc["ingest"] = {
        "divisions": sorted(divisions),
        "blank_pages": ingest.get("blank_pages") or [],
        "sections": [{"number": s.get("number"), "title": s.get("title"),
                      "pages": s.get("pages")}
                     for s in ingest.get("spec_sections") or ()],
    }
    doc["wbs"] = [{"code": c, "parent": p, "name": n, "id": i + 1}
                  for i, (c, p, n) in enumerate(_WBS)]
    acts = []
    rels = []
    seen_codes = set()

    def add(act):
        if act["code"] in seen_codes:
            act["code"] = act["code"] + "_" + str(len(seen_codes))
        seen_codes.add(act["code"])
        acts.append(act)
        return act

    for slot in slots:
        kind = None
        if slot.get("code") in ("NTP",) or slot.get("cls") == "ntp":
            kind = START_MS
        if slot.get("code") in ("SUBST", "FINAL") or slot.get("cls") in (
                "substantial", "final"):
            kind = FINISH_MS
        days = slot.get("days") or 0
        if slot.get("cls") == "margin":
            days = assumptions.get("schedule_margin_days") or days
        act = _make(
            slot["code"], slot["name"], days=0 if kind else days,
            calendar=slot.get("calendar") or "5day",
            cls=slot.get("cls") or "", division=slot.get("division") or "",
            wbs=slot.get("wbs") or "1", roles=slot.get("roles") or (),
            template_slot=slot["code"], milestone_type=kind,
            basis="template default, estimated" if not kind else "milestone",
        )
        if kind:
            act["duration_kind"] = "estimated"
            act["basis"] = "milestone"
        add(act)

    _fill_divisions(acts, add, divisions, facts)
    _by_others(acts, add, facts)
    _cure_and_contract(doc, acts, facts, ct)
    _procurement(acts, rels, add, facts, assumptions)
    _inspections(acts, rels, add, facts)
    _phases(acts, rels, add, facts)
    if ptype == "plumbing_hvac_service" and not any(
            a.get("cls") == "service_repair" for a in acts):
        add(_make("REP", "Repair", days=2, cls="service_repair",
                  division="22", wbs="1.2", roles=("Technician",),
                  template_slot="REP",
                  basis="template default, estimated"))
    rule_rows = rules_mod.load(template_dir)
    _apply_rules(acts, rels, rule_rows)
    _place_holds(acts, rels)
    _apply_sequences(acts, rels, facts)
    _tie_procurement(acts, rels)
    _connect(acts, rels)
    rels[:] = _dedupe(rels)
    doc["activities"] = acts
    doc["relationships"] = rels
    _number(doc)
    apply_durations(doc, takeoff=takeoff, cost_book=cost_book,
                    table=productivity, actuals=actuals, area_sf=area_sf,
                    stories=stories,
                    crew_size=float(assumptions.get("default_crew_size") or 4))
    _roles(doc)
    return doc


def _fill_divisions(acts, add, divisions, facts):
    covered = {a.get("division") for a in acts if a.get("division")}
    others = " ".join(f.get("item") or "" for f in of_kind(facts, "by_others")).lower()
    for div in sorted(divisions):
        if div in ("00", "01") or div in covered:
            continue
        if div in others or f"division {div}" in others:
            continue
        name, cls, wbs, days, role = _FILL.get(
            div, (f"Division {div} work", "finishes", "1.6", 5, "Laborer"))
        # Cite the first section of this division when the ingest has one.
        cites = []
        for fact in facts:
            if (fact.get("division") or "")[:2] == div and fact.get("citations"):
                cites = _cite(fact)
                break
        add(_make(
            "D" + div, name, days=days, cls=cls, division=div, wbs=wbs,
            roles=(role,), template_slot="",
            basis="division present in the spec, duration estimated",
            citations=cites,
        ))


def _by_others(acts, add, facts):
    covered = {a.get("division") for a in acts}
    for fact in of_kind(facts, "by_others"):
        item = fact.get("item") or "scope"
        div = ""
        m = re.search(r"\b(\d{2})\b", item)
        if m:
            div = m.group(1)
        add(_make(
            "BO_" + _slug(item),
            f"By others / not in scope: {item}",
            days=0, cls="by_others", division=div, wbs="1.9",
            milestone_type=LOE, by_others=True,
            citations=_cite(fact),
            basis="marked by others in the spec",
            duration_kind="estimated",
        ))
        acts[-1]["type"] = LOE
        if div:
            covered.add(div)


def _cure_and_contract(doc, acts, facts, ct):
    cure = next((f for f in of_kind(facts, "cure") if f.get("value")), None)
    for act in acts:
        if act.get("cls") == "cure" and cure:
            days = int(cure["value"])
            act["calendar"] = "7day"
            set_hours(act, days, doc)
            act["duration_kind"] = "computed"
            act["basis"] = f"{days} calendar days stated in the spec"
            act["citations"] = _cite(cure)
    sub = (ct or {}).get("substantial")
    fin = (ct or {}).get("final")
    start = doc["project"]["start"]
    if sub and sub.get("days"):
        import datetime as _dt
        ntp = _dt.date.fromisoformat(start)
        days = int(sub["days"])
        when = ntp + _dt.timedelta(days=days - 1)
        doc["project"]["must_finish"] = when.isoformat()
        for act in acts:
            if act.get("cls") == "substantial":
                act["constraint"] = "finish_on_or_before"
                act["constraint_date"] = when.isoformat()
                pages = sub.get("pages") or []
                if pages:
                    act["citations"] = [{"spec_section": "", "page": pages[0],
                                         "source": "deterministic"}]
                act["basis"] = (f"contract substantial completion "
                                f"{days} {sub.get('basis') or ''} days")
    if fin and fin.get("days"):
        import datetime as _dt
        ntp = _dt.date.fromisoformat(start)
        when = ntp + _dt.timedelta(days=int(fin["days"]) - 1)
        for act in acts:
            if act.get("cls") == "final":
                act["constraint"] = "finish_on_or_before"
                act["constraint_date"] = when.isoformat()
                act["basis"] = f"contract final completion {fin['days']} days"


def _procurement(acts, rels, add, facts, assumptions):
    review = next((f for f in of_kind(facts, "submittal_review")
                   if f.get("value")), None)
    review_days = int(review["value"]) if review and review.get("value") \
        else int(assumptions.get("review_days") or 10)
    review_cal = "7day" if review and (review.get("unit") or "") != "work" \
        else "5day"
    chunk = int(assumptions.get("fab_chunk_days") or 40)
    deliver_days = int(assumptions.get("delivery_days") or 3)
    # General submittal chain so a submittal has submit -> review -> return
    # and an explicit "no fabrication" marker when nothing is being built.
    if review or True:
        _chain(add, rels, "General submittals", "general", review_days,
               review_cal, fab_days=0, deliver_days=0, chunk=chunk,
               citations=_cite(review) if review else [],
               division="01", consumer="", fabrication_na=True,
               computed=bool(review))
    for fact in of_kind(facts, "long_lead"):
        if fact.get("conflict"):
            # Not chosen. A procurement chain still exists so the item is
            # visible, with the duration left estimated and the conflict
            # on the activity.
            days = None
        else:
            days = fact.get("value")
        lead = int(days) if days else 60
        kind = "computed" if fact.get("lead_source") == "spec" else "estimated"
        _chain(add, rels, fact.get("item") or "item",
               "ll_" + _slug(fact.get("item")),
               review_days, review_cal,
               fab_days=max(5, lead - deliver_days),
               deliver_days=deliver_days, chunk=chunk,
               citations=_cite(fact), division=fact.get("division") or "",
               consumer=fact.get("consumer") or "",
               fabrication_na=False, computed=(kind == "computed"),
               conflict=bool(fact.get("conflict")))


def _chain(add, rels, title, cid, review_days, review_cal, fab_days,
           deliver_days, chunk, citations, division, consumer,
           fabrication_na, computed, conflict=False):
    def piece(suffix, name, days, calendar, cls, milestone=None, na=False):
        act = _make(
            f"{cid}_{suffix}"[:40], name, days=0 if milestone else days,
            calendar=calendar, cls=cls, division=division, wbs="1.2",
            roles=("Project engineer",) if "submittal" in cls or cls == "release"
            else ("Supplier",),
            chain_id=cid, milestone_type=milestone,
            citations=citations, fabrication_na=na,
            duration_kind="computed" if computed and not milestone else "estimated",
            basis=("stated lead time" if computed else
                   "lead time estimated") + ("; conflicting values" if conflict else ""),
        )
        act["consumer"] = consumer
        act["item"] = title
        return add(act)

    submit = piece("SUB", f"Submit {title}", 5, "5day", "submittal_submit")
    review = piece("REV", f"Review {title}", review_days, review_cal,
                   "submittal_review")
    ret = piece("RET", f"Return {title}", 1, "5day", "submittal_return")
    rels.append(_rel(submit["code"], review["code"]))
    rels.append(_rel(review["code"], ret["code"]))
    prev = ret
    if fabrication_na:
        fab = piece("FAB", f"Fabrication not required: {title}", 0, "5day",
                    "fabrication", milestone=FINISH_MS, na=True)
        rels.append(_rel(prev["code"], fab["code"]))
        return
    release = piece("REL", f"Release {title} for fabrication", 0, "5day",
                    "release", milestone=START_MS)
    rels.append(_rel(prev["code"], release["code"]))
    prev = release
    left = fab_days
    n = 1
    while left > 0:
        take = min(chunk, left)
        fab = piece(f"FAB{n}", f"Fabricate {title} ({n})", take, "7day",
                    "fabrication")
        rels.append(_rel(prev["code"], fab["code"]))
        prev = fab
        left -= take
        n += 1
    if deliver_days:
        delivery = piece("DEL", f"Deliver {title}", deliver_days, "5day",
                         "delivery")
        rels.append(_rel(prev["code"], delivery["code"]))


def _inspections(acts, rels, add, facts):
    n = 0
    for fact in of_kind(facts, "inspection") + of_kind(facts, "test"):
        n += 1
        label = fact.get("item") or "inspection"
        cls = _inspect_class(label, fact.get("kind"))
        add(_make(
            f"INSP{n}", label[:80], days=1, cls=cls, division="01",
            wbs="1.8", roles=("Inspector",),
            citations=_cite(fact), duration_kind="computed",
            basis="named in the spec",
        ))


def _place_holds(acts, rels):
    for act in list(acts):
        if act.get("cls") in ("inspection", "footing_inspection",
                              "final_inspection", "pressure_test",
                              "rough_in_inspection", "test_gate"):
            _insert_hold(acts, rels, act, act.get("name") or "", act.get("cls"))


def _insert_hold(acts, rels, gate, label, cls):
    """Put a hold point in the chain it actually holds, so it cannot float
    for the whole job. Links from the predecessor class to the successor
    class are retargeted through the hold point."""
    text = label.lower()
    if cls == "rough_in_inspection":
        pred_cls, succ_cls = {"plumb_rough", "hvac_rough", "elec_rough",
                              "fire_rough"}, {"cover"}
    elif cls == "footing_inspection":
        pred_cls, succ_cls = {"foundations"}, {"slab", "cure"}
    elif "steel" in text:
        pred_cls, succ_cls = {"structure"}, {"envelope", "roofing", "plumb_rough",
                                            "hvac_rough", "elec_rough"}
    elif cls == "final_inspection":
        pred_cls, succ_cls = {"commissioning", "punch"}, {"substantial"}
    elif cls == "pressure_test":
        pred_cls, succ_cls = {"plumb_rough", "service_repair"}, {"startup"}
    else:
        pred_cls, succ_cls = {"startup", "trim", "finishes"}, {"punch", "substantial"}
    pred_codes = {a["code"] for a in acts if a.get("cls") in pred_cls and a is not gate}
    succ_codes = {a["code"] for a in acts if a.get("cls") in succ_cls and a is not gate}
    moved = False
    kept = []
    added = []
    for rel in list(rels):
        if rel.get("pred") in pred_codes and rel.get("succ") in succ_codes \
                and rel.get("type") == "FS" and rel.get("succ") != gate["code"] \
                and rel.get("pred") != gate["code"]:
            added.append(_rel(rel["pred"], gate["code"]))
            added.append(_rel(gate["code"], rel["succ"]))
            moved = True
            continue
        kept.append(rel)
    if moved:
        rels[:] = kept + added
    elif pred_codes:
        for code in pred_codes:
            rels.append(_rel(code, gate["code"]))


def _inspect_class(label, kind):
    text = label.lower()
    if kind == "test" and "balance" in text:
        return "tab"
    if re.search(r"above[- ]ceiling|rough[- ]in|in[- ]wall|cover", text):
        return "rough_in_inspection"
    if re.search(r"footing|foundation", text):
        return "footing_inspection"
    if re.search(r"final|life safety|fire alarm", text):
        return "final_inspection"
    if re.search(r"pressure|hydro", text):
        return "pressure_test"
    if kind == "test":
        return "test_gate"
    return "inspection"


def _phases(acts, rels, add, facts):
    phases = of_kind(facts, "phasing")
    prev = None
    for i, fact in enumerate(phases, 1):
        act = _make(
            f"PH{i}", fact.get("item") or f"Phase {i}", days=0,
            cls="phase", division="01", wbs="1.1",
            milestone_type=FINISH_MS, citations=_cite(fact),
            basis="phasing statement",
        )
        add(act)
        if prev:
            rels.append(_rel(prev, act["code"]))
        prev = act["code"]


def _apply_rules(acts, rels, rule_rows):
    by_cls = {}
    for act in acts:
        by_cls.setdefault(act.get("cls") or "", []).append(act["code"])
    have = {(r["pred"], r["succ"], r["type"]) for r in rels}
    for rule in rule_rows or ():
        preds = by_cls.get(rule.get("pred_cls") or "", [])
        succs = by_cls.get(rule.get("succ_cls") or "", [])
        if not preds or not succs:
            continue
        lag_days = int(rule.get("lag_days") or 0)
        for p in preds:
            for s in succs:
                if p == s:
                    continue
                key = (p, s, rule.get("type") or "FS")
                if key in have:
                    continue
                have.add(key)
                rels.append(_rel(p, s, rule.get("type") or "FS",
                                 lag_days * 8))


def _apply_sequences(acts, rels, facts):
    """A 'completed before' sentence links two activities when each side
    matches exactly one activity name. Otherwise it stays a fact."""
    have = {(r["pred"], r["succ"], r["type"]) for r in rels}
    for fact in of_kind(facts, "sequence"):
        before = _match_one(acts, fact.get("item") or "")
        after = _match_one(acts, str(fact.get("value") or ""))
        if before and after and before != after:
            key = (before, after, "FS")
            if key not in have:
                have.add(key)
                rels.append(_rel(before, after))


def _match_one(acts, text):
    text = " ".join(str(text or "").lower().split())
    if len(text) < 4:
        return ""
    hits = [a["code"] for a in acts
            if text in a.get("name", "").lower()
            or a.get("name", "").lower() in text]
    return hits[0] if len(hits) == 1 else ""


def _tie_procurement(acts, rels):
    """Delivery waits are already inside the chain. The consuming activity
    also waits on delivery."""
    by_cls = {}
    for act in acts:
        by_cls.setdefault(act.get("cls") or "", []).append(act)
    have = {(r["pred"], r["succ"], r["type"]) for r in rels}
    for act in acts:
        if act.get("cls") != "delivery":
            continue
        consumer = act.get("consumer") or ""
        targets = by_cls.get(consumer) or []
        targets = [t for t in targets if t.get("chain_id") != act.get("chain_id")]
        if not targets:
            inst = _make(
                act["code"] + "_INS", f"Install {act.get('item') or ''}".strip(),
                days=5, cls=consumer or "trim",
                division=act.get("division") or "", wbs="1.7",
                roles=("Crew",), chain_id=act.get("chain_id") or "",
                citations=act.get("citations") or [],
                basis=act.get("basis") or "",
                duration_kind=act.get("duration_kind") or "estimated",
            )
            inst["item"] = act.get("item") or ""
            acts.append(inst)
            targets = [inst]
        for t in targets:
            key = (act["code"], t["code"], "FS")
            if key not in have:
                have.add(key)
                rels.append(_rel(act["code"], t["code"]))


def _connect(acts, rels):
    """No task is left without a predecessor or a successor, except the
    project start and the project finish. Level-of-effort markers are tied
    for the record and do not drive the pass.
    """
    preds = {}
    succs = {}
    for r in rels:
        preds.setdefault(r["succ"], set()).add(r["pred"])
        succs.setdefault(r["pred"], set()).add(r["succ"])
    start = next((a["code"] for a in acts if a.get("cls") == "ntp"), "")
    finish = next((a["code"] for a in acts if a.get("cls") == "final"), "")
    subst = next((a["code"] for a in acts if a.get("cls") == "substantial"), "")
    anchor = subst or finish
    ret = next((a["code"] for a in acts if a.get("chain_id") == "general"
                and a.get("cls") == "submittal_return"), "")
    for act in acts:
        code = act["code"]
        if act.get("type") == LOE:
            if start and code not in preds:
                rels.append(_rel(start, code, "SS"))
            if finish and code not in succs:
                rels.append(_rel(code, finish, "FF"))
            continue
        if code == start:
            continue
        if code not in preds:
            giver = start
            if ret and act.get("cls") in _FIELD:
                giver = ret
            if giver:
                rels.append(_rel(giver, code))
        if code == finish:
            continue
        if act.get("fabrication_na"):
            # A document-only submittal must not sit on the project finish
            # with months of float. It ends when the field work it released
            # has a predecessor of its own; tie it to the first field activity.
            field = next((a["code"] for a in acts if a.get("cls") in _FIELD),
                         "")
            if field and code not in succs:
                rels.append(_rel(code, field))
            elif anchor and code not in succs:
                rels.append(_rel(code, anchor))
            continue
        if code not in succs and anchor and code != anchor:
            rels.append(_rel(code, anchor))
        elif code == anchor and finish and code not in succs:
            rels.append(_rel(code, finish))


def _dedupe(rels):
    seen, out = set(), []
    for r in rels:
        key = (r["pred"], r["succ"], r.get("type") or "FS")
        if key in seen or r["pred"] == r["succ"]:
            continue
        seen.add(key)
        out.append(r)
    return out


def _rel(pred, succ, typ="FS", lag_hours=0):
    return {"pred": pred, "succ": succ, "type": typ,
            "lag_hours": float(lag_hours or 0), "comments": ""}


def _number(doc):
    """Activity ids A1010, A1020, ... in WBS order. Relationships follow."""
    wbs_order = {w["code"]: i for i, w in enumerate(doc.get("wbs") or [])}
    acts = sorted(doc["activities"],
                  key=lambda a: (wbs_order.get(a.get("wbs"), 99), a.get("code")))
    mapping = {}
    for i, act in enumerate(acts):
        new = f"A{1010 + 10 * i}"
        mapping[act["code"]] = new
        act["id"] = i + 1
        act["slot"] = act.get("template_slot") or act["code"]
        act["code"] = new
    for rel in doc["relationships"]:
        rel["pred"] = mapping.get(rel["pred"], rel["pred"])
        rel["succ"] = mapping.get(rel["succ"], rel["succ"])
    doc["activities"] = acts
    # Drop links that point at a code we removed.
    codes = {a["code"] for a in acts}
    doc["relationships"] = [r for r in doc["relationships"]
                            if r["pred"] in codes and r["succ"] in codes
                            and r["pred"] != r["succ"]]


def _roles(doc):
    names = []
    for act in doc["activities"]:
        if act.get("type") not in ("start_ms", "finish_ms", "loe", "wbs_summary") \
                and not act.get("roles"):
            act["roles"] = ["Crew"]
        for role in act.get("roles") or ():
            if role not in names:
                names.append(role)
    doc["roles"] = [{"id": i + 1, "name": n} for i, n in enumerate(names)]
    doc["resources"] = [{"id": i + 1, "name": n, "role": n, "calendar": "5day",
                         "type": "labor"} for i, n in enumerate(names)]
    assignments = []
    n = 1
    for act in doc["activities"]:
        if act.get("type") in ("start_ms", "finish_ms", "loe", "wbs_summary"):
            continue
        for role in act.get("roles") or ():
            res = next(r for r in doc["resources"] if r["name"] == role)
            hours = float(act.get("orig_hours") or 0)
            assignments.append({
                "id": n, "activity": act["code"], "resource": res["id"],
                "role": res["id"], "units": 1.0,
                "units_per_hour": 1.0,
                "budgeted_hours": hours,
                "budget_cost": 0.0,
            })
            n += 1
    doc["assignments"] = assignments
    doc["codes"] = []
    for act in doc["activities"]:
        for typ, val in (("Division", act.get("division") or ""),
                         ("Trade", (act.get("roles") or [""])[0]),
                         ("Phase", act.get("phase") or _phase_of(act)),
                         ("Responsibility", (act.get("roles") or [""])[0])):
            if val:
                doc["codes"].append({"activity": act["code"], "type": typ,
                                     "value": val})


def _phase_of(act):
    wbs = act.get("wbs") or ""
    return {
        "1.1": "General", "1.2": "Procurement", "1.3": "Site",
        "1.4": "Structure", "1.5": "Envelope", "1.6": "Interiors",
        "1.7": "MEP", "1.8": "Closeout", "1.9": "Exclusions",
    }.get(wbs, "")
