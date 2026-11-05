"""Deterministic facts from spec text. No model.

Long-lead gear is a fixed dictionary. Durations, sequences and cure times
are regular expressions. Division 01 sections are read on purpose:
progress (01 32 00), submittals (01 33 00), quality (01 45 00), product
requirements (01 60 00), closeout (01 77 00) and commissioning (01 91 00),
plus phasing language wherever it sits.

Contract time also goes through the scheduler's existing reader
(``autoschedule.contract_time``), which already keeps every statement and
flags disagreements. A fact from that reader is labeled the same way.
"""
import re

# item, pattern, default calendar days, division, consumer class
LONG_LEAD = (
    ("switchgear", r"switchgears?|switchboards?", 140, "26", "elec_rough"),
    ("elevator", r"\belevators?\b", 180, "14", "structure"),
    ("chiller", r"\bchillers?\b", 160, "23", "hvac_rough"),
    ("air handler", r"air[- ]handlers?|\bAHUs?\b", 120, "23", "hvac_rough"),
    ("structural steel", r"structural steel", 84, "05", "structure"),
    ("joist and deck", r"joists? and deck|steel joists?|bar joists?|metal deck",
     70, "05", "structure"),
    ("curtain wall", r"curtain walls?", 140, "08", "envelope"),
    ("roofing", r"\broofing\b", 56, "07", "roofing"),
    ("generator", r"\bgenerators?\b|\bgensets?\b", 150, "26", "elec_rough"),
    ("fire pump", r"fire pumps?", 90, "21", "fire_rough"),
    ("rooftop unit", r"rooftop units?|\bRTUs?\b", 100, "23", "hvac_rough"),
    ("boiler", r"\bboilers?\b", 80, "23", "hvac_rough"),
    ("cooling tower", r"cooling towers?", 120, "23", "hvac_rough"),
    ("water heater", r"water heaters?", 28, "22", "plumb_rough"),
)

_LEAD_NUM = re.compile(
    r"(\d{1,3})\s*(calendar|working|work|business)?\s*-?\s*(day|days|week|weeks)\b",
    re.I,
)
_CURE = re.compile(
    r"\b(\d{1,3})\s*-?\s*day\b[^.\n]{0,40}\b(cure|curing|break|strength)\b|"
    r"\b(cure|curing)\b[^.\n]{0,40}\b(\d{1,3})\s*-?\s*day",
    re.I,
)
_BEFORE = re.compile(
    r"\b(.{3,60}?)\s+(?:shall be completed before|prior to|before)\s+(.{3,60}?)(?:[.;]|$)",
    re.I,
)
_SUBMIT_BEFORE = re.compile(
    r"\bsubmit(?:tal)?\s+(.{3,50}?)\s+before\s+(.{3,50}?)(?:[.;]|$)",
    re.I,
)
_PHASE = re.compile(r"\bphase\s+([0-9]{1,2}|[IVX]{1,4})\b[^.\n]{0,80}", re.I)
_NTP = re.compile(r"\bnotice to proceed\b|\bNTP\b", re.I)
_NTS = re.compile(r"\bNTS\b")
_BY_OTHERS = re.compile(
    r"\b(.{3,50}?)\s+(?:by others|not in (?:this )?contract|n\.?i\.?c\.?)\b",
    re.I,
)
_OFCI = re.compile(
    r"\b(owner[- ]furnished(?:[^.\n]{0,40})|OFCI|OF/CI)\b",
    re.I,
)

DIV01 = {
    "01 32 00": "progress",
    "01 33 00": "submittals",
    "01 45 00": "quality",
    "01 60 00": "products",
    "01 77 00": "closeout",
    "01 91 00": "commissioning",
}


def _fact(kind, item, section, page, text, **kw):
    return {
        "kind": kind,
        "item": " ".join(str(item or "").split())[:120],
        "spec_section": section.get("number") if isinstance(section, dict)
        else (section or ""),
        "page": page,
        "source": "deterministic",
        "text": " ".join(str(text or "").split())[:240],
        "division": (section.get("division") if isinstance(section, dict)
                     else "") or kw.get("division") or "",
        "value": kw.get("value"),
        "unit": kw.get("unit") or "",
        "consumer": kw.get("consumer") or "",
        "basis": kw.get("basis") or "",
    }


def _lead_near(text, start, end):
    window = text[max(0, start - 80):min(len(text), end + 80)]
    m = _LEAD_NUM.search(window)
    if not m:
        return None
    around = window[max(0, m.start() - 40):m.end() + 40]
    # A cure or a strength break is not a procurement lead time.
    if re.search(r"\bcure|curing|break|strength\b", around, re.I):
        return None
    n = int(m.group(1))
    unit = m.group(3).lower()
    kind = (m.group(2) or "").lower()
    days = n * 7 if unit.startswith("week") else n
    basis = "work" if re.search(r"work|business", kind) else "calendar"
    return days, basis, m.group(0)


def extract_sections(sections):
    facts = []
    for sec in sections or ():
        text = sec.get("text") or ""
        page = (sec.get("pages") or [None])[0]
        num = sec.get("number") or ""
        low = num.strip()
        for item, pat, default, div, consumer in LONG_LEAD:
            for m in re.finditer(pat, text, re.I):
                near = _lead_near(text, m.start(), m.end())
                if near:
                    days, basis, shown = near
                    src = "spec"
                else:
                    days, basis, shown = default, "default", ""
                    src = "dictionary"
                facts.append(_fact(
                    "long_lead", item, sec, page, m.group(0),
                    value=days, unit=basis, consumer=consumer, division=div,
                    basis=src if src == "spec" else "dictionary default"))
                facts[-1]["lead_source"] = src
                facts[-1]["shown"] = shown
                break
        for m in _CURE.finditer(text):
            n = int(m.group(1) or m.group(4))
            facts.append(_fact("cure", "concrete cure", sec, page, m.group(0),
                               value=n, unit="calendar"))
        for m in _BEFORE.finditer(text):
            facts.append(_fact("sequence", m.group(1), sec, page, m.group(0),
                               value=m.group(2)))
        for m in _SUBMIT_BEFORE.finditer(text):
            facts.append(_fact("sequence", "submit " + m.group(1), sec, page,
                               m.group(0), value=m.group(2)))
        for m in _PHASE.finditer(text):
            facts.append(_fact("phasing", f"Phase {m.group(1).upper()}",
                               sec, page, m.group(0)))
        if _NTP.search(text):
            facts.append(_fact("milestone", "Notice to Proceed", sec, page,
                               "Notice to Proceed"))
        if _NTS.search(text):
            # On a drawing, NTS is "not to scale". It is not a duration.
            facts.append(_fact("drawing_note", "NTS", sec, page,
                               "NTS (not a duration)"))
        for m in _BY_OTHERS.finditer(text):
            facts.append(_fact("by_others", m.group(1), sec, page, m.group(0)))
        for m in _OFCI.finditer(text):
            facts.append(_fact("owner_furnished", m.group(1), sec, page,
                               m.group(0)))
        role = DIV01.get(low)
        if role:
            facts.extend(_division_01(role, sec, page, text))
        if re.search(r"\bphas(e|ing)\b", text, re.I) and role is None:
            if re.search(r"\bphase\s+[0-9]", text, re.I) is None and \
                    re.search(r"phasing plan|work phasing", text, re.I):
                facts.append(_fact("phasing", "phasing", sec, page,
                                   "phasing mentioned"))
    return facts


def _division_01(role, sec, page, text):
    out = []
    if role == "submittals":
        m = re.search(
            r"(\d{1,3})\s*(calendar|working|work)?\s*(day|days)\b",
            text, re.I)
        days, unit = (14, "calendar")
        if m:
            days = int(m.group(1))
            unit = "work" if re.search(r"work", m.group(2) or "", re.I) \
                else "calendar"
        out.append(_fact("submittal_review", "general submittals", sec, page,
                         m.group(0) if m else "submittal review",
                         value=days, unit=unit))
    if role == "quality":
        for m in re.finditer(
                r"(?i)(?:special inspection|hold point|shall be inspected|"
                r"inspection of|test of|testing of)\s+([^.\n]{3,80})",
                text):
            out.append(_fact("inspection", m.group(0), sec, page, m.group(0)))
        if re.search(r"\btest", text, re.I):
            for m in re.finditer(
                    r"(?i)\b([A-Za-z][^.\n]{3,60}\btest(?:ing)?)\b", text):
                if len(out) > 24:
                    break
                out.append(_fact("test", m.group(1), sec, page, m.group(1)))
    if role == "products":
        if re.search(r"owner[- ]furnished|OFCI", text, re.I):
            out.append(_fact("owner_furnished", "owner-furnished products",
                             sec, page, "owner-furnished"))
    if role == "closeout":
        for label in ("closeout", "operation and maintenance", "as-built",
                      "warrant", "training", "punch"):
            if re.search(label, text, re.I):
                out.append(_fact("closeout", label, sec, page, label))
    if role == "commissioning":
        out.append(_fact("commissioning", "commissioning", sec, page,
                         "commissioning"))
        if re.search(r"test and balance|\bTAB\b", text, re.I):
            out.append(_fact("test", "test and balance", sec, page,
                             "test and balance"))
    if role == "progress":
        if re.search(r"substantial", text, re.I):
            out.append(_fact("milestone", "Substantial Completion", sec, page,
                             "Substantial Completion"))
        if re.search(r"final completion", text, re.I):
            out.append(_fact("milestone", "Final Completion", sec, page,
                             "Final Completion"))
    return out


def contract_from_pages(pages):
    """The scheduler's own contract-time reader, plus a thin fallback.

    Returns ``(ct, facts)``. ``ct`` is the autoschedule structure.
    """
    from .. import autoschedule
    rows = []
    for item in pages or ():
        if isinstance(item, dict):
            rows.append((int(item.get("page") or 0), item.get("text") or ""))
        else:
            rows.append((int(item[0]), item[1] or ""))
    ct = autoschedule.contract_time(rows)
    facts = []
    for hit in ct.get("found") or ():
        facts.append({
            "kind": "contract",
            "item": hit.get("kind") or "contract",
            "spec_section": "",
            "page": hit.get("page"),
            "source": "deterministic",
            "text": hit.get("text") or "",
            "division": "01",
            "value": hit.get("days") or hit.get("date"),
            "unit": hit.get("basis") or "",
            "consumer": "",
            "basis": "contract text",
        })
    return ct, facts


def extract(sections, spec_pages=None):
    facts = extract_sections(sections)
    ct = {"found": [], "conflicts": [], "substantial": None, "final": None,
          "dates": {}}
    if spec_pages:
        ct, extra = contract_from_pages(spec_pages)
        facts.extend(extra)
    return facts, ct
