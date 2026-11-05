"""Schedules: the tables printed on the drawings (door, window, hardware,
finish, equipment, plumbing fixture, air device, light fixture, panel,
plant, footing and column schedules), read from the positions of their
words, and the schedule keys counted on the plans.

1. read_page(page): every schedule on a sheet. The title ("DOOR
   SCHEDULE") is found first, then the header row(s) under it and the
   column x-ranges (from the table's vertical rules when it has them,
   otherwise from the header text). Rows come back as dicts keyed by the
   header names. A table whose cells don't line up with its columns (a
   cell across two columns, a row with no key, the same key twice) is
   marked not confident and its quantities are sent to review - never
   guessed.
2. count_tags(...): the schedule's keys (door numbers, P-1, SD-1, light
   type letters, plant keys...) counted on the plan sheets, inside the
   plan area only - the title block (found from the sheet's frame),
   schedules, legends and notes blocks are left out. The separate views
   on a sheet are found from their titles ("... PLAN" with a scale under
   it): a key is counted once per distinct position in the main view; a
   tag repeated in a second view (an enlarged plan, an attic or
   mezzanine view), a section or a detail is listed for review, never
   counted twice.
3. takeoff(doc, rows): the whole set - schedules read on every sheet that
   has one (detail / schedule sheets included), keys counted on the
   plans, and result lines with their CSI division:
       doors and frames 08, hardware 08 71, toilet accessories 10 28,
       equipment 11, plumbing fixtures 22 40, air devices 23 37,
       light fixtures 26 51, plants 32 93 (and windows 08 50,
       mechanical equipment 23, plumbing equipment 22, panels 26 24).
   Doors are counted from the door schedule rows and checked against the
   door tags on the plans; the two must agree, otherwise the doors (and
   the hardware sets counted from the schedule's hardware column) go to
   review.

The core works on plain tuples (words (x0, y0, x1, y1, text, block,
line, word), segments (x0, y0, x1, y1)) so it can be checked without a
PDF; the page helpers turn a fitz page into those, in the page's
displayed (rotated) coordinates.
"""
import logging
import math
import re
from collections import Counter

log = logging.getLogger(__name__)

# ------------------------------------------------------------- kinds
# kind, title pattern, CSI, disciplines whose plans carry its keys,
# line-name prefix
KINDS = [
    ("hardware", r"\b(?:DOOR\s+)?HARDWARE\s+(?:SET\s+|GROUP\s+)?"
                 r"(?:SCHEDULE|SETS?|GROUPS?)\b", "08 71 00",
     ("architectural", "interiors"), "Hardware set "),
    ("door", r"\bDOOR(?:\s*(?:AND|&|/)\s*FRAME)?S?\s+SCHEDULE\b",
     "08 10 00", ("architectural", "interiors"), ""),
    ("window", r"\b(?:WINDOW|STOREFRONT|GLAZING)\s+(?:TYPE\s+)?SCHEDULE\b",
     "08 50 00", ("architectural", "interiors"), "Window "),
    ("finish", r"\b(?:ROOM\s+)?FINISH(?:ES)?\s+SCHEDULE\b", "09 00 00",
     ("architectural", "interiors"), ""),
    ("toilet accessories", r"\b(?:TOILET\s+)?(?:ROOM\s+)?ACCESSOR(?:Y|IES)"
                           r"\s+SCHEDULE\b", "10 28 00",
     ("architectural", "interiors"), "Accessory "),
    ("air devices", r"\b(?:AIR\s+(?:DEVICE|DISTRIBUTION|INLET|OUTLET)S?|"
                    r"DIFFUSER|GRILLE|REGISTER|GRD)[\w\s,/&]*SCHEDULE\b",
     "23 37 00", ("mechanical",), ""),
    ("plumbing fixtures", r"\bPLUMBING\s+FIXTURES?\s+SCHEDULE\b|"
                          r"\bFIXTURE\s+SCHEDULE\b(?=.*@P)", "22 40 00",
     ("plumbing",), ""),
    ("light fixtures", r"\b(?:LIGHT(?:ING)?\s+FIXTURES?|LUMINAIRES?|"
                       r"FIXTURE)\s+SCHEDULE\b", "26 51 00",
     ("electrical",), "Light "),
    ("panel", r"\bPANEL(?:BOARD)?\s+(?:SCHEDULE\b|\"?[A-Z]{1,3}-?\d)",
     "26 24 00", ("electrical",), "Panel "),
    ("plants", r"\b(?:PLANT(?:ING)?|LANDSCAPE)\s+(?:SCHEDULE|LIST|LEGEND)\b",
     "32 93 00", ("landscape", "civil"), "Plant "),
    ("footing", r"\b(?:FOOTING|FOUNDATION|PIER)\s+SCHEDULE\b", "03 30 00",
     ("structural",), "Footing "),
    ("column", r"\bCOLUMN\s+SCHEDULE\b", "05 12 00", ("structural",), ""),
    ("plumbing equipment", r"\bPLUMBING\s+EQUIPMENT\s+SCHEDULE\b|"
                           r"\bWATER\s+HEATER\s+SCHEDULE\b|"
                           r"\bPUMP\s+SCHEDULE\b(?=.*@P)|"
                           r"\bFLOOR\s+DRAINS?\b[\w\s,/&]*SCHEDULE\b",
     "22 30 00",
     ("plumbing",), ""),
    ("mechanical equipment", r"\b(?:MECHANICAL|HVAC)\s+(?:EQUIPMENT\s+)?"
                             r"SCHEDULES?\b|\b(?:AIR\s+HANDL(?:ING|ER)|"
                             r"HEAT\s+PUMP|FAN|LOUVER|ROOFTOP|RTU|AHU|"
                             r"SPLIT\s+SYSTEM|CONDENSING|DOAS|ERV|VRF|"
                             r"BRANCH\s+CONTROLLER|EXHAUST\s+FAN|"
                             r"FURNACE|COOLING\s+COIL|FAN\s+COIL|"
                             r"UNIT\s+HEATER|BOILER|CHILLER|DUCTLESS|"
                             r"MINI[-\s]?SPLIT|KITCHEN\s+HOOD|EXHAUST\s+HOOD)"
                             r"[\w\s,/&-]*SCHEDULE\b", "23 00 00",
     ("mechanical",), ""),
    ("equipment", r"\b(?:EQUIPMENT|FURNITURE|CASEWORK)\s+SCHEDULE\b",
     "11 00 00", ("architectural", "interiors", "equipment"), ""),
]
_KIND_RX = [(k, re.compile(rx, re.I), csi, disc, pre)
            for k, rx, csi, disc, pre in KINDS]
CSI = {k: csi for k, _rx, csi, _d, _p in KINDS}
PREFIX = {k: pre for k, _rx, _c, _d, pre in KINDS}
DISCIPLINES = {k: d for k, _rx, _c, d, _p in KINDS}
# schedules whose rows are things counted on the plans by their key
COUNTED = ("window", "toilet accessories", "air devices",
           "plumbing fixtures", "light fixtures", "plants", "footing",
           "plumbing equipment", "mechanical equipment", "equipment")

# a title is a heading on its own, not a reference in a note
_REF_WORDS = re.compile(r"\b(SEE|REFER|PER|ON|IN|TO|FOR|WITH|AS)\b", re.I)
_SCHED_WORD = re.compile(r"\bSCHEDULES?\b|\bHARDWARE\s+(?:SETS?|GROUPS?)\b|"
                         r"\bPLANT(?:ING)?\s+(?:LIST|LEGEND)\b|"
                         r"\bPANEL(?:BOARD)?\s+\"?[A-Z]{1,3}-?\d", re.I)

# header words that name the key column, best first, per kind
_KEY_HDR = {
    "door": r"\bDOOR\s*(?:NO|NUMBER|#|MARK)\b|^(?:NO\.?|NUMBER|MARK|#|"
            r"OPENING(?:\s+NO\.?)?|DOOR)$|\bOPENING\s*(?:NO|#)",
    "hardware": r"\b(?:SET|GROUP|HW|HDWR?)\b.*\b(?:NO|#)|^(?:SET|GROUP|"
                r"NO\.?|#)$",
    "plants": r"\b(?:KEY|SYM(?:BOL)?|CODE|ABBR(?:EV)?\.?|ID|MARK|TAG)\b",
    "light fixtures": r"\b(?:TYPE|MARK|SYM(?:BOL)?|TAG|FIXTURE\s+TYPE|"
                      r"LUMINAIRE\s+TYPE|ID)\b",
    "finish": r"\b(?:ROOM\s*(?:NO|NUMBER|#)|NO\.?|NUMBER|ROOM)\b",
}
_KEY_HDR_ANY = (r"\b(?:MARK|TAG|KEY|SYM(?:BOL)?|TYPE|NO\.?|NUMBER|ID|CODE|"
                r"DESIGNATION|SET|ITEM\s*(?:NO|#))\b|^#$")
_QTY_HDR = re.compile(r"\b(?:QTY|QUANTITY|QUAN\.?|COUNT|NO\.\s*REQ'?D|"
                      r"NUMBER\s+REQ'?D|TOTAL)\b", re.I)
_DESC_HDR = re.compile(r"\b(?:DESCRIPTION|DESC\.?|FIXTURE|ITEM|NAME|"
                       r"COMMON\s+NAME|BOTANICAL\s+NAME|EQUIPMENT|TYPE|"
                       r"SERVICE|MANUFACTURER)\b", re.I)
# 'TOTAL COOLING (MBH)', 'TOTAL HEATING' are ratings, not how many
_NOT_QTY = re.compile(r"\b(?:MBH|BTUH?|CFM|KW|KVA|COOL\w*|HEAT\w*|TONS?|"
                      r"GPM|LOAD|AMPS?|WATTS?|LBS?|WEIGHT|AREA|PRESSURE|"
                      r"CAPACITY|SF|HP)\b", re.I)
_HW_HDR = re.compile(r"\b(?:HARDWARE|HDWR?\.?|HW)\b", re.I)
_SIZE_HDR = re.compile(r"\b(?:SIZE|DIMENSIONS?)\b", re.I)
_W_HDR = re.compile(r"\bWIDTH\b|^W$", re.I)
_L_HDR = re.compile(r"\bLENGTH\b|^L$", re.I)
_D_HDR = re.compile(r"\b(?:DEPTH|THICK(?:NESS)?|THK\.?)\b|^D$", re.I)
_H_HDR = re.compile(r"\b(?:HEIGHT|LENGTH|T\.?O\.?\s*STEEL|TOP\s+OF)\b", re.I)

_DIGIT = re.compile(r"\d")
# digits a header line can carry: sub-column numbers under a group ('1',
# '2', '3' under DEVICE CONNECTION) and a rating's trailing digit
# ('MIN. SEER2'); a data row has keys like 'EG-1' and values like '12x12'
_HDR_NUM = re.compile(r"^(?:\d|[A-Z][A-Z.]*\s*[A-Z]+\d)$")
_NOTE_HEAD = re.compile(r"^(?:GENERAL\s+|KEYED\s+|KEY\s+|SHEET\s+|PLAN\s+|"
                        r"CONSTRUCTION\s+|DRAWING\s+|PLUMBING\s+|"
                        r"MECHANICAL\s+|ELECTRICAL\s+|STRUCTURAL\s+|"
                        r"FRAMING\s+|SITE\s+|LANDSCAPE\s+|DEMOLITION\s+|"
                        r"SCHEDULE\s+|FOUNDATION\s+)?(?:NOTES?|REMARKS)\s*:?$",
                        re.I)
_LEGEND_HEAD = re.compile(r"^(?:[A-Z]+\s+){0,2}(?:LEGEND|SYMBOLS?|"
                          r"ABBREVIATIONS)\s*:?$", re.I)
_VIEW_WORD = re.compile(r"\bPLANS?\b", re.I)
_OTHER_VIEW = re.compile(r"\b(?:ELEVATIONS?|SECTIONS?|DETAILS?|VIEW|"
                         r"ISOMETRIC|RISER|DIAGRAM|MOUNTING\s+HEIGHTS?)\b",
                         re.I)
_FLOOR_TITLE = re.compile(r"\b(?:FLOOR|LEVEL\s*\d+)\s*$", re.I)
_SECONDARY_VIEW = re.compile(r"\b(?:ENLARGED|PARTIAL|ATTIC|MEZZANINE|"
                             r"KEY\s*PLAN|DETAIL|SECTION|ELEVATION|"
                             r"BLOW[-\s]?UP|INSET)\b", re.I)
_SCALE_TEXT = re.compile(r"\bSCALE\b|\d\s*(?:\"|''|IN\.?)\s*=\s*\d|"
                         r"=\s*1'\s*-?\s*0|\bN\.?T\.?S\.?\b|1\s*:\s*\d", re.I)
_LEVEL = re.compile(r"\b(?:(FIRST|SECOND|THIRD|FOURTH|FIFTH|GROUND|LOWER|"
                    r"UPPER|MAIN|BASEMENT|MEZZANINE|ATTIC|ROOF)\b|"
                    r"(\d+)(?:ST|ND|RD|TH)\s+FLOOR|LEVEL\s*(\d+|[A-Z])\b|"
                    r"FLOOR\s*(\d+))", re.I)
_QUOTES = str.maketrans({"″": '"', "”": '"', "“": '"', "′": "'", "’": "'",
                         "‘": "'", "‐": "-", "‑": "-", "–": "-", "—": "-"})


def kind_of(title, discipline=""):
    """The schedule kind for a title ('DOOR SCHEDULE' -> 'door'), or None.
    `discipline` tells a plumbing 'FIXTURE SCHEDULE' from a lighting one."""
    t = re.sub(r"\s+", " ", (title or "").translate(_QUOTES)).strip()
    if not _SCHED_WORD.search(t):
        return None
    tag = t + (" @P" if discipline == "plumbing" else "")
    for k, rx, _csi, _d, _p in _KIND_RX:
        if k == "light fixtures" and discipline == "plumbing" and \
                re.search(r"^\s*FIXTURE\s+SCHEDULE", t, re.I):
            continue
        if rx.search(tag):
            return k
    return None


# ------------------------------------------------------------- cells
def make_cells(words):
    """Words (x0, y0, x1, y1, text, block, line, n) -> cells: the words
    of one printed line that stand together, split at gaps wider than
    about one text height (a table's columns). [{text, x0, y0, x1, y1,
    h}]."""
    lines = {}
    for w in words:
        key = (w[5], w[6]) if len(w) > 6 else (round(w[1]), round(w[3]))
        lines.setdefault(key, []).append(w)
    out = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        cur = None
        for w in ws:
            h = max(w[3] - w[1], 1.0)
            if cur is not None and cur["ws"] and \
                    w[4] == cur["ws"][-1][2] and \
                    w[0] < cur["ws"][-1][0] + 0.5 * (w[2] - w[0]):
                # the same word printed again on top of itself (text made
                # to look bold by drawing it twice) is one word
                continue
            if cur is not None and w[0] - cur["x1"] <= 0.9 * max(h, cur["h"]) \
                    and abs((w[1] + w[3]) / 2 - (cur["y0"] + cur["y1"]) / 2) \
                    <= 0.5 * h:
                cur["text"] += " " + w[4]
                cur["ws"].append((w[0], w[2], w[4]))
                cur["x1"] = max(cur["x1"], w[2])
                cur["y0"] = min(cur["y0"], w[1])
                cur["y1"] = max(cur["y1"], w[3])
                continue
            cur = {"text": w[4], "x0": w[0], "y0": w[1], "x1": w[2],
                   "y1": w[3], "h": h, "ws": [(w[0], w[2], w[4])]}
            out.append(cur)
    for c in out:
        c["text"] = c["text"].translate(_QUOTES).strip()
        c["cx"] = (c["x0"] + c["x1"]) / 2
        c["cy"] = (c["y0"] + c["y1"]) / 2
    out = [c for c in out if c["text"]]
    # a line printed twice on top of itself (bold made by overprinting)
    keep, seen = [], {}
    for c in out:
        same = seen.setdefault(c["text"], [])
        if any(abs(p["x0"] - c["x0"]) <= 0.5 * c["h"] and
               abs(p["cy"] - c["cy"]) <= 0.5 * c["h"] for p in same):
            continue
        same.append(c)
        keep.append(c)
    return keep


def _split_cell(c, edges):
    """A cell whose words lie in two or more ruled columns ('ACT-1 / PT-4'
    and 'VARIES' printed close together across the CEILING FINISH /
    HEIGHT rule) -> one cell per column; else [c]."""
    ws = c.get("ws") or ()
    if len(ws) < 2:
        return [c]
    groups = {}
    for w in ws:
        cx = (w[0] + w[1]) / 2
        i = next((i for i in range(len(edges) - 1)
                  if edges[i] <= cx < edges[i + 1]), None)
        groups.setdefault(i, []).append(w)
    if len(groups) < 2 or None in groups:
        return [c]
    out = []
    for i in sorted(groups):
        g = groups[i]
        d = dict(c, text=" ".join(w[2] for w in g).strip(),
                 x0=min(w[0] for w in g), x1=max(w[1] for w in g), ws=g)
        d["cx"] = (d["x0"] + d["x1"]) / 2
        out.append(d)
    return out


def group_rows(cells, tol=0.45):
    """Cells -> rows (lists of cells, left to right), top to bottom: cells
    whose centres are within `tol` text heights of each other."""
    rows = []
    for c in sorted(cells, key=lambda c: c["cy"]):
        if rows and abs(c["cy"] - rows[-1]["cy"]) <= tol * min(
                c["h"], rows[-1]["h"]):
            r = rows[-1]
            r["cells"].append(c)
            n = len(r["cells"])
            r["cy"] = (r["cy"] * (n - 1) + c["cy"]) / n
            continue
        rows.append({"cy": c["cy"], "h": c["h"], "cells": [c]})
    out = []
    for r in rows:
        cs = sorted(r["cells"], key=lambda c: c["x0"])
        out.append(cs)
    return out


def _box(cs):
    return (min(c["x0"] for c in cs), min(c["y0"] for c in cs),
            max(c["x1"] for c in cs), max(c["y1"] for c in cs))


def _inside(c, rect, pad=0.0):
    x0, y0, x1, y1 = rect
    return x0 - pad <= c["cx"] <= x1 + pad and y0 - pad <= c["cy"] <= y1 + pad


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ------------------------------------------------------------- titles
def titles(cells, discipline=""):
    """Schedule titles among the cells: [(cell, kind)]. A title is a line
    of its own ('DOOR SCHEDULE', 'PLUMBING FIXTURE SCHEDULE:'), never a
    reference inside a note ('SEE DOOR SCHEDULE')."""
    out = []
    for c in cells:
        t = c["text"].strip(" :")
        if len(t) > 60 or not _SCHED_WORD.search(t):
            continue
        if _REF_WORDS.search(t.split("SCHEDULE")[0] if "SCHEDULE" in
                             t.upper() else t):
            # 'SEE DOOR SCHEDULE', 'DOORS PER SCHEDULE'; but 'SCHEDULE OF
            # ...' and 'LIGHTING FIXTURE SCHEDULE' are fine
            head = t.upper().split("SCHEDULE")[0]
            if re.search(r"\b(SEE|REFER|PER|FOR|TO)\b", head):
                continue
        # a note's line that wraps after the name ('... SEE PLUMBING' /
        # 'FIXTURE SCHEDULE FOR INDIVIDUAL RUNOUT SIZES.') is a reference
        if re.search(r"SCHEDULE\s+(?:FOR|AND|IN|ON|AS)\b|\.$", t, re.I):
            continue
        # 'DOOR SCHEDULE NOTES:' heads a list of notes, not a table
        if re.search(r"SCHEDULE\s+NOTES?$", t, re.I):
            continue
        k = kind_of(t, discipline)
        # panel headings ('PANEL LP1' beside 'PANEL LP2') stand side by
        # side by design - the heading-row test is not for them
        if k and (k == "panel" or not _in_header_row(c, cells)) and \
                not _sheet_index_entry(c, cells):
            out.append((c, k))
    return out


_SHEET_NO = re.compile(r"^[A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?[A-Z]?$")


def _sheet_index_entry(c, cells):
    """'A601  DOOR SCHEDULE & DETAILS' in the drawing index: a sheet's
    name beside its number, not a table's title."""
    h = c["h"]
    left = [d for d in cells if d is not c and
            abs(d["cy"] - c["cy"]) <= 0.5 * h and
            0 <= c["x0"] - d["x1"] <= 8 * h]
    if not left:
        return False
    d = max(left, key=lambda d: d["x1"])
    return bool(_SHEET_NO.match(d["text"].strip()))


def _in_header_row(c, cells):
    """A column heading ('HARDWARE SET' between THRESHOLD and COMMENTS)
    is not a title: it has other headings close beside it on its line;
    a title stands on a line of its own."""
    h = c["h"]
    near = [d for d in cells if d is not c and abs(d["cy"] - c["cy"]) <=
            0.5 * h and abs(d["h"] - h) <= 0.3 * h]
    def gap(d):
        return max(c["x0"] - d["x1"], d["x0"] - c["x1"])
    close = [d for d in near if gap(d) <= 6 * h]
    row = [d for d in near if gap(d) <= 20 * h]
    return bool(close) and len(row) >= 2


# ------------------------------------------------------------- tables
def _vrules(segs, box, min_len):
    """x of the vertical rules (lines) crossing `box` that are at least
    `min_len` long."""
    x0, y0, x1, y1 = box
    xs = []
    for s in segs:
        if abs(s[0] - s[2]) > 0.6:
            continue
        lo, hi = min(s[1], s[3]), max(s[1], s[3])
        if hi - lo < min_len:
            continue
        if not (x0 - 2 <= s[0] <= x1 + 2):
            continue
        if _overlap(lo, hi, y0, y1) < 0.5 * min(hi - lo, y1 - y0):
            continue
        xs.append(s[0])
    xs.sort()
    out = []
    for x in xs:
        if not out or x - out[-1] > 1.5:
            out.append(x)
    return out


def _rule_reach(x, segs, hbox, hh):
    """How far the upright rule at x runs down from the header (pieces
    drawn cell by cell joined across gaps under 1.5 text heights)."""
    ps = sorted((min(s[1], s[3]), max(s[1], s[3])) for s in segs
                if abs(s[0] - s[2]) <= 0.6 and abs(s[0] - x) <= 1.5)
    end = None
    for lo, hi in ps:
        if end is None:
            if hi >= hbox[1] and lo <= hbox[3] + 2 * hh:
                end = hi
        elif lo <= end + 1.5 * hh:
            end = max(end, hi)
    return 0.0 if end is None else end - hbox[1]


def _header_columns(hrows):
    """Header rows (lists of cells) -> columns [{x0, x1, name, cells}]:
    the row with the most cells sets the columns; cells of the other
    header rows over one column add to its name (a two-line header
    'DOOR' / 'NO.'), over several are a group header ('FRAME' over
    'MATERIAL' and 'TYPE') that prefixes each, and over none make a
    column of their own."""
    base = max(hrows, key=lambda r: (len(r), hrows.index(r)))
    cols = [{"x0": c["x0"], "x1": c["x1"], "parts": [(c["cy"], c["text"])]}
            for c in base]
    for r in hrows:
        if r is base:
            continue
        for c in r:
            over = [k for k in cols if _overlap(c["x0"], c["x1"], k["x0"],
                                                k["x1"]) > 0.0]
            if not over:
                # nearest column under a wider centred word
                near = [k for k in cols if abs(c["cx"] - (k["x0"] + k["x1"])
                                               / 2) < c["h"] * 1.0]
                over = near[:1]
            if not over:
                cols.append({"x0": c["x0"], "x1": c["x1"],
                             "parts": [(c["cy"], c["text"])]})
                continue
            for k in over:
                k["parts"].append((c["cy"], c["text"]))
                if len(over) == 1:
                    k["x0"], k["x1"] = min(k["x0"], c["x0"]), max(k["x1"],
                                                                  c["x1"])
    cols.sort(key=lambda k: k["x0"])
    names = []
    for k in cols:
        k["name"] = re.sub(r"\s+", " ", " ".join(
            t for _y, t in sorted(k["parts"]))).strip(" :")
        n, base_name = 2, k["name"]
        while k["name"] in names:                # 'WIDTH' under DOOR and
            k["name"] = f"{base_name} {n}"        # FRAME both
            n += 1
        names.append(k["name"])
    return cols


def _pick_col(cols, rx, avoid=None):
    rx = re.compile(rx, re.I) if isinstance(rx, str) else rx
    for k in cols:
        if rx.search(k["name"]) and not (avoid and avoid.search(k["name"])):
            return k["name"]
    return None


# 101, 108A, D01, GD1, 1.2, and a building-prefixed number (1A101)
_ONE_KEY = re.compile(r"^(?:[A-Z]{0,2}\d{1,4}(?:[.-]?\d{1,2})?[A-Z]?\d?|"
                      r"\d[A-Z]\d{2,4}[A-Z]?)$", re.I)


def _key_ok(text, kind):
    t = text.strip()
    if kind in ("door", "finish") and t and len(t) <= 40:
        # one number, or a merged cell naming a run or a list of them
        # ('1A101 TO 1D102', '151A 151B 151C', '258A, 258B')
        parts = [p for p in re.split(r"\s+(?:TO|THRU|-)\s+|[\s,]+", t,
                                     flags=re.I) if p]
        if 2 <= len(parts) <= 4 and all(_ONE_KEY.match(p) for p in parts):
            return True
    if not t or len(t) > 12 or len(t.split()) > 2:
        return False
    if kind in ("door", "finish"):
        return bool(_ONE_KEY.match(t.replace(" ", "")))
    # ('3/4"-WH' wall hydrant, '1/2"-HB' hose bibb: a size in the mark)
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9.#/\"-]*$",
                         t.replace(" ", "")))


def _bridged(a, b, title, segs):
    """True when one ruled line runs over the gap between header cells
    `a` and `b`, between the title and the row (one table's frame: a
    group header row - 'SIZE', 'MOUNTING', 'MATERIAL' centred over wide
    column groups - has wide gaps but is still one table)."""
    top = title["y0"] - title["h"]
    for s in segs or ():
        if abs(s[1] - s[3]) > 0.6:
            continue
        y = (s[1] + s[3]) / 2
        if not (top <= y <= a["cy"]):
            continue
        lo, hi = min(s[0], s[2]), max(s[0], s[2])
        if lo <= a["x1"] and hi >= b["x0"]:
            return True
    return False


def _cluster(cs, title, gap_h=12.0, segs=()):
    """The cells of one header row that belong to the table under
    `title`: split the row at gaps wider than `gap_h` text heights (not
    where the table's own ruled frame runs over the gap) and keep the
    run under the title (or the nearest to it)."""
    if not cs:
        return cs
    runs_, cur = [], [cs[0]]
    for c in cs[1:]:
        if c["x0"] - cur[-1]["x1"] > gap_h * max(c["h"], cur[-1]["h"]) \
                and not _bridged(cur[-1], c, title, segs):
            runs_.append(cur)
            cur = [c]
        else:
            cur.append(c)
    runs_.append(cur)
    tc = (title["x0"] + title["x1"]) / 2

    def dist(run):
        a, b = run[0]["x0"], run[-1]["x1"]
        if _overlap(a, b, title["x0"], title["x1"]) > 0:
            return 0.0
        return min(abs(a - tc), abs(b - tc))
    return min(runs_, key=dist)


# a dimension string of the drawing beside a schedule (11'-6", 3'-2 3/8")
# is never a header word
_DIM_TEXT = re.compile(r"^\d+'\s*-?\s*\d*(?:\s+\d+/\d+)?\s*(?:\"|'')?$|"
                       r"^\d+(?:\s+\d+/\d+)?\s*(?:\"|'')$")


# header lines under a title: a two-level HVAC equipment header runs to
# five (group row, then E.S.P. (IN / WC), MODEL / (MBH) lines)
HEADER_LINES_MAX = 5
# full line height / small-glyph box height (about 1.35 for common fonts)
TIGHT_GLYPH_RATIO = 1.35


def _tight_glyphs():
    """True when PyMuPDF reports small (tight) glyph heights."""
    try:
        import fitz
        return bool(fitz.TOOLS.set_small_glyph_heights())
    except Exception:
        return False


def _left_key_header(hrows, rows, hi, kind):
    """A key column (MARK / TAG) set left of a group header row ('BASIS OF
    DESIGN', 'HEATING', 'ELECTRICAL' over their columns) with a wide gap
    to the next header word - the columns between are headed only on a
    lower line - is split off by the gap and lost. When the header has no
    key column, a key header word on the header's lines to its left, with
    a data cell under it on the first data row, joins the header with the
    words between it and the header."""
    rx = re.compile(_KEY_HDR.get(kind, _KEY_HDR_ANY), re.I)
    allc = [c for r in hrows for c in r]
    if any(rx.search(c["text"]) for c in allc):
        return
    y0 = min(c["y0"] for c in allc)
    y1 = max(c["y1"] for c in allc)
    x0 = min(c["x0"] for c in allc)
    hh = max(c["h"] for c in allc)
    i0 = next((i for i, r in enumerate(rows) if hrows[0][0] in r), None)
    if i0 is None or hi is None:
        return
    band = [c for r in rows[i0:hi + 1] for c in r
            if c["x1"] < x0 and y0 - 0.5 * hh <= c["cy"] <= y1 + 0.5 * hh]
    keys = [c for c in band if rx.search(c["text"]) and
            x0 - c["x1"] <= 40 * hh]
    if not keys:
        return
    k = max(keys, key=lambda c: c["x1"])
    data = next((r for r in rows[hi + 1:hi + 5]
                 if any(_DIGIT.search(c["text"]) for c in r)), [])
    if not any(_overlap(d["x0"], d["x1"], k["x0"] - hh, k["x1"] + hh) > 0
               for d in data):
        return
    add = [c for c in band if c["x0"] >= k["x0"] - 0.5 * hh]
    for c in add:
        tgt = min(hrows, key=lambda r: abs(r[0]["cy"] - c["cy"]))
        if c not in tgt:
            tgt.append(c)
            tgt.sort(key=lambda x: x["x0"])


def _band_rows(rows, segs, left, right, hbox, hh, bottom):
    """Rows of a ruled table whose cells are merged across printed lines
    ('1A101 TO' over '1D102' beside a one-line row): the lines between
    two neighbouring row rules are one row. Only when the rules are
    close (a rule under every row); else the rows as they are."""
    width = right - left
    if width <= 0:
        return rows
    lim = (bottom if bottom is not None else float("inf")) + hh
    acc = {}
    for s in segs:
        if abs(s[1] - s[3]) > 0.6:
            continue
        y = (s[1] + s[3]) / 2
        if y < hbox[3] - 0.3 * hh or y > lim:
            continue
        ov = _overlap(min(s[0], s[2]), max(s[0], s[2]), left, right)
        if ov > 0:
            k = round(y * 2) / 2
            acc[k] = acc.get(k, 0.0) + ov
    ys = []
    for y in sorted(k for k, v in acc.items() if v >= 0.6 * width):
        if ys and y - ys[-1] <= 0.3 * hh:
            continue
        ys.append(y)
    if len(ys) < 3:
        return rows
    out, bands = [], {}
    for r in rows:
        cy = sum(c["cy"] for c in r) / len(r)
        i = next((i for i in range(len(ys) - 1)
                  if ys[i] < cy < ys[i + 1] and
                  ys[i + 1] - ys[i] <= 3.5 * hh), None)
        if i is None:
            out.append(r)
            continue
        if i in bands:
            bands[i].extend(r)
            continue
        bands[i] = list(r)
        out.append(bands[i])
    for b in bands.values():
        b.sort(key=lambda c: (c["cy"], c["x0"]))
    return out


def read_table(cells, title, kind, segs=(), page_h=None, stop=()):
    """One schedule under `title` (a cell): {kind, title, csi, bbox,
    columns, key, qty, desc, hw, rows: [{column: text, "_key_rect":
    (x0, y0, x1, y1)}], confident, why}. `stop` are the other titles on
    the sheet (a table ends where the next one starts)."""
    th = title["h"]
    page_h = page_h or 1e9
    below = [c for c in cells if c is not title and c["y0"] >= title["y1"] -
             0.3 * th and c["cy"] <= title["y1"] + 0.85 * page_h]
    # stop at the next title straight below this one (checked again
    # against the table's own width once its columns are known: a title
    # beside the table - FLOOR DRAIN SCHEDULE right of the fixture
    # schedule's lower rows - doesn't end it)
    nxt = [s for s in stop if s is not title and s["y0"] > title["y1"]
           and _overlap(s["x0"] - 40 * th, s["x1"] + 40 * th, title["x0"],
                        title["x1"]) > 0]
    near = [s["y0"] for s in nxt if _overlap(s["x0"] - 2 * th, s["x1"] +
                                             2 * th, title["x0"],
                                             title["x1"]) > 0]
    if near:
        below = [c for c in below if c["cy"] < min(near)]
    rows = group_rows(below)
    res = {"kind": kind, "title": title["text"].strip(" :"),
           "csi": CSI.get(kind, ""), "bbox": (title["x0"], title["y0"],
                                              title["x1"], title["y1"]),
           "columns": [], "key": None, "qty": None, "desc": None, "hw": None,
           "rows": [], "confident": False, "why": ""}
    if kind == "panel":
        m = re.search(r"PANEL(?:BOARD)?\s+(?:SCHEDULE\s*[-:]?\s*)?\"?"
                      r"([A-Z]{1,3}-?\d{1,3}[A-Z]?)\b", title["text"], re.I)
        # a panel schedule has its circuit table under the name; a
        # "PANEL LP1" label on a plan has not
        h = title["h"]
        table = [c for c in cells if 0 <= c["y0"] - title["y1"] <= 10 * h and
                 _overlap(c["x0"], c["x1"], title["x0"] - 30 * h,
                          title["x1"] + 30 * h) > 0 and re.search(
                              r"\b(?:CKT|CIRCUIT|BKR|BREAKER|POLES?|LOAD|"
                              r"AMPS?|VOLTS?|MAINS?|PHASE)\b", c["text"],
                              re.I)]
        if not table:
            res["skip"] = True
            res["why"] = "a panel name, not a panel schedule"
            return res
        if m and not re.match(r"^SCHEDULE", m.group(1), re.I):
            res.update(rows=[{"PANEL": m.group(1).upper(),
                              "_key_rect": res["bbox"]}], key="PANEL",
                       columns=["PANEL"], confident=True)
        else:
            res["why"] = "panel name not read from the title"
        return res
    # the header: the first row under the title that has cells over the
    # title's span, then the rows below it with no digits (up to 3)
    span = (title["x0"] - 60 * th, title["x1"] + 60 * th)
    hrows, hi = [], None
    # word boxes are shorter when PyMuPDF's small-glyph-heights switch is
    # on (the main window turns it on): the header line-gap rule is in
    # full line heights either way
    loose = TIGHT_GLYPH_RATIO if _tight_glyphs() else 1.0
    for i, r in enumerate(rows):
        if r[0]["cy"] - title["y1"] > 8 * th and not hrows:
            break
        if not hrows:
            mine = _cluster([c for c in r if not _DIM_TEXT.match(c["text"])
                             and _overlap(c["x0"], c["x1"],
                                                       *span) > 0], title,
                            segs=segs)
            if len(mine) < 2:
                continue
            hrows.append(mine)
            hi = i
            continue
        # a second / third header line: inside the first one's extent,
        # or reaching past it on a line that runs into it (the first line
        # can be a group row - 'DOOR', 'GLAZING' over their columns - that
        # doesn't reach the key column at the left)
        h0 = hrows[0]
        lo_x = h0[0]["x0"] - 3 * h0[0]["h"]
        hi_x = h0[-1]["x1"] + 3 * h0[-1]["h"]
        # a line made only of words well clear of the header (a title
        # block's turned text beside the table) is not the table's: skip
        # it rather than end the header there
        reach = 12.0 * h0[0]["h"]
        if all(c["x0"] > h0[-1]["x1"] + reach or
               c["x1"] < h0[0]["x0"] - reach for c in r):
            continue
        r = [c for c in r if not _DIM_TEXT.match(c["text"])]
        if not r:
            continue
        mine = [c for c in r if lo_x <= c["cx"] <= hi_x]
        cand = [c for c in r if _overlap(c["x0"], c["x1"], *span) > 0 and
                c["h"] <= 2.5 * h0[0]["h"]]
        if mine:
            wide = _cluster(cand, title, segs=segs)
            if wide and _overlap(wide[0]["x0"], wide[-1]["x1"], lo_x,
                                 hi_x) > 0 and len(wide) > len(mine):
                mine = wide
        elif cand:
            # a one-line header cell set between the lines of two-line ones
            # ('KEY' and 'DESCRIPTION' level with the gap between 'BOBRICK
            # NO.' and '/ ASI NO.'): cells that run on, without a big gap,
            # from the first header line's cells are header too
            both = sorted(cand + list(h0), key=lambda c: c["x0"])
            runs_, cur = [], [both[0]]
            for c in both[1:]:
                if c["x0"] - cur[-1]["x1"] > 12.0 * max(c["h"],
                                                        cur[-1]["h"]):
                    runs_.append(cur)
                    cur = [c]
                else:
                    cur.append(c)
            runs_.append(cur)
            run0 = next(rn for rn in runs_ if any(c is h0[0] for c in rn))
            ids = {id(c) for c in cand}
            mine = [c for c in run0 if id(c) in ids]
        if not mine:
            break
        if any(_DIGIT.search(c["text"]) and not _HDR_NUM.match(c["text"])
               for c in mine) or len(hrows) >= HEADER_LINES_MAX or \
                all(_HDR_NUM.match(c["text"]) for c in mine):
            break
        if mine[0]["cy"] - hrows[-1][0]["cy"] > 2.2 * mine[0]["h"] * loose:
            break
        hrows.append(mine)
        hi = i
    if not hrows:
        res["why"] = "no header row under the title"
        return res
    if len(hrows) > 1 and not any(_DIGIT.search(c["text"]) for r in rows[
            hi + 1:hi + 3] for c in r):
        # nothing with a digit follows: the last 'header' row was data
        hrows = hrows[:1]
        hi = rows.index(next(r for r in rows if hrows[0][0] in r))
    _left_key_header(hrows, rows, hi, kind)
    cols = _header_columns(hrows)
    if len(cols) < 2:
        res["why"] = "fewer than two columns"
        return res
    hbox = _box([c for r in hrows for c in r])
    hh = max(c["h"] for r in hrows for c in r)
    # column ranges: the table's vertical rules when there is one between
    # every pair of neighbouring columns, else halfway between headers
    rules = _vrules(segs, (hbox[0] - 3 * hh, hbox[1], hbox[2] + 3 * hh,
                           hbox[3]), min_len=0.8 * hh)
    bounds = []
    ruled = bool(rules)
    for a, b in zip(cols, cols[1:]):
        between = [x for x in rules if a["x1"] - 1 <= x <= b["x0"] + 1]
        if len(between) > 1 and kind in ("door", "finish"):
            # several upright strokes between two headers (a merged
            # header cell's edges, letters drawn as lines): the column rule
            # is the one that runs on down through the rows
            reach = [_rule_reach(x, segs, hbox, hh) for x in between]
            top = max(reach)
            between = [x for x, r in zip(between, reach) if r >= top - hh]
        if between:
            bounds.append(between[len(between) // 2])
        else:
            ruled = False
            bounds.append((a["x1"] + b["x0"]) / 2)
    left = rules[0] if ruled and rules[0] < cols[0]["x0"] else \
        cols[0]["x0"] - 4 * hh
    right = rules[-1] if ruled and rules[-1] > cols[-1]["x1"] else \
        cols[-1]["x1"] + 4 * hh
    edges = [left] + bounds + [right]
    stop_y = min((s["y0"] for s in nxt if _overlap(s["x0"], s["x1"], left,
                                                   right) > 0), default=None)
    # a ruled table ends where its column rules end: the plan drawn under
    # it is not more rows
    bottom = None
    if ruled and bounds:
        lows = []
        for x in bounds:
            # the rule's pieces at this column line, followed down from the
            # header (a rule drawn cell by cell is many short pieces)
            ps = sorted((min(s[1], s[3]), max(s[1], s[3])) for s in segs
                        if abs(s[0] - s[2]) <= 0.6 and abs(s[0] - x) <= 1.5)
            end = None
            for lo_, hi_ in ps:
                if end is None:
                    if hi_ >= hbox[1] and lo_ <= hbox[3] + 2 * hh:
                        end = hi_
                elif lo_ <= end + 1.5 * hh:
                    end = max(end, hi_)
            if end is not None:
                lows.append(end)
        if lows:
            bottom = max(lows)
    names = [k["name"] for k in cols]
    res["columns"] = names
    key = _pick_col(cols, _KEY_HDR.get(kind, _KEY_HDR_ANY),
                    avoid=_HW_HDR if kind == "door" else None)
    if key is None:
        key = names[0]
    res["key"] = key
    res["qty"] = _pick_col(cols, _QTY_HDR, avoid=_NOT_QTY)
    avoid_d = re.compile(r"\b(?:NO|#|MARK|KEY|SYM)\b|^TYPE$", re.I)
    # what the thing is, before who makes it: FIXTURE / ITEM / NAME /
    # DESCRIPTION first, MANUFACTURER only when nothing else names it
    res["desc"] = next((c for c in (
        _pick_col(cols, re.compile(rx, re.I), avoid=avoid_d)
        for rx in (r"\bFIXTURE\b|\bITEM\b|\bCOMMON\s+NAME\b|^NAME$",
                   r"\bDESC(?:RIPTION|\.)?\b", r"\bEQUIPMENT\b|\bSERVICE\b",
                   _DESC_HDR.pattern)) if c and c != key), None) or next(
        (n for n in names if n not in (key, res["qty"])), None)
    if kind == "door":
        res["hw"] = _pick_col(cols, _HW_HDR)
    ki = names.index(key)
    critical = {ki} | ({names.index(res["qty"])} if res["qty"] else set())
    # data rows: until a big gap, a notes heading or another table
    data, last_y, pitch = [], hrows[-1][0]["y1"], None
    bad, total = 0, 0
    why = []
    # rows that didn't read, held until a good row follows: two in a row
    # end the table (the plan's own text under it - a room name, a note -
    # is not part of the schedule and doesn't make it unsure)
    held = {"bad": 0, "rows": 0, "why": []}
    orphans = []

    def reject(n_bad, msg):
        held["bad"] += n_bad
        held["rows"] += 1
        if msg:
            held["why"].append(msg)
    body_rows = rows[hi + 1:]
    if ruled:
        body_rows = _band_rows(body_rows, segs, left, right, hbox, hh,
                               bottom)
    for r in body_rows:
        # (text turned up the sheet - a title block's name beside the
        # table - is not a schedule row)
        mine = [c for c in r if left - hh <= c["cx"] <= right + hh and
                c["h"] <= 2.5 * hh]
        if not mine:
            continue
        if ruled:
            mine = [d for c in mine for d in _split_cell(c, edges)]
        gap = mine[0]["y0"] - last_y
        lim = max(3.0 * (pitch or mine[0]["h"] * 1.5), 2.5 * mine[0]["h"])
        if gap > lim or held["rows"] >= 2:
            break
        if bottom is not None and mine[0]["cy"] > bottom + 0.3 * hh:
            break
        if stop_y is not None and mine[0]["cy"] >= stop_y:
            break
        gross_bad0 = bad
        why0 = len(why)
        first = mine[0]["text"].upper()
        if _NOTE_HEAD.match(first) or re.match(r"^NOTES?\b|^\d+\.\s+[A-Z]",
                                               first):
            break
        if pitch is None:
            pitch = max(mine[0]["cy"] - hrows[-1][0]["cy"], mine[0]["h"])
        else:
            pitch = min(pitch, max(mine[0]["cy"] - last_cy, mine[0]["h"]))
        last_y = max(c["y1"] for c in mine)
        last_cy = mine[0]["cy"]
        row = {}
        rect = None
        for c in mine:
            total += 1
            # the column(s) this cell lies across
            idx = [i for i in range(len(cols))
                   if _overlap(c["x0"], c["x1"], edges[i], edges[i + 1]) >
                   0.2 * (c["x1"] - c["x0"]) + 0.5]
            if ruled:
                spans = [i for i in idx if _overlap(c["x0"], c["x1"],
                                                    edges[i],
                                                    edges[i + 1]) >= 1.0]
            else:
                spans = [i for i in range(len(cols))
                         if _overlap(c["x0"], c["x1"], cols[i]["x0"],
                                     cols[i]["x1"]) > 0.5]
            # long text running over a neighbouring description column
            # ('OWNER FURNISHED / CONTRACTOR INSTALLED') reads fine; only a
            # cell across the key or the quantity column is a misread
            across = len(spans) > 1 and bool(set(spans) & critical)
            col = next((i for i in range(len(cols))
                        if edges[i] <= c["cx"] < edges[i + 1]), None)
            if across or col is None:
                bad += 1
                if len(why) < 3:
                    why.append(f"'{c['text'][:20]}' lies across columns")
                if col is None:
                    continue
            n = names[col]
            row[n] = (row[n] + " " + c["text"]) if n in row else c["text"]
            if col == ki:
                rect = (c["x0"], c["y0"], c["x1"], c["y1"])
        row_bad = bad - gross_bad0
        bad = gross_bad0
        tight = pitch is None or gap <= 0.8 * pitch
        if key not in row and bottom is not None:
            # a ruled table with tall rows ('WALL-HUNG' / 'P-1' /
            # 'LAVATORY (H.C.)' and a description of several lines): a line
            # with no key belongs to the row whose key is nearest
            orphans.append((mine[0]["cy"], row, row_bad))
            continue
        if key not in row:
            if data and tight and not held["rows"]:
                # a wrapped line of the row above
                bad += row_bad
                for n, v in row.items():
                    data[-1][n] = (data[-1].get(n, "") + " " + v).strip()
                continue
            reject(row_bad + 1, "a row has no key")
            continue
        if not _key_ok(row[key], kind):
            if kind in ("door", "finish") and len(mine) == 1 and \
                    re.match(r"^[A-Z]{3,}", row[key], re.I):
                # a heading row across the table ('BASEMENT', 'FIRST
                # FLOOR', 'LOW ROOF - 1'-0" RAISED'): a merged cell that
                # groups the rows under it, not a misread (door and room
                # numbers have digits, so it is not a wrapped key)
                del why[why0:]
                reject(0, None)
                continue
            if data and tight and not held["rows"] and len(row) <= 2 and \
                    not _DIGIT.search(row[key]):
                bad += row_bad
                for n, v in row.items():
                    data[-1][n] = (data[-1].get(n, "") + " " + v).strip()
                continue
            reject(row_bad + 1, f"'{row[key][:20]}' doesn't look like a "
                                f"{key.lower()}")
            continue
        # a good row: what was held between good rows was inside the table
        bad += held["bad"] + row_bad
        why += held["why"]
        held.update(bad=0, rows=0, why=[])
        row["_key_rect"] = rect
        data.append(row)
    for cy, row, rb in orphans:
        if not data:
            break
        tgt = min(data, key=lambda d: abs((d["_key_rect"][1] +
                                           d["_key_rect"][3]) / 2 - cy)
                  if d.get("_key_rect") else 1e9)
        bad += rb
        for n, v in row.items():
            tgt[n] = (tgt.get(n, "") + " " + v).strip() if n in tgt else v
    keys = [r[key].replace(" ", "") for r in data]
    dup = [k for k, n in Counter(keys).items() if n > 1]
    res["rows"] = data
    allc = [c for r in hrows for c in r]
    box = _box(allc)
    res["bbox"] = (min(box[0], title["x0"], left), title["y0"],
                   max(box[2], title["x1"], right),
                   max(box[3], last_y))
    if not data:
        res["why"] = "no rows read"
        return res
    if dup and kind != "hardware":
        why.append("the same key twice: " + ", ".join(dup[:5]))
    share = bad / max(1, total)
    res["confident"] = share <= 0.05 and not (dup and kind != "hardware")
    if not res["confident"]:
        res["why"] = "columns don't line up - " + "; ".join(why[:3]) if \
            share > 0.05 else "; ".join(why[:3])
    elif why:
        res["why"] = "; ".join(why[:2])
    return res


def read_cells(cells, segs=(), page_w=None, page_h=None, discipline=""):
    """Every schedule in a sheet's cells (displayed coordinates)."""
    ts = titles(cells, discipline)
    if page_w and page_h:
        # the sheet title in the title block ("HVAC SCHEDULES") is not a
        # table (only a title block found from the frame's lines)
        tb = _tb_strips(page_w, page_h, segs or [])
        ts = [(c, k) for c, k in ts if not any(_inside(c, r) for r in tb)]
    out = []
    for c, k in ts:
        try:
            t = read_table(cells, c, k, segs, page_h,
                           stop=[x for x, _k in ts])
        except Exception:                         # noqa: BLE001
            log.exception("schedule %r not read", c["text"])
            continue
        out.append(t)
    return out


# ------------------------------------------------------------- page
def _disp(page):
    """(matrix to displayed coordinates, matrix back) for a fitz page."""
    if not page.rotation:
        return None, None
    return page.rotation_matrix, page.derotation_matrix


def page_words(page, textpage=None):
    """Words in displayed coordinates, with block/line numbers."""
    import fitz
    ws = page.get_text("words", textpage=textpage)
    m, _ = _disp(page)
    if m is None:
        return [tuple(w[:8]) for w in ws]
    out = []
    for w in ws:
        r = (fitz.Rect(w[:4]) * m).normalize()
        out.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:8]))
    return out


def page_segments(page):
    """Every stroked straight piece of linework, displayed coordinates."""
    import fitz
    from . import tradetakeoff as tt
    m, _ = _disp(page)
    out = []
    for segs in tt.styled_segments(page).values():
        for s in segs:
            if m is None:
                out.append(s)
            else:
                a = fitz.Point(s[0], s[1]) * m
                b = fitz.Point(s[2], s[3]) * m
                out.append((a.x, a.y, b.x, b.y))
    return out


def page_size(page):
    r = page.rect                      # displayed size
    return r.width, r.height


def to_page(page, rect):
    """A displayed-coordinates rect back to the page's own coordinates
    (what marks and get_text use)."""
    import fitz
    _m, back = _disp(page)
    if back is None:
        return tuple(rect)
    r = (fitz.Rect(rect) * back).normalize()
    return (r.x0, r.y0, r.x1, r.y1)


def read_page(page, discipline="", cache=None):
    """Every schedule on a fitz page, in displayed coordinates."""
    info = sheet_info(page, cache)
    return read_cells(info["cells"], info["segs"], info["w"], info["h"],
                      discipline)


def sheet_info(page, cache=None):
    """Cells, linework and size of a page (cached per page number)."""
    key = getattr(page, "number", id(page))
    if cache is not None and key in cache:
        return cache[key]
    w, h = page_size(page)
    info = {"cells": make_cells(page_words(page)), "w": w, "h": h,
            "segs": None}
    try:
        info["segs"] = page_segments(page)
    except Exception:                                     # noqa: BLE001
        info["segs"] = []
    if cache is not None:
        cache[key] = info
    return info


# ------------------------------------------------------------- plan area
def _tb_strips(w, h, segs):
    """The title block strips found from the sheet frame's lines: the
    right-hand strip from a long vertical line in the right part of the
    sheet, a bottom strip from a long horizontal line near the bottom.
    [] when the sheet has neither."""
    out = []
    vert = [s[0] for s in segs if abs(s[0] - s[2]) < 0.8 and
            abs(s[3] - s[1]) >= 0.75 * h and 0.70 * w <= s[0] <= 0.965 * w]
    hor = [s[1] for s in segs if abs(s[1] - s[3]) < 0.8 and
           abs(s[2] - s[0]) >= 0.75 * w and 0.75 * h <= s[1] <= 0.965 * h]
    if vert:
        out.append((min(vert), 0.0, w, h))
    if hor:
        out.append((0.0, min(hor), w, h))
    return out


def title_block(w, h, segs):
    """Rects (displayed coordinates) left out of the plan area for the
    title block and the margin: the strips of _tb_strips, or without
    one the right 20% of the sheet; and the margin outside the frame
    (plot stamps, file paths)."""
    out = _tb_strips(w, h, segs) or [(0.80 * w, 0.0, w, h)]
    m = 0.015 * min(w, h)
    out += [(0, 0, m, h), (0, 0, w, m), (w - m, 0, w, h), (0, h - m, w, h)]
    return out


def text_blocks(cells, head_rx, max_down=None):
    """Rects of the blocks under headings that match `head_rx` (legends,
    notes): the heading and the lines below it that start near its left
    edge, down to the first big gap."""
    out = []
    rows = group_rows(cells)
    for c in cells:
        if not head_rx.match(c["text"].strip()):
            continue
        h = c["h"]
        x_lo, x_hi = c["x0"] - 3 * h, c["x0"] + 12 * h
        lim = c["y1"] + (max_down or 120 * h)
        box = [c["x0"], c["y0"], c["x1"], c["y1"]]
        last = c["y1"]
        for r in rows:
            if r[0]["cy"] <= c["cy"] + 0.3 * h or r[0]["y0"] > lim:
                continue
            start = [x for x in r if x_lo <= x["x0"] <= x_hi]
            if not start:
                continue
            s = start[0]
            if s["y0"] - last > max(3.0 * s["h"], 2.0 * h):
                break
            # the line's text running on to the right from there
            chain = [s]
            for x in r:
                if x["x0"] > chain[-1]["x1"] and \
                        x["x0"] - chain[-1]["x1"] <= 4 * x["h"]:
                    chain.append(x)
            # a legend's symbols sit left of the description
            box[0] = min(box[0], s["x0"] - 6 * s["h"])
            box[2] = max(box[2], chain[-1]["x1"])
            box[3] = max(box[3], s["y1"])
            last = s["y1"]
        out.append(tuple(box))
    return out


def views(cells, excl=(), loose=False):
    """The separate drawings on a sheet, from their titles: a line with
    PLAN (or ELEVATION / SECTION / DETAIL / VIEW) that has a scale (or
    SCALE / NTS) just under it. [{title, rect, plan, secondary, level}].
    loose: also a big title naming a floor with no PLAN word ("FINISHED
    FLOOR"), and a scale line set so tight under its title that the two
    boxes touch (the walls engine's sheet parts; tag counting keeps the
    strict reading)."""
    out = []
    for c in cells:
        t = c["text"]
        floor = False
        if len(t) > 70 or not (_VIEW_WORD.search(t) or
                               _OTHER_VIEW.search(t)):
            # a big title naming a floor with its scale just under it
            # ("FINISHED FLOOR" / "LEVEL 2", no PLAN word) is a plan view
            if not loose or len(t) > 40 or not _FLOOR_TITLE.search(t):
                continue
            floor = True
        if any(_inside(c, r) for r in excl):
            continue
        if _SCALE_TEXT.search(t) and not re.search(r"\bPLAN\b", t, re.I):
            continue
        h = c["h"]
        # (a scale line set tight under a big title can touch its box)
        under = [x for x in cells if x is not c and
                 (-0.3 * h if loose else 0) <= x["y0"] - c["y1"] <= 3.0 * h
                 and
                 (not floor or x["h"] <= 0.7 * h) and
                 _overlap(x["x0"], x["x1"], c["x0"] - 2 * h,
                          c["x1"] + 2 * h) > 0 and _SCALE_TEXT.search(
                              x["text"])]
        same = _SCALE_TEXT.search(t.split("PLAN")[-1]) if "PLAN" in t.upper() \
            else None
        if not under and not same and _OTHER_VIEW.search(t) and \
                not _VIEW_WORD.search(t):
            # an elevation / detail / mounting-heights drawing is often
            # titled with its scale just above the title instead
            # (a title is set bigger than its scale line - a line of notes
            # under a sentence that mentions a scale is not a title)
            under = [x for x in cells if x is not c and
                     x["h"] <= 0.8 * h and
                     0 <= c["y0"] - x["y1"] <= 3.0 * h and
                     _overlap(x["x0"], x["x1"], c["x0"] - 2 * h,
                              c["x1"] + 2 * h) > 0 and
                     _SCALE_TEXT.search(x["text"])]
        if not under and not same:
            continue
        if floor and not under:
            continue
        lv = _LEVEL.search(t)
        out.append({"title": t, "rect": (c["x0"], c["y0"], c["x1"], c["y1"]),
                    "plan": floor or bool(_VIEW_WORD.search(t)) and
                    not _OTHER_VIEW.search(re.sub(r"\bPLANS?\b", "", t)),
                    "secondary": bool(_SECONDARY_VIEW.search(t)),
                    "level": level_of(t) if lv else ""})
    return out


def fold_levels(levels):
    """Plans' levels with a plan that names no level ('ENLARGED FLOOR
    PLAN & ADA') put on the set's one named level, when it names only one
    (Oct 31: its tags were counted as another floor)."""
    # a roof plan is not a floor: it neither blocks the fold nor takes
    # the unnamed plans (HMB: A101 MAIN LEVEL, A102 no level, A105 ROOF)
    named = {lv for lv in levels if lv and lv != "ROOF"}
    if len(named) != 1:
        return list(levels)
    only = next(iter(named))
    return [lv or only for lv in levels]


def level_of(title):
    m = _LEVEL.search(title or "")
    if not m:
        return ""
    v = next(g for g in m.groups() if g)
    return {"FIRST": "1", "GROUND": "1", "MAIN": "1", "LOWER": "1",
            "SECOND": "2", "UPPER": "2", "THIRD": "3", "FOURTH": "4",
            "FIFTH": "5"}.get(v.upper(), v.upper())


REGION_CELL = 4.0        # pt per grid cell when finding a view's drawing
REGION_JOIN = 3          # cells of dilation: walls and pipes 12 pt apart join


def view_regions(vs, segs, w, h, excl=()):
    """Each view's drawing: the linework above its title, found as the
    connected patch of ink (lines joined across small gaps) that sits on
    the title. Sets v["region"] (x0, y0, x1, y1) where one is found. Used
    when titles are centred under wide drawings, where 'nearest title
    below' picks the wrong view."""
    if len(vs) < 2 or not segs:
        return vs
    try:
        import cv2
        import numpy as np
    except Exception:                                     # noqa: BLE001
        return vs
    k = REGION_CELL
    gw, gh = int(w / k) + 2, int(h / k) + 2
    g = np.zeros((gh, gw), np.uint8)
    for x0, y0, x1, y1 in segs:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if any(e[0] <= cx <= e[2] and e[1] <= cy <= e[3] for e in excl):
            continue
        if max(abs(x1 - x0), abs(y1 - y0)) > 0.6 * max(w, h):
            continue                      # the sheet frame
        cv2.line(g, (int(x0 / k), int(y0 / k)), (int(x1 / k), int(y1 / k)),
                 255, 1)
    if REGION_JOIN:
        g = cv2.dilate(g, np.ones((2 * REGION_JOIN + 1, 2 * REGION_JOIN + 1),
                                  np.uint8))
    n, lab, stats, _c = cv2.connectedComponentsWithStats(g, connectivity=8)
    for v in vs:
        tx0, ty0, tx1, _ty1 = v["rect"]
        best = None
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            bx0, by0, bx1, by1 = x * k, y * k, (x + bw) * k, (y + bh) * k
            if by1 < ty0 - 12 * k * REGION_JOIN or by0 > ty0:
                continue                  # not ending just above the title
            if bx1 < tx0 or bx0 > tx1:
                continue                  # not over the title
            if best is None or area > best[0]:
                best = (area, (bx0, by0, bx1, by1))
        if best:
            v["region"] = best[1]
    # regions that are one patch for two titles say nothing: drop them
    seen = {}
    for v in vs:
        if v.get("region"):
            seen.setdefault(v["region"], []).append(v)
    for rg, lst in seen.items():
        if len(lst) > 1:
            for v in lst:
                v.pop("region", None)
    return vs


def view_of(c, vs, w):
    """The view a cell belongs to: views are titled under their drawing,
    left-aligned - the nearest title below it (by rows of titles) whose
    left edge is not to the right of the cell. None when there are no
    views."""
    if not vs:
        return None
    inside = [v for v in vs if v.get("region") and
              v["region"][0] <= c["cx"] <= v["region"][2] and
              v["region"][1] <= c["cy"] <= v["region"][3]]
    if inside:
        return min(inside, key=lambda v: (v["region"][2] - v["region"][0]) *
                   (v["region"][3] - v["region"][1]))
    tol = 3.0 * c["h"]
    below = [v for v in vs if v["rect"][1] >= c["cy"] - 0.5 * c["h"] and
             v["rect"][0] <= c["cx"] + tol]
    if not below:
        below = [v for v in vs if v["rect"][0] <= c["cx"] + tol] or vs
        return min(below, key=lambda v: abs(v["rect"][1] - c["cy"]) +
                   abs(v["rect"][0] - c["cx"]))
    band = max(c["h"] * 6, 0.06 * w)
    top = min(v["rect"][1] for v in below)
    row = [v for v in below if v["rect"][1] - top <= band]
    return max(row, key=lambda v: v["rect"][0])


_VIEW_AREA = re.compile(
    r"\b(?:AREA|PART|ZONE|WING|BUILDING|BLDG|PHASE|POD|SECTOR|UNIT)\s+"
    r"([A-Z0-9]{1,3})\b|\b(NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|"
    r"SOUTHEAST|SOUTHWEST|CENTRAL)\s+(?:WING|AREA|PART|ZONE|HALF|SIDE)\b|"
    r"\b(?:AREA|PART|ZONE)\s*-\s*([A-Z0-9]{1,3})\b", re.I)


def view_area(title):
    """The plan-area word of a view title ('FLOOR PLAN - AREA B' -> 'B',
    'FIRST FLOOR PLAN - EAST WING' -> 'EAST'), '' when there is none."""
    m = _VIEW_AREA.search(title or "")
    if not m:
        return ""
    return next(g for g in m.groups() if g).upper()


def main_views(vs, counts=None):
    """Which views are counted: plan views that aren't enlarged / partial
    / attic / mezzanine / detail views; of several on one level, the one
    with the most tags (`counts` {id(view): n}). Different levels (FIRST
    and SECOND FLOOR PLAN) are each a main view."""
    plans = [v for v in vs if v["plan"] and not v["secondary"]]
    if not plans:
        # a sheet of enlarged plans only: each one shows its own rooms
        return [v for v in vs if v["plan"]]
    by_lv = {}
    for v in plans:
        # separate plan areas of one level (AREA A / AREA B, EAST / WEST
        # WING) each show their own part of the floor (H2)
        by_lv.setdefault((v["level"], view_area(v["title"])), []).append(v)
    out = []
    for lv, group in by_lv.items():
        out.append(max(group, key=lambda v: ((counts or {}).get(id(v), 0),
                                             -group.index(v))))
    return out


def plan_exclusions(info, tables=None):
    """Rects left out of tag counting on a sheet: title block and margin,
    schedules, legends and notes blocks."""
    cells, w, h = info["cells"], info["w"], info["h"]
    ex = title_block(w, h, info["segs"] or [])
    for t in tables or []:
        x0, y0, x1, y1 = t["bbox"]
        ex.append((x0 - 2, y0 - 2, x1 + 2, y1 + 2))
    ex += text_blocks(cells, _LEGEND_HEAD)
    ex += text_blocks(cells, _NOTE_HEAD)
    return ex


# ------------------------------------------------------------- tags
def norm_key(k, kind=""):
    k = re.sub(r"\s+", "", (k or "").translate(_QUOTES))
    k = k.strip(".,;:()[]")
    return k if kind == "plants" else k.upper()


_ANNOT = re.compile(r"^(?:\d{1,4}(?:\s*CFM)?|CFM|TYP\.?|\(?\d+\)?|"
                    r"[A-Z]-?\d{1,2}|\d+\s*W|EM|NL)$", re.I)
_SIZED_TAG = re.compile(r"^\d{1,2}(?:[- ]?\d/\d)?\s*(?:\"|'')\s*-\s*"
                        r"([A-Z]{2,4})$", re.I)
_PLANT_N = re.compile(r"^\(?(\d{1,3})\)?\s*[-xX]?\s*([A-Za-z][A-Za-z0-9]*)$")


def _tag_match(text, keys, kind):
    """(key, n) when a cell is a tag for one of `keys`, else None. A tag
    is the key alone, or the key with a short annotation (a CFM, a
    circuit: 'SD-1 120', 'A-2 EM'); a plant label may carry a count
    ('5 Ab', '(3) DxVJ')."""
    t = text.strip().strip(",;")
    k = norm_key(t, kind)
    if k in keys:
        return keys[k], 1
    if kind == "plants":
        m = _PLANT_N.match(t)
        if m and norm_key(m.group(2), kind) in keys:
            return keys[norm_key(m.group(2), kind)], int(m.group(1))
        return None
    if kind in ("plumbing equipment", "plumbing fixtures"):
        # a pipe size before the symbol: '3"-FD', '4"-GCO'
        m = _SIZED_TAG.match(t)
        if m and norm_key(m.group(1), kind) in keys:
            return keys[norm_key(m.group(1), kind)], 1
    toks = t.split()
    if 1 < len(toks) <= 3:
        k0 = norm_key(toks[0], kind)
        if k0 in keys and all(_ANNOT.match(x) for x in toks[1:]):
            return keys[k0], 1
    return None


CIRCLE_TOL = 0.15     # a bubble's outline: within 15% of one radius
CHORD_MAX = 0.8       # its pieces: short against the radius (a polygon)
TANGENT_TOL = 0.3     # a chord runs round the centre, not toward it
DIAG_TOL = 22.5       # degrees either side of each diagonal
BUBBLE_SHIFTS = (0.0, 0.6, -0.6, 0.9, -0.9)  # circle centre off the letter, x h


def _circled(c, segs, lo=2.0, hi=6.0):
    """A one-character tag inside a grid bubble (a circle drawn around
    it, `lo`-`hi` text heights across): short chords - pieces with both
    ends at one distance from the letter (within CIRCLE_TOL), no longer
    than CHORD_MAX of it - all round it. Linework that only passes nearby
    (a ceiling grid, the circuits round a fixture printed beside the
    letter) is not a bubble."""
    h = c["h"]
    # the letter in the middle of the circle, or in one half of a split
    # circle (a section / detail marker: the letter over its sheet number)
    return any(_ring(c["cx"], c["cy"] + k * h, h, segs, lo, hi)
               for k in BUBBLE_SHIFTS)


def _ring(cx, cy, h, segs, lo, hi):
    """Short chords all round (cx, cy) at one radius: a drawn circle."""
    c = {"cx": cx, "cy": cy}
    ch = []
    for s in segs:
        d0 = ((s[0] - c["cx"]) ** 2 + (s[1] - c["cy"]) ** 2) ** 0.5
        d1 = ((s[2] - c["cx"]) ** 2 + (s[3] - c["cy"]) ** 2) ** 0.5
        if not (lo * h / 2 <= d0 <= hi * h / 2 and
                lo * h / 2 <= d1 <= hi * h / 2):
            continue
        r = (d0 + d1) / 2
        L = ((s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2) ** 0.5
        if abs(d0 - d1) <= CIRCLE_TOL * r and L <= CHORD_MAX * r:
            ch.append((r, (s[0] + s[2]) / 2 - c["cx"],
                       (s[1] + s[3]) / 2 - c["cy"], s))  # centre-relative
    if len(ch) < 8:
        return False
    # the chords of a drawn circle join end to end (hatch dashes do not)
    ends = Counter((round(x, 1), round(y, 1)) for *_r, s in ch
                   for x, y in ((s[0], s[1]), (s[2], s[3])))
    ch = [(r, x, y, s[2] - s[0], s[3] - s[1]) for r, x, y, s in ch
          if ends[(round(s[0], 1), round(s[1], 1))] > 1 or
          ends[(round(s[2], 1), round(s[3], 1))] > 1]
    if len(ch) < 8:
        return False
    for r0, *_rest in ch:
        on = [(x, y, dx, dy) for r, x, y, dx, dy in ch
              if abs(r - r0) <= CIRCLE_TOL * r0]
        if len(on) < 8:
            continue
        q = Counter((x > 0, y > 0) for x, y, _dx, _dy in on)
        if len(q) == 4 and min(q.values()) >= 2 and _diagonals(on):
            return True
    return False


def _diagonals(on):
    """A circle has chords at every angle; a square grid round the letter
    only runs across and up. Needs tangent chords near all four diagonals."""
    hit = set()
    for x, y, dx, dy in on:
        r = math.hypot(x, y)
        L = math.hypot(dx, dy)
        if not r or not L or abs(dx * x + dy * y) / (L * r) > TANGENT_TOL:
            continue
        a = math.degrees(math.atan2(y, x)) % 360
        for k, d in enumerate((45, 135, 225, 315)):
            if abs((a - d + 180) % 360 - 180) <= DIAG_TOL:
                hit.add(k)
    return len(hit) == 4


def _room_tag(c, cells):
    """A number that is a room number: a room name printed just above it
    (or its area in SF just below)."""
    h = c["h"]
    for x in cells:
        if x is c:
            continue
        if 0 <= c["y0"] - x["y1"] <= 1.2 * h and \
                _overlap(x["x0"], x["x1"], c["x0"] - h, c["x1"] + h) > 0 and \
                re.match(r"^[A-Z][A-Z .&/'-]{2,}$", x["text"]) and \
                not _SCALE_TEXT.search(x["text"]):
            return True
        if 0 <= x["y0"] - c["y1"] <= 1.2 * h and \
                re.search(r"\bS\.?F\.?$|\bSQ\.?\s*FT", x["text"], re.I) and \
                _overlap(x["x0"], x["x1"], c["x0"] - 2 * h, c["x1"] + 2 * h):
            return True
    return False


STRIP_MIN_KEYS = 4        # a key strip shows at least this many keys ...
STRIP_SHARE = 0.5         # ... and at least this share of the schedule's keys


def _drop_key_strips(hits, keys):
    """Tags that form a key strip are not plan tags: one of each of most of
    the schedule's keys on one baseline (or one left edge), the way a key
    legend or a mounting-height elevation lists them. Plan tags sit at
    their items, so a row holding at least STRIP_SHARE of the schedule's
    keys (and STRIP_MIN_KEYS), each once, is the strip; a few tags lined up
    along a wall, or a key repeated in the row, are still tags.
    Returns (kept hits, number of strips dropped)."""
    need = max(STRIP_MIN_KEYS, -(-int(len(set(keys.values())) *
                                      STRIP_SHARE * 100) // 100))
    if len(hits) < need:
        return hits, 0
    drop = set()
    strips = 0
    for axis in ("cy", "x0"):
        used = set()
        for i, (k, _n, c) in enumerate(hits):
            if i in used or i in drop:
                continue
            tol = 0.3 * c["h"]
            row = [j for j, (_k, _m, d) in enumerate(hits)
                   if j not in drop and abs(d[axis] - c[axis]) <= tol and
                   0.8 <= d["h"] / max(c["h"], 1e-6) <= 1.25]
            used.update(row)
            ks = [hits[j][0] for j in row]
            # (a legend lists sized variants of one key - '4"-GCO' and
            # '3"-GCO' - each once: the printed tags are what must differ)
            txt = [re.sub(r"\s+", "", hits[j][2]["text"]).upper()
                   for j in row]
            if len(set(txt)) == len(txt) and len(txt) >= need and \
                    len(set(ks)) >= min(need, len(set(keys.values()))):
                drop.update(row)
                strips += 1
    return [h for j, h in enumerate(hits) if j not in drop], strips


TAG_SIZE_MIN_HITS = 8   # enough tags on a sheet to know their text size
TAG_SIZE_SHARE = 0.8     # a one-letter hit below this share of it: not a tag
TAG_SIZE_MAX = 1.25      # ... or above this share (zone letters, titles)


_PART = re.compile(r"^\(([A-Z][A-Z0-9 /&.-]{1,20})\)$")


def _part_label(c, cells):
    """'(ERV)', '(DX COIL)' printed with an equipment tag: the tag names a
    part of one unit drawn as several pieces."""
    h = c["h"]
    for d in cells:
        m = _PART.match(d["text"].strip())
        if not m or d is c:
            continue
        if abs(d["cy"] - c["cy"]) <= 2.2 * h and \
                c["x0"] - 6 * h <= d["cx"] <= c["x1"] + 6 * h:
            return m.group(1).upper()
    return None


_SENSOR = re.compile(r"^(?:T|S|H|TS|HS|TH|CO2?|RH|SD|DS)$", re.I)


def _sensor_label(c, cells):
    """True when `c` labels a thermostat / sensor symbol beside it ('(T)
    AHU-1' on an HVAC plan names the unit the thermostat serves - it is
    not the unit's tag)."""
    h = c["h"]
    for d in cells:
        if d is c or not _SENSOR.match(d["text"].strip()):
            continue
        if abs(d["cy"] - c["cy"]) > 1.2 * h:
            continue                 # (the T sits in a circle, a bit low)
        gap = c["x0"] - d["x1"] if d["cx"] < c["cx"] else d["x0"] - c["x1"]
        if -0.2 * h <= gap <= 2.5 * h:
            return True
    return False


def count_tags(info, keys, kind, excl, vs=None):
    """Tags of `keys` ({normalised key: key}) on one sheet: {"main": {key:
    [hit]}, "other": [(key, [hit], view title)], "skipped": n} where a
    hit is {rect, n} in displayed coordinates. Counted once per distinct
    position in the main view(s); tags in other views go to "other"."""
    cells, w = info["cells"], info["w"]
    segs = info["segs"] or []
    vs = views(cells, excl) if vs is None else vs
    raw = []
    skipped = 0
    for c in cells:
        if any(_inside(c, r) for r in excl):
            continue
        m = _tag_match(c["text"], keys, kind)
        if not m:
            continue
        key, n = m
        if len(key) == 1 and _circled(c, segs):
            skipped += 1                     # a grid bubble
            continue
        if kind == "door" and _room_tag(c, cells):
            skipped += 1
            continue
        if kind == "mechanical equipment" and _sensor_label(c, cells):
            skipped += 1                     # '(T) AHU-1': its thermostat
            continue
        raw.append((key, n, c))
    # one per distinct position: a tag drawn twice on top of itself
    hits = []
    for key, n, c in raw:
        if any(k == key and abs(c["cx"] - d["cx"]) <= 1.5 * c["h"] and
               abs(c["cy"] - d["cy"]) <= 1.5 * c["h"] for k, _n, d in hits):
            continue
        hits.append((key, n, c))
    hits, strips = _drop_key_strips(hits, keys)
    # a one-letter hit set much smaller than the sheet's tags is a
    # subscript or note letter (a dimmer switch's D), much bigger a sheet
    # zone letter in the margin - not a tag
    if len(hits) >= TAG_SIZE_MIN_HITS:
        hs = sorted(c["h"] for _k, _n, c in hits)
        med = hs[len(hs) // 2]
        small = [t for t in hits if len(t[0]) == 1 and not (
                 TAG_SIZE_SHARE * med <= t[2]["h"] <= TAG_SIZE_MAX * med)]
        if small:
            skipped += len(small)
            hits = [t for t in hits if t not in small]
    owner = {}
    counts = Counter()
    for key, n, c in hits:
        v = view_of(c, vs, w)
        owner[id(c)] = v
        if v is not None:
            counts[id(v)] += 1
    mains = main_views(vs, counts)
    main_ids = {id(v) for v in mains}
    out = {"main": {}, "other": [], "skipped": skipped, "strips": strips,
           "views": [v["title"] for v in vs],
           "main_views": [v["title"] for v in mains]}
    other = {}
    for key, n, c in hits:
        v = owner[id(c)]
        hit = {"rect": (c["x0"], c["y0"], c["x1"], c["y1"]), "n": n,
               "text": c["text"]}
        if "equipment" in (kind or ""):
            pt = _part_label(c, cells)
            if pt:
                hit["part"] = pt
        if v is None or id(v) in main_ids or (not mains and v["plan"]):
            out["main"].setdefault(key, []).append(hit)
        else:
            other.setdefault((key, v["title"]), []).append(hit)
    # a mezzanine / attic plan drawn beside the floor plan shows its own
    # equipment (the condensing units and fans up in the mezzanine): a key
    # tagged only there - never in the main view - is counted from it
    for (k, t), hs in list(other.items()):
        if k not in out["main"] and _LEVEL_VIEW.search(t) and \
                not _PART_VIEW.search(t):
            out["main"][k] = hs
            del other[(k, t)]
    out["other"] = [(k, hs, t) for (k, t), hs in other.items()]
    return out


_LEVEL_VIEW = re.compile(r"\b(?:MEZZANINE|ATTIC)\b", re.I)
_PART_VIEW = re.compile(r"\b(?:ENLARGED|PARTIAL|DETAIL|SECTION|ELEVATION|"
                        r"KEY\s*PLAN|BLOW[-\s]?UP|INSET)\b", re.I)


# ------------------------------------------------------------- set
def _row_qty(row, t):
    if not t.get("qty"):
        return None
    m = re.search(r"\d+", row.get(t["qty"], "") or "")
    return int(m.group(0)) if m else None


def _desc(row, t):
    d = (row.get(t.get("desc") or "", "") or "").strip()
    return re.sub(r"\s+", " ", d)[:48]


def hw_value(v):
    """'SET 1.0', '#1', 'HW-1', '1' -> '1.0' style set numbers as written
    (only SET / # / HW- words dropped)."""
    t = re.sub(r"^(?:HDWR?\.?|HW|HARDWARE)?\s*(?:SET|GROUP|GRP\.?)?\s*[#-]?\s*",
               "", (v or "").strip(), flags=re.I)
    return t.strip(" .") or ""


def line_name(kind, key, desc=""):
    pre = PREFIX.get(kind, "")
    base = f"{pre}{key}"
    return (f"{base} {desc}".strip() if desc else base)[:60].rstrip()


_LIGHTING = re.compile(r"\bLIGHTING\b", re.I)
_DEVICE_PLAN = re.compile(r"\b(?:POWER|SIGNAL|DATA|TELECOM\w*|FIRE\s+ALARM|"
                          r"SYSTEMS?|AUXILIARY|SECURITY)\b", re.I)


_ELEV_TYPE_WORD = re.compile(r"\b(?:STOREFRONT|WINDOW|CURTAIN\s*WALL)\s+"
                             r"(?:TYPE\s+)?[A-Z0-9](?:\.\d{1,2})?\s*$",
                             re.I | re.M)
_ELEV_TYPE = re.compile(r"^(?:ALUM(?:INUM)?\.?\s+)?(?:STOREFRONT|WINDOW|"
                        r"CURTAIN\s*WALL)\s+(?:TYPE\s+)?([A-Z](?:\.\d{1,2})?|"
                        r"\d{1,2}[A-Z]?)$", re.I)


def _elevation_widths(rows, cells):
    """The overall width of each elevation type ('_width_ft'): the topmost
    dimension string over the drawing above its title - between the title
    row above and the title, from the title to the next title in its row."""
    from .scalecheck import _ft
    keys = [r["_key_rect"] for r in rows]
    dims = []
    for c in cells:
        if c["x1"] - c["x0"] < c["y1"] - c["y0"]:
            continue                                  # turned text
        v = _ft(c["text"])
        if v and v >= 1.0:
            dims.append((c, v))
    for r, k in zip(rows, keys):
        h = max(k[3] - k[1], 4.0)
        cy = (k[1] + k[3]) / 2
        top = max([o[3] for o in keys if (o[1] + o[3]) / 2 < cy - 2 * h],
                  default=0.0)
        right = min([o[0] for o in keys if o is not k and
                     abs((o[1] + o[3]) / 2 - cy) <= h and o[0] > k[0]],
                    default=1e9)
        cand = [(c, v) for c, v in dims if top < c["cy"] < k[1] and
                k[0] - 3 * h <= c["cx"] < right - 3 * h]
        if not cand:
            continue
        c0, v0 = min(cand, key=lambda cv: cv[0]["cy"])
        # the overall dimension: none in its row is longer
        if all(v <= v0 + 1e-6 for c, v in cand
               if abs(c["cy"] - c0["cy"]) <= h):
            r["_width_ft"] = round(v0, 3)


def elevation_types(cells):
    """Window / storefront types drawn as elevations, each under its own
    title ('STOREFRONT A.1', 'WINDOW TYPE 3'), as a window table to count
    on the plans; None for fewer than two types."""
    rows, seen = [], set()
    for c in sorted(cells, key=lambda c: (c["cy"], c["cx"])):
        m = _ELEV_TYPE.match(c["text"].strip(" :"))
        if not m or m.group(1).upper() in seen:
            continue
        seen.add(m.group(1).upper())
        rows.append({"MARK": m.group(1).upper(),
                     "_key_rect": (c["x0"], c["y0"], c["x1"], c["y1"])})
    if len(rows) < 2:
        return None
    _elevation_widths(rows, cells)
    box = _box([c for c in cells if _ELEV_TYPE.match(c["text"].strip(" :"))])
    return {"kind": "window", "title": "STOREFRONT / WINDOW TYPES",
            "csi": CSI.get("window", ""), "bbox": box, "columns": ["MARK"],
            "key": "MARK", "qty": None, "desc": None, "hw": None,
            "rows": rows, "confident": True, "why": "", "elevations": True}


DETAIL_PT_PER_FT = 72.0        # larger than 1" = 1'-0" is a detail scale


def _detail_scaled(r):
    sc = r.get("scale")
    if not sc or r.get("page") is None:
        return False
    try:
        ppf = float(sc[1]) * {"ft": 1.0, "in": 12.0, "m": 0.3048,
                              "yd": 1 / 3.0}.get(sc[2], 1.0)
    except (TypeError, ValueError, IndexError):
        return False
    return bool(ppf and ppf > DETAIL_PT_PER_FT * 1.01)


def fixture_plans(kind, rs):
    """The plans a schedule's keys are counted on. Light fixtures are
    counted on the lighting plans: when the set has one, the power /
    signal / fire alarm plans are left out (their letters are device
    suffixes - a GFCI receptacle's G - not fixture tags)."""
    if kind != "light fixtures" or not any(
            _LIGHTING.search(r.get("title") or "") for r in rs):
        return rs
    return [r for r in rs if _LIGHTING.search(r.get("title") or "") or
            not _DEVICE_PLAN.search(r.get("title") or "")]


def takeoff(doc, rows, progress=None, cache=None, pages=None):
    """Schedules across the set: {"tables": [table + page/sheet], "lines":
    [{kind, key, name, csi, qty, unit, status ('taken off' | 'review'),
    basis, page, hits: [{page, rect}], why}], "review": [...],
    "problems": [...], "pages": [schedule pages]}.

    `rows` are aitakeoff.plan_set rows: which sheets are plans (where keys
    are counted) and their disciplines. `pages`: read schedules only on
    these (all sheets when None); keys are counted on every plan."""
    cache = {} if cache is None else cache
    res = {"tables": [], "lines": [], "review": [], "problems": [],
           "pages": []}
    by_page = {r["page"]: r for r in rows}

    def sheet(p):
        r = by_page.get(p) or {}
        return r.get("number") or f"page {p + 1}"
    live = [r for r in rows if r.get("kind") != "superseded" and
            not r.get("raster")]
    tables = {}
    for i, r in enumerate(live):
        if progress and progress(i, len(live)) is False:
            break
        p = r["page"]
        if pages is not None and p not in pages:
            continue
        try:
            txt = doc[p].get_text()
        except Exception:                                 # noqa: BLE001
            continue
        if not _SCHED_WORD.search(txt):
            continue
        try:
            info = sheet_info(doc[p], cache)
            ts = read_cells(info["cells"], info["segs"], info["w"],
                            info["h"], r.get("discipline", ""))
        except Exception as e:                            # noqa: BLE001
            log.exception("schedules on page %d", p)
            res["problems"].append(f"{sheet(p)}: schedules not read ({e})")
            continue
        for t in ts:
            t["page"], t["sheet"] = p, sheet(p)
            t["discipline"] = r.get("discipline", "")
        if ts:
            tables[p] = ts
            res["pages"].append(p)
            res["tables"] += [t for t in ts if not t.get("skip")]
            # panel names headed on a schedule sheet whose circuit table
            # isn't text (drawn as linework): the panels still exist
            if r.get("kind") != "plan":
                for t in ts:
                    m = re.match(r"^PANEL(?:BOARD)?\s+\"?([A-Z]{1,3}-?\d{1,3}"
                                 r"[A-Z]?)\"?$", t.get("title") or "", re.I)
                    if t.get("kind") == "panel" and t.get("skip") and m:
                        res.setdefault("panel_names", {}).setdefault(
                            m.group(1).upper(), (p, sheet(p)))
    if not any(t["kind"] == "window" for t in res["tables"]):
        # no window schedule: storefront / window types drawn as elevations
        # ('STOREFRONT A.1', 'STOREFRONT B' on A-802) are the type list
        for r in live:
            if r.get("discipline") not in ("architectural", "") or (
                    pages is not None and r["page"] not in pages):
                continue
            try:
                txt = doc[r["page"]].get_text()
            except Exception:                             # noqa: BLE001
                continue
            if not _ELEV_TYPE_WORD.search(txt):
                continue
            t = elevation_types(sheet_info(doc[r["page"]], cache)["cells"])
            if t:
                t.update(page=r["page"], sheet=sheet(r["page"]),
                         discipline=r.get("discipline", ""))
                t["why"] = (f"types from the elevation titles on "
                            f"{t['sheet']} (the set has no window schedule)")
                res["tables"].append(t)
                break
    # sheets where keys are counted: plans, and schedule sheets that
    # carry a plan view of their own
    plan_pages = [r for r in live if r.get("kind") == "plan"]
    extra = [r for r in live if r["page"] in tables and r.get("kind") !=
             "plan"]
    tag_cache = {}

    def counts_on(r, keys, kind):
        p = r["page"]
        info = sheet_info(doc[p], cache)
        if p not in tag_cache:
            ex = plan_exclusions(info, tables.get(p))
            tag_cache[p] = (ex, view_regions(views(info["cells"], ex),
                                             info["segs"] or [], info["w"],
                                             info["h"], ex))
        ex, vs = tag_cache[p]
        if r.get("kind") != "plan" and not any(v["plan"] for v in vs):
            return None
        return count_tags(info, keys, kind, ex, vs)

    def plans_for(t):
        discs = set(DISCIPLINES.get(t["kind"], ())) | {t["discipline"]}
        rs = [r for r in plan_pages + extra if r.get("discipline") in discs]
        # a sheet drawn at a detail scale (A-701 'ATTIC ACCESS' at 1-1/2" =
        # 1'-0") is not where the set's tags are counted
        keep = [r for r in rs if not _detail_scaled(r)]
        return fixture_plans(t["kind"], keep or rs)
    door_t = [t for t in res["tables"] if t["kind"] == "door"]
    for t in res["tables"]:
        if t["kind"] == "finish" or t["kind"] == "column":
            continue                    # read for others (structural)
        if t["kind"] == "hardware":
            continue                    # counted from the door schedule
        try:
            if t["kind"] == "door":
                _doors(t, plans_for(t), counts_on, res, sheet)
            elif t["kind"] == "panel":
                if not t.get("skip"):
                    _panel(t, res)
            elif t["kind"] in COUNTED:
                _keyed(t, plans_for(t), counts_on, res, sheet, by_page)
        except Exception as e:                            # noqa: BLE001
            log.exception("schedule %s", t["title"])
            res["problems"].append(f"{t['sheet']}: {t['title']} not "
                                   f"counted ({e})")
    _one_line_per_tag(res, sheet)
    for t in res["tables"]:
        if not t["confident"] and not t.get("skip") and t["kind"] in \
                COUNTED + ("door", "panel"):
            res["problems"].append(
                f"{t['sheet']}: {t['title']} - {t['why'] or 'not read with confidence'}"
                " - its quantities are in review")
    if not door_t and any(t["kind"] == "hardware" for t in res["tables"]):
        res["problems"].append("hardware sets read but no door schedule to "
                               "count them from - count them by hand")
    return res


def _one_line_per_tag(res, sheet):
    """One piece of equipment listed in two schedules (the water heater in
    the plumbing schedule and again in the electrical connection
    schedule, a louver in the louver and the fan schedules) is one item:
    a later schedule's line whose key and tags are a line already counted
    is dropped, and the drop is listed for review."""
    seen = {}
    keep = []
    for ln in res["lines"]:
        hs = ln.get("hits") or []
        if ln.get("kind") in ("door", "plants") or not hs or \
                ln.get("status") != "taken off":
            keep.append(ln)
            continue
        k = norm_key(ln.get("key") or "", ln.get("kind") or "").upper()
        sig = {(h["page"], tuple(round(v) for v in h["rect"])) for h in hs}
        prev = seen.get(k)
        if prev is not None and sig & prev[1]:
            res["review"].append({
                "sheet": sheet(ln["page"]), "page": ln["page"],
                "name": ln["name"], "qty": ln["qty"], "unit": "ea",
                "why": f"listed again in another schedule ('{prev[0]['name']}'"
                       ") - the same tags on the plans, counted once",
                "engine": "schedules", "csi": ln.get("csi"),
                "kind": ln.get("kind"), "key": ln.get("key")})
            continue
        if prev is None:
            seen[k] = (ln, sig)
        keep.append(ln)
    res["lines"] = keep


def _review(res, t, name, qty, why, page=None, kind=None, key=None,
            sheet_name=None):
    res["review"].append({"sheet": sheet_name or t["sheet"],
                          "page": t["page"] if page is None else page,
                          "name": name, "qty": qty, "unit": "ea",
                          "why": why, "engine": "schedules",
                          "csi": t["csi"], "kind": kind or t["kind"],
                          "key": key})


def _schedule_hits(t, rows_):
    return [{"page": t["page"], "rect": r["_key_rect"]} for r in rows_
            if r.get("_key_rect")]


def _doors(t, plans, counts_on, res, sheet):
    rows_ = t["rows"]
    if not rows_:
        _review(res, t, "Doors", None, t["why"] or "no door rows read")
        return
    sched = {norm_key(r[t["key"]]): r for r in rows_}
    n_sched = 0
    for r in rows_:
        q = _row_qty(r, t)
        n_sched += q if q else 1
    keys = {k: k for k in sched}
    seen, where, other = {}, {}, []
    for pr in plans:
        c = counts_on(pr, keys, "door")
        if c is None:
            continue
        for k, hs in c["main"].items():
            if k not in seen:
                seen[k] = {"page": pr["page"], "rect": hs[0]["rect"]}
                where[k] = pr["page"]
        for k, hs, vt in c["other"]:
            other.append((pr["page"], k, len(hs), vt))
    found = set(seen)
    missing = sorted(set(sched) - found)
    reasons = []
    if not t["confident"]:
        reasons.append(t["why"] or "door schedule not read with confidence")
    if not plans:
        reasons.append("no architectural plan to check the door tags on")
    elif missing:
        reasons.append(f"{len(missing)} door(s) in the schedule with no tag "
                       "on the plans: " + ", ".join(missing[:10]))
    if n_sched != len(rows_):
        reasons.append("door schedule has a quantity column - check")
    ok = not reasons
    line = {"kind": "door", "key": "Doors", "name": "Doors", "csi": t["csi"],
            "qty": n_sched, "unit": "ea", "page": t["page"],
            "basis": f"{len(rows_)} door schedule row(s) on {t['sheet']}, "
                     f"{len(found)} door tag(s) found on the plans",
            "status": "taken off" if ok else "review",
            "why": "; ".join(reasons)}
    if ok:
        # one mark per door, on the plan at its tag
        line["hits"] = [{"page": seen[k]["page"], "rect": seen[k]["rect"]}
                        for k in sched if k in seen]
        res["lines"].append(line)
    else:
        line["hits"] = []
        res["lines"].append(line)
        _review(res, t, "Doors", n_sched, "door count: " + line["why"])
    for p, k, n, vt in other:
        _review(res, t, f"Door {k}", n, f"door tag also in the view "
                f"'{vt}' on {sheet(p)} - not counted twice", page=p,
                key=k, sheet_name=sheet(p))
    # hardware sets: how many doors carry each set
    if t.get("hw"):
        hw = Counter()
        hw_rows = {}
        for r in rows_:
            v = hw_value(r.get(t["hw"], ""))
            if v:
                hw[v] += _row_qty(r, t) or 1
                hw_rows.setdefault(v, []).append(r)
        blank = sum(1 for r in rows_ if not hw_value(r.get(t["hw"], "")))
        for v, n in sorted(hw.items(), key=lambda kv: _num(kv[0])):
            name = line_name("hardware", v)
            hl = {"kind": "hardware", "key": v, "name": name,
                  "csi": CSI["hardware"], "qty": n, "unit": "ea",
                  "page": t["page"], "basis": f"door schedule {t['hw']} "
                  f"column on {t['sheet']}",
                  "status": "taken off" if ok else "review",
                  "why": "" if ok else "door count not confirmed: " +
                  line["why"],
                  "hits": _schedule_hits(t, hw_rows[v]) if ok else []}
            res["lines"].append(hl)
            if not ok:
                _review(res, t, name, n, hl["why"], kind="hardware", key=v)
        if blank:
            _review(res, t, "Hardware set (blank)", blank,
                    f"{blank} door(s) with no hardware set in the schedule",
                    kind="hardware")


def _num(v):
    try:
        return (0, float(re.sub(r"[^\d.]", "", v) or 0), v)
    except ValueError:
        return (1, 0.0, v)


def _panel(t, res):
    if not t["rows"]:
        _review(res, t, t["title"][:40], None, t["why"] or "panel not read",
                kind="panel")
        return
    name = line_name("panel", t["rows"][0]["PANEL"])
    if any(ln["kind"] == "panel" and ln["name"] == name
           for ln in res["lines"]):
        return                         # the same panel named twice
    res["lines"].append({"kind": "panel", "key": t["rows"][0]["PANEL"],
                         "name": name, "csi": t["csi"], "qty": 1,
                         "unit": "ea", "page": t["page"], "status":
                         "taken off", "why": "", "basis": "panel schedule "
                         f"on {t['sheet']}",
                         "hits": [{"page": t["page"], "rect": t["bbox"]}]})


def _keyed(t, plans, counts_on, res, sheet, by_page):
    """A schedule of things tagged on the plan by key: each key counted on
    the plans (counts_on), checked against the schedule's QTY column."""
    if not t["rows"]:
        _review(res, t, t["title"][:40], None, t["why"] or "no rows read")
        return
    keyrow = {}
    for r in t["rows"]:
        keyrow.setdefault(norm_key(r[t["key"]], t["kind"]), r)
    # a row keyed by the number of a sheet in the set is a cross-reference
    # ('see A-805 storefront details'), not a type: on the plans that
    # number is the sheet named in section / detail callouts
    nums = {norm_key(r.get("number") or "") for r in by_page.values()}
    keyrow = {k: r for k, r in keyrow.items()
              if not (k in nums and re.search(r"\d", k))}
    keys = {k: k for k in keyrow}
    if t["kind"] != "plants":
        keys = {k.upper(): k for k in keys}
    per_sheet = {}                       # key -> [(page, level, hits)]
    others = []
    lvs = dict(zip([id(pr) for pr in plans], fold_levels(
        [level_of(pr.get("title", "")) for pr in plans])))
    for pr in plans:
        c = counts_on(pr, keys, t["kind"])
        if c is None:
            continue
        lv = lvs[id(pr)]
        for k, hs in c["main"].items():
            per_sheet.setdefault(k, []).append((pr["page"], lv, hs))
        for k, hs, vt in c["other"]:
            others.append((pr["page"], k, hs, vt))
    # the schedule's QTY column is proven when at least two keys tagged on
    # the plans agree with it and (nearly) none disagree: an item it lists
    # that isn't tagged on the plans (loose equipment) then takes its QTY
    agree = disagree = 0
    for k, r in keyrow.items():
        sq_ = _row_qty(r, t)
        n_ = sum(h["n"] for _p, _lv, hs in per_sheet.get(k, [])[:1]
                 for h in hs)
        if sq_ is not None and n_:
            if sq_ == n_:
                agree += 1
            else:
                disagree += 1
    qty_proven = t["confident"] and agree >= 2 and \
        agree >= 3 * disagree and agree / max(1, agree + disagree) >= 0.75
    for k, r in keyrow.items():
        desc = _desc(r, t)
        name = line_name(t["kind"], r[t["key"]].strip(), desc)
        sq = _row_qty(r, t)
        found = per_sheet.get(k, [])
        # one sheet per level (the one with the most tags); the same key on
        # another sheet of that level is the same thing drawn again
        by_lv = {}
        for p, lv, hs in found:
            by_lv.setdefault(lv, []).append((p, hs))
        hits, again = [], []
        for lv, lst in by_lv.items():
            lst.sort(key=lambda x: -sum(h["n"] for h in x[1]))
            p, hs = lst[0]
            hits += [{"page": p, "rect": h["rect"], "n": h["n"],
                      "part": h.get("part")} for h in hs]
            again += lst[1:]
        n_plan = sum(h["n"] for h in hits)
        reasons = []
        parts = [h.get("part") for h in hits]
        part_note = ""
        if len(hits) > 1 and all(parts) and len(set(parts)) == len(parts):
            # DOAS-1 '(ERV)' and DOAS-1 '(DX COIL)': one unit in parts
            part_note = (f"; one unit drawn as its parts "
                         f"({', '.join(parts)}) - counted once")
            for h in hits[1:]:
                h["n"] = 0
            n_plan = 1
        if not t["confident"]:
            reasons.append(t["why"] or "schedule not read with confidence")
        if not plans:
            reasons.append("no plan sheet for this schedule's discipline")
        elif not hits:
            reasons.append("no tags found on the plans")
        if sq is not None and hits and sq != n_plan:
            reasons.append(f"schedule QTY says {sq}, {n_plan} tag(s) on the "
                           "plans")
        if again:
            reasons.append("also tagged on " + ", ".join(
                sheet(p) for p, _hs in again) + " - taken from " + ", ".join(
                sorted({sheet(h['page']) for h in hits})) + " only")
        qty = n_plan if hits else sq
        ok = bool(hits) and t["confident"] and (sq is None or sq == n_plan)
        from_qty = (not hits and plans and sq is not None and sq > 0 and
                    qty_proven)
        if from_qty:
            ok = True
            reasons = ["not tagged on the plans - taken from the "
                       "schedule's QTY column (the other keys' tags agree "
                       "with it)"]
        line = {"kind": t["kind"], "key": r[t["key"]].strip(), "name": name,
                "csi": t["csi"], "qty": qty, "unit": "ea",
                "page": hits[0]["page"] if hits else t["page"],
                "basis": f"{n_plan} tag(s) on the plans" +
                (f", schedule QTY {sq}" if sq is not None else "") +
                part_note,
                "status": "taken off" if ok else "review",
                "why": "; ".join(reasons) if not ok or from_qty else
                "; ".join(reasons[-1:]) if again else "",
                "hits": [h for h in hits for _ in range(h["n"])] if ok
                else []}
        if from_qty:
            line["from_qty"] = True          # no plan tags to mark
        res["lines"].append(line)
        if not ok:
            _review(res, t, name, qty, "; ".join(reasons), key=line["key"])
        elif again:
            for p, hs in again:
                _review(res, t, name, sum(h["n"] for h in hs),
                        f"same key on {sheet(p)} too - not counted twice",
                        page=p, key=line["key"], sheet_name=sheet(p))
    for p, k, hs, vt in others:
        r = keyrow.get(k) or keyrow.get(norm_key(k, t["kind"]))
        nm = line_name(t["kind"], r[t["key"]].strip() if r else k,
                       _desc(r, t) if r else "")
        _review(res, t, nm, sum(h["n"] for h in hs),
                f"tag repeated in the view '{vt}' on {sheet(p)} - not "
                "counted twice; check it isn't a separate item",
                page=p, key=k, sheet_name=sheet(p))
