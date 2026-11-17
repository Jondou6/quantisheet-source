"""Scope a retrofit set states away from its work notes (Nov 12).

callouts.py reads the boxed notes. An estimator also takes scope from:

* the summary table on a general sheet - stations down the side, kinds
  of work across the top, an X where a station gets it (marks());
* sentences in the numbered notes - 'FURNISH AND INSTALL A 100A, 480V,
  3-PHASE MANUAL TRANSFER SWITCH', '4#1, #8 GND IN A 1-1/2" ALUMINUM
  RIGID CONDUIT' (equipment(), feeders());
* 'NOTES BY SYMBOL' on an electrical sheet - a numbered note says what
  to provide and its number stands on the drawing once per item
  (keyed());
* the run itself - the fence layer's lines measured at the sheet's
  bar scale, beside the length the note states (measured());
* what a replacement implies - the old one comes out (removals());
* the specification's rules for an assembly - 'line post spacing not
  exceeding 10 feet', '3 strands of barbed wire' (spec_facts(),
  fence_parts()).

Every row added here says where it came from in 'check', so the
estimator can tell a stated quantity from a worked-out one. Nothing is
invented: a rule that the documents don't give is not applied.
"""
import re

from . import callouts as co

MATRIX = "marked on the summary table; no note for it on the station sheet"
RATED = "rating read from the numbered notes"
FROM_NOTES = "from a sentence in the numbered notes, not a work note"
IMPLIED = "worked out: a replacement removes the old one"
BY_SPEC = "worked out from the specification"
MEASURE = "make-up read from the notes; the length has to be measured"
_SHEET = re.compile(r"^[A-Z]{1,2}-?\d{1,3}(?:\.\d+)?$")
MATCH_SHARE = 0.7
_STOP = {"AND", "OF", "THE", "FOR", "WITH", "TO", "AT", "A", "AN"}


def _cx(w):
    return (w[0] + w[2]) / 2.0


def _cy(w):
    return (w[1] + w[3]) / 2.0


def _groups(vals, gap):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


# ------------------------------------------------------ the summary table
def marks(words, min_marks=6):
    """[(sheet, heading)] for each X of a summary table. `words` are
    (x0, y0, x1, y1, text) as shown on the page. [] when the page has
    no such table."""
    xs = [w for w in words if w[4].strip().upper() == "X"]
    sheets = [w for w in words if _SHEET.match(w[4].strip())]
    if len(xs) < min_marks or len(sheets) < 3:
        return []
    h = sorted(w[3] - w[1] for w in xs)[len(xs) // 2] or 1.0
    # the sheet numbers stand in one column
    best = []
    for s in sheets:
        col = [t for t in sheets if abs(_cx(t) - _cx(s)) <= 2.5 * h]
        if len(col) > len(best):
            best = col
    if len(best) < 3:
        return []
    cols = _groups([_cx(w) for w in xs], 1.5 * h)
    pitch = min((b - a for a, b in zip(cols, cols[1:])), default=8 * h)
    rows_y = sorted(_cy(s) for s in best)
    rpitch = min((b - a for a, b in zip(rows_y, rows_y[1:])), default=4 * h)
    top = min(w[1] for w in best + xs)
    heads = {}
    for c in cols:
        cand = [w for w in words if w[3] <= top and
                abs(_cx(w) - c) <= 0.47 * pitch and
                re.search(r"[A-Za-z]{2}", w[4])]
        cand.sort(key=lambda w: -w[3])
        keep, last = [], None
        for w in cand:                     # walk up until the lines stop
            if last is not None and last - w[3] > 2.2 * h:
                break
            keep.append(w)
            last = min(last, w[1]) if last is not None else w[1]
        keep.sort(key=lambda w: (round(w[1] / (0.6 * h)), w[0]))
        heads[c] = co._clean(" ".join(w[4] for w in keep))
    out = []
    for x in xs:
        c = min(cols, key=lambda v: abs(v - _cx(x)))
        s = min(best, key=lambda t: abs(_cy(t) - _cy(x)))
        if abs(_cy(s) - _cy(x)) <= 0.6 * rpitch and heads.get(c):
            out.append((s[4].strip(), heads[c]))
    return sorted(set(out))


def _stems(text):
    return {re.sub(r"(ING|S)$", "", w) for w in
            re.findall(r"[A-Z]{2,}", co._clean(text)) if w not in _STOP}


def covered(heading, what, share=MATCH_SHARE):
    """Does a note's item cover a table heading? Most of the heading's
    words are in it."""
    hs = _stems(heading)
    return bool(hs) and len(hs & _stems(what)) / len(hs) >= share


MEASURED_SHARE = 0.5


def _covers(row, heading):
    """A counted note covers a heading it names. A measured note (a
    length of fence) covers it too, unless the heading's thing is only
    tacked on after an AND ('130 LF SITE FENCING AND GATE' is fence by
    the foot; the gate is still to count)."""
    if row["unit"] == "EA":
        return covered(heading, row["what"])
    main = re.split(r"\s+AND\s+", row["what"])[0]
    return covered(heading, main, MEASURED_SHARE)


def from_table(rows, table_marks):
    """Rows for marks that no note on that sheet covers."""
    out = []
    for sheet, heading in table_marks:
        here = [r for r in rows if r.get("sheet") == sheet]
        if any(_covers(r, heading) for r in here):
            continue
        if _stems(heading) <= {"DEMOLITION", "DEMOLISH"} and any(
                r["action"] in ("Demolish", "Remove") for r in here):
            continue
        r = co._row("", 1, "EA", heading, "", [MATRIX])
        r.update(sheet=sheet, page=None, rect=None, source="table")
        out.append(r)
    return out


# ------------------------------------------------------ numbered notes
_RATING = (r"(\d{2,4}\s*A(?:MP)?S?\s*,\s*\d{3}\s*V\s*,\s*\d\s*-?\s*PHASE)")
_EQUIP = re.compile(
    r"(?:FURNISH AND INSTALL|INSTALL|PROVIDE)\s+AN?\s+" + _RATING +
    r"\s+([A-Z][A-Z \-]{3,60}?(?:SWITCH|PANELBOARD|PANEL|GENERATOR|"
    r"BREAKER|DISCONNECT|TRANSFORMER))\b", re.I)
_FEED = re.compile(
    r"(\d)\s*#\s*(\d+(?:/0)?)\s*,\s*#\s*(\d+(?:/0)?)\s*G(?:ND|ROUND)\.?\s+IN\s+"
    r"AN?\s+([\d\-/ ]+?)\s*(?:\"|-?INCH|IN\.)\s+([A-Z ]{3,40}?CONDUIT)", re.I)


def _flat(text):
    return re.sub(r"\s+", " ", text or "")


def equipment(text):
    """[(rating, item)] from sentences like 'FURNISH AND INSTALL A 100A,
    480V, 3-PHASE MANUAL TRANSFER SWITCH'."""
    out = []
    for m in _EQUIP.finditer(_flat(text)):
        rating = re.sub(r"\s+", "", m.group(1).upper()).replace(",", ", ")
        rating = rating.replace("-PHASE", " PHASE").replace("PHASE",
                                                             " PHASE")
        rating = re.sub(r"\s+", " ", rating).replace("- ", " ")
        item = (rating, co._clean(m.group(2)))
        if item not in out:
            out.append(item)
    return out


def feeders(text):
    """[(conductors, wire, ground, conduit size, conduit)] for each run
    the notes describe; the same make-up twice is two runs."""
    return [(int(m.group(1)), "#" + m.group(2), "#" + m.group(3),
             m.group(4).strip() + '"', co._clean(m.group(5)))
            for m in _FEED.finditer(_flat(text))]


def from_sentences(rows, text, sheet):
    """Put a rating on the note it belongs to, or add the item when no
    note has it; add each feeder's make-up with the length to measure."""
    out = []
    for rating, item in equipment(text):
        hit = next((r for r in rows if r.get("sheet") == sheet and
                    r["unit"] == "EA" and covered(item, r["what"])), None)
        if hit:
            if rating not in hit["what"]:
                hit["what"] = rating + " " + hit["what"]
                hit["check"].append(RATED)
            continue
        r = co._row("Install", 1, "EA", rating + " " + item, "",
                    [FROM_NOTES])
        r.update(sheet=sheet, page=None, rect=None, source="notes")
        out.append(r)
    for n, wire, gnd, size, conduit in feeders(text):
        for what, mult in ((f"{size} {conduit}", 1), (f"{wire} WIRE", n),
                           (f"{gnd} GROUND WIRE", 1)):
            r = co._row("Install", 0, "LF", what, "", [MEASURE])
            r.update(sheet=sheet, page=None, rect=None, source="notes",
                     per_run_ft=mult)
            out.append(r)
    return out



# ------------------------------------------------------ notes by symbol
KEYED = ("from a keyed note; counted by its number on the sheet - other "
         "numbers on a sheet can look like a symbol, so check the count")
KEY_ONCE = "from a keyed note; its symbol was not found, counted as 1"
_TABLE_ROW = re.compile(r"\d\s*\"\s*C\b|^[A-Z]{2,5}-\d+[A-Z]?$|^SPARE$", re.I)
_KEYHEAD = re.compile(r"NOTES?\s+BY\s+SYMBOL|KEY(?:ED)?\s*NOTES", re.I)
_PROVIDE = re.compile(
    r"\b(?:PROVIDE|FURNISH AND INSTALL|INSTALL)\s+(?:AN?\s+|NEW\s+|"
    r"ADDITIONAL\s+)*(?:NEW\s+)?(.+)$", re.I)
_NEW_IS = re.compile(r"\bNEW\s+([A-Z][A-Z \-]{3,50}?)\s+SHALL\s+BE\b", re.I)
_DEMO = re.compile(r"^(?:EXISTING\s+)?(.+?)\s+SHALL\s+BE\s+(?:DEMOLISHED|"
                   r"REMOVED)\b", re.I)
_TAIL = re.compile(r"\s*(?:,\s*(?:WHICH|MOUNTED|WITH\s+THE)\b|\s+(?:ON|AT|"
                   r"FOR|PER|IN ACCORDANCE|TO METRO|AS REQUIRED|WHICH)\s+THE"
                   r"\b|\s+FOR\s+FUTURE\b|\s+INSTALL\s+PER\b).*$", re.I)


def _note_items(text):
    """[(action, item)] one keyed note asks for. A note that only
    explains ('SHALL REMAIN', 'SHALL NOT EXCEED') asks for nothing."""
    out = []
    for sent in re.split(r"(?<=[A-Z0-9\)\"])\.\s+", _flat(text).strip(" .")):
        sent = sent.strip(" .")
        m = _DEMO.match(sent)
        if m:
            out.append(("Demolish", co._clean(m.group(1))))
            continue
        m = re.match(r"^(?:DEMOLISH|DEMOLITION(?:\s+OF)?|REMOVE)\s+"
                     r"(?:THE\s+)?(.+)$", sent, re.I)
        if m:
            out.append(("Demolish", co._clean(m.group(1))))
            continue
        if re.search(r"\bSHALL\s+(?:REMAIN|NOT)\b|\bREFER\s+TO\b", sent,
                     re.I) and not re.match(r"PROVIDE|INSTALL", sent, re.I):
            m = _NEW_IS.search(sent)
            if m:
                out.append(("Install", co._clean(m.group(1))))
            continue
        m = _PROVIDE.match(sent)
        if m:
            what = co._clean(_TAIL.sub("", m.group(1)))
            if what and not re.match(
                    r"(EXTERNALLY|ALL|PER|ELECTRICAL EQUIPMENT TO)\b", what):
                out.append(("Install", what))
            continue
        m = _NEW_IS.search(sent)
        if m:
            out.append(("Install", co._clean(m.group(1))))
    return out


IN_SYMBOL = "from a keyed note; counted by its symbols on the sheet"
TYPICAL = ("its symbol is marked TYP: one symbol stands for every one like "
           "it - count them on the sheet")
TYP_COUNTED = ("its symbol is marked TYP: counted the {n} symbols{label} "
               "on the sheet that look like the one it points at - check "
               "the count")
SYMBOL_KEYS = 3        # a shape is the notes' symbol when it holds this many
#                        different note numbers


def pick_symbols(pairs, keys):
    """{note number: count} from [(number, shape)] - every 1-2 digit
    number on the sheet with the small drawn shape around it (None for
    none). The notes' symbol is the shape that holds the most different
    note numbers (a hexagon, a diamond...); numbers in any other shape,
    or in none, are something else - a detail bubble, a duct number.
    None when no shape holds SYMBOL_KEYS of the notes' numbers."""
    by = {}
    for num, shape in pairs:
        if shape is not None and num in keys:
            by.setdefault(shape, {})
            by[shape][num] = by[shape].get(num, 0) + 1
    if not by:
        return None
    best = max(by.values(), key=lambda c: (len(c), sum(c.values())))
    return dict(best) if len(best) >= SYMBOL_KEYS else None


def page_symbols(page):
    """[(number, shape)] for pick_symbols: shape is (straight pieces,
    curved pieces, width, height) of the smallest drawn shape, up to
    40 points across, around the number."""
    import fitz
    small = []
    for d in page.get_drawings():
        r = d["rect"]
        if 4 <= max(r.width, r.height) <= 40:
            kinds = [it[0] for it in d["items"]]
            small.append((r, (kinds.count("l"), kinds.count("c"),
                              int(round(r.width)), int(round(r.height)))))
    out = []
    for w in page.get_text("words"):
        t = w[4].strip()
        if not t.isdigit() or len(t) > 2:
            continue
        c = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
        best = None
        for r, sig in small:
            if r.contains(c) and (best is None or
                                  r.get_area() < best[0].get_area()):
                best = (r, sig)
        out.append((int(t), best[1] if best else None))
    return out


def _shape_sig(d):
    kinds = [it[0] for it in d["items"]]
    r = d["rect"]
    return (kinds.count("l"), kinds.count("c"), kinds.count("re"),
            int(round(r.width)), int(round(r.height)), bool(d.get("fill")))


def _ends(d):
    """The end points of a drawn path's line pieces."""
    pts = []
    for it in d["items"]:
        if it[0] == "l":
            pts += [it[1], it[2]]
        elif it[0] == "c":
            pts += [it[1], it[4]]
    return pts


def typical_counter(page, symbols=None, debug=None):
    """A typ_count(n) for keyed(): for the note symbol n marked TYP, follow
    its leader line to the symbol it points at, then count the symbols on
    the sheet drawn the same way (and, when that symbol has a short label
    beside it such as 'G', with the same label). Returns (count, label) or
    None when the leader or its target can't be found."""
    import fitz
    drawings = page.get_drawings()
    small = [d for d in drawings if 3 <= max(d["rect"].width,
                                             d["rect"].height) <= 40]
    words = page.get_text("words")
    pairs = symbols if symbols is not None else page_symbols(page)

    def shape_of_notes():
        by = {}
        for num, shp in pairs:
            if shp is not None:
                by.setdefault(shp, set()).add(num)
        return max(by, key=lambda k: len(by[k])) if by else None
    note_shape = shape_of_notes()

    def note_rects(n):
        out = []
        for w in words:
            if w[4].strip() != str(n):
                continue
            c = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            best = None
            for d in small:
                r = d["rect"]
                kinds = [it[0] for it in d["items"]]
                sig = (kinds.count("l"), kinds.count("c"),
                       int(round(r.width)), int(round(r.height)))
                if r.contains(c) and sig == note_shape and (
                        best is None or r.get_area() < best.get_area()):
                    best = r
            if best is not None:
                out.append(best)
        return out

    def near_typ(r):
        h = max(r.width, r.height)
        for w in words:
            if re.fullmatch(r"TYP(?:ICAL)?\.?", w[4].strip(), re.I):
                wr = fitz.Rect(w[:4])
                if (wr.intersects(r + (-1.5 * h, -1.5 * h, 1.5 * h,
                                       1.5 * h))):
                    return True
        return False

    def label_near(r):
        h = max(r.width, r.height, 4)
        c = (r.tl + r.br) / 2
        best = None
        for w in words:
            t = w[4].strip()
            if not (1 <= len(t) <= 2 and t.isalpha() and t.isupper()):
                continue
            wc = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            dist = abs(wc - c)
            if dist <= 2.2 * h and not r.contains(wc) and (
                    best is None or dist < best[0]):
                best = (dist, t)
        return best[1] if best else None

    say = debug.append if debug is not None else (lambda *_: None)

    def count(n):
        say(("note shape", note_shape, "rects", note_rects(n)))
        for rs in note_rects(n):
            if not near_typ(rs):
                say(("no TYP near", rs))
                continue
            c0 = (rs.tl + rs.br) / 2
            grab = rs + (-3, -3, 3, 3)
            far = None
            for d in drawings:
                if d["rect"] == rs or max(d["rect"].width,
                                          d["rect"].height) > 600:
                    continue
                pts = _ends(d)
                if not any(grab.contains(p) for p in pts):
                    continue
                if d["rect"].width <= rs.width + 1 and \
                        d["rect"].height <= rs.height + 1:
                    continue                      # the symbol itself
                p = max(pts, key=lambda q: abs(q - c0))
                if far is None or abs(p - c0) > abs(far - c0):
                    far = p
            say(("leader end", far))
            if far is None:
                continue
            target = None
            for d in small:
                r = d["rect"]
                if not (r + (-12, -12, 12, 12)).contains(far):
                    continue
                kinds = [it[0] for it in d["items"]]
                if "c" not in kinds and "re" not in kinds and \
                        len(kinds) <= 3:
                    continue                      # a leader piece, an arrow
                if r.width < 4 or r.height < 4:
                    continue                      # a dot, a tick
                dist = abs((r.tl + r.br) / 2 - far)
                if target is None or dist < target[0]:
                    target = (dist, d)
            say(("target", target and (_shape_sig(target[1]),
                                       target[1]["rect"])))
            if target is None:
                continue
            sig = _shape_sig(target[1])
            label = label_near(target[1]["rect"])
            same = [d for d in small if _shape_sig(d) == sig]
            if label:
                same = [d for d in same if label_near(d["rect"]) == label]
            if same:
                return len(same), label
        return None
    return count


def keyed(blocks, sheet="", page=None, symbols=None, typ_count=None):
    """Rows from a sheet's 'NOTES BY SYMBOL': each note that asks for
    something, counted by how many times its number stands as a symbol
    on the drawing. `blocks` as callouts.page_blocks(); `symbols` as
    page_symbols() lets the count go by the symbol's drawn shape.
    `typ_count(n)` (typical_counter()) counts what a note marked TYP
    points at, so one symbol can stand for all of them."""
    head = next((b for b in blocks if _KEYHEAD.search(" ".join(b[0]))), None)
    if not head:
        return []
    hx, hy = head[1][0], head[1][1]
    h = max(head[1][3] - head[1][1], 1.0)
    notes, used = {}, {id(head[0])}
    for lines, rect in blocks:
        m = re.match(r"^(\d{1,2})\.$", lines[0].strip()) if lines else None
        if (m and len(lines) > 1 and abs(rect[0] - hx) <= 2 * h and
                rect[1] > hy):
            notes[int(m.group(1))] = " ".join(lines[1:])
            used.add(id(lines))
    if not notes:
        return []
    count = {}
    for lines, rect in blocks:
        if id(lines) in used or len(lines) > 5:
            continue
        if any(_SHEET.match(ln.strip()) for ln in lines):
            continue                       # a detail bubble: '1 / E-3'
        if any(_TABLE_ROW.search(ln) for ln in lines):
            continue                       # a schedule row: '1 / GEN-D / 2"C.'
        for ln in lines:
            if re.fullmatch(r"\d{1,2}", ln.strip()) and \
                    int(ln) in notes:
                count[int(ln)] = count.get(int(ln), 0) + 1
    typical = set()                # '16 / TYP': one symbol stands for all
    for lines, rect in blocks:
        if id(lines) in used or len(lines) > 5:
            continue
        if any(re.fullmatch(r"TYP(?:ICAL)?\.?", ln.strip(), re.I)
               for ln in lines):
            typical |= {int(ln) for ln in lines
                        if re.fullmatch(r"\d{1,2}", ln.strip()) and
                        int(ln) in notes}
    # 'TYP' set as its own text just under or beside the symbol
    nums = [(int(lines[0]), rect) for lines, rect in blocks
            if id(lines) not in used and len(lines) == 1 and
            re.fullmatch(r"\d{1,2}", lines[0].strip()) and
            int(lines[0]) in notes]
    for lines, rect in blocks:
        if len(lines) != 1 or not re.fullmatch(r"TYP(?:ICAL)?\.?",
                                               lines[0].strip(), re.I):
            continue
        h = max(rect[3] - rect[1], 1.0)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        best = None
        for n, r in nums:
            d = ((cx - (r[0] + r[2]) / 2) ** 2 +
                 (cy - (r[1] + r[3]) / 2) ** 2) ** 0.5
            if d <= 3 * h and (best is None or d < best[0]):
                best = (d, n)
        if best:
            typical.add(best[1])
    shaped = pick_symbols(symbols, set(notes)) if symbols else None
    if shaped is not None:
        count = shaped
    rows = []
    for n in sorted(notes):
        for k, (action, what) in enumerate(_note_items(notes[n])):
            q = count.get(n, 0) if k == 0 else 1
            r = co._row(action, q or 1, "EA", what, f"NOTE {n}",
                        [(IN_SYMBOL if shaped is not None else KEYED)
                         if q else KEY_ONCE])
            if n in typical and k == 0:
                got = typ_count(n) if typ_count else None
                if got and got[0] > r["qty"]:
                    r["qty"] = got[0]
                    r["check"] = [TYP_COUNTED.format(
                        n=got[0], label=f" marked '{got[1]}'" if got[1]
                        else "")]
                else:
                    r["check"].append(TYPICAL)
            r.update(sheet=sheet, page=page, rect=None, source="keyed")
            rows.append(r)
    return rows




# ------------------------------------------------------ one-line feeders
_TAG = re.compile(r"^[A-Z]{1,6}-?\d{1,3}[A-Z]?$")
_RUN = re.compile(
    r"^\s*(\d)\s*#\s*(\d+(?:/0)?)\s*,\s*(?:#\s*(\d+(?:/0)?)\s*G(?:ND)?\.?"
    r"\s*,\s*)?(\d+(?:[ \-]\d+/\d+|/\d+)?)\s*\"\s*C\.?\s*$", re.I)
ONE_LINE = ("make-up read from a feeder tag on the one-line diagram; the "
            "length has to be measured")


def feeder_tags(blocks):
    """{tag: (conductors, wire, ground or '', conduit size)} from a
    one-line diagram's feeder tags - 'UTIL-03P' over '4 #2, #8G.,
    1 1/4"C.'. A tag printed at both ends of its feeder is one feeder."""
    out = {}
    for lines, _rect in blocks:
        ls = [ln.strip() for ln in lines if ln and ln.strip()]
        for a, b in zip(ls, ls[1:]):
            m = _RUN.match(b)
            if _TAG.match(a) and m and a not in out:
                out[a] = (int(m.group(1)), "#" + m.group(2),
                          "#" + m.group(3) if m.group(3) else "",
                          re.sub(r"\s+", "-", m.group(4).strip()) + '"')
    return out


def from_feeder_tags(blocks, sheet="", page=None):
    rows = []
    for tag, (n, wire, gnd, size) in sorted(feeder_tags(blocks).items()):
        parts = [(f"{size} CONDUIT", 1), (f"{wire} WIRE", n)]
        if gnd:
            parts.append((f"{gnd} GROUND WIRE", 1))
        for what, mult in parts:
            r = co._row("Install", 0, "LF", what, f"FEEDER {tag}",
                        [ONE_LINE])
            r.update(sheet=sheet, page=page, rect=None, source="oneline",
                     per_run_ft=mult)
            rows.append(r)
    return rows


# ------------------------------------------------------ runs as drawn
MEASURED = ("measured on the sheet: straight length of the fence layer's "
            "lines at the sheet's bar scale; compare with the note")
HEAVY = 3.0          # a new run is drawn this many times heavier


def bar_ppf(words):
    """Points per foot from a bar scale ('0  10\'  20\'' over 'SCALE IN
    FEET'): the distance between the 0 and the first tick's label. None
    when the sheet has no such bar or two bars disagree."""
    feet = [w for w in words if re.fullmatch(r"\d{1,4}'", w[4].strip())]
    zeros = [w for w in words if w[4].strip() == "0"]
    found = set()
    for z in zeros:
        h = max(z[3] - z[1], 1.0)
        row = sorted((w for w in feet if abs(_cy(w) - _cy(z)) <= 0.6 * h and
                      0 < _cx(w) - _cx(z) <= 60 * h), key=_cx)
        if not row:
            continue
        first = row[0]
        ft = float(first[4].strip().rstrip("'"))
        if ft > 0:
            found.add(round((_cx(first) - _cx(z)) / ft, 3))
    if not found or max(found) - min(found) > 0.03 * max(found):
        return None
    return sum(found) / len(found)


def fence_lines(pens):
    """(new, all) lengths from [(layer, pen width, straight length)] of
    the layers named for fence. 'New' is a layer named PROP/NEW, or a
    pen at least HEAVY times the lightest fence pen."""
    fence = [(str(a).upper(), w, n) for a, w, n in pens
             if "FENC" in str(a).upper() and n > 0 and
             "TX" not in str(a).upper()]
    if not fence:
        return 0.0, 0.0
    light = min(w for _, w, _ in fence if w > 0) if any(
        w > 0 for _, w, _ in fence) else 0.0
    new = sum(n for a, w, n in fence if re.search(r"PROP|NEW", a) or
              (light and w >= HEAVY * light and len({x[1] for x in fence})
               > 1))
    # a sheet whose whole fence is drawn heavy has no light pen to
    # compare with: a heavy-only fence on an EX layer is still new work
    if not new and len({x[1] for x in fence}) == 1 and light >= 1.5:
        new = sum(n for _, _, n in fence)
    return new, sum(n for _, _, n in fence)


def page_pens(page):
    import math
    out = {}
    for d in page.get_drawings():
        key = (d.get("layer") or "", round(d.get("width") or 0, 3))
        n = sum(math.hypot(it[2].x - it[1].x, it[2].y - it[1].y)
                for it in d["items"] if it[0] == "l")
        out[key] = out.get(key, 0.0) + n
    return [(a, w, n) for (a, w), n in out.items()]


def measured(rows, pens, ppf, sheet):
    """Rows for the fence as drawn, on a sheet whose notes give fence or
    barbed wire by the foot."""
    said = [r for r in rows if r.get("sheet") == sheet and
            r["unit"] == "LF" and re.search(r"FENC|BARBED", r["what"])]
    if not said or not ppf:
        return []
    new, every = fence_lines(pens)
    out = []
    stated = ", ".join(f"{r['qty']:g} LF {r['action'].lower()}"
                       for r in said)
    for n, what in ((new, "NEW FENCE LINE AS DRAWN"),
                    (every, "WHOLE FENCE LINE AS DRAWN")):
        if n <= 0:
            continue
        r = co._row("", round(n / ppf, 1), "LF", what, "",
                    [MEASURED + f" (notes: {stated})"])
        r.update(sheet=sheet, page=None, rect=None, source="measured")
        out.append(r)
    return out


# ------------------------------------------------------ what follows
def removals(rows):
    """The removal half of every 'remove and replace'."""
    out = []
    for r in rows:
        if r["action"] != "Remove and replace":
            continue
        what = re.split(r"\s+WITH\s+", r["what"])[0]
        x = co._row("Remove", r["qty"], r["unit"], what, "",
                    [IMPLIED] + [c for c in r["check"] if c != co.NO_COUNT],
                    r["approx"])
        x.update(sheet=r.get("sheet"), page=r.get("page"),
                 rect=r.get("rect"), source="implied")
        out.append(x)
    return out


_SPACING = re.compile(r"LINE\s+POSTS?\s+SPACING\s*:?[^.]{0,60}?NOT\s+(?:EXCEEDING|"
                      r"EXCEED|MORE\s+THAN)\s+(\d+(?:\.\d+)?)\s*(?:FEET|FOOT|"
                      r"FT|')", re.I)
_STRANDS = re.compile(r"(\d|ONE|TWO|THREE|FOUR)\s+STRANDS?\s+OF\s+BARBED\s+"
                      r"WIRE", re.I)


def spec_facts(text):
    """{'post_spacing_ft', 'barbed_strands'} as far as the specification
    says them. A value the specification gives two ways is left out."""
    flat, out = _flat(text), {}
    sp = {float(m.group(1)) for m in _SPACING.finditer(flat)}
    if len(sp) == 1:
        out["post_spacing_ft"] = sp.pop()
    st = set()
    for m in _STRANDS.finditer(flat):
        v = m.group(1).upper()
        st.add(co._WORDS.get(v) or int(v))
    if len(st) == 1:
        out["barbed_strands"] = st.pop()
    return out


def is_fence(row):
    return (row["unit"] == "LF" and "FENC" in row["what"] and
            row["action"] in ("Install", "Remove and replace", "Replace"))


GATE_IN_LINE = ("this sheet also has a gate note: the gate opening may be "
                "inside the drawn line")
SOURCES = {"note": "Sheet note", "table": "Summary table",
           "notes": "Numbered note", "keyed": "Keyed note",
           "oneline": "One-line diagram",
           "implied": "Worked out", "spec": "From the specification",
           "measured": "Measured on the sheet"}


def _run_length(row, rows):
    """(feet, how) for a fence note: the new line as drawn when the
    sheet has one; the whole line as drawn when the note is the sheet's
    only fence note or says ALL; else what the note states."""
    here = [r for r in rows if r.get("sheet") == row.get("sheet")]
    drawn = {r["what"]: r["qty"] for r in here
             if r.get("source") == "measured"}
    if "NEW FENCE LINE AS DRAWN" in drawn:
        return drawn["NEW FENCE LINE AS DRAWN"], "the new line as drawn"
    notes = [r for r in here if r.get("source", "note") == "note" and
             r["unit"] == "LF" and re.search(r"FENC|BARBED", r["what"])]
    if "WHOLE FENCE LINE AS DRAWN" in drawn and (
            len(notes) == 1 or re.match(r"ALL\b", row["what"])):
        return drawn["WHOLE FENCE LINE AS DRAWN"], "the whole line as drawn"
    return row["qty"], "the length the note states"


def wire_only(r):
    """A fence note for its barbed wire alone ('REPLACE ALL SITE FENCING
    BARBED WIRE')."""
    return bool(re.search(r"\bBARB(?:ED)?\b", r["what"], re.I))


def fence_parts(rows, facts):
    """Posts and barbed wire strands for each sheet's new fence, by the
    specification's spacing and strand count, once per sheet."""
    out, done = [], set()
    notes = [r for r in rows if is_fence(r) and r["qty"] and
             r.get("source", "note") == "note"]
    # Nov 17: a note that replaces only the barbed wire ('SITE FENCING
    # BARBED WIRE') sets no posts; on a sheet with a fence note too, the
    # fence note covers the wire
    fenced = {r.get("sheet") for r in notes if not wire_only(r)}
    for r in notes:
        only = wire_only(r)
        if only and r.get("sheet") in fenced:
            continue
        feet, how = _run_length(r, rows)
        key = (r.get("sheet"), how)
        if how != "the length the note states":
            gap = sum(x["qty"] for x in rows
                      if x.get("sheet") == r.get("sheet") and
                      x["what"] == "GATE OPENINGS IN THE LINE")
            if gap and gap < feet:
                feet = round(feet - gap, 3)
                how += ", " + GATE_TAKEN_OUT.format(f=gap)
        if how != "the length the note states":
            if key in done:
                continue
            done.add(key)
        sp, st = facts.get("post_spacing_ft"), facts.get("barbed_strands")
        add = []
        if sp and not only:
            posts = int(feet / sp + 0.5) + 1
            add.append((posts, "EA", f"FENCE POSTS AT {sp:g} FT"))
        if st:
            add.append((round(feet * st, 3), "LF",
                        "STRAND BARBED WIRE REPLACED" if only
                        else "STRAND BARBED WIRE ON NEW FENCE"))
        for q, u, what in add:
            x = co._row("Install", q, u, what, "",
                        [BY_SPEC + f", on {how} ({feet:g} LF)"], r["approx"])
            x.update(sheet=r.get("sheet"), page=None, rect=None,
                     source="spec")
            out.append(x)
    return out


_GATE_W = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-\s*)?(?:FOOT|FEET|FT\.?|')\s*(?:WIDE\s+)?"
    r"(?:(?:DOUBLE|SINGLE|SWING|SLIDE|SLIDING|CANTILEVER|VEHICLE|VEHICULAR|"
    r"ACCESS|CHAIN[\s-]*LINK)\s+)*GATE\b", re.I)
GATE_OPENING = ("gate openings the notes give a width for, taken out of the "
                "line as drawn for posts and barbed wire")
GATE_TAKEN_OUT = "less {f:g} LF of gate openings"


def gate_openings(rows, sheet):
    """(feet, gates) of new gates with a stated width on a sheet."""
    feet = gates = 0
    for r in rows:
        if (r.get("sheet") != sheet or r["unit"] != "EA" or
                r.get("source") == "implied" or
                r["action"] not in ("Install", "Remove and replace",
                                    "Replace")):
            continue
        m = _GATE_W.search(r["what"])
        if m and r["qty"]:
            feet += float(m.group(1)) * r["qty"]
            gates += r["qty"]
    return feet, gates


def flag_gates(rows):
    """On a sheet with a measured line: gates whose width the notes give
    become a GATE OPENINGS row (taken out for posts and wire); a gate
    note without a width marks the measured new line instead."""
    gates = {r.get("sheet") for r in rows if re.search(r"\bGATE\b",
                                                       r["what"]) and
             not re.search(r"\bGATE\s+VALVE", r["what"])}
    sheets = {r.get("sheet") for r in rows if r.get("source") == "measured"}
    for sheet in sheets & gates:
        if any(r.get("sheet") == sheet and
               r["what"] == "GATE OPENINGS IN THE LINE" for r in rows):
            continue
        feet, n = gate_openings(rows, sheet)
        if feet:
            x = co._row("", feet, "LF", "GATE OPENINGS IN THE LINE", "",
                        [GATE_OPENING + f" ({n:g} gate{'s' if n != 1 else ''})"])
            x.update(sheet=sheet, page=None, rect=None, source="measured")
            rows.append(x)
            continue
        for r in rows:
            if (r.get("source") == "measured" and r.get("sheet") == sheet
                    and r["what"].startswith("NEW") and
                    GATE_IN_LINE not in r["check"]):
                r["check"].append(GATE_IN_LINE)


def sheet_table(rows):
    """Rows for a spreadsheet: every row with where it came from."""
    out = [["Sheet", "From", "Action", "Item", "Qty", "Unit", "Detail",
            "Check"]]
    for r in rows:
        q = "measure" if (r["unit"] == "LF" and not r["qty"]) else \
            co._q(r["qty"])
        out.append([r.get("sheet", ""),
                    SOURCES.get(r.get("source", "note"), ""), r["action"],
                    r["what"], q, r["unit"], r["ref"],
                    "; ".join(r["check"])])
    return out


def export_xlsx(rows, path):
    from . import acrobat
    tot, _each = co.table([r for r in rows if r["qty"]])
    acrobat.write_xlsx(path, [("Totals", tot),
                              ("Every row", sheet_table(rows))])
    return path


def page_words(page):
    import fitz
    rot = page.rotation_matrix
    out = []
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4]) * rot
        r.normalize()
        out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    return out


def read_set(path, spec_text="", sheet_of=None):
    """Everything: the work notes, then what the table, the numbered
    notes and the specification add. Returns (rows, facts)."""
    import fitz
    from . import overlay
    rows, table_marks, texts, drawn = [], [], {}, {}
    with fitz.open(path) as doc:
        for n, page in enumerate(doc):
            try:
                name = (sheet_of(page) if sheet_of else
                        overlay.sheet_number(page)) or f"p.{n + 1}"
            except Exception:                              # noqa: BLE001
                name = f"p.{n + 1}"
            got = co.read_page(page, name, n)
            for r in got:
                r["source"] = "note"
            rows += got
            blocks = co.page_blocks(page)
            if any(_KEYHEAD.search(" ".join(b[0])) for b in blocks):
                syms = page_symbols(page)
                rows += keyed(blocks, name, n, syms,
                              typical_counter(page, syms))
            rows += from_feeder_tags(blocks, name, n)
            words = page_words(page)
            table_marks += marks(words)
            if any(r["unit"] == "LF" for r in got):
                drawn[name] = (page_pens(page), bar_ppf(words))
            texts[name] = page.get_text("text")
    rows += from_table(rows, table_marks)
    for name, text in texts.items():
        rows += from_sentences(rows, text, name)
    rows += removals(rows)
    for name, (pens, ppf) in drawn.items():
        rows += measured(rows, pens, ppf, name)
    flag_gates(rows)
    facts = spec_facts(spec_text)
    rows += fence_parts(rows, facts)
    return rows, facts


def pdf_text(path):
    import fitz
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)
