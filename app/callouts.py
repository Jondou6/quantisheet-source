"""Work callouts (Nov 12): the quantities a retrofit or upfit set states
in words on the sheet.

Rehab and upfit drawings often carry the takeoff in boxed notes rather
than in linework:

    INSTALL:                      REMOVE AND REPLACE:
    1 - 6-INCH PLUG VALVE         105 LF SITE FENCING
    1 - PIPE SUPPORT              (SEE DETAIL 5.0)

parse() reads one such note into rows (action, quantity, unit, what,
detail). read_page() finds the notes on a sheet and summary() adds the
same item up across the set. Nothing is guessed: a note with no number
counts as 1 and is marked to be checked, "APPROX." stays marked, a note
that is on a sheet twice is counted twice and marked (two views of one
item look the same), and of two copies drawn on top of each other one
is read.

Only parse()/summary()/table() are needed for the arithmetic; they use
no PDF library, so they can be tested with plain text.
"""
import re

ACTIONS = (
    ("REMOVE AND REPLACE", "Remove and replace"),
    ("FURNISH AND INSTALL", "Install"),
    ("DEMOLITION OF", "Demolish"),
    ("DEMOLISH", "Demolish"),
    ("INSTALL", "Install"),
    ("REPLACE", "Replace"),
    ("REMOVE", "Remove"),
    ("SALVAGE", "Salvage"),
    ("RELOCATE", "Relocate"),
    ("PROPOSED", "Install"),
)
_ACT = "|".join(a for a, _ in ACTIONS)
_HEAD = re.compile(rf"^({_ACT})\b\s*:?\s*(.*)$", re.I)
_REF = re.compile(r"\(\s*(?:SEE\s+)?(DETAILS?\b[^)]*)\)", re.I | re.S)
_COUNT = re.compile(r"^(?:AND\s+)?(\d{1,3})\s*-\s*"
                    r"(?!(?:FOOT|FEET|FT|INCH|IN)\b)(\S.*)$", re.I)
_WORDS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
          "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10}
_WORD_COUNT = re.compile(rf"^({'|'.join(_WORDS)})\s*\((\d{{1,3}})\)\s+(.+)$",
                         re.I)
UNITS = ("LF", "SF", "SY", "CY")
_MEAS = re.compile(r"(APPROX(?:\.|IMATELY)?\s*)?(\d[\d,]*(?:\.\d+)?)\s*"
                   rf"({'|'.join(UNITS)})\b", re.I)
_LOOSE = re.compile(r"^\(?\s*APPROX(?:\.|IMATELY)?\s*(\d[\d,]*(?:\.\d+)?)"
                    rf"\s*({'|'.join(UNITS)})\s*\)?$", re.I)
_INNER = re.compile(rf"^(.*?)\b({_ACT})\s*:\s*$", re.I)
_STOP = re.compile(r"^(CONTRACTOR|OWNER|ENGINEER)\b", re.I)
MAX_LINES = 16
MAX_CHARS = 420

NO_COUNT = "no number in the note; counted as 1"
APPROX = "the sheet says approximate"
DOUBLED = "the note's text is drawn twice on top of itself; read the sheet"
PROPOSED = "labelled 'proposed', not a work note; may repeat another note"
LOOSE = "a quantity printed by itself; named from the nearest label"
REPEAT = ("the same note is on this sheet more than once; each is counted - "
          "check they aren't two views of one item")
TWICE = "drawn twice on top of itself; the other copy was left out"


def _clean(s):
    s = re.sub(r"\s+", " ", s or "").strip(" .,;:-")
    return s.upper()


def _action(word):
    w = _clean(word)
    for a, name in ACTIONS:
        if w == a:
            return name
    return ""


def _num(s):
    v = float(s.replace(",", ""))
    return int(v) if v == int(v) else v


def is_callout(lines):
    ls = [ln.strip() for ln in lines if ln and ln.strip()]
    if not ls or len(ls) > MAX_LINES or sum(map(len, ls)) > MAX_CHARS:
        return False
    return bool(_HEAD.match(ls[0])) and not re.match(r"^\d+\.\s", ls[0])


def _undouble(lines):
    """A note drawn twice on itself comes out with its heading twice.
    Returns (lines without exact repeats, True when it was doubled)."""
    heads = [ln for ln in lines if _HEAD.match(ln) and ln.rstrip().endswith(":")]
    if len(heads) < 2:
        return lines, False
    out = []
    for ln in lines:
        if not out or _clean(ln) != _clean(out[-1]):
            out.append(ln)
    return out, True


def _row(action, qty, unit, what, ref, checks, approx=False):
    return {"action": action, "qty": qty, "unit": unit, "what": _clean(what),
            "ref": _clean(ref), "approx": bool(approx), "note": "",
            "check": list(dict.fromkeys(c for c in checks if c))}


def _measured(text, action, ref, checks):
    """Rows for a note that gives lengths or areas: 'REMOVE 24 LF AND
    INSTALL 50 LF OF SITE FENCING' is two rows of site fencing."""
    ms = list(_MEAS.finditer(text))
    rows, act = [], action
    lead = text[:ms[0].start()]
    m = re.search(rf"({_ACT})\s*$", lead, re.I)
    if m:
        act, lead = _action(m.group(1)) or act, lead[:m.start()]
    whats = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        tail = text[m.end():end]
        nxt = re.search(rf"\b(?:AND\s+)?({_ACT})\s*$", tail.strip(" ()"), re.I)
        next_act = None
        if nxt and i + 1 < len(ms):
            next_act = _action(nxt.group(1))
            tail = tail[:tail.upper().rfind(nxt.group(0).upper())]
        tail = re.sub(r"^\s*\)?\s*(?:OF\s+)?", "", tail)
        tail = re.sub(r"\s+AND\s*$", "", tail.strip(" ()"))
        whats.append(_clean(tail))
        rows.append([act, _num(m.group(2)), m.group(3).upper(),
                     bool(m.group(1))])
        if next_act:
            act = next_act
    lead = _clean(re.sub(r"\(\s*$", "", lead))
    for i in range(len(whats) - 1, -1, -1):          # fill names backwards
        if not whats[i]:
            whats[i] = whats[i + 1] if i + 1 < len(whats) else ""
    out = []
    for (a, q, u, approx), w in zip(rows, whats):
        w = " ".join(x for x in (lead, w) if x) if lead and lead != w else w
        out.append(_row(a, q, u, w or lead, ref,
                        checks + ([APPROX] if approx else []), approx))
    return out


def parse(lines):
    """Rows for one note (a list of its printed lines), [] when it isn't
    a work note."""
    ls = [ln.strip() for ln in lines if ln and ln.strip()]
    if not is_callout(ls):
        return []
    ls, doubled = _undouble(ls)
    head = _HEAD.match(ls[0])
    action = _action(head.group(1))
    checks = [DOUBLED] if doubled else []
    if head.group(1).upper() == "PROPOSED":
        checks.append(PROPOSED)
    body = ([head.group(2)] if head.group(2).strip() else []) + ls[1:]
    if doubled:
        body = [b for b in body
                if not (_HEAD.match(b) and b.endswith(":"))]
    text = "\n".join(body)
    refs = [_clean(r) for r in _REF.findall(text)]
    ref = "; ".join(dict.fromkeys(refs))
    text = _REF.sub(" ", text)
    text = re.sub(r"\s+AND\s+(?=\d{1,3}\s+-\s)", "\n", text)
    rows, segs, pre, note, done = [], [], [], [], False

    def flush():
        lead = re.sub(r"\s+AND\s*$", "", " ".join(pre).strip())
        if segs:
            if len(_clean(lead)) > 3:           # words before the first count
                rows.extend(_free(lead, action, ref, checks))
            for n, what in segs:
                rows.append(_row(action, n, "EA", what, ref, checks))
        else:
            rows.extend(_free(lead, action, ref, checks))
        segs.clear()
        pre.clear()

    for ln in (x.strip() for x in text.split("\n")):
        if not ln:
            continue
        if done or _STOP.match(ln):             # 'CONTRACTOR TO FLUSH...'
            done = True
            note.append(ln)
            continue
        inner = _INNER.match(ln)
        if inner:                               # '... AND INSTALL:' inside
            if inner.group(1).strip():
                (segs[-1].__setitem__(1, segs[-1][1] + " " + inner.group(1))
                 if segs else pre.append(inner.group(1).strip()))
            flush()
            action = _action(inner.group(2))
            continue
        m = _COUNT.match(ln)
        if m:
            segs.append([int(m.group(1)), m.group(2)])
        elif segs:
            segs[-1][1] += " " + ln
        else:
            pre.append(ln)
    flush()
    for r in rows:
        r["note"] = _clean(" ".join(note))
    return rows


def _free(text, action, ref, checks):
    text = re.sub(r"\s+", " ", text).strip()
    if not _clean(text):
        return []
    m = _WORD_COUNT.match(text)
    if m:
        return [_row(action, int(m.group(2)), "EA", m.group(3), ref, checks)]
    if _MEAS.search(text):
        return _measured(text, action, ref, checks)
    return [_row(action, 1, "EA", text, ref, checks + [NO_COUNT])]


def loose_measure(lines):
    """(qty, unit) for a quantity printed by itself ('APPROX. 50 SY')."""
    ls = [ln.strip() for ln in lines if ln and ln.strip()]
    m = _LOOSE.match(" ".join(ls)) if 0 < len(ls) <= 2 else None
    return (_num(m.group(1)), m.group(2).upper()) if m else None


# ------------------------------------------------------------- the sheet
def _near(a, b):
    """Gap between two rectangles (0 when they touch or overlap)."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _cover(a, b):
    """Share of the smaller rectangle that lies inside the other."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / small if small > 0 else 0.0


def read_blocks(blocks, sheet="", page=0):
    """Rows for a sheet from its text blocks [(lines, (x0, y0, x1, y1))].
    Each row gets 'sheet', 'page' and 'rect' (where the note is)."""
    rows, loose = [], []
    notes = [(lines, rect) for lines, rect in blocks if is_callout(lines)]
    dropped, twice = set(), set()
    for i, (la, ra) in enumerate(notes):
        for j in range(i + 1, len(notes)):
            lb, rb = notes[j]
            if i in dropped or j in dropped or _cover(ra, rb) < 0.5:
                continue
            lose = j if sum(map(len, la)) >= sum(map(len, lb)) else i
            dropped.add(lose)
            twice.add(i + j - lose)
    gone = {id(notes[i][0]) for i in dropped}
    kept = {id(notes[i][0]) for i in twice}
    for lines, rect in blocks:
        if id(lines) in gone:
            continue
        got = parse(lines)
        if got:
            for r in got:
                if id(lines) in kept:
                    r["check"].append(TWICE)
                r.update(sheet=sheet, page=page, rect=[float(v) for v in rect])
            rows += got
            continue
        lm = loose_measure(lines)
        if lm:
            loose.append((lm, rect))
    for (q, u), rect in loose:
        best = None
        for lines, r2 in blocks:
            if r2 == rect or loose_measure(lines) or parse(lines):
                continue
            t = _clean(" ".join(lines))
            if not t or len(t) > 60 or re.search(r"\d", t):
                continue
            d = _near(rect, r2)
            if best is None or d < best[0]:
                best = (d, t)
        h = max(rect[3] - rect[1], 1.0)
        what = best[1] if best and best[0] <= 6 * h else "QUANTITY WITH NO LABEL"
        r = _row("", q, u, what, "", [LOOSE, APPROX], True)
        r.update(sheet=sheet, page=page, rect=[float(v) for v in rect])
        rows.append(r)
    seen = {}
    for r in rows:
        seen.setdefault((r["action"], r["what"], r["qty"], r["unit"]),
                        []).append(r)
    for same in seen.values():
        if len(same) > 1:
            for r in same:
                if REPEAT not in r["check"]:
                    r["check"].append(REPEAT)
    return rows


def page_blocks(page):
    """[(lines, rect)] for a PDF page, in the page's shown (rotated)
    coordinates."""
    import fitz
    out = []
    rot = page.rotation_matrix
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        lines = ["".join(s["text"] for s in ln["spans"]).strip()
                 for ln in b["lines"]]
        lines = [ln for ln in lines if ln]
        if lines:
            r = fitz.Rect(b["bbox"]) * rot
            r.normalize()
            out.append((lines, (r.x0, r.y0, r.x1, r.y1)))
    return out


def read_page(page, sheet="", number=0):
    return read_blocks(page_blocks(page), sheet, number)


def read_pdf(path, pages=None, sheet_of=None):
    """Rows for a drawing set. `sheet_of(page)` names a sheet (default:
    the sheet number printed in the title block, else 'p.N')."""
    import fitz
    rows = []
    with fitz.open(path) as doc:
        for n in (range(len(doc)) if pages is None else pages):
            page = doc[n]
            name = ""
            try:
                if sheet_of:
                    name = sheet_of(page) or ""
                else:
                    from . import overlay
                    name = overlay.sheet_number(page) or ""
            except Exception:                              # noqa: BLE001
                name = ""
            rows += read_page(page, name or f"p.{n + 1}", n)
    return rows


# ------------------------------------------------------------ adding up
def key_of(what):
    """The same item worded a little differently lands on one key:
    '3 FOOT X 5 FOOT' and '3-FOOT X 5-FOOT', with or without 'EXISTING'."""
    k = _clean(what)
    k = re.sub(r"(\d)\s*-?\s*(FOOT|FEET|FT|INCH|IN)\b",
               lambda m: m.group(1) + "-" +
               ("FOOT" if m.group(2) in ("FOOT", "FEET", "FT") else "INCH"), k)
    k = " ".join(w for w in k.split()             # 'EXISTING', 'EIXSTING'
                 if sorted(w) != sorted("EXISTING"))
    k = re.sub(r"\bFITTINGS\b", "FITTING", k)
    k = re.sub(r"\bGRATES\b", "GRATE", k)
    k = re.sub(r"\bCOVERS\b", "COVER", k)
    return re.sub(r"\s+", " ", k).strip()


SAME_WORDING = 0.92


def _same(a, b):
    """Two wordings of one item: nearly the same letters and exactly the
    same numbers ('GENERATOR FUEL TANK' / 'GENERATOR FUEL LEVEL', a
    misspelt word). A different size is never the same item."""
    if re.findall(r"\d+(?:\.\d+)?", a) != re.findall(r"\d+(?:\.\d+)?", b):
        return False
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= SAME_WORDING


def summary(rows):
    """One line per (action, item, unit) with the total and where it is.
    Every note is counted; 'repeats' says how many of them repeat a note
    on the same sheet (they may be two views of one item). Wordings that
    differ by a letter or two are added together and listed in 'also'."""
    count = {}
    for r in rows:
        k = (r["action"], key_of(r["what"]), r["unit"])
        count[k] = count.get(k, 0) + 1
    lead = {}
    for k in sorted(count, key=lambda k: (-count[k], k)):
        for big in lead.values():
            if big[0] == k[0] and big[2] == k[2] and _same(big[1], k[1]):
                lead[k] = big
                break
        else:
            lead[k] = k
    out = {}
    for r in rows:
        own = (r["action"], key_of(r["what"]), r["unit"])
        k = lead[own]
        s = out.setdefault(k, {"action": k[0], "what": k[1], "unit": k[2],
                               "qty": 0, "sheets": [], "notes": 0,
                               "repeats": 0, "approx": False, "check": [],
                               "also": [], "_seen": set()})
        s["notes"] += 1
        s["qty"] += r["qty"]
        s["approx"] = s["approx"] or r["approx"]
        if own[1] != k[1] and own[1] not in s["also"]:
            s["also"].append(own[1])
        for c in r["check"]:
            if c not in s["check"]:
                s["check"].append(c)
        once = (r.get("sheet"), r["qty"])
        if REPEAT in r["check"] and once in s["_seen"]:
            s["repeats"] += 1
        s["_seen"].add(once)
        if r.get("sheet") and r["sheet"] not in s["sheets"]:
            s["sheets"].append(r["sheet"])
    res = []
    for s in out.values():
        s.pop("_seen")
        res.append(s)
    res.sort(key=lambda s: (s["what"], s["action"], s["unit"]))
    return res


def _q(v):
    return int(v) if float(v) == int(v) else round(float(v), 3)


def table(rows):
    """Rows for a spreadsheet: the totals, then every note."""
    tot = [["Action", "Item", "Qty", "Unit", "Sheets", "Notes read",
            "Repeated on a sheet", "Also worded", "Check"]]
    for s in summary(rows):
        tot.append([s["action"], s["what"], _q(s["qty"]), s["unit"],
                    ", ".join(s["sheets"]), s["notes"], s["repeats"],
                    "; ".join(s["also"]), "; ".join(s["check"])])
    each = [["Sheet", "Action", "Item", "Qty", "Unit", "Detail", "Note",
             "Check"]]
    for r in rows:
        each.append([r.get("sheet", ""), r["action"], r["what"], _q(r["qty"]),
                     r["unit"], r["ref"], r.get("note", ""),
                     "; ".join(r["check"])])
    return tot, each


def export_xlsx(rows, path):
    from . import acrobat
    tot, each = table(rows)
    acrobat.write_xlsx(path, [("Totals", tot), ("Every note", each)])
    return path
