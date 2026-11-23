"""Project assistants (Nov 23, Jon: features like our competitors', built
ourselves): a daily log drafted from the day's notes and photos, a
submittal checked against its spec section, and risk flags across the
job's RFIs, submittals, schedule and logs. The reading is done here by
pattern; the AI on this PC (Ollama) only tidies wording when asked.
Nothing leaves the PC, and every draft is for a person to check.

    draft_daily(notes, day, photos=())        -> daily-log record fields
    section_text(spec_doc, code)              -> (text, [pages])
    check_submittal(spec_text, sub_text, code)-> [{check, spec, found, ok}]
    risk_flags(store, today=None)             -> [{level, item, reason, ...}]
"""
import datetime as dt
import os
import re

# ----------------------------------------------------------- daily log
_UNITS = r"(?:men|man|workers?|guys|crew|people|ppl|laborers?|techs?|" \
         r"electricians?|plumbers?|carpenters?|operators?|hands)"
_MANPOWER = re.compile(
    r"^\s*(?P<company>[A-Za-z][\w&.,'/ -]*?)\s*[-:–(]?\s*(?P<workers>\d{1,3})"
    r"\s*" + _UNITS + r"\b\)?(?:\s*(?:x|@|for|,)?\s*(?P<hours>\d{1,2}(?:\.\d)?)"
    r"\s*(?:hrs?|hours)\b)?\s*[,;:–-]?\s*(?P<notes>.*)$", re.I)
_DELIVERY = re.compile(r"\bdeliver(?:y|ies|ed)\b|\breceived\b", re.I)
_FROM = re.compile(r"\bfrom\s+([A-Za-z][A-Za-z&.' -]{1,40}?)"
                   r"(?=\s+(?:at\s+)?\d|\s*[,;]|\s*$)", re.I)
_TIME = re.compile(r"\b(\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?)",
                   re.I)
_INSPECT = re.compile(r"\binspect(?:ion|ed|or)?\b", re.I)
_SAFETY = re.compile(r"\b(?:safety|incident|near[ -]miss|injur\w*|"
                     r"toolbox talk|first aid|osha)\b", re.I)
_DELAY = re.compile(r"\b(?:delay\w*|rain\w*|wind\w*|snow\w*|waiting on|"
                    r"stopped|shut ?down|idle|no show|stand[- ]?by)\b", re.I)
_VISIT = re.compile(r"\b(?:visit\w*|walk[- ]?through|on site:|owner on site|"
                    r"architect on site|engineer on site)\b", re.I)
_HOURS = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:hrs?|hours)\b", re.I)


def _delay_cause(t):
    low = t.lower()
    if re.search(r"rain|wind|snow|storm|weather|heat|cold|lightning", low):
        return "Weather"
    if "inspect" in low:
        return "Inspection"
    if re.search(r"material|deliver|supplier|backorder", low):
        return "Material"
    if re.search(r"\brfi\b|drawing|design|architect|engineer", low):
        return "Design"
    if "owner" in low:
        return "Owner"
    if re.search(r"\bsub\b|no show|crew", low):
        return "Sub"
    return "Other"


def photo_time(path):
    """When a photo was taken (its camera time when it has one, else the
    file's time), as 'HH:MM' text, or ''."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get(36867) or ex.get_ifd(0x8769).get(36867) or \
                ex.get(306)
        if raw:
            return str(raw)[11:16]
    except Exception:                                     # noqa: BLE001
        pass
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path)) \
            .strftime("%H:%M")
    except OSError:
        return ""


def draft_daily(notes, day=None, photos=()):
    """The day's notes (one item per line, as typed in the field) sorted
    into a daily log's parts: manpower, work, deliveries, visitors,
    safety, delays and inspections. Photos are listed with their time.
    Returns the record's fields (status Draft) for a person to check."""
    rec = {"date": (day or dt.date.today()).isoformat()
           if not isinstance(day, str) else day,
           "manpower": [], "work": "", "deliveries": [], "visitors": [],
           "safety": "", "delays": [], "inspections_note": "",
           "status": "Draft"}
    work, safety, insp = [], [], []
    for raw in (notes or "").splitlines():
        line = raw.strip(" -*•\t")
        if not line:
            continue
        m = _MANPOWER.match(line)
        if m and not _DELIVERY.search(line):
            rec["manpower"].append({
                "company": m.group("company").strip(" -,"),
                "trade": "", "workers": int(m.group("workers")),
                "hours": float(m.group("hours")) if m.group("hours") else 8,
                "location": "", "notes": m.group("notes").strip()})
            if m.group("notes").strip():
                work.append(f"{m.group('company').strip(' -,')}: "
                            f"{m.group('notes').strip()}")
            continue
        if _DELIVERY.search(line):
            fm, tm = _FROM.search(line), _TIME.search(line)
            rec["deliveries"].append({
                "time": tm.group(1) if tm else "",
                "supplier": fm.group(1).strip() if fm else "",
                "contents": line, "received_by": ""})
            continue
        if _SAFETY.search(line):
            safety.append(line)
            continue
        if _DELAY.search(line):
            hm = _HOURS.search(line)
            rec["delays"].append({"cause": _delay_cause(line),
                                  "hours": float(hm.group(1)) if hm else 0,
                                  "description": line})
            continue
        if _INSPECT.search(line):
            insp.append(line)
            continue
        if _VISIT.search(line):
            rec["visitors"].append({"name": "", "company": "",
                                    "purpose": line, "time": ""})
            continue
        work.append(line)
    if photos:
        work.append("Photos: " + "; ".join(
            f"{os.path.basename(p)}" + (f" ({photo_time(p)})"
                                        if photo_time(p) else "")
            for p in photos))
    rec["work"] = "\n".join(work)
    rec["safety"] = "\n".join(safety)
    rec["inspections_note"] = "\n".join(insp)
    return rec


def tidy_prompt(work):
    return ("Rewrite these construction field notes as the 'Work performed' "
            "part of a daily log: short plain sentences, one per line, in "
            "the past tense. Keep every fact, name, number and location "
            "exactly; add nothing that is not in the notes.\n\nNOTES:\n"
            + work)


# ---------------------------------------------------------- submittals
_STD = re.compile(r"\b(?:ASTM|ANSI|UL|NFPA|ASHRAE|AWWA|ASME|AISC|ACI|AWS|"
                  r"SMACNA|NEMA|IEEE|FM|CSA|ISO|AAMA|NSF|TCNA|BHMA|SDI|"
                  r"NAAMM|ICC-ES|GA)\s?[A-Z]?\s?\d[\w.\-/]*", re.I)
_WARRANTY = re.compile(r"(\w+)\s*(?:\(\d+\)\s*)?[- ]?years?\b[^.]{0,60}?"
                       r"\bwarrant|\bwarrant\w*[^.]{0,80}?\b(\w+)\s*"
                       r"(?:\(\d+\)\s*)?[- ]?years?\b", re.I)
_NUM_WORDS = {w: n for n, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
    "twenty".split(), 1)}
_SUBMIT_KINDS = (("product data", r"product data"),
                 ("shop drawings", r"shop drawings?"),
                 ("samples", r"\bsamples?\b"),
                 ("certificates", r"certificat\w+"),
                 ("test reports", r"test reports?"),
                 ("warranty", r"warrant\w+"),
                 ("installation instructions", r"installation instructions"),
                 ("operation and maintenance data",
                  r"operation and maintenance|o\s*&\s*m\b"))


def _code_re(code):
    d = re.sub(r"\D", "", code or "")
    if len(d) < 6:
        return None
    return re.compile(r"\b" + d[0:2] + r"\s?" + d[2:4] + r"\s?" + d[4:6] +
                      r"\b")


def section_text(spec_doc, code):
    """The text of one spec section (by its number, e.g. 08 71 00): the
    pages that start it or carry it in the footer, until the next section
    or END OF SECTION."""
    rx = _code_re(code)
    if rx is None or spec_doc is None:
        return "", []
    out, pages, inside = [], [], False
    for p in range(spec_doc.page_count):
        t = spec_doc[p].get_text() or ""
        head = re.search(r"\bSECTION\s+(\d{2}\s?\d{2}\s?\d{2})", t)
        mine = bool(rx.search(t[:300]) or rx.search(t[-300:]) or
                    (head and rx.search(head.group(0))))
        if head and not rx.search(head.group(0)) and inside:
            break
        if mine or inside:
            out.append(t)
            pages.append(p)
            inside = True
            if re.search(r"END OF SECTION", t):
                break
    return "\n".join(out), pages


def _years(text):
    m = _WARRANTY.search(text or "")
    if not m:
        return None
    w = (m.group(1) or m.group(2) or "").lower()
    return int(w) if w.isdigit() else _NUM_WORDS.get(w)


class _TextDoc:
    """Text standing in for a one-page document (specmfrs reads pages)."""
    page_count = 1

    def __init__(self, text):
        self.text = text

    def __getitem__(self, i):
        return self

    def get_text(self, *a):
        return self.text


def check_submittal(spec_text, sub_text, code=""):
    """What the spec section asks for, and whether the submittal shows it:
    the listed manufacturers (or basis of design), each referenced
    standard, the warranty term and the kinds of submittal asked for."""
    from . import specmfrs
    rows = []
    spec = spec_text or ""
    sub = sub_text or ""
    low = sub.lower()

    mfrs = [r["manufacturer"] for r in specmfrs.find(_TextDoc(spec))]
    if mfrs:
        named = [m for m in mfrs if m.lower().split()[0] in low]
        rows.append({"check": "Manufacturer",
                     "spec": ", ".join(mfrs[:8]),
                     "found": ", ".join(named) or "none of those named",
                     "ok": bool(named)})
    stds = []
    for m in _STD.finditer(spec):
        s = re.sub(r"\s+", " ", m.group(0).upper()).strip(" .,;")
        if s not in stds:
            stds.append(s)
    for s in stds[:25]:
        key = re.sub(r"\s", "", s).lower()
        rows.append({"check": "Standard", "spec": s,
                     "found": "shown" if key in re.sub(r"\s", "", low)
                     else "not shown", "ok": key in re.sub(r"\s", "", low)})
    want = _years(spec)
    if want:
        got = _years(sub)
        rows.append({"check": "Warranty", "spec": f"{want} years",
                     "found": f"{got} years" if got else "not shown",
                     "ok": bool(got and got >= want)})
    m = re.search(r"\bSUBMITTALS\b(.{0,2500}?)(?:\n\s*1\.\d+\s+[A-Z]|PART 2)",
                  spec, re.S)
    if m:
        art = m.group(1).lower()
        for name, rx in _SUBMIT_KINDS:
            if re.search(rx, art):
                there = bool(re.search(rx, low))
                rows.append({"check": "Submittal item", "spec": name,
                             "found": "included" if there else "not found",
                             "ok": there})
    return rows


# ---------------------------------------------------------- risk flags
def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days(a, b):
    return (a - b).days if a and b else None


def risk_flags(store, today=None):
    """RFIs, submittals, schedule activities, issues, change events and
    delays that look likely to cost time or money, each with the reason -
    by rule, worst first."""
    from .pm import schema
    today = today or dt.date.today()
    out = []

    def add(level, coll, r, what, reason, days=None):
        no = r.get("_no") or ""
        out.append({"level": level, "coll": coll, "id": r.get("_id"),
                    "item": f"{what} {no}".strip() + (
                        f" - {r.get('subject') or r.get('title') or r.get('name') or ''}"
                        .rstrip(" -")),
                    "reason": reason, "days": days})

    for r in store.list("rfi"):
        if schema.is_closed("rfi", r):
            continue
        due, sent = _d(r.get("due")), _d(r.get("sent"))
        late = _days(today, due)
        if late and late > 0:
            add("High" if late > 7 else "Medium", "rfi", r, "RFI",
                f"answer is {late} day(s) late", late)
        elif sent and _days(today, sent) and _days(today, sent) > 14:
            add("Medium", "rfi", r, "RFI",
                f"open {_days(today, sent)} days", _days(today, sent))
        if r.get("cost_impact") == "Yes" and not r.get("change_event"):
            add("High", "rfi", r, "RFI",
                "has a cost impact but no change event", None)
        if r.get("schedule_impact") == "Yes":
            add("Medium", "rfi", r, "RFI", "may affect the schedule"
                + (f" ({r.get('schedule_days')} days)"
                   if r.get("schedule_days") else ""), None)
    for r in store.list("submittal"):
        if schema.is_closed("submittal", r):
            continue
        st = r.get("status") or ""
        submit_by, onsite = _d(r.get("submit_by")), _d(r.get("required_on_site"))
        late = _days(today, submit_by)
        if late and late > 0 and st in ("Draft", "Not Submitted"):
            add("High", "submittal", r, "Submittal",
                f"not submitted - {late} day(s) past its submit-by date",
                late)
        if onsite:
            need = int(float(r.get("lead_days") or 0)) + \
                int(float(r.get("review_days") or 0))
            left = _days(onsite, today)
            if left is not None and left < need:
                add("High" if left < 0 else "Medium", "submittal", r,
                    "Submittal", f"needed on site in {left} day(s) but lead "
                    f"and review take {need}", -left)
        if st in ("Revise and Resubmit", "Rejected"):
            add("Medium", "submittal", r, "Submittal",
                f"{st.lower()} - back with the sub", None)
        for step in r.get("workflow") or []:
            sdue = _d(step.get("due"))
            if sdue and not step.get("returned") and sdue < today:
                add("Medium", "submittal", r, "Submittal",
                    f"review by {step.get('reviewer') or 'reviewer'} is "
                    f"{_days(today, sdue)} day(s) late", _days(today, sdue))
                break
    for r in store.list("activity"):
        if r.get("status") == "Complete":
            continue
        pct = float(r.get("percent") or 0)
        fin, start = _d(r.get("baseline_finish")), _d(r.get("start"))
        if fin and fin < today and pct < 100:
            add("High", "activity", r, "Activity",
                f"{pct:g}% done, {_days(today, fin)} day(s) past its "
                "baseline finish", _days(today, fin))
        elif start and start < today and r.get("status") == "Not Started":
            add("Medium", "activity", r, "Activity",
                f"should have started {_days(today, start)} day(s) ago",
                _days(today, start))
    for r in store.list("issue"):
        if schema.is_closed("issue", r):
            continue
        late = _days(today, _d(r.get("due")))
        if late and late > 0:
            add("Medium", "issue", r, "Issue", f"{late} day(s) overdue", late)
    for r in store.list("event"):
        if schema.is_closed("event", r):
            continue
        made = _d(r.get("_created"))
        if made and _days(today, made) > 30:
            add("Medium", "event", r, "Change event",
                f"pending {_days(today, made)} days", _days(today, made))
    lost = 0.0
    for r in store.list("daily"):
        d = _d(r.get("date"))
        if d and 0 <= _days(today, d) <= 14:
            for x in r.get("delays") or []:
                try:
                    lost += float(x.get("hours") or 0)
                except (TypeError, ValueError):
                    pass
    if lost >= 16:
        out.append({"level": "Medium", "coll": "daily", "id": None,
                    "item": "Daily logs - last 14 days",
                    "reason": f"{lost:g} hours lost to delays", "days": None})
    rank = {"High": 0, "Medium": 1}
    out.sort(key=lambda f: (rank.get(f["level"], 2), -(f["days"] or 0)))
    return out
