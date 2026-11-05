"""Find RFIs in a plan set with rules, not a language model (v36).

The old finder sent every page's raw text to a 3B local model in 24k-char
chunks and waited for all of it before showing anything. Plan-sheet text is
a word salad to a small model, so it guessed. These checks read the labels
a civil/wastewater reviewer actually reads - pipe runs, structure rims and
inverts, slopes, callouts, spec sections, schedules, open-scope notes - and
compare them across sheets. Every finding carries the exact quotes and the
sheets they came from, so the RFI can cite both sides.

pages: [(page index, sheet number, title, text)] as rfi_finder.gather()
returns. Nothing here touches a PDF or the network.

Finding keys (all also in the old rfi_finder format, so create_rfis and the
RFI log take them unchanged): kind, subject, title, question, reason,
reference, quote, page, doc, source="check", severity ("high" | "medium" |
"low"), cites [{"sheet", "page", "quote", "doc"}], proposal.
"""
import re

ID = r"(?:SAN\s+)?((?:MH|SMH|SSMH|CO|CB|INL|WW|LS)\s?-?\s?\d{1,4}[A-Z]?)"
SEG = re.compile(
    ID + r"\s+(?:TO|-|–)\s+" + ID +
    r"\s*:?\s+(\d+(?:\.\d+)?)\s*(?:LF|FT|')\s+(?:OF\s+)?(\d{1,2})\s*(?:\"|IN\.?|-IN)\s*"
    r"(PVC|DIP|DI|HDPE|RCP|VCP|CIPP|PP|FRP)\b\s*"
    r"((?:SDR|DR)\s?-?\s?\d+|C ?900|C ?905|CL(?:ASS)?\s?-?\s?\d+)?"
    r"\s*(?:@|AT|S\s*=)\s*(-?\d*\.\d+)\s*(%|FT/FT|')?", re.I)
RIM = re.compile(r"\bRIM\s*(?:EL\.?)?\s*[=:]?\s*(\d{2,4}\.\d{1,3})", re.I)
INV = re.compile(r"\bI(?:NV|E)\.?\s*(IN|OUT)?\s*(?:\([NSEW]{1,2}\))?\s*[=:]?"
                 r"\s*(\d{2,4}\.\d{1,3})", re.I)
STRUCT = re.compile(r"\b" + ID + r"\b", re.I)
CALLOUT = re.compile(r"\b(\d{1,2}[A-Z]?)\s*/\s*([A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?)\b")
SEE_SHEET = re.compile(r"\bSEE\s+SHEET\s+([A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?)\b",
                       re.I)
DETAIL_ON = re.compile(r"\bDETAIL\s+(\d{1,2}[A-Z]?)\b", re.I)
SPEC_SEC = re.compile(r"\b(\d{2})\s(\d{2})\s(\d{2})(?:\.\d{2})?\b")
SECTION_HEAD = re.compile(r"SECTION\s+(\d{2})\s?(\d{2})\s?(\d{2})", re.I)
EQUIP = re.compile(r"\b([A-Z]{1,4})-(\d{1,3}[A-Z]?)\b")
NOT_EQUIP = {"A", "S", "M", "E", "C", "L", "T", "FP", "ID", "AD", "G", "FA",
             "NO", "SHT", "REV", "DWG", "ASTM", "UL", "ANSI", "NFPA", "SF",
             "LF", "EA", "TYP", "SDR", "DR", "MH", "SMH", "SSMH", "CO", "CB",
             "INL", "STA", "CL", "AWWA"}
OPEN_SCOPE = re.compile(r"\b(TBD|T\.B\.D\.|TO BE DETERMINED|BY OTHERS|"
                        r"N\.I\.C\.|NIC|NOT IN CONTRACT)\b")
CLASS_TOK = re.compile(r"\b(SDR|DR)\s?-?\s?(\d{2})\b|\b(C ?9[0-9]{2})\b", re.I)
# Ten States Standards (2014) 33.41: minimum slope for 8"-27" gravity sewer
MIN_SLOPE = {8: 0.40, 10: 0.28, 12: 0.22, 14: 0.17, 15: 0.15, 16: 0.14,
             18: 0.12, 21: 0.10, 24: 0.08, 27: 0.067}
# ---- what is and isn't a tag, a sheet or a spec section (phase 2: Aiken) --------
# MasterFormat 2004/2018 divisions that exist
MF_DIVISIONS = {"00", "01", "02", "03", "04", "05", "06", "07", "08", "09",
                "10", "11", "12", "13", "14", "21", "22", "23", "25", "26",
                "27", "28", "31", "32", "33", "34", "35", "40", "41", "42",
                "43", "44", "45", "46", "48"}
# finish / paint / material codes on finish plans and legends: PT-2 is a
# paint, not a sheet; VCT-1 a floor tile, not equipment
FINISH_CODES = {"PT", "PNT", "CPT", "VCT", "LVT", "VWC", "WC", "ACT", "EPX",
                "CT", "QT", "RB", "PL", "SS", "SV", "FRP", "WD", "GL", "TB",
                "WB", "MTL", "TL", "CG", "LAM", "BS", "RES", "SF", "RFT",
                "SCT", "PC", "WT", "FWC", "CPT", "EPT", "ETR", "STN"}
# figure and value references in code / ADA diagrams and notes: R-19 is an
# insulation value, B-054 a figure; only an equipment schedule listing the
# family makes them tags
FIGURE_PREFIXES = {"R", "B", "FIG"}
CODE_SHEET = re.compile(r"\b(CODE|ADA|ACCESSIB\w*|LIFE\s+SAFETY|EGRESS|"
                        r"MOUNTING\s+HEIGHTS?|ANSI|ICC|A117)\b", re.I)
EQUIP_SCHED = re.compile(r"\b(EQUIPMENT|FIXTURE|FAN|PUMP|UNIT|AHU|RTU|"
                         r"HEATER|BOILER|CHILLER|PANEL|DRAIN|DIFFUSER|"
                         r"GRILLE|REGISTER|LIGHTING|LUMINAIRE)\b", re.I)
SPEC_CONTEXT = re.compile(r"\b(SECTION|SECT\.|SEC\.|SPEC(?:IFICATION)?S?\.?|"
                          r"DIV(?:ISION)?\.?|CSI)\b[^\n]{0,30}$", re.I)
SPEC_CONTEXT_AFTER = re.compile(r"^[^\n]{0,25}\bSPEC(?:IFICATION)?S?\b", re.I)


def sheet_key(s):
    """'P-101', 'P101', 'P 1.01' -> one key for comparing sheet numbers."""
    return re.sub(r"[\s\-.]", "", (s or "").upper())


def set_sheets(pages):
    """The set's own sheet numbers (as sheets.scan / gather read them)."""
    return {sheet_key(n) for _i, n, _t, _x in pages if n}


def sheet_prefixes(pages):
    return {re.match(r"[A-Z]*", sheet_key(n)).group(0)
            for _i, n, _t, _x in pages if n}


def is_finish_code(prefix, prefixes=()):
    """PT-2, CPT-1, VCT-3: a finish, unless the set really has sheets with
    that prefix."""
    p = (prefix or "").upper()
    return p in FINISH_CODES and p not in prefixes


def is_code_sheet(num, title):
    """A code / ADA / life-safety sheet: its figure numbers aren't tags."""
    return bool(CODE_SHEET.search(title or "")) or \
        (num or "").upper().startswith(("G", "CS"))


def spec_ref_ok(text, m, have=None):
    """True when the 'NN NN NN' at match `m` reads as a spec section
    citation: a MasterFormat division, not a run of numbers (12 12 12,
    13 14 15, 20 19 18, a dimension string, a part of a longer run), a
    "SECTION" / "SPEC" word nearby, and - when the manual's sections are
    known - a division the manual has."""
    a, b, c = (int(g) for g in m.groups()[:3])
    if m.group(1) not in MF_DIVISIONS:
        return False
    if abs(b - a) <= 1 and abs(c - b) <= 1:
        return False                     # 12 12 12, 13 14 15, 10 10 11
    before = text[max(0, m.start() - 40):m.start()]
    after = text[m.end():m.end() + 30]
    if re.search(r"\d[ \t]*$", before) or re.match(r"^[ \t]?\d", after):
        return False                     # inside a longer run of numbers
    if re.match(r"^\s*(?:'|\"|-\d|/|%|SF\b|LF\b|IN\b|FT\b)", after):
        return False                     # a dimension or a quantity
    if not (SPEC_CONTEXT.search(before) or SPEC_CONTEXT_AFTER.match(after)):
        return False
    if have:
        divs = {h[:2] for h in have}
        if m.group(1) not in divs:
            return False
    return True


def near_section(sec, have):
    """The manual's section closest to `sec` - same division and level 2
    (09 91 99 -> 09 91 23, likely a typo) - for the question, or ''."""
    same = sorted(h for h in have if h[:4] == sec[:4])
    if not same:
        return ""
    best = min(same, key=lambda h: abs(int(h[:6]) - int(sec[:6])))
    return f"{best[:2]} {best[2:4]} {best[4:6]}"


def page_no(i):
    """The 1-based page number for people (findings keep `page` as the
    0-based index the viewer, locate() and the RFI log use)."""
    return None if i is None else i + 1


SLOPE_TOL = 0.02        # % - label vs inverts; rounding to 0.01 ft is finer
ELEV_TOL = 0.005        # ft


def _id(s):
    s = re.sub(r"\s+", "", s.upper().replace("SAN", "", 1)
               if s.upper().startswith("SAN ") else s.upper())
    m = re.match(r"([A-Z]+)-?(\d+[A-Z]?)$", s)
    return f"{m.group(1)}-{m.group(2)}" if m else s


def _cls(s):
    if not s:
        return ""
    s = re.sub(r"\s+", "", s.upper())
    m = re.match(r"(SDR|DR|CLASS|CL)-?(\d+)$", s)
    if m:
        return f"{'CL' if m.group(1).startswith('CL') else m.group(1)}-{m.group(2)}"
    return s.replace(" ", "")


def _mat(s):
    s = s.upper()
    return "DIP" if s == "DI" else s


def _slope(v, unit):
    v = float(v)
    # S=0.0040 (ft/ft) -> 0.40 %
    return round(v * 100, 4) if unit != "%" and abs(v) < 0.1 else v


def _sheet(num, i):
    return num or f"page {i + 1}"


def _line_at(text, pos):
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a:b if b >= 0 else len(text)].strip()


def _f(kind, subject, title, question, reason, cites, severity="medium",
       proposal=""):
    first = cites[0]
    return {"kind": kind, "subject": subject, "title": title,
            "question": question, "reason": reason,
            "reference": ", ".join(dict.fromkeys(
                c["sheet"] for c in cites if c.get("sheet")))[:80],
            "quote": first["quote"][:200], "page": first["page"],
            "page_no": page_no(first["page"]),
            "doc": first.get("doc", "plans"), "source": "check",
            "severity": severity, "cites": cites, "proposal": proposal}


def _cite(i, num, quote, doc="plans"):
    return {"sheet": _sheet(num, i), "page": i, "page_no": page_no(i),
            "quote": quote[:200], "doc": doc}


# ---- parsing ----------------------------------------------------------------------

def parse(pages):
    """(segments, structures). segments: {(a, b): [mention]}; structures:
    {id: [mention]}, each mention has page, sheet number and the line."""
    segs, structs = {}, {}
    for i, num, _t, text in pages:
        for m in SEG.finditer(text):
            a, b = _id(m.group(1)), _id(m.group(2))
            segs.setdefault((a, b), []).append({
                "page": i, "num": num, "line": _line_at(text, m.start()),
                "len": float(m.group(3)), "size": int(m.group(4)),
                "mat": _mat(m.group(5)), "cls": _cls(m.group(6)),
                "slope": _slope(m.group(7), m.group(8))})
        for line in text.splitlines():
            rim = RIM.search(line)
            invs = list(INV.finditer(line))
            if not rim and not invs:
                continue
            sm = STRUCT.search(line)
            if not sm or SEG.search(line):
                continue
            rec = {"page": i, "num": num, "line": line.strip(),
                   "rim": float(rim.group(1)) if rim else None,
                   "in": None, "out": None}
            for v in invs:
                key = (v.group(1) or "in").lower()
                if rec[key] is None:
                    rec[key] = float(v.group(2))
            structs.setdefault(_id(sm.group(1)), []).append(rec)
    return segs, structs


def _distinct(mentions, key, tol=0.0):
    vals = []
    for m in mentions:
        v = m.get(key)
        if v in (None, ""):
            continue
        if not any((abs(v - w) <= tol) if isinstance(v, float) else v == w
                   for w, _m in vals):
            vals.append((v, m))
    return vals


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, float) else str(v)


# ---- the checks -------------------------------------------------------------------

LABEL = {"size": "pipe size", "mat": "pipe material", "cls": "pipe class",
         "len": "length", "slope": "slope", "rim": "rim elevation",
         "in": "invert in", "out": "invert out"}


def pipe_checks(segs, structs, spec_classes=None):
    out, bad_struct = [], set()
    # structure elevations that disagree between sheets
    good = {}
    for sid, ms in structs.items():
        diffs = [(k, _distinct(ms, k, ELEV_TOL)) for k in ("rim", "in", "out")]
        diffs = [(k, d) for k, d in diffs if len(d) > 1]
        good[sid] = {k: (_distinct(ms, k, ELEV_TOL) or [(None, None)])[0][0]
                     for k in ("rim", "in", "out")}
        if diffs:
            bad_struct.add(sid)
            k, d = diffs[0]
            (v1, m1), (v2, m2) = d[0], d[1]
            what = " and ".join(LABEL[k] for k, _d in diffs)
            out.append(_f(
                "elev_conflict", sid, f"{sid} {what} differs between sheets",
                f"Sheet {_sheet(m1['num'], m1['page'])} gives {sid} "
                f"{LABEL[k]} {_fmt(v1)} and sheet "
                f"{_sheet(m2['num'], m2['page'])} gives {_fmt(v2)}. Which "
                f"elevation is correct for {sid}?",
                "Rim and invert elevations set manhole depth, pipe slope "
                "and excavation; two values can't both be built.",
                [_cite(m1["page"], m1["num"], m1["line"]),
                 _cite(m2["page"], m2["num"], m2["line"])], "high",
                f"Confirm one value for {sid} {LABEL[k]} and revise the "
                "other sheet."))
    bad_seg = set()
    for (a, b), ms in segs.items():
        name = f"{a} to {b}"
        diffs = [(k, _distinct(ms, k)) for k in ("size", "mat", "cls", "len",
                                                 "slope")]
        diffs = [(k, d) for k, d in diffs if len(d) > 1]
        if diffs:
            bad_seg.add((a, b))
            k, d = diffs[0]
            (v1, m1), (v2, m2) = d[0], d[1]
            what = " and ".join(LABEL[k] for k, _d in diffs)
            unit = '"' if k == "size" else ""
            out.append(_f(
                "pipe_conflict", f"{a}/{b}",
                f"{name}: {what} differs between sheets",
                f"Sheet {_sheet(m1['num'], m1['page'])} labels the "
                f"{name} run {_fmt(v1)}{unit} and sheet "
                f"{_sheet(m2['num'], m2['page'])} labels it "
                f"{_fmt(v2)}{unit}. Which {LABEL[k]} governs for {name}?",
                "Pipe size, material and class drive the unit price, "
                "fittings and submittals.",
                [_cite(m1["page"], m1["num"], m1["line"]),
                 _cite(m2["page"], m2["num"], m2["line"])], "high",
                f"Confirm the {LABEL[k]} for {name} and revise the other "
                "sheet; we will carry the larger/costlier item until "
                "answered."))
            continue
        g = ms[0]
        cite = [_cite(g["page"], g["num"], g["line"])]
        # slope against the inverts at each end
        if a not in bad_struct and b not in bad_struct and g["len"] > 0:
            up = good.get(a, {}).get("out")
            dn = good.get(b, {}).get("in")
            if up is not None and dn is not None:
                calc = (up - dn) / g["len"] * 100
                if abs(calc - g["slope"]) > SLOPE_TOL + 0.01 / g["len"] * 100:
                    sa, sb = structs[a][0], structs[b][0]
                    out.append(_f(
                        "slope_math", f"{a}/{b}",
                        f"{name}: labelled slope doesn't match the inverts",
                        f"{name} is labelled {g['slope']:.2f}% over "
                        f"{g['len']:g} LF, but invert out {up:.2f} at {a} "
                        f"and invert in {dn:.2f} at {b} give {calc:.2f}%. "
                        "Which governs: the slope or the inverts?",
                        "Slope and inverts can't both be met; it changes "
                        "depth, dewatering and possibly the pipe class.",
                        cite + [_cite(sa["page"], sa["num"], sa["line"]),
                                _cite(sb["page"], sb["num"], sb["line"])],
                        "high", "Confirm the inverts govern and the slope "
                        "label is revised (or provide revised inverts)."))
                    bad_seg.add((a, b))
        if (a, b) not in bad_seg and g["size"] in MIN_SLOPE and \
                0 <= g["slope"] < MIN_SLOPE[g["size"]] - 1e-9:
            out.append(_f(
                "min_slope", f"{a}/{b}",
                f"{name}: {g['size']}\" at {g['slope']:.2f}% is below the "
                f"{MIN_SLOPE[g['size']]:.2f}% minimum",
                f"{name} is {g['size']}\" at {g['slope']:.2f}%, below the "
                f"{MIN_SLOPE[g['size']]:.2f}% minimum slope for "
                f"{g['size']}\" sewer in the Ten States Standards. Please "
                "confirm the slope is intended, or provide revised inverts.",
                "A flat sewer may fail acceptance (deflection/mandrel and "
                "low-pressure air tests don't catch it; the reviewing "
                "agency will).", cite, "medium",
                "Confirm in writing that the design slope is accepted by "
                "the reviewing agency."))
        if spec_classes and g["cls"] and g["mat"] == "PVC" and \
                g["cls"].startswith(("SDR", "DR")) and \
                g["cls"] not in spec_classes:
            out.append(_f(
                "spec_class", f"{a}/{b}",
                f"{name}: {g['cls']} on the drawings, not in the spec",
                f"Sheet {_sheet(g['num'], g['page'])} calls for {g['size']}\" "
                f"PVC {g['cls']} for {name}, but the specifications allow "
                f"{', '.join(sorted(spec_classes))}. Which pipe class "
                "governs?", "Pipe class changes the material price and the "
                "submittal.", cite, "medium",
                f"Confirm {g['cls']} for this run (drawings govern) or "
                "revise the label to the specified class."))
    # structures shown with a rim but never an invert, and pipe ends that
    # no sheet defines
    ends = {s for k in segs for s in k}
    if len(structs) >= 3:
        for sid in sorted(ends, key=_natural):
            ms = structs.get(sid)
            if ms is None:
                g = next(m for k, v in segs.items() if sid in k for m in v)
                out.append(_f(
                    "undefined_structure", sid,
                    f"{sid} has no rim or invert anywhere in the set",
                    f"A pipe runs to {sid} on sheet "
                    f"{_sheet(g['num'], g['page'])}, but no sheet gives "
                    f"{sid}'s type, rim or inverts. Please provide them.",
                    "Can't price or set a structure with no data.",
                    [_cite(g["page"], g["num"], g["line"])], "high",
                    "Provide the structure data, or confirm it is an "
                    "existing structure to connect to."))
            elif all(m["in"] is None and m["out"] is None for m in ms):
                m = ms[0]
                out.append(_f(
                    "missing_invert", sid, f"{sid}: no invert elevations",
                    f"Sheet {_sheet(m['num'], m['page'])} gives {sid} a rim "
                    "but no invert elevations. Please provide the invert in "
                    "and out.", "Inverts set the manhole depth, drop and "
                    "pipe slopes.", [_cite(m["page"], m["num"], m["line"])],
                    "high"))
    return out


def _natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def reference_checks(plans, specs=None):
    out = []
    sheets = {}
    for i, num, _t, text in plans:
        if num:
            sheets[num.replace("-", "").upper()] = (i, text)
    prefixes = sheet_prefixes(plans)
    if len(sheets) >= 2:
        seen = set()
        for i, num, _t, text in plans:
            refs = [(m.group(0), m.group(1).upper(), m.group(2).upper(),
                     m.start()) for m in CALLOUT.finditer(text)]
            refs += [(m.group(0), None, m.group(1).upper(), m.start())
                     for m in SEE_SHEET.finditer(text)]
            for whole, det, target, pos in refs:
                key = target.replace("-", "")
                if not re.match(r"^[A-Z]{1,2}\d", key) or (det, key) in seen:
                    continue
                if key == (num or "").replace("-", "").upper():
                    continue
                if is_finish_code(re.match(r"[A-Z]+", key).group(0),
                                  prefixes):
                    continue             # PT-2 is a paint, not a sheet
                seen.add((det, key))
                line = _line_at(text, pos)
                if key not in sheets:
                    out.append(_f(
                        "missing_sheet", target,
                        f"Sheet {target} is referenced but not in the set",
                        f"Sheet {_sheet(num, i)} says \"{line}\", but sheet "
                        f"{target} is not in the drawing set. Please issue "
                        f"{target} or correct the reference.",
                        "A referenced detail that isn't in the set can't be "
                        "priced or built.", [_cite(i, num, line)], "high",
                        "Issue the missing sheet by addendum."))
                elif det:
                    ti, ttext = sheets[key]
                    have = {d.upper() for d in DETAIL_ON.findall(ttext)}
                    # trust the list only if the sheet names 3+ details
                    if len(have) >= 3 and det not in have:
                        out.append(_f(
                            "missing_detail", f"{det}/{target}",
                            f"Detail {det}/{target} is not on sheet {target}",
                            f"Sheet {_sheet(num, i)} says \"{line}\", but "
                            f"sheet {target} only has details "
                            f"{', '.join(sorted(have, key=_natural))}. Which "
                            "detail applies?",
                            "The callout points at a detail that doesn't "
                            "exist.", [_cite(i, num, line)], "high",
                            "Confirm the intended detail number."))
    if specs:
        have = {"".join(m.groups()) for _i, _n, _t, text in specs
                for m in SECTION_HEAD.finditer(text)}
        if have:
            seen = set()
            for i, num, _t, text in plans:
                for m in SPEC_SEC.finditer(text):
                    sec = "".join(m.groups())
                    if sec in have or sec in seen or \
                            not spec_ref_ok(text, m, have):
                        continue
                    seen.add(sec)
                    label = " ".join(m.groups())
                    line = _line_at(text, m.start())
                    near = near_section(sec, have)
                    hint = (f" The nearest section in the manual is {near}."
                            if near else "")
                    out.append(_f(
                        "missing_spec", label,
                        f"Section {label} is cited but not in the manual",
                        f"Sheet {_sheet(num, i)} says \"{line}\", but "
                        f"Section {label} is not in the project manual.{hint} "
                        "Please issue the section or correct the reference.",
                        "Work tied to a missing spec section has no "
                        "requirements to price against.",
                        [_cite(i, num, line)], "medium",
                        "Issue the section by addendum, or name the "
                        "governing standard."))
    return out


SCHED_HEAD = re.compile(r"^[ A-Z&/-]*\bSCHEDULE\s*$", re.M)


def _is_sched(title, text, num=""):
    # a general sheet (G-series: index, abbreviations, legends) mentions
    # tags without scheduling them
    if (num or "").upper().startswith("G") or re.search(
            r"INDEX|ABBREVIATION|LEGEND|SYMBOL", (title or "").upper()):
        return False
    return "SCHEDULE" in (title or "").upper() or \
        bool(SCHED_HEAD.search(text.upper()))


def _disc(num):
    m = re.match(r"[A-Z]+", (num or "").upper())
    return m.group(0)[:1] if m else ""


def schedule_checks(plans):
    """Tags on plans missing from a schedule of the same discipline, for
    tag families the schedule really lists (3+ tags of that prefix)."""
    out = []
    sched = [(i, num, title, t) for i, num, title, t in plans
             if _is_sched(title, t, num)]
    if not sched:
        return out
    own = set_sheets(plans)              # P-101 is a sheet, not a pump
    prefixes = sheet_prefixes(plans)
    # families an equipment schedule lists (R-1 registers, B-1 boilers):
    # only those make R-# / B-# tags instead of figure or R-value refs
    equip_fams = set()
    by_disc = {}
    for i, num, title, t in sched:
        d = by_disc.setdefault(_disc(num), {"on": set(), "at": (i, num)})
        tags = {m.group(0) for m in EQUIP.finditer(t)
                if sheet_key(m.group(0)) not in own}
        d["on"] |= tags
        if EQUIP_SCHED.search(title or "") or EQUIP_SCHED.search(
                " ".join(SCHED_HEAD.findall(t.upper()))):
            equip_fams |= {x.split("-")[0] for x in tags}
    for d in by_disc.values():
        fam = {}
        for tag in d["on"]:
            fam.setdefault(tag.split("-")[0], set()).add(tag)
        d["fams"] = {k for k, v in fam.items() if len(v) >= 3} - NOT_EQUIP
    # one schedule for a small set: any discipline may use it
    if len(by_disc) == 1:
        only = next(iter(by_disc.values()))
        only["fams"] = {t.split("-")[0] for t in only["on"]} - NOT_EQUIP
    seen = set()
    for i, num, title, t in plans:
        if _is_sched(title, t, num) or is_code_sheet(num, title):
            continue                     # code / ADA figures aren't tags
        d = by_disc.get(_disc(num)) or (next(iter(by_disc.values()))
                                         if len(by_disc) == 1 else None)
        if not d:
            continue
        for m in EQUIP.finditer(t):
            tag = m.group(0)
            if m.group(1) not in d["fams"] or tag in d["on"] or tag in seen:
                continue
            if sheet_key(tag) in own or is_finish_code(m.group(1), prefixes) \
                    or (m.group(1) in FIGURE_PREFIXES and
                        m.group(1) not in equip_fams):
                continue                 # a sheet, a finish, a figure
            if re.search(r"(?:/|\bSHEETS?\s+|\bSHT\.?\s*|\bFIG(?:URE)?\.?\s*)$",
                         t[max(0, m.start() - 8):m.start()], re.I):
                continue                 # 5/P-201, SEE SHEET P-201
            if t[m.end():m.end() + 1] == "-" or \
                    re.search(r"\b(EX\.?|EXIST(ING)?\.?)\s*$",
                              t[max(0, m.start() - 10):m.start()]):
                continue        # an instrument loop number, or existing
            seen.add(tag)
            line = _line_at(t, m.start())
            si, sn = d["at"]
            out.append(_f(
                "unscheduled_equip", tag,
                f"{tag} is shown but not in the {m.group(1)} schedule",
                f"Sheet {_sheet(num, i)} shows {tag} (\"{line}\"), but it is "
                f"not in the schedule on {_sheet(sn, si)}. Please provide "
                "its schedule data.",
                "Unscheduled equipment can't be selected or priced.",
                [_cite(i, num, line)], "medium"))
    return out


def _not_scope(u):
    """Legend entries ("NIC  NOT IN CONTRACT") and phrases that only look
    like open scope ("REPORTED BY OTHERS", "TO BE DETERMINED BY THE
    EQUIPMENT FURNISHED")."""
    if "=" in u or u in ("NOT IN CONTRACT", "TO BE DETERMINED", "BY OTHERS"):
        return True
    if re.fullmatch(r"(N\.?I\.?C\.?|T\.?B\.?D\.?)\s*[-:=]?\s*"
                    r"(NOT IN CONTRACT|TO BE DETERMINED)", u):
        return True
    return bool(re.search(r"(REPORTED|PREPARED|SURVEYED|DESIGNED|DRAWN|"
                          r"FURNISHED TO US) BY OTHERS|TO BE DETERMINED BY|"
                          r"TBD BY", u))


def open_scope(plans, specs=None):
    out, seen = [], set()
    for doc, pages in (("plans", plans), ("specs", specs or [])):
        for i, num, _t, text in pages:
            for line in text.splitlines():
                m = OPEN_SCOPE.search(line.upper())
                if not m:
                    continue
                q = re.sub(r"^\s*\d+[.)]\s*", "", line.strip()).rstrip(".")
                if len(q) < 6 or q.upper() in seen or _not_scope(q.upper()):
                    continue
                seen.add(q.upper())
                word = m.group(1).upper()
                if word.startswith(("TBD", "T.B.D", "TO BE")):
                    ask = (f"\"{q}\" is to be determined. Please provide "
                           "the requirement so it can be priced, or confirm "
                           "it is excluded from the base bid.")
                else:
                    ask = (f"\"{q}\": please confirm who furnishes and "
                           "installs this work and that it is not in our "
                           "contract.")
                out.append(_f(
                    "open_scope", q.upper(), q[:80], ask,
                    "Open scope affects price and responsibility.",
                    [_cite(i, num, line.strip(), doc)], "low",
                    "We will exclude it from our bid unless directed "
                    "otherwise."))
    return group_open_scope(out)


def group_open_scope(notes):
    """Two or more open-scope notes (TBD / by others) become ONE low item
    listing them all, so they don't bury the coordination findings (PM
    review NW-19). `items` keeps each note's subject."""
    if len(notes) < 2:
        return notes
    cites = [c for n in notes for c in n["cites"]]
    lines = "\n".join(f"  - {c['sheet'] if c.get('doc', 'plans') == 'plans' else 'Specs'}"
                      f": \"{n['title']}\"" for n in notes
                      for c in n["cites"][:1])
    g = _f("open_scope", "OPEN SCOPE NOTES",
           f"Open scope: {len(notes)} TBD / by-others notes",
           "For each note below, please provide the requirement so it can "
           "be priced, or confirm who furnishes and installs it and that it "
           "is excluded from our contract?\n" + lines,
           "Open scope affects price and responsibility.", cites, "low",
           "We will exclude these items from our bid unless directed "
           "otherwise.")
    g["items"] = [n["subject"] for n in notes]
    return [g]


def spec_pipe_classes(specs):
    out = set()
    for _i, _n, _t, text in specs or []:
        for m in CLASS_TOK.finditer(text):
            if m.group(1):
                out.add(f"{m.group(1).upper()}-{m.group(2)}")
    return out


ORDER = {"high": 0, "medium": 1, "low": 2}


def find(plans, specs=None):
    """All rule findings, most serious first."""
    segs, structs = parse(plans)
    found = (pipe_checks(segs, structs, spec_pipe_classes(specs)) +
             reference_checks(plans, specs) + schedule_checks(plans) +
             open_scope(plans, specs))
    # coordination findings first; the open-scope list always last
    found.sort(key=lambda f: (ORDER.get(f["severity"], 3),
                              f["kind"] == "open_scope",
                              f["page"] if f["page"] is not None else 1e9))
    return found


# ---- the RFI draft (deterministic; AI may reword it) --------------------------------

def draft(f, number=""):
    """A CSI-style RFI from a finding: subject, references, question,
    the conflicting quotes, proposed resolution, impacts."""
    refs = "; ".join(dict.fromkeys(
        f"Sheet {c['sheet']}" if c.get("doc", "plans") == "plans"
        else f"Specs p. {c['page'] + 1}" for c in f.get("cites") or []))
    quotes = "\n".join(f"  - {('Sheet ' + c['sheet']) if c.get('doc', 'plans') == 'plans' else 'Specs'}: \"{c['quote']}\""
                       for c in f.get("cites") or [])
    parts = [f"Subject: {f.get('title') or f['question'][:80]}",
             f"References: {refs or f.get('reference', '')}",
             "", f"Question: {f['question']}"]
    if quotes:
        parts += ["", "The documents say:", quotes]
    if f.get("proposal"):
        parts += ["", f"Proposed resolution: {f['proposal']}"]
    parts += ["", f"Why it matters: {f.get('reason', '')}",
              "Cost impact: TBD    Schedule impact: TBD"]
    return "\n".join(parts)


# ---- optional: let the local model smooth the wording ------------------------------

POLISH = (
    "Rewrite this construction RFI question as one clear, neutral, specific "
    "question to the engineer, at most 70 words. Keep every sheet number, "
    "structure ID, size, elevation, slope and spec section exactly as "
    "given. Do not add facts. Reply with the question only.\n\n")


def _facts(text):
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def polish(f, ask=None, on_text=None):
    """The finding's question reworded by the local model, or the original
    if the model drops or changes any number/reference (it is checked, not
    trusted). `ask(prompt, on_text) -> text`; defaults to Ollama, streamed.
    The prompt is the structured finding only - a few hundred characters,
    not the drawing text."""
    from . import review
    ask = ask or (lambda p, cb: review.stream(p, cb))
    facts = {"question": f["question"],
             "quotes": [c["quote"] for c in f.get("cites") or []]}
    import json
    reply = (ask(POLISH + json.dumps(facts), on_text) or "").strip()
    reply = reply.strip('"').strip()
    if not reply or len(reply) > 700 or \
            not _facts(f["question"]) <= _facts(reply):
        return f["question"], False
    return reply, True
