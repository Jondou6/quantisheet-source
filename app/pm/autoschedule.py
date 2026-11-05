"""Build a draft schedule from a drawing set and its spec book.

1. Contract time, read from the specs (bid form, agreement, Division 00 /
   01): days to Substantial Completion and to Final Completion (calendar
   or working days, or a fixed date), and liquidated damages. Every place
   it's stated is kept with its page, and places that disagree are
   reported - never silently picked.
2. Scope: the disciplines in the set (sheet numbers C, S, A, M, P, E, FP
   ...), the CSI divisions in the spec book, the building area (room tags
   on the floor plans) and quantities already taken off (pipe LF).
3. A draft schedule in the normal building sequence - mobilize, site,
   foundations, structure, envelope (dried in), rough-ins, finishes, MEP
   trim, site finishes, punch, Substantial and Final Completion - and the
   links between them. Durations come from quantities: quantity /
   (production rate x crews), clamped per activity family (productivity.py
   - the GC's table, editable), with the quantity taken off or estimated
   from the floor area and levels. Each activity keeps its BASIS (in its
   Notes). Phases are summary rows; everything is editable in the
   Scheduler.
4. A fit check: the predicted Substantial / Final Completion against the
   contract dates (calendar days counted from Notice to Proceed), and
   fit() to squeeze the work durations when it runs long.

Nothing is invented from nothing: the sequence and rates are rules, the
quantities are the drawings', and anything assumed is listed as assumed.
"""
import datetime as _dt
import math
import os
import re
from collections import Counter

from . import schedule
from . import schedule_types as _types

# ------------------------------------------------------------- contract time
_MONTHS = ("jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec")
_DATE = re.compile(rf"\b((?:{_MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s+\d{{4}})",
                   re.I)
_DAYS = re.compile(r"\(?\b(\d{1,4})\)?\s*(?:\)\s*)?((?:(?:consecutive|"
                   r"calendar|working|work|business)\s*,?\s*){0,3})days?\b",
                   re.I)
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
# completing THE WORK (not "within 90 days of completing TAB")
_ABOUT_TIME = re.compile(
    r"substantial(?:ly)?\s+complet|final(?:ly)?\s+complet|"
    r"fully\s+complet|complet\w*\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?"
    r"(?:work|project|contract|construction)|completion of (?:the )?"
    r"(?:work|project|contract)|contract\s+time|time\s+(?:of|for)\s+"
    r"completion|notice\s+to\s+proceed", re.I)
_NOT_TIME = re.compile(r"warrant|guarant|submit|submittal|payment|invoice|"
                       r"retainage|bid security|bid bond|award|execute|"
                       r"sign|delay|notif|claim|extension|holiday|"
                       r"inspection request|withdraw|reject|accept\w* of "
                       r"(?:the )?bid|after receipt|written request|"
                       r"maintenance|training|test|terminat|surety|"
                       r"default|suspend|protest|addend", re.I)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").replace("’", "'"))


def _sentences(text):
    return [s for s in re.split(r"(?<=[.;])\s+(?=[A-Z0-9(\"“])",
                                _norm(text)) if s.strip()]


# the EJCDC agreement's wording for Final Completion ("... and completed
# and ready for final payment ... within 210 days")
_FINAL_PAYMENT = re.compile(r"\b(?:complete[ds]?|completion)\s+and\s+ready\s+"
                            r"for\s+final\s+payment\b", re.I)


def contract_time(pages):
    """pages: [(page number 1-based, text)]. Returns
    {"substantial": {days, basis, pages} or None, "final": {...} or None,
     "final_after_substantial": days or None, "dates": {...},
     "ld_per_day": float or None, "ld_pages": [...], "found": [...],
     "conflicts": [text]}."""
    found = []
    lds = []
    for pno, text in pages:
        for orig in _sentences(text):
            s = _FINAL_PAYMENT.sub("finally completed", orig)
            low = s.lower()
            if "liquidated damages" in low:
                m = _MONEY.search(s)
                if m and re.search(r"\bday\b|\bdays\b|per diem", low):
                    try:
                        lds.append((float(m.group(1).replace(",", "")), pno,
                                    orig[:200]))
                    except ValueError:
                        pass
                continue
            if not _ABOUT_TIME.search(s):
                continue
            for m in _DAYS.finditer(s):
                n = int(m.group(1))
                if not 14 <= n <= 2000:
                    continue
                # judge each number by the words around it (a bid form is
                # one long run of text with no periods)
                before = s[max(0, m.start() - 160):m.start()]
                near = before + s[m.end():m.end() + 25]
                if not _ABOUT_TIME.search(before + s[m.end():m.end() + 80]) \
                        or _NOT_TIME.search(near):
                    continue
                kind = _kind(before)
                q = m.group(2).lower()
                basis = "working" if re.search(r"working|work|business", q) \
                    else "calendar"
                tail = s[m.end():m.end() + 60].lower()
                if kind == "final" and "after" in tail and "substantial" in \
                        tail:
                    found.append({"kind": "final_after", "days": n,
                                  "basis": basis, "page": pno,
                                  "text": orig[:240]})
                    continue
                found.append({"kind": kind, "days": n, "basis": basis,
                              "page": pno, "text": orig[:240]})
            for m in _DATE.finditer(s):
                d = _parse_long_date(m.group(1))
                before = s[max(0, m.start() - 160):m.start()].lower()
                if not d or not re.search(r"complet", before) or \
                        _NOT_TIME.search(before[-80:]):
                    continue
                kind = _kind(before)
                kind = "final" if kind == "total" else kind
                if d:
                    found.append({"kind": kind + "_date", "date":
                                  d.isoformat(), "page": pno,
                                  "text": orig[:240]})
    out = {"found": found, "conflicts": [], "dates": {}}

    def pick(kinds):
        vals = [(f["days"], f["basis"]) for f in found if f["kind"] in kinds]
        if not vals:
            return None
        cnt = Counter(vals)
        (days, basis), _n = cnt.most_common(1)[0]
        pages_ = sorted({f["page"] for f in found if f["kind"] in kinds and
                         (f["days"], f["basis"]) == (days, basis)})
        if len(cnt) > 1:
            other = ", ".join(
                f"{d} {b} days (p. " + ", ".join(str(f["page"]) for f in found
                                                  if f["kind"] in kinds and
                                                  (f["days"], f["basis"]) ==
                                                  (d, b)) + ")"
                for (d, b) in cnt if (d, b) != (days, basis))
            out["conflicts"].append(
                f"The specs disagree on the time to "
                f"{'Substantial' if 'substantial' in kinds else 'Final'} "
                f"Completion: {days} {basis} days (p. "
                f"{', '.join(map(str, pages_))}) vs {other}.")
        return {"days": days, "basis": basis, "pages": pages_}
    out["substantial"] = pick(("substantial",))
    out["final"] = pick(("final", "total"))
    fa = [f for f in found if f["kind"] == "final_after"]
    out["final_after_substantial"] = Counter(
        f["days"] for f in fa).most_common(1)[0][0] if fa else None
    for k in ("substantial_date", "final_date", "total_date"):
        ds = sorted({f["date"] for f in found if f["kind"] == k})
        if ds:
            out["dates"][k.replace("total", "final").replace("_date", "")] = \
                ds[-1]
    if lds:
        cnt = Counter(v for v, _p, _t in lds)
        out["ld_per_day"] = cnt.most_common(1)[0][0]
        out["ld_pages"] = sorted({p for v, p, _t in lds
                                  if v == out["ld_per_day"]})
        if len(cnt) > 1:
            out["conflicts"].append(
                "Liquidated damages are stated differently: " +
                ", ".join(f"${v:,.2f} (p. {p})" for v, p, _t in lds))
    else:
        out["ld_per_day"], out["ld_pages"] = None, []
    return out


def _kind(before):
    """Substantial / final / total from the nearest such words before a
    number ("...substantially complete ... and fully complete within 180
    days" -> final)."""
    b = before.lower()
    subs = b.rfind("substantial")
    fin = max(b.rfind("final"), b.rfind("fully"))
    if subs < 0 and fin < 0:
        return "total"
    return "substantial" if subs > fin else "final"


def _parse_long_date(t):
    t = re.sub(r"\s+", " ", t.replace(",", " ").replace(".", " ")).strip()
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def spec_pages(doc, first=None):
    """[(page 1-based, text)] of a spec book. The contract time lives in
    the front (bid form, agreement, Divisions 00 and 01): `first` pages
    only when given."""
    n = doc.page_count if first is None else min(first, doc.page_count)
    out = []
    for i in range(n):
        try:
            out.append((i + 1, doc[i].get_text()))
        except Exception:
            continue
    return out


def contract_dates(ct, ntp, cal=None):
    """Required Substantial / Final Completion dates from Notice to
    Proceed. Calendar days count every day; working days skip weekends
    (and the calendar's holidays)."""
    def add(days, basis):
        if basis == "working" and cal is not None:
            return cal.date(cal.index(ntp) + days - 1)
        if basis == "working":
            d, n = ntp, days
            while n > 1:
                d += _dt.timedelta(days=1)
                if d.weekday() < 5:
                    n -= 1
            return d
        return ntp + _dt.timedelta(days=days - 1)
    out = {}
    if ct.get("dates", {}).get("substantial"):
        out["substantial"] = _dt.date.fromisoformat(ct["dates"]["substantial"])
    elif ct.get("substantial"):
        out["substantial"] = add(ct["substantial"]["days"],
                                 ct["substantial"]["basis"])
    if ct.get("dates", {}).get("final"):
        out["final"] = _dt.date.fromisoformat(ct["dates"]["final"])
    elif ct.get("final"):
        out["final"] = add(ct["final"]["days"], ct["final"]["basis"])
    if "substantial" in out and ct.get("final_after_substantial") and \
            "final" not in out:
        out["final"] = out["substantial"] + _dt.timedelta(
            days=ct["final_after_substantial"])
    if "final" in out and "substantial" not in out:
        out["substantial"] = out["final"]       # one date for both
    return out


# ------------------------------------------------------------- scope
_DISC = [("FP", "fire_supp"), ("FA", "fire_alarm"), ("C", "civil"),
         ("L", "landscape"), ("S", "structural"), ("A", "architectural"),
         ("M", "hvac"), ("P", "plumbing"), ("E", "electrical"),
         ("F", "fire_supp"), ("T", "technology"), ("D", "demolition")]
_DIVS = {"02": "demolition", "03": "concrete", "04": "masonry",
         "05": "steel", "06": "wood", "07": "roofing", "08": "openings",
         "09": "finishes", "10": "specialties", "11": "equipment",
         "12": "furnishings", "13": "special", "14": "conveying",
         "21": "fire_supp", "22": "plumbing", "23": "hvac",
         "26": "electrical", "27": "technology", "28": "fire_alarm",
         "31": "civil", "32": "paving", "33": "utilities"}


_TITLE_DISC = [(re.compile(r"\bPLUMBING\b"), "plumbing"),
               (re.compile(r"\b(?:MECHANICAL|HVAC)\b(?! DEMOLITION)"),
                "hvac"),
               (re.compile(r"\b(?:ELECTRICAL|LIGHTING|POWER) "
                           r"(?:PLAN|PLANS|LAYOUT)\b"), "electrical"),
               (re.compile(r"\bFIRE (?:SPRINKLER|PROTECTION|SUPPRESSION)|"
                           r"\bSPRINKLER PLAN"), "fire_supp"),
               (re.compile(r"\bFIRE ALARM\b"), "fire_alarm")]


_WAREHOUSE = re.compile(r"\bWAREHOUSE|DISTRIBUTION (?:CENTER|FACILITY|"
                        r"BUILDING)|\bINDUSTRIAL\b|MANUFACTURING (?:BUILDING|"
                        r"FACILITY|PLANT)|SELF[- ]STORAGE|\bFLEX (?:SPACE|"
                        r"BUILDING)|LOGISTICS (?:CENTER|BUILDING)", re.I)
MEP_MISSING_NOTE = ("MEP sheets not in this set - rows kept from the "
                    "template; check the scope.")
_MEP = ("plumbing", "hvac", "electrical")
# the roof structure's long-lead item (schedule_types._item_of): a house
# or small wood building gets trusses unless the set names steel joists
_RESIDENTIAL = re.compile(r"\bRESIDENCE|SINGLE[- ]FAMILY|\bDWELLING|"
                          r"\bBEDROOMS?\b|\bHOUSE\b|\bDUPLEX|TOWNHOM",
                          re.I)
# Generate Set's own self-check lines on its cover sheet (genset/audit.py)
# name bedrooms and the house whatever the building is: they are not
# evidence of a residence (review 0.12.39 #1 - every generated commercial
# set read as a house: trusses and wood framing)
_SELF_CHECK = re.compile(r"No walking through bedrooms(?:,? baths)?(?: or "
                         r"service rooms)?|Garage door opens into the house"
                         r"(?: \(not a bedroom or bath\))?", re.I)
# the Generate Set plan's own building type (its .genset.json)
GENSET_RESIDENTIAL = ("single_family",)


def genset_building_type(gs):
    """The building type a Generate Set plan says it is ("warehouse",
    "single_family"...), or None when there is no plan or it names none."""
    plan = (gs or {}).get("plan") if isinstance(gs, dict) else None
    if not isinstance(plan, dict):
        return None
    bt = (plan.get("project") or {}).get("building_type") or \
        (plan.get("fields") or {}).get("building_type")
    return str(bt) if bt else None


def residential_text(texts):
    """True when the drawing text reads as a house, the set's self-check
    lines left out."""
    return bool(_RESIDENTIAL.search(" ".join(
        _SELF_CHECK.sub(" ", re.sub(r"\s+", " ", str(x))) for x in texts)))


_JOISTS = re.compile(r"STEEL (?:ROOF )?JOISTS?|BAR JOISTS?|OPEN[- ]WEB|"
                     r"JOIST SCHEDULE|JOIST GIRDERS?|\b\d{1,2}K\d{1,2}\b|"
                     r"\b\d{2}LH\d{2}\b", re.I)


def scope(sheets=None, divisions=(), area_sf=None, takeoff=(), stories=1,
          sections=None, texts=None, project_type=None, lead_weeks=None,
          rooms=None, genset=None):
    """Flags for what the job includes, plus the numbers that size it.
    sheets: rows from sheets.scan ({number, title}); divisions: CSI
    division numbers in the spec book; takeoff: annotate.takeoff_items.
    sections: spec sections [{number, title}] (find_sections / the TOC);
    texts: lines of drawing text (cover, general notes, schedules).
    rooms: the room tags counted for the area ([{name, sf}]); genset: a
    Generate Set set's own data ({"rows": quantity rows, "plan": its
    .genset.json, "source": what was read}) - read_genset().

    The project type is detected from all of it (schedule_types.detect) -
    with the evidence kept - unless `project_type` names it. Nothing
    recognized: type "unknown", never an assumed building."""
    flags = set()
    for r in sheets or []:
        no = (r.get("number") or "").upper().strip()
        title = (r.get("title") or "").upper()
        for pre, flag in _DISC:
            if re.match(rf"^{pre}[-\d]", no):
                flags.add(flag)
                break
        if "DEMO" in title:
            flags.add("demolition")
        # a small set draws the trades on A-sheets ("A-6 ELECTRICAL PLAN")
        for rx, flag in _TITLE_DISC:
            if rx.search(title):
                flags.add(flag)
        if re.search(r"\bPAVING|PAVEMENT|PARKING", title):
            flags.add("paving")
        if re.search(r"UTILIT|SEWER|WATER|STORM|DRAINAGE", title):
            flags.add("utilities")
        if re.search(r"LANDSCAP|PLANTING|IRRIGAT", title):
            flags.add("landscape")
    secs = [s if isinstance(s, dict) else
            {"number": s[0], "title": s[1] if len(s) > 1 else ""}
            for s in (sections or ())]
    divs = {str(d)[:2] for d in divisions or ()} | \
        {str(s.get("number") or "")[:2] for s in secs
         if str(s.get("number") or "")[:2].isdigit()}
    for d in sorted(divs):
        f = _DIVS.get(d)
        if f:
            flags.add(f)
    if flags & {"concrete", "masonry", "steel", "wood"}:
        flags.add("structural")
    if flags & {"finishes", "openings", "roofing", "specialties"}:
        flags.add("architectural")
    if flags & {"utilities", "paving"}:
        flags.add("civil")
    pipe_lf = 0.0
    for it in takeoff or ():
        g = (it.get("group") or "").lower()
        if it.get("type") == "length" and re.search(
                r"sewer|sanitary|water|storm|pipe|drain|force main", g) and \
                "existing" not in g:
            pipe_lf += float(it.get("value") or 0)
    if pipe_lf:
        flags.add("utilities")
    texts = [t for t in (texts or ()) if str(t).strip()]
    equip = _types.equipment(
        texts + [r.get("title") or "" for r in sheets or ()] +
        [f"{s.get('number', '')} {s.get('title', '')}" for s in secs],
        sheets, secs)
    excl = _types.exclusions(texts)
    gone = {k for e in excl if not e.get("only") and not e.get("ofci")
            for k in e["kinds"]}
    gone_trades = {t for e in excl if not e.get("only") and not
                   e.get("ofci") for t in e.get("trades") or ()}
    design = []
    flat = [re.sub(r"\s+", " ", str(t)).strip() for t in texts]
    for i, t in enumerate(flat):    # "MEP design is by others": a note
        if not _types._DESIGN_NOTE.search(t):
            continue
        a = i                       # back to where its sentence starts
        while a > 0 and i - a < 3 and flat[a - 1] and \
                not flat[a - 1].rstrip().endswith((".", ":", ";")) and (
                    flat[a][:1].islower() or re.search(
                        r"(?:[,&/-]|\b(?:and|or|of|the|for|with|by|are|"
                        r"is))\s*$", flat[a - 1], re.I)):
            a -= 1
        t = " ".join(flat[a:i + 1])
        t = re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", t)
        t = next((x for x in t if _types._DESIGN_NOTE.search(x)), t[-1])
        if t[:160] not in design:
            design.append(t[:160])
    owner = {k for e in excl if e.get("ofci") for k in e["kinds"]} - gone
    for e in equip:
        if e["kind"] in gone:          # "... NOT INCLUDED IN THIS CONTRACT"
            e["by_others"] = True
            e["long_lead"] = False
        elif e["kind"] in owner:       # OFCI: the owner buys, we install
            e["ofci"] = True
            e["long_lead"] = False
    det = _types.detect(sheets, secs, texts, sorted(divs), equip)
    evidence_text = [r.get("title") or "" for r in sheets or ()] + \
        [f"{s.get('number', '')} {s.get('title', '')}" for s in secs] + texts
    feats = _types.features(evidence_text, equip, sheets)
    from . import productivity as _prod
    gs = genset if isinstance(genset, dict) else {}
    setq = _prod.set_quantities(gs.get("rows") or (), gs.get("plan"))
    if setq.get("overhead_doors") or _prod.takeoff_quantity(
            "overhead_doors", _prod.FAMILIES["overhead_doors"],
            takeoff or (), _prod.defaults()):
        flags.add("overhead_doors")
    # what the building is: the Generate Set plan's own type when there
    # is one, else the drawing text (without the set's self-check lines)
    gs_type = genset_building_type(gs)
    if gs_type:
        residential = gs_type in GENSET_RESIDENTIAL
        warehouse = gs_type == "warehouse" or bool(_WAREHOUSE.search(
            " ".join(str(x) for x in evidence_text)))
    else:
        residential = residential_text(evidence_text)
        warehouse = bool(_WAREHOUSE.search(" ".join(
            str(x) for x in evidence_text)))
    sc = {"building_flags": flags, "features": feats,
          "excluded_trades": gone_trades, "design_notes": design[:3],
          "rooms": [dict(r) for r in rooms or () if isinstance(r, dict)],
          "warehouse": warehouse, "residential": residential,
          "genset_type": gs_type,
          "joists_named": bool(_JOISTS.search(" ".join(
              [str(x) for x in evidence_text] +
              [str(it.get("group") or "") for it in takeoff or ()
               if isinstance(it, dict)] +
              [str(r[1]) + " " + str(r[4] or "")
               for r in _prod._rows_of(gs.get("rows") or ())]))),
          "set_quantities": setq,
          "genset": {"source": gs.get("source") or "Generate Set"}
          if setq else None,
          "area_sf": float(area_sf) if area_sf else 5000.0,
          "area_found": bool(area_sf), "pipe_lf": pipe_lf,
          "stories": max(1, int(stories or 1)), "equipment": equip,
          "detected": det, "lead_weeks": dict(lead_weeks or {}),
          "scope_items": _types.scope_items(texts), "exclusions": excl,
          "takeoff": [{"group": str(it.get("group") or ""),
                       "type": it.get("type"), "unit": it.get("unit"),
                       "value": it.get("value")} for it in takeoff or ()
                      if isinstance(it, dict)]}
    sc["features"] = set(feats) - gone     # not this contract's work
    return retype(sc, project_type or det["type"],
                  picked=bool(project_type))


def retype(sc, project_type, picked=True):
    """The scope as `project_type` (one of schedule_types.TYPES): its
    flags, evidence and notes. The dialog calls this when the person picks
    a different type."""
    sc = dict(sc)
    det = sc.get("detected") or {"type": _types.UNKNOWN, "why": {},
                                 "ranked": [], "recognized": False}
    t = project_type if project_type in _types.TYPES else _types.UNKNOWN
    bflags = set(sc.get("building_flags") or sc.get("flags") or ())
    feats = set(sc.get("features") or ())
    notes = []
    if t in _types.BUILDING_TYPES or t == "reroof":
        if not sc.get("area_found", True) and not (
                t == "renovation" and len(sc.get("scope_items") or ()) >= 3):
            notes.append("Building area not found on the floor plans - "
                         "assumed 5,000 SF (change it and rebuild).")
    if t in _types.BUILDING_TYPES:
        flags = set(bflags) if t == "new_building" else bflags | feats
        if not flags & {"architectural", "structural", "civil"}:
            flags |= {"architectural", "structural"}
            notes.append("No architectural or structural sheets recognized"
                         " - building trades included because the type "
                         "was set to " + _types.label(t) + ".")
    else:
        flags = bflags | feats
    gone_trades = set(sc.get("excluded_trades") or ())
    flags -= gone_trades                 # "ELECTRICAL WORK BY OTHERS"
    if t == "new_building":
        # a new building has plumbing, HVAC and electrical work even when
        # the set has no MEP sheets ("MEP design by others")
        missing = [m for m in _MEP if m not in flags and m not in
                   gone_trades]
        if missing:
            flags |= set(missing)
            notes.append(MEP_MISSING_NOTE)
    if t == "new_building" and flags & {"plumbing", "electrical"}:
        from . import productivity as _prod
        if _prod.has_bay(sc):
            flags.add("warehouse_bay")    # its own trim row (T8)
    for d in sc.get("design_notes") or ():
        notes.append("Design by others (drawings): " + d + " The work is "
                     "still scheduled.")
    if sc.get("set_quantities"):
        from . import productivity as _prod
        src = (sc.get("genset") or {}).get("source") or "set"
        use, set_floor, gap = _prod.set_area_check(sc)
        area = float(sc.get("area_sf") or 5000.0)
        if not use:
            notes.append(f"Generate Set data ({src}) not used for the "
                         f"quantities: its rooms total {set_floor:,.0f} SF "
                         f"but the floor area is {area:,.0f} SF "
                         f"({gap:.0%} apart) - check the area.")
        else:
            notes.append("Quantities from the Generate Set data (" + src +
                         "): the activities' BASIS says 'genset'.")
            if gap > _prod.SET_AREA_NOTE:
                notes.append(f"Floor area: the Generate Set rooms total "
                             f"{set_floor:,.0f} SF, the drawing text reads "
                             f"{area:,.0f} SF ({gap:.1%} apart) - the set's"
                             " quantities are used.")
    unclear = _types.ambiguous_note(det)
    if t == _types.UNKNOWN and unclear:
        notes.append(unclear)
    elif t == _types.UNKNOWN:
        notes.append("Project type not recognized from the sheets, specs "
                     "or drawing text - pick the project type and build "
                     "again (no building was assumed).")
    elif picked and t != det.get("type"):
        notes.append(f"Project type set to {_types.label(t)} (detected: "
                     f"{_types.label(det.get('type'))}).")
    if sc.get("scanned"):
        notes.append(scanned_note(sc["scanned"]))
    if t == "renovation" and sc.get("scope_items"):
        notes.append(f"{len(sc['scope_items'])} activities from the "
                     "drawings' Description of Work list (durations "
                     "assumed).")
    for e in sc.get("exclusions") or ():
        if e.get("ofci"):
            notes.append("Owner-furnished, contractor-installed (drawings): "
                         + e["text"] + " The installation is scheduled; the "
                         "purchase is the owner's - set the delivery date.")
        elif not e.get("only"):
            notes.append("Not in this contract (drawings): " + e["text"])
    if t != _types.UNKNOWN:
        leads, kinds = [], set()
        for e in sc.get("equipment") or ():
            if e.get("long_lead") and e["kind"] not in kinds and \
                    _types.lead_assumed(sc, e["kind"]):
                kinds.add(e["kind"])
                leads.append(f"{e.get('tag') or e['desc']} "
                             f"{_types.lead_weeks(sc, e['kind']):g} weeks")
        if leads:
            notes.append("Lead times assumed - confirm with the supplier: "
                         + ", ".join(leads) + ".")
        notes.append(_types.STARTING_VALUES_NOTE)
    why = det.get("why") or {}
    evidence = list(why.get(t, []))
    if t == _types.UNKNOWN and unclear:      # both sides of a close call
        evidence = [f"{_types.label(k)}: {w}" for k in det["candidates"]
                    for w in why.get(k, [])[:4]]
    sc.update({"type": t, "type_label": _types.label(t), "flags": flags,
               "evidence": evidence,
               "notes": notes, "building_flags": bflags})
    return sc


def building_area(doc, rows, rooms=None):
    """Floor area from the room tags ("245 SF") on the floor plan sheets:
    the floor plan with the most tagged area (a set often repeats the same
    rooms on several A-sheets), plus other levels' plans. (SF, stories)
    `rooms`, a list, gets the tags ({name, sf}) of the plans counted."""
    from .. import autotakeoff
    best, levels, tags = {}, set(), {}
    for r in rows:
        no, title = (r.get("number") or "").upper(), \
            (r.get("title") or "").upper()
        if not no.startswith("A") or "PLAN" not in title or \
                re.search(r"ROOF|REFLECTED|CEILING|ENLARGED|SITE|DEMO",
                          title):
            continue
        try:
            found = [t for t in autotakeoff.room_tags(doc[r["page"]])
                     if t.get("sf")]
            sf = sum(t["sf"] for t in found)
        except Exception:
            continue
        if not sf:
            continue
        m = re.search(r"(SECOND|2ND|THIRD|3RD|FOURTH|4TH|LEVEL\s*[2-9]|"
                      r"MEZZANINE|UPPER|BASEMENT)", title)
        key = m.group(1) if m else "FIRST"
        levels.add(key)
        if sf > best.get(key, 0):
            best[key] = sf
            tags[key] = [{"name": str(t.get("name") or ""),
                          "sf": float(t["sf"])} for t in found]
    if rooms is not None:
        for k in sorted(tags):
            rooms.extend(tags[k])
    return (sum(best.values()) or None), max(1, len(levels))


# ------------------------------------------------------------- template
# (key, phase, name, needs (any; empty = always), duration(f, s), preds)
# f = building area / 1000 SF; s = the scope dict. preds: "key", or
# "key:SS+3" style.


PHASES = ["Preconstruction", "Sitework", "Foundations", "Structure",
          "Envelope", "Rough-ins", "Interiors", "MEP Trim & Startup",
          "Site Finishes", "Closeout"]

TEMPLATE = [
    ("ntp", "Preconstruction", "Notice to Proceed", (), lambda f, s: 0, []),
    ("submittals", "Preconstruction", "Submittals & procurement", (),
     lambda f, s: 20, ["ntp"]),
    ("permit", "Preconstruction", _types.PERMIT_NAME, (),
     lambda f, s: 10, ["ntp"]),
    ("trade_permits", "Preconstruction", _types.trade_permits_name,
     ("plumbing", "hvac", "electrical", "fire_supp"), lambda f, s: 3,
     ["permit"]),
    ("mobilize", "Preconstruction", "Mobilize & temporary facilities", (),
     lambda f, s: 5, ["permit"]),
    ("layout", "Preconstruction", "Survey & layout", (),
     lambda f, s: 2, ["mobilize"]),
    ("demo", "Sitework", "Demolition", ("demolition",),
     lambda f, s: 5 + 2 * f, ["mobilize"]),
    ("erosion", "Sitework", "Erosion control (SWPPP)", ("civil",),
     lambda f, s: 3, ["mobilize"]),
    ("clearing", "Sitework", "Clearing & grubbing", ("civil",),
     lambda f, s: 4, ["erosion", "demo"]),
    ("grading", "Sitework", "Mass grading & building pad", ("civil",),
     lambda f, s: 8 + f, ["clearing"]),
    # lead-ins (schedule_types.LEAD_INS): the real work a lag used to
    # stand for - DCMA point 3 wants lags on <= 5% of the links
    ("util_layout", "Sitework", _types.UTIL_LAYOUT_NAME, ("utilities",),
     lambda f, s: 3, ["grading:SS"]),
    ("utilities", "Sitework", "Underground utilities", ("utilities",),
     lambda f, s: max(8, s["pipe_lf"] / 80), ["util_layout"]),
    ("footings", "Foundations", "Footings & foundations",
     ("structural", "architectural"), lambda f, s: 8 + 2 * f,
     ["grading", "layout"]),
    ("footing_insp", "Foundations", "Footing & foundation inspection",
     ("structural", "architectural"), lambda f, s: 1, ["footings"]),
    ("underslab", "Foundations", _types.without_electrical(
        "Under-slab plumbing & electrical", "Under-slab plumbing",
        "Under-slab electrical"),
     ("plumbing", "electrical"), lambda f, s: 4 + f,
     ["footings", "trade_permits"]),
    ("slab", "Foundations", "Slab on grade", ("structural", "architectural"),
     lambda f, s: 4 + f, ["footing_insp", "underslab"]),
    ("structure", "Structure", "Structure (framing / masonry / steel)",
     ("structural", "architectural"),
     lambda f, s: 10 + 4 * f + 5 * (s["stories"] - 1),
     ["slab", "submittals"]),
    ("roofstruct", "Structure", "Roof structure & deck",
     ("structural", "architectural"), lambda f, s: 4 + f, ["structure"]),
    ("roofing", "Envelope", "Roofing", ("roofing", "architectural"),
     lambda f, s: 5 + f, ["roofstruct"]),
    ("ext_mockup", "Envelope", "Exterior wall mock-up & review",
     ("architectural",), lambda f, s: 5, ["structure:SS"]),
    ("exterior", "Envelope", "Exterior walls & finishes", ("architectural",),
     lambda f, s: 10 + 3 * f, ["ext_mockup"]),
    ("win_mockup", "Envelope", "Window mock-up & field water test",
     ("openings", "architectural"), lambda f, s: 5, ["exterior:SS"]),
    ("windows", "Envelope", "Windows & exterior doors",
     ("openings", "architectural"), lambda f, s: 5 + f, ["win_mockup"]),
    # only when the set counts them (Generate Set's dock / drive-in doors,
    # a takeoff count): the "overhead_doors" flag
    ("oh_doors", "Envelope", _types.overhead_doors_name, ("overhead_doors",),
     lambda f, s: 2, ["exterior"]),
    ("driedin", "Envelope", "Building dried in", ("architectural",),
     lambda f, s: 0, ["roofing", "windows", "oh_doors"]),
    ("plumb_rough", "Rough-ins", "Plumbing rough-in", ("plumbing",),
     lambda f, s: 6 + 2 * f, ["roofstruct", "trade_permits"]),
    ("hvac_rough", "Rough-ins", "HVAC rough-in & ductwork", ("hvac",),
     lambda f, s: 8 + 2 * f, ["roofstruct", "trade_permits"]),
    ("elec_rough", "Rough-ins", "Electrical rough-in", ("electrical",),
     lambda f, s: 8 + 2 * f, ["roofstruct", "trade_permits"]),
    ("fs_rough", "Rough-ins", "Fire sprinkler rough-in", ("fire_supp",),
     lambda f, s: 5 + f, ["roofstruct", "trade_permits"]),
    ("lv_boxes", "Rough-ins", _types.LV_BOXES_NAME,
     ("fire_alarm", "technology"), lambda f, s: 3, ["elec_rough:SS"]),
    ("fa_rough", "Rough-ins", "Fire alarm & low voltage rough-in",
     ("fire_alarm", "technology"), lambda f, s: 4 + f, ["lv_boxes"]),
    ("inspect", "Rough-ins", "Rough-in inspections", (),
     lambda f, s: 3, ["plumb_rough", "hvac_rough", "elec_rough", "fs_rough",
                      "fa_rough", "driedin"]),
    ("insulation", "Interiors", "Insulation", ("architectural",),
     lambda f, s: 3 + f / 2, ["inspect"]),
    ("drywall", "Interiors", "Drywall hang, tape & finish",
     ("finishes", "architectural"), lambda f, s: 10 + 3 * f,
     ["insulation"]),
    ("ceilings", "Interiors", "Ceilings", ("finishes", "architectural"),
     lambda f, s: 5 + f, ["drywall"]),
    ("paint", "Interiors", "Painting", ("finishes", "architectural"),
     lambda f, s: 6 + 2 * f, ["drywall"]),
    ("flooring", "Interiors", "Flooring", ("finishes", "architectural"),
     lambda f, s: 5 + 2 * f, ["paint", "ceilings"]),
    ("doors", "Interiors", "Doors, frames & hardware",
     ("openings", "architectural"), lambda f, s: 4 + f, ["paint"]),
    ("casework", "Interiors", "Casework, specialties & accessories",
     ("specialties", "architectural"), lambda f, s: 5 + f, ["paint"]),
    ("equipment", "Interiors", "Equipment", ("equipment",),
     lambda f, s: 5, ["flooring"]),
    ("mep_trim", "MEP Trim & Startup", _types.without_electrical(
        "Plumbing & electrical trim", "Plumbing trim", "Electrical trim"),
     ("plumbing", "electrical"), lambda f, s: 6 + f, ["paint"]),
    # a warehouse bay's lights, devices and connections: after the rough-in
    # inspections, beside the office finishes (not behind the office
    # paint - review 0.12.38 T8); the "warehouse_bay" flag (retype)
    ("bay_trim", "MEP Trim & Startup", "Warehouse bay MEP trim - lights, "
     "devices & connections", ("warehouse_bay",), lambda f, s: 6 + f,
     ["inspect"]),
    ("hvac_start", "MEP Trim & Startup", "HVAC startup, test & balance",
     ("hvac",), lambda f, s: 5, ["mep_trim", "bay_trim", "ceilings"]),
    ("fa_final", "MEP Trim & Startup", "Fire alarm & sprinkler testing",
     ("fire_alarm", "fire_supp"), lambda f, s: 3, ["mep_trim", "bay_trim"]),
    ("paving", "Site Finishes", "Curb, paving & sidewalks",
     ("paving", "civil"), lambda f, s: 8 + f, ["utilities", "exterior"]),
    ("landscape", "Site Finishes", "Landscaping & seeding",
     ("landscape", "civil"), lambda f, s: 6, ["paving"]),
    ("striping", "Site Finishes", "Striping, signage & site cleanup",
     ("paving", "civil"), lambda f, s: 3, ["landscape"]),
    ("punch", "Closeout", "Punch list & corrections", (),
     lambda f, s: 10, ["flooring", "doors", "casework", "equipment",
                       "mep_trim", "hvac_start", "fa_final", "striping"]),
    ("co", "Closeout", "Final inspections & certificate of occupancy", (),
     lambda f, s: 5, ["punch"]),
    ("sc", "Closeout", "Substantial Completion", (), lambda f, s: 0,
     ["co"]),
    ("clean", "Closeout", "Final cleaning", (), lambda f, s: 3, ["sc"]),
    ("closeout", "Closeout", "Closeout documents, O&Ms & warranties", (),
     lambda f, s: 10, ["sc"]),
    ("fc", "Closeout", "Final Completion", (), lambda f, s: 0,
     ["clean", "closeout"]),
]


def template_for(sc):
    """The activity tuples for the scope's project type: TEMPLATE for a
    new building (and for an old scope with no type), the type's own list
    otherwise (schedule_types), each with procurement for long-lead
    equipment."""
    t = sc.get("type") or "new_building"
    return _types.template(t, sc, TEMPLATE)


def plan(sc, table=None):
    """The activities for a scope: [{key, phase, name, duration, preds:
    [(key, type, lag)], basis, family, quantity_driven}], links to
    activities left out are passed through to what they depended on.

    Duration: an activity with a production-rate family (productivity.py)
    is quantity / (rate x crews), within the family's min and max; one
    without keeps its template duration - fixed, or for one that grew with
    the area, its 5,000 SF duration x (area / 5,000)^0.5. `basis` says
    which, with the numbers. `table`: productivity.load() by default."""
    from . import productivity as _prod
    table = table or _prod.load()
    flags = sc["flags"]
    f = sc["area_sf"] / 1000.0
    tkey = sc.get("type") or "new_building"
    est = _prod.estimates(sc, table)
    tmpl = template_for(sc)
    keep = {}
    for key, phase, name, needs, dur, preds in tmpl:
        if needs and not set(needs) & flags:
            continue
        d, basis, fam = _duration(tkey, key, dur, f, sc, table, est)
        src = _source(d, basis, fam, sc)
        own = _types.chain_basis(key, sc, d)    # a set item's procurement
        if own:
            basis, src = own
        keep[key] = {"key": key, "phase": phase,
                     "name": name(sc) if callable(name) else name,
                     "duration": d, "basis": basis, "family": fam,
                     "quantity_driven": fam is not None, "source": src,
                     "raw_preds": preds}
    allp = {k: p for k, _ph, _n, _nd, _d, p in tmpl}
    # a lead-in only stands between its work and the trade that follows:
    # without either it goes, and the links pass through it
    for key in [k for k in keep if k in _types.LEAD_INS]:
        src = keep[key]["raw_preds"][0].partition(":")[0]
        used = any(key in [r.partition(":")[0] for r in a["raw_preds"]]
                   for k, a in keep.items() if k != key)
        if src not in keep or not used:
            del keep[key]

    def resolve(ref, seen=()):
        k, _, rest = ref.partition(":")
        if k in keep:
            return [(k, rest)]
        out = []
        for r in allp.get(k, []):
            if r.split(":")[0] not in seen:
                # through a lead-in that isn't scheduled: the work after it
                # waits on the finish of the work it led into, not on the
                # start (no start-to-start link made up - review T10)
                if k in _types.LEAD_INS:
                    r = r.partition(":")[0]
                out += resolve(r, seen + (k,))
        return out
    for a in keep.values():
        links = []
        for ref in a["raw_preds"]:
            for k, rest in resolve(ref):
                m = re.match(r"^(FS|SS|FF|SF)?([+-]\d+)?$", rest or "")
                t = (m.group(1) if m and m.group(1) else "FS")
                lag = int(m.group(2)) if m and m.group(2) else 0
                if k != a["key"] and (k, t, lag) not in links:
                    links.append((k, t, lag))
        a["preds"] = links
    clean_links(keep)
    return list(keep.values())


def clean_links(acts):
    """Drop the links the logic doesn't need (review 0.12.35 T10): a
    second link to the same predecessor (the finish-to-start one is kept),
    and a plain finish-to-start link A -> C when C already waits on A
    through another finish-to-start chain (A -> B -> C). `acts`: {key:
    {"preds": [(key, type, lag)]}}, changed in place."""
    for a in acts.values():
        by = {}
        for k, t, lag in a["preds"]:
            old = by.get(k)
            if old is None or (t == "FS" and (old[1] != "FS" or
                                              lag > old[2])):
                by[k] = (k, t, lag)
        a["preds"] = [by[k] for k in dict.fromkeys(k for k, _t, _l in
                                                   a["preds"])]
    memo = {}

    def before(k, path=()):
        """Every activity k waits on through FS links with no lead."""
        if k in memo:
            return memo[k]
        out = set()
        for p, t, lag in (acts.get(k) or {}).get("preds", ()):
            if t == "FS" and lag >= 0 and p not in path:
                out.add(p)
                out |= before(p, path + (k,))
        memo[k] = out
        return out
    for a in acts.values():
        fs = [p for p, t, lag in a["preds"] if t == "FS" and lag >= 0]
        drop = {p for p in fs for q in fs if q != p and p in before(q)}
        if drop:
            a["preds"] = [x for x in a["preds"] if not (
                x[0] in drop and x[1] == "FS" and x[2] == 0)]
    return acts


BASE_KSF = 5.0          # a job this size (5,000 SF) keeps its durations

# where an activity's duration (or, for a procurement chain, its scope)
# comes from - the "SOURCE:" line of its Notes (review T5)
SOURCES = ("genset", "takeoff", "estimate", "area_assumed", "fixed",
           "milestone")
MEASURED_SOURCES = ("genset", "takeoff", "estimate")


def _source(d, basis, fam, sc):
    """One of SOURCES for an activity's duration: the Generate Set
    quantities, the takeoff, an estimate from the floor area read off the
    plans - or from the assumed 5,000 SF ("area_assumed"); "fixed" for a
    duration the template sets; "milestone"."""
    b = basis or ""
    if d == 0 and b.startswith("milestone"):
        return "milestone"
    if "(genset:" in b or b.startswith("genset:"):
        return "genset"
    if "(takeoff" in b or b.startswith("takeoff"):
        return "takeoff"
    if fam is not None or "(no production rate" in b:
        return "estimate" if sc.get("area_found", True) else \
            "area_assumed"
    return "fixed"


def _duration(tkey, key, dur, f, sc, table, est):
    """(days, basis, family or None) for one template activity."""
    from . import productivity as _prod
    now = max(0.0, float(dur(f, sc)))
    at_base = max(0.0, float(dur(BASE_KSF, sc)))
    at_twice = max(0.0, float(dur(2 * BASE_KSF, sc)))
    if now == 0 and at_base == 0 and at_twice == 0:
        return 0, "milestone (0 d)", None
    sized = _prod.size(tkey, key, sc, table, est)
    if sized:
        return sized["duration"], sized["basis"], sized["family"]
    if abs(at_twice - at_base) < 1e-9:              # not sized by area
        d = int(round(now))
        return d, f"fixed {d} d", None
    # grew linearly with the area: square-root scaling from 5,000 SF
    d = max(1, int(round(at_base * math.sqrt(max(f, 0.0) / BASE_KSF))))
    return d, (f"{at_base:g} d at 5,000 SF x ({f * 1000:,.0f} SF / 5,000 "
               f"SF)^0.5 = {d} d (no production rate - assumed)"), None


def basis_summary(acts):
    """"28 of 42 activities sized from quantities ..." for the report."""
    n = len(acts)
    q = sum(1 for a in acts if a.get("quantity_driven"))
    tk = sum(1 for a in acts if a.get("quantity_driven") and
             "takeoff:" in (a.get("basis") or ""))
    gs = sum(1 for a in acts if a.get("quantity_driven") and
             "genset:" in (a.get("basis") or ""))
    return (f"Durations: {q} of {n} activities sized from quantities / "
            f"(production rate x crews)" +
            (f", {tk} of them from the takeoff" if tk else "") +
            (f", {gs} from the Generate Set quantities" if gs else "") +
            "; the rest are fixed or milestones. Each activity's Notes "
            "give its basis; the rates are assumed starting values - "
            "change them in Production Rates.")


# ------------------------------------------------------------- build
def build(store, sc, ntp, ct=None, replace=False, holidays=True):
    """Write the draft into the project's schedule (phases as summary
    rows). Returns {"activities": n, "report": [...], "fit": {...}}.
    With `holidays`, a schedule without any gets the usual construction
    holidays (specs usually say the time excludes them)."""
    old = store.list("activity")
    if old and not replace:
        raise ValueError("This project already has a schedule. Build into "
                         "a new schedule, or replace this one.")
    for a in old:
        store.delete("activity", a["_id"])
    store.set_setting("project_start", ntp.isoformat())
    if holidays and not store.setting("holidays"):
        store.set_setting("holidays", default_holidays(
            ntp, ntp + _dt.timedelta(days=3 * 365)))
    acts = plan(sc)
    phase_rec = {}
    by_key = {}
    seq = 1.0
    for a in acts:
        ph = a["phase"]
        if ph not in phase_rec:
            phase_rec[ph] = store.save_record("activity", {
                "name": ph, "seq": seq, "status": "Not Started",
                "auto": "plans"})
            seq += 1
        kids = sum(1 for r in by_key.values() if r.get("parent") ==
                   phase_rec[ph]["_id"])
        rec = store.save_record("activity", {
            "name": a["name"], "duration": a["duration"], "seq": kids + 1.0,
            "parent": phase_rec[ph]["_id"], "status": "Not Started",
            "area": ph, "auto": "plans", "basis": a.get("basis") or "",
            "family": a.get("family") or "",
            "source": a.get("source") or "",
            "notes": "BASIS: " + (a.get("basis") or "") +
            ("\nSOURCE: " + a["source"] if a.get("source") else "")})
        by_key[a["key"]] = rec
    for a in acts:
        rec = store.get("activity", by_key[a["key"]]["_id"])
        rec["preds"] = [{"id": by_key[k]["_no"], "type": t, "lag": lag}
                        for k, t, lag in a["preds"] if k in by_key]
        if rec["preds"]:
            store.save_record("activity", rec)
    _contract_notes(store, by_key, ct or {}, ntp)
    report = list(sc.get("notes") or []) + [basis_summary(acts)]
    fitr = fit_check(store, ct or {}, ntp)
    return {"activities": len(acts), "report": report, "fit": fitr,
            "basis": basis_summary(acts),
            "keys": {k: r["_id"] for k, r in by_key.items()}}


def _contract_notes(store, by_key, ct, ntp):
    """The contract's Substantial / Final Completion (days from the specs,
    with their pages, and the date from NTP) in those milestones' notes."""
    if not ct:
        return
    try:
        req = contract_dates(ct, ntp, schedule.calendar(store, ntp))
    except Exception:                                     # noqa: BLE001
        req = contract_dates(ct, ntp)
    for key, kind, label in (("sc", "substantial", "Substantial"),
                             ("fc", "final", "Final")):
        if key not in by_key or kind not in req:
            continue
        got = ct.get(kind) or {}
        if (ct.get("dates") or {}).get(kind):
            what = f"{ct['dates'][kind]} in the specs"
        elif got.get("days"):
            pg = ", ".join(map(str, got.get("pages") or ()))
            what = (f"{got['days']} {got['basis']} days from Notice to "
                    "Proceed" + (f" (spec p. {pg})" if pg else ""))
        elif kind == "final" and ct.get("final_after_substantial"):
            what = (f"{ct['final_after_substantial']} days after Substantial"
                    " Completion")
        else:
            what = "the contract time (one date for both)"
        rec = store.get("activity", by_key[key]["_id"])
        rec["contract_date"] = req[kind].isoformat()
        rec["notes"] = (rec.get("notes") or "").rstrip() + \
            f"\nCONTRACT: {label} Completion {what} = {req[kind]:%b %d, %Y}."
        store.save_record("activity", rec)


def _milestone(store, name):
    cpm = schedule.compute(store, ntp_or_today(store))
    return next((r for r in cpm["rows"] if r.get("name") == name), None), \
        cpm


def ntp_or_today(store):
    """Plan from Notice to Proceed: the status date is the NTP when that's
    still ahead, so nothing gets pushed to today."""
    ps = schedule._d(store.setting("project_start"))
    today = _dt.date.today()
    return ps if ps and ps > today else today


def fit_check(store, ct, ntp):
    """Predicted Substantial / Final Completion against the contract."""
    sc_row, cpm = _milestone(store, "Substantial Completion")
    fc_row = next((r for r in cpm["rows"] if r.get("name") ==
                   "Final Completion"), None)
    req = contract_dates(ct, ntp, cpm["cal"]) if ct else {}
    out = {"predicted_substantial": sc_row["ef"] if sc_row else None,
           "predicted_final": fc_row["ef"] if fc_row else None,
           "required_substantial": req.get("substantial"),
           "required_final": req.get("final")}
    for k in ("substantial", "final"):
        p, r = out[f"predicted_{k}"], out[f"required_{k}"]
        out[f"{k}_days_spare"] = (r - p).days if p and r else None
    return out


# procurement and lead-time rows: submittals, review & approval,
# fabricate & deliver, procure, owner deliveries. Fit to Contract leaves
# them alone - an approval period or a supplier's lead time doesn't get
# shorter because the work has to (review finding 11).
_LEAD_NAME = re.compile(
    r"^\s*(submit|submittal|review\s*&\s*approve|fabricat|procure|"
    r"owner\s+deliver|utility\s+work\s+order)|lead\s*time|long\s+lead|"
    r"\bOFCI\b|- fabricate\b", re.I)
FIT_TAG = "FIT:"
_FIT_FROM = re.compile(r"^FIT: cut from (\d+) d\b")


def is_lead_row(a):
    """A procurement / lead-time activity (not squeezed by fit())."""
    return (a.get("area") or "").strip().lower() == "procurement" or \
        bool(_LEAD_NAME.search(a.get("name") or ""))


def _fit_note(notes, line):
    """`notes` with its Fit to Contract line (if any) replaced by `line`,
    everything else - BASIS, SOURCE, CONTRACT, the PM's own text - kept.
    Also drops the old whole-note form "... by Fit to Contract."."""
    keep = [x for x in (notes or "").splitlines()
            if not x.startswith(FIT_TAG) and
            not (x.startswith("BASIS:") and
                 x.rstrip().endswith("by Fit to Contract."))]
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep + [line])


def _fit_from(notes, now):
    """The duration before the first Fit to Contract (kept across rounds
    and repeated fits)."""
    for x in (notes or "").splitlines():
        m = _FIT_FROM.match(x)
        if m:
            return int(m.group(1))
    return now


def driving_path(cpm, end_id):
    """The rows that drive `end_id`'s start, back to the start of the job
    (each step the predecessor whose link sets the start), `end_id` first.
    `cpm`: schedule.compute()."""
    by = {r["_id"]: r for r in cpm["rows"]}
    out, seen, i = [], set(), end_id
    while i in by and i not in seen:
        seen.add(i)
        r = by[i]
        out.append(r)
        n, es = r.get("dur") or 0, r.get("es_i")
        nxt, best = None, None
        for p, t, lag in r.get("links") or ():
            q = by.get(p)
            if q is None:
                continue
            got = {"FS": q["ef_i"] + lag, "SS": q["es_i"] + lag,
                   "FF": q["ef_i"] + lag - n}.get(t, q["es_i"] + lag - n)
            # two links setting the start: follow the lead-time row (the
            # work beside it can't make the start earlier), else the later
            rank = (is_lead_row(q), q["ef_i"])
            if got == es and (nxt is None or rank > best):
                nxt, best = p, rank
        i = nxt
    return out


LEAD_DRIVES = ("Lead time on {row} drives the finish - Fit to Contract "
               "can't reach the target without changing it.")


def fit(store, target, ntp, rounds=6):
    """Squeeze the work (not the milestones, summaries or procurement and
    lead-time rows - is_lead_row) so Substantial Completion lands on or
    before `target`. Returns the new predicted date; fit_result() also
    says why it stopped short."""
    return fit_result(store, target, ntp, rounds)["finish"]


def fit_result(store, target, ntp, rounds=6):
    """fit(), as {"finish": predicted Substantial Completion, "message":
    None or why the target wasn't reached, "lead_row": the lead-time row
    that drives the finish (or None)}.

    Each round cuts only the work on the current driving path to
    Substantial Completion (driving_path), by the share that path's work
    has to lose, at least 1 day each; work off the path keeps its
    duration. When the driving path is all lead-time rows and milestones
    it stops and names the lead row. Each changed row's Notes keep what
    they said and get one "FIT:" line (the lead rows: that their lead time
    wasn't compressed)."""
    acts = store.list("activity")
    parents = {x.get("parent") for x in acts}
    for a in acts:
        if a["_id"] in parents or schedule._num(a.get("duration")) <= 1 \
                or not is_lead_row(a):
            continue
        line = (f"{FIT_TAG} lead time not compressed by Fit to "
                "Contract - confirm it with the supplier / reviewer.")
        if line not in (a.get("notes") or "").splitlines():
            a["notes"] = _fit_note(a.get("notes"), line)
            store.save_record("activity", a)
    out = {"finish": None, "message": None, "lead_row": None}
    for _ in range(rounds):
        row, cpm = _milestone(store, "Substantial Completion")
        if row is None:
            out["message"] = "No Substantial Completion milestone to fit"
            return out
        out["finish"] = row["ef"]
        if row["ef"] <= target:
            return out
        cal = cpm["cal"]
        need = cal.index(row["ef"]) - cal.index(target)
        path = driving_path(cpm, row["_id"])
        cut = _cuttable(path, parents)
        if not cut:
            out.update(_stopped(path))
            return out
        work = sum(schedule._num(r.get("duration")) for r in cut)
        k = max(0.3, (work - need) / max(1.0, work))
        for r in cut:
            a = store.get("activity", r["_id"])
            n = schedule._num(a.get("duration"))
            was = _fit_from(a.get("notes"), int(round(n)))
            a["duration"] = max(1, int(math.floor(n * k)))
            a["notes"] = _fit_note(
                a.get("notes"), f"{FIT_TAG} cut from {was} d to "
                f"{a['duration']} d by Fit to Contract (the BASIS above is"
                " the uncut estimate).")
            store.save_record("activity", a)
    row, cpm = _milestone(store, "Substantial Completion")
    out["finish"] = row["ef"] if row else None
    if row is not None and row["ef"] > target:
        path = driving_path(cpm, row["_id"])
        if not _cuttable(path, parents):
            out.update(_stopped(path))
    return out


def _cuttable(path, parents):
    """The work rows on a driving path Fit to Contract may shorten."""
    return [r for r in path if not r.get("summary") and
            r["_id"] not in parents and not is_lead_row(r) and
            schedule._num(r.get("duration")) > 1]


def _stopped(path):
    """{"message", "lead_row"} when nothing on the driving path can be cut:
    the longest lead-time row on it drives the finish."""
    leads = [r for r in path if is_lead_row(r) and (r.get("dur") or 0) > 0]
    if leads:
        lead = max(leads, key=lambda r: r.get("dur") or 0)
        return {"lead_row": lead.get("name"),
                "message": LEAD_DRIVES.format(row=lead.get("name"))}
    return {"lead_row": None,
            "message": "The work on the driving path is already at 1 day "
                       "each - Fit to Contract can't reach the target."}


def summary_text(ct, sc, result):
    """What was read and built, for the person to check."""
    lines = []
    if ct and ct.get("substantial"):
        s = ct["substantial"]
        lines.append(f"Substantial Completion: {s['days']} {s['basis']} days"
                     f" (spec p. {', '.join(map(str, s['pages']))}).")
    if ct and ct.get("final"):
        s = ct["final"]
        lines.append(f"Contract / Final Completion: {s['days']} "
                     f"{s['basis']} days (spec p. "
                     f"{', '.join(map(str, s['pages']))}).")
    if ct and ct.get("final_after_substantial"):
        lines.append(f"Final Completion {ct['final_after_substantial']} "
                     "days after Substantial.")
    if ct and ct.get("dates"):
        for k, v in ct["dates"].items():
            lines.append(f"{k.title()} Completion date in the specs: {v}.")
    if ct and not ct.get("substantial") and ct.get("final"):
        lines.append("No separate Substantial Completion time in the specs:"
                     " the contract time is used for both.")
    if ct and not (ct.get("substantial") or ct.get("final") or
                   ct.get("dates")):
        lines.append("No contract time found in the specs - enter it.")
    if ct and ct.get("ld_per_day"):
        lines.append(f"Liquidated damages: ${ct['ld_per_day']:,.2f} per day "
                     f"(p. {', '.join(map(str, ct['ld_pages']))}).")
    for c in (ct or {}).get("conflicts", []):
        lines.append("CHECK: " + c)
    if sc.get("type"):
        ev = sc.get("evidence") or []
        lines.append(f"Project type: {sc.get('type_label')}" +
                     (f" - from {'; '.join(ev[:4])}" if ev else "") + ".")
    eq = [e for e in sc.get("equipment") or ()
          if e.get("tag") and not e.get("by_others")]
    if eq:
        lines.append("Equipment: " + ", ".join(
            f"{e['tag']} ({e['desc']})" for e in eq[:10]) + ".")
    sized = sc.get("type") in (None, "new_building", "renovation", "reroof")
    lines.append(f"Scope: {', '.join(sorted(sc['flags']))}"
                 + (f"; {sc['area_sf']:,.0f} SF, {sc['stories']} level(s)"
                    if sized else "")
                 + (f"; {sc['pipe_lf']:,.0f} LF of pipe taken off" if
                    sc["pipe_lf"] else "") + ".")
    lines += [n for n in sc.get("notes", [])]
    if result.get("basis"):
        lines.append(result["basis"])
    f = result.get("fit") or {}
    if f.get("predicted_substantial"):
        lines.append(f"Draft Substantial Completion: "
                     f"{f['predicted_substantial']:%b %d, %Y}.")
    if f.get("required_substantial"):
        spare = f["substantial_days_spare"]
        lines.append(f"Contract Substantial Completion: "
                     f"{f['required_substantial']:%b %d, %Y} - "
                     + (f"{spare} days to spare." if spare >= 0 else
                        f"RUNS {-spare} DAYS LATE: shorten activities or "
                        "use Fit to Contract."))
    if f.get("required_final") and f.get("predicted_final"):
        spare = f["final_days_spare"]
        lines.append(f"Contract Final Completion: "
                     f"{f['required_final']:%b %d, %Y} - "
                     + (f"{spare} days to spare." if spare >= 0 else
                        f"runs {-spare} days late."))
    return lines


# ------------------------------------------------------------- reading a job
def default_holidays(start, end):
    """The usual construction holidays between two dates: New Year's,
    Memorial Day, July 4, Labor Day, Thanksgiving and the Friday after,
    Christmas Eve and Day (moved off weekends)."""
    out = []
    for y in range(start.year, end.year + 1):
        def nth(month, weekday, n):
            d = _dt.date(y, month, 1)
            while d.weekday() != weekday:
                d += _dt.timedelta(days=1)
            return d + _dt.timedelta(days=7 * (n - 1))

        def last(month, weekday):
            d = _dt.date(y, month + 1, 1) - _dt.timedelta(days=1)
            while d.weekday() != weekday:
                d -= _dt.timedelta(days=1)
            return d

        def observed(d):
            return d - _dt.timedelta(days=1) if d.weekday() == 5 else \
                d + _dt.timedelta(days=1) if d.weekday() == 6 else d
        tg = nth(11, 3, 4)
        days = [observed(_dt.date(y, 1, 1)), last(5, 0),
                observed(_dt.date(y, 7, 4)), nth(9, 0, 1), tg,
                tg + _dt.timedelta(days=1), _dt.date(y, 12, 24),
                observed(_dt.date(y, 12, 25))]
        out += [d for d in days if start <= d <= end and d.weekday() < 5]
    return sorted({d.isoformat() for d in out})


_TEXT_SHEETS = re.compile(r"COVER|TITLE|GENERAL|NOTES|INDEX|SCHEDULE|"
                          r"ONE[- ]LINE|SINGLE[- ]LINE|LEGEND|ABBREV|"
                          r"EQUIPMENT|RISER", re.I)


def drawing_text_pages(rows, first=3, most=15):
    """Pages whose drawing text tells what the job is: the first sheets
    (cover / title sheet / general notes) and the ones titled schedules,
    one-lines, legends or equipment."""
    pages = [r["page"] for r in rows[:first]]
    for r in rows:
        if len(pages) >= most:
            break
        if r["page"] not in pages and _TEXT_SHEETS.search(
                r.get("title") or ""):
            pages.append(r["page"])
    return pages


def scanned_pages(doc, most=400):
    """1-based numbers of the pages with no text (scanned sheets): what's
    on them can't be read into the schedule."""
    out = []
    for i in range(min(len(doc), most)):
        try:
            if len(doc[i].get_text().strip()) < 20:
                out.append(i + 1)
        except Exception:
            continue
    return out


def scanned_note(pages):
    shown = ", ".join(map(str, pages[:12])) + ("..." if len(pages) > 12
                                              else "")
    return (f"{len(pages)} page(s) are scanned images with no text (p. "
            f"{shown}) - their work is NOT in this draft. Run OCR on the "
            "drawings (or add their work by hand) and build again.")


GENSET_MAX_BYTES = 20 * 1024 * 1024


def read_genset(pdf_path=None, doc=None):
    """A Generate Set set's own data for a drawing set: the plan beside it
    (<name>.genset.json), its quantities (<name>.quantities.csv beside it,
    else the rows embedded in the PDF). {"rows", "plan", "source"}, or None
    when the set wasn't made by Generate Set."""
    import csv
    import json
    rows, plan, src = [], None, []
    base = os.path.splitext(pdf_path)[0] if pdf_path else None
    if base and os.path.isfile(base + ".genset.json"):
        try:
            if os.path.getsize(base + ".genset.json") <= GENSET_MAX_BYTES:
                with open(base + ".genset.json", encoding="utf-8") as fh:
                    plan = json.load(fh)
                if isinstance(plan, dict):
                    src.append(os.path.basename(base) + ".genset.json")
                else:
                    plan = None
        except (OSError, ValueError):
            plan = None
    if base and os.path.isfile(base + ".quantities.csv"):
        try:
            with open(base + ".quantities.csv", encoding="utf-8",
                      newline="") as fh:
                for r in list(csv.reader(fh))[1:5000]:
                    if len(r) >= 4:
                        rows.append(tuple(r[:5]))
            if rows:
                src.append(os.path.basename(base) + ".quantities.csv")
        except (OSError, ValueError, csv.Error):
            rows = []
    if not rows and doc is not None:
        try:
            from .. import estimate
            rows = estimate.set_items(doc)
            if rows:
                src.append("the quantities embedded in the PDF")
        except Exception:                                 # noqa: BLE001
            rows = []
    if not rows and plan is not None:
        try:                        # the plan alone: its quantity rows
            from ..genset import quantities as _gq
            rows = list(_gq.rows(plan))
        except Exception:                                 # noqa: BLE001
            rows = []
    if not rows and plan is None:
        return None
    return {"rows": rows, "plan": plan, "source": " and ".join(src) or
            "Generate Set"}


def read_job(plans=None, spec=None, progress=None, project_type=None):
    """Read a drawing set and/or a spec book (fitz documents): contract
    time, project type (with its evidence), equipment, scope and building
    size. {"ct", "scope", "sheets", "divisions", "area_found", "type",
    "evidence", "equipment", "sections", "detected"}."""
    from .. import annotate, sheets as _sheets, specs as _specs
    rows, area, levels, takeoff, divisions = [], None, 1, [], []
    texts, sections, rooms, genset = [], [], [], None
    if plans is not None:
        if progress:
            progress("Reading the sheet index…")
        rows = _sheets.scan(plans, numbers=False)
        name = os.path.splitext(os.path.basename(
            getattr(plans, "name", "") or ""))[0]
        if name:                       # "Fire_Rescue_HQ_Renovations_Plan_Set"
            texts.append(re.sub(r"[_\-]+", " ", name))
        try:
            meta = (plans.metadata or {}).get("title") or ""
        except Exception:
            meta = ""
        if meta.strip():
            texts.append(meta.strip())
        if progress:
            progress("Reading the cover, notes and equipment schedules…")
        for i in drawing_text_pages(rows):
            try:
                texts += _sheets.page_lines(plans[i])
            except Exception:
                continue
        if progress:
            progress("Reading room tags for the building area…")
        area, levels = building_area(plans, rows, rooms)
        try:
            takeoff = annotate.takeoff_items(plans)
        except Exception:
            takeoff = []
        try:
            genset = read_genset(getattr(plans, "name", None), plans)
        except Exception:                                 # noqa: BLE001
            genset = None
    pages = []
    if spec is not None:
        if progress:
            progress("Reading the spec book's sections…")
        try:
            sections = [{"number": s["number"], "title": s["title"]}
                        for s in _specs.find_sections(spec)]
        except Exception:
            sections = []
        if progress:
            progress("Looking for the contract time…")
        pages = spec_pages(spec)
        have = {s["number"][:8] for s in sections}
        # the table of contents names every section, even ones whose
        # first page doesn't start with "SECTION nn nn nn"
        sections += [s for s in _types.toc_sections(
            [t for _p, t in pages[:40]]) if s["number"] not in have]
        for _p, t in pages[:2]:                 # the project manual's cover
            texts += [ln for ln in t.splitlines() if ln.strip() and
                      not _types.toc_sections([ln])][:40]
        divisions = sorted({s["number"][:2] for s in sections})
    ct = contract_time(pages)
    sc = scope(rows, divisions, area, takeoff, levels, sections=sections,
               texts=texts, project_type=project_type, rooms=rooms,
               genset=genset)
    scanned = scanned_pages(plans) if plans is not None else []
    if scanned:
        sc["scanned"] = scanned
        sc = retype(sc, sc["type"], picked=bool(project_type))
    return {"ct": ct, "scope": sc, "sheets": len(rows),
            "divisions": divisions, "area_found": bool(area),
            "type": sc["type"], "evidence": sc["evidence"],
            "equipment": sc["equipment"], "sections": len(sections),
            "detected": sc["detected"]}
