"""Score a compiled schedule against a hand-built expectation.

The five measures are division recall, long-lead coverage, logic
validity, duration plausibility and citation accuracy. Schedule health
is reported beside them. The same measures can be applied to the
existing plan generator when it can be run without a window.
"""


def score(doc, expected):
    divisions = list(expected.get("divisions") or [])
    covered = set()
    for a in doc.get("activities") or []:
        if a.get("division"):
            covered.add(str(a["division"])[:2])
        if a.get("by_others") and a.get("division"):
            covered.add(str(a["division"])[:2])
    # Division 01 is covered by general conditions even when the code is 01.
    if any(a.get("cls") == "ntp" for a in doc.get("activities") or []):
        covered.add("01")
    hit = [d for d in divisions if d in covered]
    division_recall = len(hit) / len(divisions) if divisions else 1.0

    leads = [x.lower() for x in expected.get("long_leads") or []]
    found = 0
    for item in leads:
        ok = False
        for a in doc.get("activities") or []:
            blob = f"{a.get('name') or ''} {a.get('item') or ''}".lower()
            if item in blob and a.get("cls") in (
                    "fabrication", "release", "delivery", "submittal_submit"):
                ok = True
                break
        if ok:
            found += 1
    long_lead = found / len(leads) if leads else 1.0

    logic = _logic(doc)
    duration = _duration(doc, expected.get("max_days") or 44)
    citation = _citation(doc)
    health = (doc.get("health") or {}).get("score")
    health_items = {i["key"]: i.get("passed")
                    for i in (doc.get("health") or {}).get("items") or []}
    return {
        "division_recall": round(division_recall, 3),
        "long_lead_coverage": round(long_lead, 3),
        "logic_validity": round(logic, 3),
        "duration_plausibility": round(duration, 3),
        "citation_accuracy": round(citation, 3),
        "health_score": health,
        "health_items": health_items,
        "rubric_passed": bool((doc.get("rubric") or {}).get("passed")),
        "rubric_score": (doc.get("rubric") or {}).get("score"),
        "status": doc.get("status"),
        "activities": len(doc.get("activities") or []),
    }


def _logic(doc):
    rels = doc.get("relationships") or []
    acts = [a for a in doc.get("activities") or []
            if a.get("type") not in ("loe", "wbs_summary")]
    if not acts:
        return 0.0
    preds, succs = set(), set()
    bad_rel = 0
    for r in rels:
        if r.get("type") not in ("FS", "SS", "FF", "SF"):
            bad_rel += 1
        if float(r.get("lag_hours") or 0) < 0:
            bad_rel += 1
        preds.add(r.get("succ"))
        succs.add(r.get("pred"))
    bad_act = 0
    for a in acts:
        if a.get("cls") != "ntp" and a["code"] not in preds:
            bad_act += 1
        if a.get("cls") != "final" and a["code"] not in succs:
            bad_act += 1
    # A loop shows up in the log.
    loops = sum(1 for line in doc.get("log") or [] if "loop" in line.lower())
    total = len(acts) + max(1, len(rels))
    bad = bad_act + bad_rel + loops
    return max(0.0, 1.0 - bad / total)


def _duration(doc, limit):
    rows = [a for a in doc.get("activities") or []
            if a.get("type") not in ("loe", "wbs_summary", "start_ms", "finish_ms")]
    if not rows:
        return 1.0
    ok = 0
    for a in rows:
        days = a.get("dur_days")
        if days is None:
            continue
        if 0 < days <= limit:
            ok += 1
    return ok / len(rows)


def _citation(doc):
    known = {}
    for sec in (doc.get("ingest") or {}).get("sections") or []:
        known[sec.get("number") or ""] = set(sec.get("pages") or [])
    claimed = valid = 0
    for a in doc.get("activities") or []:
        cites = a.get("citations") or []
        if not cites:
            # A spec-driven activity (computed, not a template slot) should
            # carry a pointer. Template rows are not required to.
            if a.get("duration_kind") == "computed" and not a.get("template_slot"):
                claimed += 1
            continue
        for c in cites:
            claimed += 1
            sec = c.get("spec_section") or ""
            page = c.get("page")
            if sec and sec in known and (page is None or not known[sec]
                                         or page in known[sec]):
                valid += 1
            elif not sec and page is not None:
                # Contract reader cites a page without a section number.
                if any(page in pages for pages in known.values()):
                    valid += 1
    if not claimed:
        return 1.0
    return valid / claimed


def score_legacy(activities, expected):
    """The same measures on the existing generator's activity dicts.

    Those dicts have name, duration and preds. They have no division
    field, so a division counts as recalled when a keyword is in a name.
    """
    names = " ".join((a.get("name") or "").lower() for a in activities)
    keywords = {
        "01": ("mobil", "closeout", "punch", "substantial"),
        "02": ("demo",),
        "03": ("foundation", "slab", "concrete", "footing"),
        "04": ("mason",),
        "05": ("steel", "joist"),
        "06": ("wood", "framing", "carpentry"),
        "07": ("roof",),
        "08": ("door", "window", "storefront", "enclosure"),
        "09": ("paint", "floor", "drywall", "finish", "ceiling"),
        "14": ("elevator",),
        "21": ("sprinkler", "fire protection"),
        "22": ("plumb",),
        "23": ("hvac", "mechanical", "air handler", "rooftop"),
        "26": ("electr", "switchgear", "generator"),
        "31": ("excavat", "grading", "site", "erosion"),
        "32": ("paving", "landscape", "sidewalk"),
        "33": ("utilit", "sewer", "water"),
    }
    divisions = list(expected.get("divisions") or [])
    hit = 0
    for div in divisions:
        words = keywords.get(div, ())
        if any(w in names for w in words):
            hit += 1
    division_recall = hit / len(divisions) if divisions else 1.0
    leads = [x.lower() for x in expected.get("long_leads") or []]
    found = sum(1 for item in leads if item in names)
    long_lead = found / len(leads) if leads else 1.0
    bad = 0
    total = 0
    for a in activities:
        total += 1
        for pred in a.get("preds") or []:
            total += 1
            typ = pred[1] if isinstance(pred, (list, tuple)) and len(pred) > 1 else "FS"
            lag = pred[2] if isinstance(pred, (list, tuple)) and len(pred) > 2 else 0
            if typ not in ("FS", "SS", "FF", "SF") or (lag or 0) < 0:
                bad += 1
        if not a.get("preds") and "notice" not in (a.get("name") or "").lower():
            bad += 1
    logic = max(0.0, 1.0 - bad / total) if total else 0.0
    limit = expected.get("max_days") or 44
    durs = [a for a in activities if (a.get("duration") or 0) > 0]
    ok = sum(1 for a in durs if 0 < (a.get("duration") or 0) <= limit)
    duration = ok / len(durs) if durs else 1.0
    return {
        "division_recall": round(division_recall, 3),
        "long_lead_coverage": round(long_lead, 3),
        "logic_validity": round(logic, 3),
        "duration_plausibility": round(duration, 3),
        "citation_accuracy": None,
        "activities": len(activities),
    }


def run_legacy(spec_pages, drawings, project_type, area_sf=20000):
    """Run the existing headless generator (``autoschedule.plan``).

    It does not call a model. Returns its activity list, or an error
    string when the project type it knows cannot be built from the text.
    """
    from .. import autoschedule
    sections = []
    divisions = []
    texts = []
    for item in spec_pages or []:
        if isinstance(item, dict):
            texts.append(item.get("text") or "")
        else:
            texts.append(item[1] or "")
    # Sections the new reader found are passed in drawings as sheet rows
    # and spec text is enough for scope() when we also pass sections.
    from .ingest import segment_spec
    secs, _q = segment_spec(spec_pages or [])
    for sec in secs:
        sections.append({"number": sec["number"], "title": sec.get("title") or ""})
        if sec.get("division"):
            divisions.append(sec["division"])
    sheets = []
    for d in drawings or []:
        if isinstance(d, dict):
            sheets.append({"number": d.get("number") or d.get("sheet") or "",
                           "title": d.get("title") or ""})
            texts.append(d.get("text") or "")
            texts.append(d.get("title") or "")
    try:
        sc = autoschedule.scope(
            sheets, divisions, sections=sections, texts=texts,
            area_sf=area_sf, project_type=project_type)
        return autoschedule.plan(sc), ""
    except Exception as exc:                            # noqa: BLE001
        return [], str(exc)[:300]


def score_bid(activities, expected):
    """Score a schedule for a bid-set job against an answer key.

    `activities` are dicts with name, cls, es, ef, dur_days (a compiled
    draft's activities, or any other schedule turned into that shape - an
    older draft has only names and dates). `expected`:
      activities: [{"label", "match" (regex on the name), "cls"?}]
      forbid:     [regex] - removed scope that must not be scheduled
      order:      [[label, label], ...] - the first finishes before the
                  second starts
      durations:  {label: [workdays, tolerance fraction]}
    Returns recall, the misses, the forbidden hits, order and duration
    results, and weekend starts/finishes."""
    import datetime as _dt
    import re as _re
    acts = list(activities or [])

    def find(e):
        pat = _re.compile(e["match"], _re.I)
        for a in acts:
            if e.get("cls") and a.get("cls") and a.get("cls") != e["cls"]:
                continue
            if pat.search(a.get("name") or ""):
                return a
        return None

    hits = {}
    for e in expected.get("activities") or []:
        a = find(e)
        if a is not None:
            hits[e["label"]] = a
    want = [e["label"] for e in expected.get("activities") or []]
    missed = [w for w in want if w not in hits]
    forbidden = []
    for pat in expected.get("forbid") or []:
        rx = _re.compile(pat, _re.I)
        forbidden += [a.get("name") for a in acts if rx.search(a.get("name")
                                                                 or "")]
    order_bad = []
    for first, second in expected.get("order") or []:
        a, b = hits.get(first), hits.get(second)
        if not a or not b or not a.get("ef") or not b.get("es"):
            order_bad.append(f"{first} -> {second}: not both scheduled")
        elif a["ef"][:10] > b["es"][:10] or (
                a["ef"][:10] == b["es"][:10] and (a.get("dur_days") or 0) and
                (b.get("dur_days") or 0)):
            order_bad.append(f"{first} ({a['ef'][:10]}) -> {second} "
                             f"({b['es'][:10]})")
    dur_bad = []
    for label, (days, tol) in (expected.get("durations") or {}).items():
        a = hits.get(label)
        got = a.get("dur_days") if a else None
        if got is None or abs(float(got) - days) > days * tol:
            dur_bad.append(f"{label}: {got} workdays, expected about {days}")
    weekend = []
    for a in acts:
        if a.get("calendar") not in (None, "", "5day", "weather"):
            continue
        for k in ("es", "ef"):
            d = a.get(k)
            if d and _dt.date.fromisoformat(d[:10]).weekday() >= 5:
                weekend.append(f"{a.get('name')} {k} {d[:10]}")
    return {"recall": round(len(hits) / len(want), 3) if want else 1.0,
            "missed": missed, "forbidden": forbidden, "order": order_bad,
            "durations": dur_bad, "weekend": weekend}
