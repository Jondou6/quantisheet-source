"""Civil and wastewater takeoff: what a utility or site bid is built on.

From a sewer / water / storm plan sheet (vector PDF from CAD):

* Pipe LF by size and material (pipe_systems): runs are traced by line
  style and named from the pipe label printed along them - '8" PVC
  SDR-35', '12" RCP', '4" PVC FM', 'PROP. 8" SAN @ 0.40%'. The length
  written in a label ("245 LF") is kept to check the traced length.
* Structures (structures): manholes, cleanouts, catch basins, inlets,
  valves and hydrants counted by their tags ('MH-12', 'SSMH #3', 'CB-4',
  'CO-2', 'GV-1'), once each across the set, with rim and invert
  elevations read from their callouts ('RIM=104.50', 'INV IN (W)
  8"=96.20', 'INV OUT=96.10') and the depth worked out.
* Depth per run: each run takes the depth of the structures at its ends,
  so pipe LF comes out by depth band (0-6, 6-10, 10-14, 14-18, 18+ ft).
* Profiles: the profile part of a plan-and-profile sheet (found by its
  elevation scale) is left out, so pipe isn't counted twice.

assemblies_for() turns the result into job assemblies (catalog trench
assemblies with D = diameter and H = depth filled in: excavation, bedding,
backfill, shoring...) and marks() into ordinary editable measurements.
"""
import math
import re
from collections import defaultdict

import fitz

from . import tradetakeoff as tt

# ------------------------------------------------------------- text lines
def lines(page):
    """[(text, rect)] - one printed line each (rotated labels along a
    pipe are one line too), in unrotated page coordinates like
    get_drawings()."""
    return [(t, r) for t, r, _, _ in lines_sized(page)]


def lines_sized(page):
    """lines() with each line's text size and direction:
    [(text, rect, size, (cos, sin))]."""
    out = []
    try:
        d = page.get_text("dict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            spans = ln.get("spans", [])
            t = " ".join(sp.get("text", "") for sp in spans)
            t = re.sub(r"\s+", " ", t).strip()
            if t:
                size = max((sp.get("size", 0) for sp in spans), default=0)
                out.append((t, fitz.Rect(ln["bbox"]), size,
                            tuple(ln.get("dir") or (1, 0))))
    return out


def _c(r):
    return ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


# ------------------------------------------------------------- pipe labels
_Q = "\"”″"
_SIZE = rf"(?<![\d./])(\d{{1,2}}(?:\.\d)?)\s*(?:[{_Q}]|''|-?IN\.?(?![A-Z])|-?INCH)"
_MAT = (r"PVC|C-?900|C-?905|D\.?I\.?P\.?|DUCTILE\s+IRON|DI|RCP|R\.C\.P\.|"
        r"HDPE|PE|VCP|V\.C\.P\.|CMP|CPP|ADS|ABS|C\.?I\.?P?|CAST\s+IRON|"
        r"STEEL|STL|CONC(?:RETE)?|PP|N-?12")
# treatment-plant service codes (yard and process piping plans):
# '8" PDG', '12" NPW', '24" DIP ML', '6" TWAS'
_PLANT = (r"TWAS|WAS|SRAS|RAS|MLR|ML|PDG|PDP|NPW|PTE|SCE|RSP|ECS|SCUM|"
          r"HYPO|SH|FE|SE|INF|EFF|LPA|AIR|TS|DS|W2|W3")
_SYS = (_PLANT + r"|SAN(?:ITARY)?(?:\s+SEWER)?|S\.?S\.?|SEWER|F\.?M\.?|FORCE\s*MAIN|"
        r"STM|STORM(?:\s+(?:DRAIN|SEWER))?|ROOF\s+DRAIN|R\.?D\.?|"
        r"DOWNSPOUT|S\.?D\.?|W\.?M\.?|"
        r"WATER(?:\s*(?:MAIN|LINE))?|W|PW|POTABLE(?:\s+WATER)?|GM|GAS|RW|"
        r"RECLAIMED|IRR")
PIPE_LABEL = re.compile(
    _SIZE + r"\s*(?:Ø|DIA\.?)?\s*-?\s*(?:(?P<mat>" + _MAT +
    r")\b\.?)?\s*(?P<cls>(?:SDR|DR)[- ]?\d+|CL(?:ASS)?\.?\s*(?:\d+|[IVX]+\b)|"
    r"SCH(?:\.|EDULE)?\s*\d+|PC\s*\d+)?\s*(?:(?P<mat2>" + _MAT +
    r")\b\.?)?\s*(?:UNKNOWN\s+|UNK\.?\s+)?(?P<sys>" + _SYS + r")?\b",
    re.I)
# not pipe for this takeoff: electrical / telecom conduit, sleeves
_NOT_PIPE = re.compile(r"^\W*(CONDUIT|ELEC|CABLE|TELE|FIBER|SLEEVE|"
                       r"COMM\b|CATV)", re.I)
_SLOPE = re.compile(r"(?:@|S\s*=)\s*(-?\d*\.\d+|\d+)\s*(%|FT/FT|'/')?",
                    re.I)
_LEN = re.compile(r"(?:(?<![\d.])(\d{1,5}(?:\.\d+)?)\s*(?:L\.?F\.?|LIN\.?\s*"
                  r"FT)(?![A-Z])|(?<![\d.])(\d{1,5}(?:\.\d+)?)\s*'"
                  r"(?!\s*-?\s*\d)|L\s*=\s*(\d{1,5}(?:\.\d+)?))", re.I)
_EXIST = re.compile(r"\b(EX\.?|EXIST(?:ING|\.)?|E\.)\s", re.I)
# "(E)" before the label, or an existing mark straight after it:
# '6" PVC SAN (E)', '18" RCP (EXIST.)', '6" W EXISTING'
_EXIST_PAREN = re.compile(r"\((?:E|EX|EXIST|EXISTING)\.?\)\s*$", re.I)
_EXIST_AFTER = re.compile(r"^\s*(?:\((?:E|EX|EXIST|EXISTING)\.?\)|"
                          r"EXIST(?:ING|\.)?(?![A-Z]))", re.I)
_ABAND = re.compile(r"\b(ABAND(?:ON(?:ED)?)?|REMOVE|TO\s+BE\s+REMOVED)\b",
                    re.I)

SYSTEM_NAMES = [
    ("sanitary", re.compile(r"^(SAN|SANITARY|SANITARY SEWER|S\.?S\.?|SEWER)$",
                            re.I)),
    ("force main", re.compile(r"^(F\.?M\.?|FORCE\s*MAIN)$", re.I)),
    ("storm", re.compile(r"^(STM|STORM|STORM DRAIN|STORM SEWER|S\.?D\.?|"
                         r"ROOF\s+DRAIN|R\.?D\.?|DOWNSPOUT)$", re.I)),
    ("water", re.compile(r"^(W|W\.?M\.?|WATER|WATER MAIN|WATER LINE|PW|"
                         r"POTABLE|POTABLE WATER)$", re.I)),
    ("water", re.compile(r"^(NPW)$", re.I)),
    ("plant drain", re.compile(r"^(PDG|SCUM)$", re.I)),
    ("process", re.compile(r"^(" + _PLANT + r")$", re.I)),
    ("gas", re.compile(r"^(GM|GAS)$", re.I)),
    ("reclaimed", re.compile(r"^(RW|RECLAIMED|IRR)$", re.I)),
]


def _system(sys_text, mat):
    s = (sys_text or "").strip()
    for name, rx in SYSTEM_NAMES:
        if rx.match(s):
            return name
    m = (mat or "").upper().replace(".", "")
    if m in ("RCP", "CMP", "ADS", "N-12", "N12", "CPP", "PP", "CONC",
             "CONCRETE"):
        return "storm"
    if m.startswith("C900") or m.startswith("C-900") or m in ("DIP", "DI"):
        return "water"
    if m in ("PVC", "VCP"):
        return "sanitary"
    return ""


def _mat(mat):
    m = re.sub(r"\s+", " ", (mat or "").upper().replace(".", "")).strip()
    return {"DUCTILE IRON": "DIP", "DI": "DIP", "CAST IRON": "CIP",
            "CI": "CIP", "C900": "C900", "C-900": "C900", "C-905": "C905",
            "STL": "STEEL", "CONC": "RCP", "CONCRETE": "RCP"}.get(m, m)


def parse_pipe_label(text):
    """{'size', 'material', 'class', 'system', 'slope', 'length',
    'existing', 'name'} for a pipe label, or None."""
    t = text.translate({0x201D: '"', 0x2033: '"'})
    for m in PIPE_LABEL.finditer(t):
        size = float(m.group(1))
        mat, sysx = m.group("mat") or m.group("mat2"), m.group("sys")
        if not (mat or sysx) or not 1.5 <= size <= 96:
            continue
        rest = t[m.end():]
        if _NOT_PIPE.match(rest):
            continue
        before = t[:m.start()]
        slope = None
        sm = _SLOPE.search(rest)
        if sm:
            v = float(sm.group(1))
            slope = v if (sm.group(2) or "").startswith("%") or v > 0.2 \
                else v * 100
        length = None
        for lm in _LEN.finditer(before + " " + rest):
            length = float(lm.group(1) or lm.group(2) or lm.group(3))
            break
        system = _system(sysx, mat)
        material = _mat(mat)
        sz = f"{size:g}\""
        shown = {"force main": "FM"}.get(system, system)
        code = (sysx or "").strip().upper()
        if re.fullmatch(_PLANT, code):
            shown = code          # '6" PDG', '24" DIP ML', '12" NPW'
        name = " ".join(x for x in (sz, material or "", shown) if x)
        return {"size": size, "material": material,
                "class": (m.group("cls") or "").upper().replace(" ", ""),
                "system": system, "slope": slope, "length": length,
                # system read from the material alone (PVC -> sanitary)
                "guessed": bool(system) and not sysx,
                "existing": bool(_EXIST.search(before + " ") or
                                 _EXIST_PAREN.search(before) or
                                 _EXIST_AFTER.match(rest) or
                                 _ABAND.search(t)),
                "name": name}
    return None


# a length-and-size label whose material is printed on the next line:
# '110 LF-4"' over 'PVC', '4" - 110 LF' under 'SDR-35 PVC' (3c C7)
SPLIT_LABEL = re.compile(
    r"^\s*(?:\d{1,5}(?:\.\d+)?\s*(?:L\.?F\.?|LIN\.?\s*FT\.?)\s*[-@]?\s*"
    r"\d{1,2}(?:\.\d)?\s*(?:[\"”″]|''|-?IN\.?)\s*(?:Ø|DIA\.?)?"
    r"|\d{1,2}(?:\.\d)?\s*(?:[\"”″]|'')\s*(?:Ø|DIA\.?)?\s*[-@]?\s*"
    r"\d{1,5}(?:\.\d+)?\s*(?:L\.?F\.?|LIN\.?\s*FT\.?))\s*$", re.I)


_SIZE_FIRST = re.compile(
    r"^\s*(?P<size>\d{1,2}(?:\.\d)?\s*(?:[\"”″]|'')\s*(?:Ø|DIA\.?)?)"
    r"\s*[-@]?\s*(?P<len>\d{1,5}(?:\.\d+)?\s*(?:L\.?F\.?|LIN\.?\s*FT\.?))\s*$",
    re.I)


def _length_first(text):
    """'6" - 75 LF' -> '75 LF-6"': the size-first form of a split label put
    the way parse_pipe_label reads it (size, then the material that
    follows on the next line). Other text comes back as it is."""
    m = _SIZE_FIRST.match(text or "")
    if not m:
        return text
    return f"{m.group('len').strip()}-{m.group('size').strip()}"


def _join_two(text, t2):
    """The joined label text for a split label and its partner line, in
    a form parse_pipe_label reads, or None."""
    for t in (f"{text} {t2}", f"{_length_first(text)} {t2}"):
        p = parse_pipe_label(t)
        if p and p.get("length"):
            return t
    return None


def join_split_labels(items):
    """[(text, rect, size, dir)] -> the same with each length-and-size
    line that names no material or system ('110 LF-4"') joined to the
    line printed just above or below it that does ('PVC', 'SDR-26 PVC
    SAN'). The partner line is used once."""
    used = set()
    joined_at = {}
    for i, (text, r, size, dr) in enumerate(items):
        if i in used or parse_pipe_label(text) or \
                not SPLIT_LABEL.match(text):
            continue
        sz = size or 6.0
        c = _c(r)
        cos, sin = dr if dr else (1.0, 0.0)
        best = None
        for j, (t2, r2, _s2, d2) in enumerate(items):
            if j == i or j in used or j in joined_at or \
                    parse_pipe_label(t2) or SPLIT_LABEL.match(t2):
                continue
            if d2 and dr and abs(d2[0] * cos + d2[1] * sin) < 0.95:
                continue                       # not the same direction
            c2 = _c(r2)
            vx, vy = c2[0] - c[0], c2[1] - c[1]
            across = abs(-sin * vx + cos * vy)
            along = abs(cos * vx + sin * vy)
            half = max(r.width, r.height, r2.width, r2.height) / 2
            if across > 2.4 * sz or along > half + sz:
                continue
            if _join_two(text, t2) is None:
                continue
            if best is None or across < best[0]:
                best = (across, j)
        if best is not None:
            used.add(best[1])
            joined_at[i] = best[1]
    out = []
    for i, (text, r, size, dr) in enumerate(items):
        if i in used:
            continue
        if i in joined_at:
            t2, r2 = items[joined_at[i]][0], items[joined_at[i]][1]
            out.append((_join_two(text, t2) or f"{text} {t2}",
                        fitz.Rect(r) | r2, size, dr))
        else:
            out.append((text, r, size, dr))
    return out


def pipe_labels(page):
    out = []
    for text, r, size, dr in join_split_labels(lines_sized(page)):
        p = parse_pipe_label(text)
        if p:
            p.update(text=text, rect=r, center=_c(r), size_pt=size or 6.0,
                     dir=dr)
            out.append(p)
    return out


# ------------------------------------------------------------- structures
_STRUCT = re.compile(
    r"(?<![A-Z0-9])(?P<ex>EX\.?\s+|EXIST(?:ING)?\.?\s+|PROP\.?\s+)?"
    r"(?P<kind>SAN(?:ITARY)?\s+MH|SSMH|SMH|SDMH|STMH|MH|MANHOLE|CB|"
    r"CATCH\s+BASIN|DI|DROP\s+INLET|INL(?:ET)?|YI|JB|JUNCTION\s+BOX|"
    r"SSCO|SCO|CO|CLEANOUT|GV|WV|BFV|VALVE|FH|HYD(?:RANT)?|ARV|AV|"
    r"LS|PS|LIFT\s+STATION|PUMP\s+STATION|WW|WET\s+WELL|VLT|VAULT|"
    r"STRUCT(?:URE)?|S)\s*(?:NO\.?|#)?\s*[-#]?\s*(?P<id>\d{1,4}[A-Z]?)"
    r"(?![\d.])(?!\s*(?:[\"']|IN\b|LF|SF|%))", re.I)
KINDS = {
    "manhole": ("SAN MH", "SANITARY MH", "SSMH", "SMH", "MH", "MANHOLE"),
    "storm manhole": ("SDMH", "STMH"),
    "catch basin": ("CB", "CATCH BASIN"),
    "inlet": ("DI", "DROP INLET", "INL", "INLET", "YI"),
    "junction box": ("JB", "JUNCTION BOX"),
    "cleanout": ("SSCO", "SCO", "CO", "CLEANOUT"),
    "valve": ("GV", "WV", "BFV", "VALVE", "ARV", "AV"),
    "hydrant": ("FH", "HYD", "HYDRANT"),
    "pump station": ("LS", "PS", "LIFT STATION", "PUMP STATION", "WW",
                     "WET WELL"),
    "vault": ("VLT", "VAULT"),
    "structure": ("STRUCT", "STRUCTURE", "S"),
}
_KIND_OF = {k: kind for kind, ks in KINDS.items() for k in ks}
_PREFIX = {"manhole": "MH", "manhole 60": "MH", "storm manhole": "SDMH", "catch basin": "CB",
           "inlet": "INL", "junction box": "JB", "cleanout": "CO",
           "valve": "VALVE", "hydrant": "FH", "pump station": "PS",
           "vault": "VAULT", "structure": "S"}
_RIM = re.compile(r"\b(?:RIM|TOP|T\.?C\.?|GRATE|TG|T\.?O\.?C\.?)\s*"
                  r"(?:EL(?:EV)?\.?)?\s*[=:]?\s*(\d{1,4}\.\d{1,3})", re.I)
_INV = re.compile(
    r"\b(?:INVERT|INV|I\.?\s?E)(?![A-Z])\.?"
    r"(?P<mid>(?:[^=:\d]|\d{1,2}\s*[\"\u201d]){0,30}?)"
    r"\s*[=:]?\s*(?P<el>\d{1,4}\.\d{1,3})", re.I)
_IO = re.compile(r"\b(IN|OUT)\b", re.I)
_DIR = re.compile(r"\b(NE|NW|SE|SW|N|S|E|W)\b")
_ISZ = re.compile(r"(\d{1,2})\s*[\"\u201d]")


def _invert(m):
    mid = m.group("mid") or ""
    io, d, sz = _IO.search(mid), _DIR.search(mid.upper()), _ISZ.search(mid)
    return {"io": io.group(1).upper() if io else "",
            "dir": d.group(1) if d else "",
            "size": float(sz.group(1)) if sz else None,
            "el": float(m.group("el"))}


def _kind(k):
    k = re.sub(r"\s+", " ", k.upper()).strip()
    return _KIND_OF.get(k, "structure")


# callouts with no number, as treatment-plant yard piping plans print
# them: "5' Ø MANHOLE", "12\" PLUG VALVE", "FIRE HYDRANT", "CLEANOUT"
_UNNAMED = re.compile(
    r"(?<![A-Z0-9])(?P<ex>EX\.?\s+|EXIST(?:ING)?\.?\s+)?"
    r"(?:(?P<dia>\d{1,2}(?:\.\d)?)\s*'\s*(?:-\s*0\"\s*)?(?:Ø|DIA\.?)?\s*)?"
    r"(?:(?P<vsz>\d{1,2})\s*[\"\u201d]\s*)?"
    r"(?P<kind>MANHOLE|(?:PLUG|GATE|BUTTERFLY|CHECK)\s+VALVE|"
    r"(?:FIRE|YARD)\s+HYDRANT|CLEANOUT)\b(?!\s*(?:No\.?|#)\s*\d)",
    re.I)
_FIVE_FT = re.compile(r"(?<![\d.])5\s*'\s*(?:-\s*0\"\s*)?(?:Ø|DIA)|60\s*[\"\u201d]"
                      r"\s*(?:Ø|DIA)", re.I)
_UNNAMED_KIND = {"MANHOLE": "manhole", "FIRE HYDRANT": "hydrant",
                 "YARD HYDRANT": "hydrant", "CLEANOUT": "cleanout"}


def structure_tags(page):
    """[{id, kind, existing, rect, center}] for each structure tag on the
    page (a bare 'S-1' only when a callout with RIM/INV sits by it).
    Callouts with no number ("5' Ø MANHOLE") get an id from the page and
    their order ("MH p15-1") and "unnumbered": True."""
    out = []
    unnamed = 0
    ls = lines(page)
    elev_lines = [r for t, r in ls if _RIM.search(t) or _INV.search(t)]
    for text, r in ls:
        numbered = not (PIPE_LABEL.search(text) and not re.search(
            r"\b(MH|CO|CB)\b", text, re.I))
        for m in (_STRUCT.finditer(text) if numbered else ()):
            kind = _kind(m.group("kind"))
            if kind == "structure" and not any(
                    abs(e.y0 - r.y1) < 40 and abs(e.x0 - r.x0) < 80
                    for e in elev_lines):
                continue
            if kind == "manhole" and _FIVE_FT.search(text):
                kind = "manhole 60"
            sid = f"{_PREFIX[kind]}-{m.group('id').upper()}"
            ex = (m.group("ex") or "").strip().upper()
            out.append({"id": sid, "kind": kind,
                        "existing": ex.startswith("EX"),
                        "rect": r, "center": _c(r), "text": text})
        if numbered and _STRUCT.search(text):
            continue          # tagged above ("EX MANHOLE No. 9")
        for m in _UNNAMED.finditer(text):
            word = re.sub(r"\s+", " ", m.group("kind").upper())
            kind = _UNNAMED_KIND.get(word, "valve")
            if kind == "manhole" and m.group("dia") and \
                    abs(float(m.group("dia")) - 5) < 0.01:
                kind = "manhole 60"           # "5' Ø MANHOLE" is 60 in
            if kind == "valve" and not m.group("vsz"):
                continue          # "VALVE BOX", "SEE VALVE SCHEDULE"
            c = _c(r)
            # the same structure named twice side by side ("FIRE HYDRANT"
            # at the symbol and "1 - FIRE HYDRANT ASSEMBLY PER ..." in its
            # callout) is one structure
            # (valves of different sizes at one tee stay apart)
            if kind != "valve" and any(
                    o.get("unnumbered") and o["kind"] == kind and
                    math.dist(o["center"], c) <= UNNAMED_SAME_PT
                    for o in out):
                continue
            unnamed += 1
            pno = getattr(page, "number", None)
            where = f"p{pno + 1}-" if isinstance(pno, int) else ""
            label = (f'{m.group("vsz")}" {word.title()}' if kind == "valve"
                     else _PREFIX[kind])
            out.append({"id": f"{label} {where}{unnamed}", "kind": kind,
                        "existing": bool(m.group("ex")),
                        "unnumbered": True, "dia_ft": m.group("dia"),
                        "rect": r, "center": c, "text": text})
    return out


UNNAMED_SAME_PT = 100.0      # two unnumbered callouts of one kind this close

# ------------------------------------------------------------- services
# Water / sewer service callouts that state a count: "1 - 6" x 2" DOUBLE
# STRAP SADDLE TAP PER CITY OF AIKEN", "1 - GATE VALVE AND BOX ...",
# "1 - 2" METER AND BOX", "1 - 2" RPZ BACKFLOW PREVENTER AND ABOVE ...".
_SVC_LINE = re.compile(r"^\s*\(?(\d{1,2})\)?\s*[-\u2013]\s+(\S.*)$")
_SVC_SIZE = re.compile(r"(\d{1,2}(?:\s*\d/\d)?)\s*(?:\"|'')\s*"
                       r"(?:[xX]\s*(\d{1,2}(?:\s*\d/\d)?)\s*(?:\"|''))?")
SERVICE_ITEMS = [
    ("tapping sleeve", re.compile(r"\bTAPPING\s+SLEEVE\b", re.I)),
    ("tapping valve", re.compile(r"\bTAPPING\s+SLEEVE\s+AND\s+VALVE\b",
                                 re.I)),
    ("saddle tap", re.compile(r"\bSADDLE\s+TAP\b", re.I)),
    ("gate valve", re.compile(r"\bGATE\s+VALVE\b", re.I)),
    ("valve box", re.compile(r"\bVALVE\s+(?:AND\s+)?BOX\b", re.I)),
    ("water meter", re.compile(r"\bMETER\b", re.I)),
    ("meter box", re.compile(r"\bMETER\s+(?:AND\s+)?BOX\b", re.I)),
    ("RPZ backflow preventer", re.compile(r"\bRPZ\b|\bBACKFLOW\s+"
                                          r"PREVENTER\b", re.I)),
]


def service_items(page):
    """[{name, qty, size, text, rect}] from service callouts that state a
    count. A callout without a size ("1 - GATE VALVE AND BOX") takes the
    branch size of the tap above it in the same stack ("6\" x 2\" SADDLE
    TAP" -> 2"); a callout that runs on to the next line ("... TAPPING
    SLEEVE AND" / "VALVE ASSEMBLY ...") is read as one."""
    ls = sorted(lines(page), key=lambda tr: (round(tr[1].x0 / 40), tr[1].y0))
    out = []
    branch = None
    last = None
    for i, (text, r) in enumerate(ls):
        m = _SVC_LINE.match(text)
        if not m:
            continue
        body = m.group(2)
        if re.search(r"\bAND\s*$", body) and i + 1 < len(ls):
            t2, r2 = ls[i + 1]
            if 0 <= r2.y0 - r.y1 <= 1.5 * r.height and abs(r2.x0 - r.x0) < \
                    3 * r.height and not _SVC_LINE.match(t2):
                body = body + " " + t2
        kinds = [k for k, rx in SERVICE_ITEMS if rx.search(body)]
        if not kinds:
            continue
        sz = _SVC_SIZE.search(body)
        main = sz.group(1).replace(" ", "-") + '"' if sz else None
        sub = sz.group(2).replace(" ", "-") + '"' if sz and sz.group(2) \
            else None
        same_stack = last is not None and abs(last.x0 - r.x0) < 12 and \
            0 <= r.y0 - last.y1 <= 12 * r.height
        if not same_stack:
            branch = None
        for k in kinds:
            if k in ("tapping sleeve", "saddle tap") and sub:
                size = f"{main} x {sub}"
            elif k == "tapping valve":
                size = sub or main
            elif main and k not in ("tapping sleeve", "saddle tap"):
                size = main
            else:
                size = branch
            name = f"{size} {k}" if size else k
            out.append({"name": name, "qty": int(m.group(1)), "size": size,
                        "kind": k, "text": text, "rect": r,
                        "size_from_tap": bool(size and size == branch and
                                              not main)})
        if sub and ("saddle tap" in kinds or "tapping sleeve" in kinds):
            branch = sub
        last = r
    return out


def structures(page):
    """structure_tags() with their callout read: rim, inverts
    [{io, dir, size, el}], depth (rim - lowest invert) - one entry per
    structure id on the page."""
    tags = structure_tags(page)
    ls = lines(page)
    info = defaultdict(lambda: {"rim": None, "inverts": []})
    # every RIM / INV line goes to the nearest tag above or beside it
    for text, r in ls:
        rims = _RIM.findall(text)
        invs = list(_INV.finditer(text))
        if not rims and not invs:
            continue
        best, bd = None, 160.0
        for t in tags:
            tr = t["rect"]
            dy = r.y0 - tr.y1
            dx = r.x0 - tr.x0
            if tr.intersects(r) or (-6 <= dy <= 130 and -60 <= dx <= 160):
                d = math.hypot(max(0, dx), max(0, dy))
                if tr.intersects(r):
                    d = 0
                if d < bd:
                    best, bd = t, d
        if best is None:
            continue
        rec = info[best["id"]]
        if rims and rec["rim"] is None:
            rec["rim"] = float(rims[0])
        for m in invs:
            rec["inverts"].append(_invert(m))
    out = {}
    for t in tags:
        rec = out.get(t["id"])
        if rec is None:
            rec = out[t["id"]] = dict(t, rim=None, inverts=[], depth=None,
                                      pts=[t["center"]])
        else:
            rec["pts"].append(t["center"])
        got = info.get(t["id"])
        if got:
            rec["rim"] = rec["rim"] or got["rim"]
            have = {(i["io"], i["dir"], i["el"]) for i in rec["inverts"]}
            rec["inverts"] += [i for i in got["inverts"]
                               if (i["io"], i["dir"], i["el"]) not in have]
    for rec in out.values():
        if rec["rim"] is not None and rec["inverts"]:
            d = rec["rim"] - min(i["el"] for i in rec["inverts"])
            rec["depth"] = round(d, 2) if 0 < d < 60 else None
    return list(out.values())


# ------------------------------------------------------------- profiles
_ELEV_NUM = re.compile(r"^\d{2,4}(?:\.0{1,2})?$")


def profile_zones(page):
    """Rects of profile views: a vertical column of evenly spaced, evenly
    stepped elevation numbers (an elevation scale), spanning across to a
    matching column on the far side when there is one."""
    words = page.get_text("words")
    nums = [w for w in words if _ELEV_NUM.match(w[4])]
    cols = defaultdict(list)
    for w in nums:
        cols[round((w[0] + w[2]) / 2 / 6)].append(w)
    axes = []
    for ws in cols.values():
        if len(ws) < 5:
            continue
        ws.sort(key=lambda w: w[1])
        vals = [float(w[4]) for w in ws]
        ys = [(w[1] + w[3]) / 2 for w in ws]
        dv = [vals[i] - vals[i + 1] for i in range(len(vals) - 1)]
        dy = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        if not dv or min(dv) <= 0:
            continue                    # elevations go down the page
        if max(dv) - min(dv) > 1e-6 or max(dy) - min(dy) > max(2.0,
                                                               0.08 * dy[0]):
            continue
        axes.append(fitz.Rect(min(w[0] for w in ws), ys[0] - dy[0] / 2,
                              max(w[2] for w in ws), ys[-1] + dy[0] / 2))
    zones, used = [], set()
    for i, a in enumerate(axes):
        if i in used:
            continue
        partner = None
        for j, b in enumerate(axes):
            if j != i and j not in used and abs(a.y0 - b.y0) < 12 and \
                    abs(a.y1 - b.y1) < 12 and b.x0 > a.x1:
                partner = j if partner is None or b.x0 < axes[partner].x0 \
                    else partner
        if partner is not None:
            used |= {i, partner}
            b = axes[partner]
            zones.append(fitz.Rect(a.x0, min(a.y0, b.y0), b.x1,
                                   max(a.y1, b.y1)))
        else:
            used.add(i)
            zones.append(fitz.Rect(a.x0, a.y0, page.rect.width, a.y1))
    return zones


def _in_zones(pts, zones):
    if not zones:
        return False
    inside = 0
    for p in pts:
        if any(z.contains(fitz.Point(p)) for z in zones):
            inside += 1
    return inside >= len(pts) / 2


# ------------------------------------------------------------- pipe runs
BANDS = [(0, 6), (6, 10), (10, 14), (14, 18), (18, 99)]


def band_of(depth):
    if depth is None:
        return None
    for lo, hi in BANDS:
        if lo <= depth < hi:
            return (lo, hi)
    return BANDS[-1]


def band_name(b):
    if b is None:
        return "depth unknown"
    lo, hi = b
    return f"{lo}-{hi} ft deep" if hi < 99 else f"over {lo} ft deep"


DEBUG = None          # a list to collect why pipe was (not) found


def pipe_systems(page, ppu, unit="ft", min_ft=4.0, reach_ft=25.0,
                 structs=None, zones=None, grade=None):
    """Pipe on a plan sheet: [{name, size, material, system, existing,
    length, label_length, runs: [{pts, length, label, depth}], bands:
    {band: length}, style_name, suggested}], biggest first."""
    per_ft = tt._per_ft(ppu, unit)
    if per_ft <= 0:
        return []
    zones = profile_zones(page) if zones is None else zones
    labs = [l for l in pipe_labels(page)
            if not _in_zones([l["center"]], zones)]
    if not labs:
        return []
    structs = structures(page) if structs is None else structs
    cls = centerlines(page) if grade is not None else []
    reach = reach_ft * per_ft
    groups = tt.styled_segments(page)
    # a pipe label's own text box (or its masking/underline) is not pipe
    boxes = []
    for l in labs:
        m = 1.5 * l["size_pt"]
        r = fitz.Rect(l["rect"])
        boxes.append(fitz.Rect(r.x0 - m, r.y0 - m, r.x1 + m, r.y1 + m))
    text_boxes = []
    for _t, r, size, _d in lines_sized(page):
        m = 0.4 * (size or 6.0)
        text_boxes.append(fitz.Rect(r.x0 - m, r.y0 - m, r.x1 + m, r.y1 + m))
    runs_all = []
    for style, segs in groups.items():
        # utility linetypes ("--- SS --- >> ---") are dashes with gaps
        # for their letters: bridge collinear gaps up to a few feet
        segs = segs + bridge_dashes(segs, 4.0 * per_ft, texts=text_boxes,
                                    text_gap=60.0 * per_ft,
                                    probe=1.5 * per_ft)
        rs = [r for r in tt.runs(segs) if tt.poly_len(r) >= min_ft * per_ft]
        for r in rs:
            if _in_zones(r, zones) or _closed(r):
                continue
            if any(all(b.contains(fitz.Point(x, y)) for x, y in r)
                   for b in boxes):
                continue
            runs_all.append((style, r))
    # a label set off to the side points at its pipe with a leader: look
    # for the pipe at the leader's tip (and the leader itself isn't pipe)
    _leaders(page, labs)
    lead = [l["leader"] for l in labs if l.get("leader")]
    if lead:
        runs_all = [(st, r) for st, r in runs_all
                    if not any(all(tt.dist_to_poly(pt, ld) < 1.0
                                   for pt in r) for ld in lead)]
    # each label belongs to the one run it sits on (the nearest), so a
    # service lateral leaving a main doesn't take the main's label
    mine = {}
    picks = []
    for li, lab in enumerate(labs):
        # a label sits right on its pipe (within a few text heights);
        # only when nothing is that close, the nearest within reach
        near = min(reach, max(10.0, 3.0 * lab["size_pt"]))
        best, bd = None, reach
        close, par = [], set()
        for ri, (_, r) in enumerate(runs_all):
            dd = tt.dist_to_poly(lab["center"], r)
            if dd > reach:
                continue
            along = lab["dir"] is None or _parallel(lab["dir"],
                                                    lab["center"], r)
            if along:
                par.add(ri)
            close.append((dd * (1.0 if along else 2.0), ri))
        tight = [c for c in close if c[0] <= near]
        # a label set along its pipe names a run it runs along: a line
        # that only crosses the label (a lot edge, a curb) is not its
        # pipe when one it follows is that close
        tight = [c for c in tight if c[1] in par] or tight
        pool = tight or [c for c in close if c[0] <= reach]
        if pool:
            bd, best = min(pool)
        picks.append((li, best, bd, close, near))
    # the same label printed several times names one pipe pen: a label
    # with a leader (or set across lines) that landed on another pen
    # takes its twins' pen when a run of it is that close
    pen_of = defaultdict(lambda: defaultdict(int))
    for li, best, bd, close, near in picks:
        lab = labs[li]
        if best is not None and lab["dir"] is not None and \
                not lab.get("leader"):
            pen_of[lab["text"]][runs_all[best][0]] += 1
    for k, (li, best, bd, close, near) in enumerate(picks):
        lab = labs[li]
        pens = pen_of.get(lab["text"])
        if best is None or not pens:
            continue
        pen = max(pens, key=pens.get)
        if runs_all[best][0] == pen:
            continue
        alt = [c for c in close if runs_all[c[1]][0] == pen and
               c[0] <= near]
        if alt:
            bd2, best2 = min(alt)
            picks[k] = (li, best2, bd2, close, near)
    for li, best, bd, _close, _near in picks:
        lab = labs[li]
        if DEBUG is not None:
            DEBUG.append(("label", lab["text"], None if best is None else
                          (tt.style_name(runs_all[best][0]), round(bd, 1),
                           round(tt.poly_len(runs_all[best][1]) / per_ft))))
        if best is not None and (best not in mine or bd < mine[best][1]):
            mine[best] = (lab, bd)
    found = [(style, r, mine[i][0] if i in mine else None)
             for i, (style, r) in enumerate(runs_all)]
    circles = _circles(groups)
    by_style = defaultdict(list)
    for style, r, lab in found:
        by_style[style].append((_to_centres(r, circles), lab))
    out = {}
    for style, items in by_style.items():
        named = [lab for _, lab in items if lab]
        if not named:
            continue
        share = defaultdict(float)
        for r, lab in items:
            if lab:
                share[lab["name"]] += tt.poly_len(r)
        # only styles mostly made of labelled runs (not building outlines
        # that happen to pass a label)
        lab_len = sum(share.values())
        all_len = sum(tt.poly_len(r) for r, _ in items)
        n_lab = sum(1 for _, lab in items if lab)
        if DEBUG is not None:
            DEBUG.append(("style", tt.style_name(style), n_lab,
                          round(lab_len / per_ft), round(all_len / per_ft)))
        if lab_len < (0.35 if n_lab >= 2 else 0.6) * all_len:
            # a pen used for much else too (curbs, buildings): keep the
            # labelled runs and the runs joined to them end to end
            nodes = [(cx, cy) for cx, cy, _r in circles] + \
                [tuple(s_["center"]) for s_ in structs if s_.get("center")]
            frac = lab_len / all_len if all_len else 1.0
            owns, lens, all_have = defaultdict(float), defaultdict(float), {}
            for r, l_ in items:
                if l_:
                    owns[l_["name"]] += tt.poly_len(r)
            for l_ in named:
                lens[l_["name"]] += l_.get("length") or 0.0
                all_have[l_["name"]] = all_have.get(l_["name"], True) and \
                    bool(l_.get("length"))

            def budget(lab, frac=frac, owns=owns, lens=lens,
                       all_have=all_have):
                # labels that print their length ("49 LF-18\" RCP") can't
                # walk to many times that; labels often skip a run between
                # manholes, so allow up to twice. Without lengths, a pen
                # that's nearly all something else (contours, curbs) only
                # walks a little way past its labels.
                nm = lab["name"]
                own = owns[nm]
                if all_have.get(nm):
                    k = 1.25 if frac < 0.05 else 2.0
                    return max(own, k * lens[nm] * per_ft)
                if frac < 0.05:
                    return max(4.0 * own, 50.0 * per_ft)
                return None
            items = _connected(items, 2.0 * per_ft, nodes=nodes,
                               budget=budget)
            if DEBUG is not None:
                DEBUG.append(("kept connected", tt.style_name(style),
                              len(items), round(sum(tt.poly_len(r) for r, _
                                                    in items) / per_ft)))
        elif len(share) > 1:
            # a pen carrying several sizes (2" service, 4" and 6" mains
            # drawn alike): an unlabelled run takes the label of the run it
            # carries on from (through elbows and at structures), never
            # the pen's most common size; a run joined to no labelled
            # run is not pipe this pen's labels can name
            nodes = [(cx, cy) for cx, cy, _r in circles] + \
                [tuple(s_["center"]) for s_ in structs if s_.get("center")]
            items = _connected(items, 2.0 * per_ft, nodes=nodes,
                               max_turn=95.0)
        # a pipe drawn as a thin outlined shape (or stroked twice) is one
        # pipe, not two or three
        items = _drop_coincident(items, max(1.5, 0.5 * per_ft))
        main = max(share, key=share.get)
        main_lab = next(lab for lab in named if lab["name"] == main)
        for r, own in items:
            lab = own or main_lab
            key = (lab["name"], lab["existing"])
            g = out.get(key)
            if g is None:
                g = out[key] = {"name": lab["name"] + (" (existing)" if
                                                       lab["existing"] else
                                                       ""),
                                "size": lab["size"],
                                "material": lab["material"],
                                "system": lab["system"],
                                "guessed": lab.get("guessed", False),
                                "existing": lab["existing"],
                                "length": 0.0, "label_length": 0.0,
                                "labels": set(), "runs": [],
                                "style_name": tt.style_name(style),
                                "slope": lab["slope"]}
            ln = tt.poly_len(r) / ppu
            depth = _run_depth(r, structs, max(reach, 72.0))
            est = False
            if depth is None and grade is not None:
                depth = _cl_depth(r, cls, grade, lab["size"],
                                  max(reach, 72.0))
                est = depth is not None
            g["runs"].append({"pts": r, "length": ln, "label": lab["name"],
                              "depth": depth, "depth_est": est,
                              "screened": _screened(style),
                              # its own label gives a length or slope:
                              # a design callout, so new pipe
                              "designed": bool(own and (own.get("length") or
                                                        own.get("slope")))})
            g["length"] += ln
            # the same label printed twice on a sheet ("216 LF-8\" SDR-26
            # PVC" at both ends of the run) counts once
            lk = (lab["text"], lab.get("length"))
            if lab.get("length") and lk not in g["labels"]:
                g["labels"].add(lk)
                g["label_length"] += lab["length"]
    _band_pipes(page, labs, groups, per_ft, ppu, out, structs, reach)
    _clip_at_match_lines(page, out, ppu)
    _screened_is_existing(out)
    res = []
    for g in out.values():
        bands = defaultdict(float)
        for r in g["runs"]:
            bands[band_of(r["depth"])] += r["length"]
        g["bands"] = dict(bands)
        g["labels"] = len(g["labels"])
        g["suggested"] = not g["existing"]
        res.append(g)
    res.sort(key=lambda g: (g["existing"], -g["size"], -g["length"]))
    return res


# Large pipe (storm culverts, big mains) is often drawn to scale as a band:
# two edges the pipe's outside diameter apart with hatch between, or a
# filled strip. A sized label beside (or pointing at) such a band names it,
# and the pipe is measured once along the band's centre. Only sizes whose
# band is at least BAND_MIN_PT wide on the sheet are looked for; plain
# parallel edges with nothing between (curb and gutter, a walk) are not
# pipe.
BAND_MIN_PT = 3.0


def _od_range(size_in, per_ft):
    """Band widths (pt) a pipe of this nominal size can be drawn at: from a
    little under the nominal size to the outside diameter of thick-walled
    pipe (RCP walls ~ size/12 + 1 in each side)."""
    return (0.9 * size_in / 12 * per_ft,
            (1.35 * size_in + 4) / 12 * per_ft)


def _band_pieces(page, groups, lo, hi):
    """Straight band pieces [(p0, p1, width)] on a page."""
    pieces = []
    # filled strips
    for dr in page.get_drawings():
        f = dr.get("fill")
        if f is None or min(f) > 0.95:
            continue
        pts = []
        for it in dr["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "re":
                r = it[1]
                pts += [r.tl, r.tr, r.br, r.bl]
            elif it[0] == "qu":
                q = it[1]
                pts += [q.ul, q.ur, q.lr, q.ll]
        if len(pts) < 4:
            continue
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        sxx = sum((p.x - cx) ** 2 for p in pts)
        syy = sum((p.y - cy) ** 2 for p in pts)
        sxy = sum((p.x - cx) * (p.y - cy) for p in pts)
        ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
        ux, uy = math.cos(ang), math.sin(ang)
        al = [(p.x - cx) * ux + (p.y - cy) * uy for p in pts]
        ac = [-(p.x - cx) * uy + (p.y - cy) * ux for p in pts]
        L, W = max(al) - min(al), max(ac) - min(ac)
        seq = [p for it in dr["items"] if it[0] == "l" for p in (it[1],)]
        area = abs(sum(a.x * b.y - b.x * a.y
                       for a, b in zip(seq, seq[1:] + seq[:1]))) / 2 \
            if len(seq) >= 3 else L * W
        # a strip: its area fills its box (a sliver or wedge does not)
        if lo <= W <= hi and L >= 3 * W and 0.8 <= area / (L * W) <= 1.2:
            m = (max(ac) + min(ac)) / 2
            ox, oy = cx - uy * m, cy + ux * m
            pieces.append(((ox + ux * min(al), oy + uy * min(al)),
                           (ox + ux * max(al), oy + uy * max(al)), W))
    # hatched edge pairs
    segs = [sg for v in groups.values() for sg in v]
    longs = [sg for sg in segs if math.hypot(sg[2] - sg[0], sg[3] - sg[1])
             >= 3 * lo]
    shorts = []
    for st, v in groups.items():
        for sg in v:
            ln = math.hypot(sg[2] - sg[0], sg[3] - sg[1])
            if 0 < ln < 2.5 * hi:
                a = math.degrees(math.atan2(sg[3] - sg[1], sg[2] - sg[0]))
                shorts.append(((sg[0] + sg[2]) / 2, (sg[1] + sg[3]) / 2,
                               st, round((a % 180) / 10) % 18,
                               (sg[2] - sg[0]) / ln, (sg[3] - sg[1]) / ln))
    G = max(hi * 4, 20.0)
    grid = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(longs):
        for t in (0.0, 0.5, 1.0):
            grid[(int((x0 + t * (x1 - x0)) // G),
                  int((y0 + t * (y1 - y0)) // G))].append(i)
    sgrid = defaultdict(list)
    for sh_ in shorts:
        sgrid[(int(sh_[0] // G), int(sh_[1] // G))].append(sh_)
    done = set()
    for i, (x0, y0, x1, y1) in enumerate(longs):
        L = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        cand = set()
        for t in (0.0, 0.5, 1.0):
            gx = int((x0 + t * (x1 - x0)) // G)
            gy = int((y0 + t * (y1 - y0)) // G)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cand.update(grid[(gx + dx, gy + dy)])
        for j in cand:
            if j <= i or (i, j) in done:
                continue
            done.add((i, j))
            a0, b0, a1, b1 = longs[j]
            L2 = math.hypot(a1 - a0, b1 - b0)
            vx, vy = (a1 - a0) / L2, (b1 - b0) / L2
            if abs(ux * vx + uy * vy) < 0.995:
                continue
            w = abs(-(a0 - x0) * uy + (b0 - y0) * ux)
            if not lo <= w <= hi:
                continue
            t0 = (a0 - x0) * ux + (b0 - y0) * uy
            t1 = (a1 - x0) * ux + (b1 - y0) * uy
            s0, s1 = max(0.0, min(t0, t1)), min(L, max(t0, t1))
            if s1 - s0 < 3 * lo:
                continue
            side = 1 if (-(a0 - x0) * uy + (b0 - y0) * ux) > 0 else -1
            nx, ny = -uy * side, ux * side
            # hatch between the edges: closely spaced strokes of one pen
            # and one slant, across the strip
            n_in = defaultdict(int)
            gx0 = int(min(x0, x1) // G) - 1
            gx1 = int(max(x0, x1) // G) + 1
            gy0 = int(min(y0, y1) // G) - 1
            gy1 = int(max(y0, y1) // G) + 1
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    for x, y, st, ab, cx_, cy_ in sgrid.get((gx, gy), ()):
                        tt_ = (x - x0) * ux + (y - y0) * uy
                        nn = (x - x0) * nx + (y - y0) * ny
                        if s0 <= tt_ <= s1 and 0.2 * w <= nn <= 0.8 * w \
                                and abs(cx_ * ux + cy_ * uy) < 0.9:
                            n_in[(st, ab)] += 1
            if not n_in or max(n_in.values()) < 2.0 * (s1 - s0) / w:
                continue
            ox, oy = x0 + nx * w / 2, y0 + ny * w / 2
            pieces.append(((ox + ux * s0, oy + uy * s0),
                           (ox + ux * s1, oy + uy * s1), w))
    # one band found twice (its fill and its edges): keep the longer
    pieces.sort(key=lambda p: -math.dist(p[0], p[1]))
    out = []
    for p in pieces:
        m = ((p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2)
        if any(tt.dist_to_poly(m, [q[0], q[1]]) < q[2] / 2 for q in out):
            continue
        out.append(p)
    return out


def _band_pipes(page, labs, groups, per_ft, ppu, out, structs, reach):
    """Measure sized labels' pipe drawn as a band (see BAND_MIN_PT)."""
    sizes = sorted({l["size"] for l in labs if l.get("size") and
                    _od_range(l["size"], per_ft)[0] >= BAND_MIN_PT})
    for size in sizes:
        lo, hi = _od_range(size, per_ft)
        try:
            pcs = _band_pieces(page, groups, lo, hi)
        except Exception:                                # noqa: BLE001
            continue
        if not pcs:
            continue
        used = set()
        for lab in [l for l in labs if l.get("size") == size]:
            pts = [lab["center"]] + ([lab["leader"][-1]]
                                     if lab.get("leader") else [])
            near = max(3.0 * lab["size_pt"], hi * 2)
            seed = [k for k, p in enumerate(pcs) if k not in used and
                    any(tt.dist_to_poly(q, [p[0], p[1]]) <= near
                        for q in pts)]
            if not seed:
                continue
            chain, todo = set(seed), list(seed)
            while todo:                       # pieces joined end to end
                k = todo.pop()
                for j, q in enumerate(pcs):
                    if j in chain or j in used:
                        continue
                    if abs(q[2] - pcs[k][2]) > 0.25 * max(q[2], pcs[k][2]):
                        continue                 # another band width
                    if min(math.dist(a, b) for a in pcs[k][:2]
                           for b in q[:2]) <= 1.5 * max(pcs[k][2], q[2]):
                        chain.add(j)
                        todo.append(j)
            used |= chain
            key = (lab["name"], lab["existing"])
            g = out.get(key)
            if g is None:
                g = out[key] = {"name": lab["name"] + (" (existing)" if
                                                       lab["existing"] else
                                                       ""),
                                "size": lab["size"],
                                "material": lab["material"],
                                "system": lab["system"],
                                "guessed": lab.get("guessed", False),
                                "existing": lab["existing"],
                                "length": 0.0, "label_length": 0.0,
                                "labels": set(), "runs": [],
                                "style_name": "drawn to scale (band)",
                                "slope": lab["slope"]}
            band = [[list(pcs[k][0]), list(pcs[k][1])] for k in chain]
            # the band's own edges or a centreline already taken for this
            # label are the same pipe: drop runs lying inside the band
            def inside(r, band=band, w=max(pcs[k][2] for k in chain)):
                return all(min(tt.dist_to_poly(pt, b) for b in band) <= w
                           for pt in r["pts"])
            g["runs"] = [r for r in g["runs"] if not inside(r)]
            for b in band:
                ln = tt.poly_len(b) / ppu
                g["runs"].append({"pts": b, "length": ln,
                                  "label": lab["name"],
                                  "depth": _run_depth(b, structs,
                                                      max(reach, 72.0)),
                                  "depth_est": False, "screened": False,
                                  "designed": bool(lab.get("length") or
                                                   lab.get("slope")),
                                  "band": True})
            g["length"] = sum(r["length"] for r in g["runs"])
            lk = (lab["text"], lab.get("length"))
            if lab.get("length") and lk not in g["labels"]:
                g["labels"].add(lk)
                g["label_length"] += lab["length"]


_MATCH = re.compile(r"\bMATCH\s*LINE\b", re.I)


def match_lines(page):
    """[(axis, coord)] - the match lines on a sheet: a long straight line
    (at least half the sheet's short side, possibly dashed) running beside and
    along a "MATCH LINE ..." note. axis 'x' is a line of constant x."""
    out = []
    notes = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(sp["text"] for sp in ln["spans"])
            if _MATCH.search(t):
                notes.append((fitz.Rect(ln["bbox"]), ln["dir"]))
    if not notes:
        return out
    segs = [sg for v in tt.styled_segments(page).values() for sg in v]
    short = min(page.mediabox.width, page.mediabox.height)
    for r, (dx, dy) in notes:
        if abs(dx) > 0.98:            # text runs along x: a line of const y
            axis, lo, hi, h = "y", r.y0, r.y1, r.height
        elif abs(dy) > 0.98:
            axis, lo, hi, h = "x", r.x0, r.x1, r.width
        else:
            continue
        tot = defaultdict(float)
        for x0, y0, x1, y1 in segs:
            if axis == "y" and abs(y1 - y0) < 0.2:
                c, L = (y0 + y1) / 2, abs(x1 - x0)
            elif axis == "x" and abs(x1 - x0) < 0.2:
                c, L = (x0 + x1) / 2, abs(y1 - y0)
            else:
                continue
            if lo - 3 * h <= c <= hi + 3 * h:
                tot[round(c)] += L
        # the long line nearest the note (a sheet border further off is
        # long too, but is not the match line)
        mid = (lo + hi) / 2
        long_ = [c for c, L in tot.items() if L >= 0.5 * short]
        if long_:
            c = min(long_, key=lambda c: abs(c - mid))
            if all(a != axis or abs(c - c0) > h for a, c0 in out):
                out.append((axis, float(c)))
    return out


def _clip_poly(pts, axis, c, keep):
    """The parts of a polyline on one side of a line (keep = +1: coord >=
    c, -1: coord <= c)."""
    k = 0 if axis == "x" else 1
    parts, cur = [], []
    for a, b in zip(pts, pts[1:]):
        ia, ib = (a[k] - c) * keep >= 0, (b[k] - c) * keep >= 0
        if ia and not cur:
            cur = [tuple(a)]
        if ia != ib:
            t = (c - a[k]) / (b[k] - a[k])
            m = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            cur.append(m)
            if ia:
                parts.append(cur)
                cur = []
            else:
                cur = [m]
        if ib:
            cur.append(tuple(b))
    if len(cur) > 1:
        parts.append(cur)
    return [p for p in parts if len(p) > 1]


def _clip_at_match_lines(page, out, ppu):
    """Pipe drawn past a match line belongs to the next sheet: each run is
    cut at the line and the part on the far side (the side with less of the
    sheet's pipe) dropped, so the two sheets don't both count it."""
    try:
        mls = match_lines(page)
    except Exception:                                    # noqa: BLE001
        return
    for axis, c in mls:
        k = 0 if axis == "x" else 1
        side = 0.0
        for g in out.values():
            for r in g["runs"]:
                for a, b in zip(r["pts"], r["pts"][1:]):
                    L = math.dist(a, b)
                    side += L if (a[k] + b[k]) / 2 >= c else -L
        keep = 1 if side >= 0 else -1
        for g in out.values():
            runs = []
            for r in g["runs"]:
                for part in _clip_poly(r["pts"], axis, c, keep):
                    runs.append(dict(r, pts=part,
                                     length=tt.poly_len(part) / ppu))
            g["runs"] = runs
            g["length"] = sum(r["length"] for r in runs)
    for key in [k for k, g in out.items() if not g["runs"]]:
        del out[key]


def _samples(r, step):
    out = []
    for a, b in zip(r, r[1:]):
        L = math.dist(a, b)
        n = max(1, int(L / step))
        for k in range(n):
            t = k / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(tuple(r[-1]))
    if len(out) > 60:
        out = out[::max(1, len(out) // 60)]
    return out


def _drop_coincident(items, tol):
    """[(run, label)] without the runs that lie on top of a longer one
    (90% of their length within `tol`): the two long edges of a pipe drawn
    as a thin outline, a line stroked twice. A dropped run's label goes
    to the run it lies on when that has none."""
    # a run that turns right back on itself (out along one edge of the
    # outline and back along the other) is split at the turn first
    split = []
    for r, lab in items:
        piece = [r[0]]
        for k in range(1, len(r) - 1):
            a, b, c = r[k - 1], r[k], r[k + 1]
            u = (b[0] - a[0], b[1] - a[1])
            v = (c[0] - b[0], c[1] - b[1])
            nu, nv = math.hypot(*u), math.hypot(*v)
            piece.append(b)
            if nu and nv and (u[0] * v[0] + u[1] * v[1]) / (nu * nv) < -0.95:
                split.append((piece, lab))
                piece = [b]
        piece.append(r[-1])
        split.append((piece, lab))
    items = [(r, lab) for r, lab in split if len(r) >= 2]
    order = sorted(range(len(items)), key=lambda i: -tt.poly_len(items[i][0]))
    kept = []                      # [(run, label, bbox)]
    grid = defaultdict(list)
    cell = max(20.0, 10 * tol)

    def keys(bb):
        for gx in range(int(bb[0] // cell), int(bb[2] // cell) + 1):
            for gy in range(int(bb[1] // cell), int(bb[3] // cell) + 1):
                yield gx, gy
    for i in order:
        r, lab = items[i]
        bb = tt._bbox(r)
        bb = (bb[0] - tol, bb[1] - tol, bb[2] + tol, bb[3] + tol)
        cands = {k for key in keys(bb) for k in grid[key]}
        pts = _samples(r, max(2 * tol, 1.0))
        host = None
        for k in sorted(cands):
            kr = kept[k][0]
            n_on = sum(1 for p in pts if tt.dist_to_poly(p, kr) <= tol)
            if n_on >= 0.9 * len(pts):
                host = k
                break
        if host is not None:
            if lab and not kept[host][1]:
                kept[host] = (kept[host][0], lab, kept[host][2])
            continue
        kept.append((r, lab, bb))
        for key in keys(bb):
            grid[key].append(len(kept) - 1)
    return [(r, lab) for r, lab, _bb in kept]


def _screened(style):
    """Grey (screened) linework: how plans show existing pipe next to new
    pipe drawn in black."""
    rgb = style[0] if style else None
    if not rgb:
        return False
    return max(rgb) - min(rgb) < 0.1 and rgb[0] >= 0.55


def _screened_is_existing(out):
    """On a sheet with new pipe drawn in black, pipe drawn in grey is the
    existing piping (a plant expansion's existing clarifier lines were
    counted as new). Moves those runs to the "(existing)" group."""
    if not any(not r.get("screened") for g in out.values()
               if not g["existing"] for r in g["runs"]):
        return
    for key in list(out):
        g = out[key]
        if g["existing"]:
            continue
        grey = [r for r in g["runs"] if r.get("screened")]
        if not grey or any(r.get("designed") for r in grey):
            continue          # "314 LF OF 8\" PDG @ -0.40%" is new pipe
        g["runs"] = [r for r in g["runs"] if not r.get("screened")]
        moved = sum(r["length"] for r in grey)
        g["length"] -= moved
        ekey = (key[0], True)
        e = out.get(ekey)
        if e is None:
            e = out[ekey] = dict(g, name=g["name"] + " (existing)",
                                 existing=True, length=0.0,
                                 label_length=0.0, labels=set(), runs=[])
        e["runs"] += grey
        e["length"] += moved
        if not g["runs"]:
            del out[key]


def _end_dir(r, at_start):
    """Unit direction leaving the run at that end (outward)."""
    a, b = (r[0], r[1]) if at_start else (r[-1], r[-2])
    dx, dy = a[0] - b[0], a[1] - b[1]
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def _connected(items, tol, max_runs=400, nodes=(), max_turn=35.0,
               budget=None):
    """The labelled runs plus the unlabelled runs that carry on from them
    (through a chain of others): joined end to end and going on in about
    the same direction, or meeting at a structure (`nodes`, manhole
    centres). Each added run takes its neighbour's label.

    `budget(lab)`: the most pipe (page units) one label may end up with,
    its own runs included, or None for no limit. A label that prints its
    length ("49 LF-18\" RCP") can't grow to ten times that by walking
    along a pen that's also used for curbs and contours."""
    cos_t = math.cos(math.radians(max_turn))
    keep = [(r, lab) for r, lab in items if lab]
    rest = [(r, lab) for r, lab in items if not lab]
    have = defaultdict(float)
    for r, lab in keep:
        have[lab["name"]] += tt.poly_len(r)

    def room(lab, r):
        b = budget(lab) if budget else None
        return b is None or have[lab["name"]] + tt.poly_len(r) <= b

    def ends_of(r):
        return [(r[0], _end_dir(r, True)), (r[-1], _end_dir(r, False))]
    ends = [(e, d, lab) for r, lab in keep for e, d in ends_of(r)]

    def at_node(pt):
        return any(math.dist(pt, n) <= 2.5 * tol for n in nodes)
    changed = True
    while changed and rest and len(keep) < max_runs:
        changed = False
        left = []
        for r, _lab in rest:
            hit = None
            for e, de in ends_of(r):
                for a, da, lab in ends:
                    if math.dist(e, a) > tol:
                        continue
                    # carries straight on: the two outward directions oppose
                    if (-(de[0] * da[0] + de[1] * da[1]) >= cos_t or
                            at_node(a)) and room(lab, r):
                        hit = lab
                        break
                if hit:
                    break
            if hit:
                keep.append((r, hit))
                have[hit["name"]] += tt.poly_len(r)
                ends += [(e, d, hit) for e, d in ends_of(r)]
                changed = True
            else:
                left.append((r, None))
        rest = left
    return keep


def _leaders(page, labs):
    """For labels with a leader line (a thin line or two-part polyline
    that starts at the text and runs off to the pipe), move the label's
    point to the leader's tip and drop its text direction."""
    if not labs:
        return
    try:
        paths = page.get_drawings()
    except Exception:
        return
    chains = []
    for p in paths:
        w = p.get("width") or 0
        if w > 1.0:
            continue
        pts = []
        for it in p.get("items", ()):
            if it[0] != "l":
                pts = []
                break
            a, b = it[1], it[2]
            if pts and abs(pts[-1] - a) < 0.5:
                pts.append(b)
            elif not pts:
                pts = [a, b]
            else:
                pts = []
                break
        if 2 <= len(pts) <= 4:
            chains.append(pts)
    for lab in labs:
        sz = lab["size_pt"] or 6.0
        r = fitz.Rect(lab["rect"])
        near = fitz.Rect(r.x0 - 1.2 * sz, r.y0 - 1.2 * sz, r.x1 + 1.2 * sz,
                         r.y1 + 1.2 * sz)
        best = None
        for pts in chains:
            for a, b in ((pts[0], pts[-1]), (pts[-1], pts[0])):
                if not near.contains(a) or near.contains(b):
                    continue
                L = sum(abs(pts[i + 1] - pts[i]) for i in range(len(pts) - 1))
                if not 2.5 * sz <= L <= 120 * sz:
                    continue
                # the start sits at the text's edge, not across it
                d = min(abs(a.x - r.x0), abs(a.x - r.x1), abs(a.y - r.y0),
                        abs(a.y - r.y1))
                if best is None or d < best[0]:
                    best = (d, b, [(q.x, q.y) for q in pts])
        if best is not None:
            lab["center"] = (best[1].x, best[1].y)
            lab["dir"] = None
            lab["leader"] = best[2]


def bridge_dashes(segs, max_gap, max_turn=12.0, texts=(), text_gap=0.0,
                  probe=0.0):
    """Connectors across the gaps of a dashed line: for each segment end,
    the nearest other segment end within max_gap that continues in the
    same direction (both segments and the gap within max_turn degrees of
    each other). With `texts` (text boxes), a gap up to text_gap is
    bridged too where the line runs into lettering ("-- PRIVATE SS >> --"):
    both ends, looking `probe` ahead, land in the same text box.
    [(x0, y0, x1, y1)]"""
    if not segs or max_gap <= 0:
        return []
    import math as _m
    ends = []
    for i, (x0, y0, x1, y1) in enumerate(segs):
        L = _m.hypot(x1 - x0, y1 - y0)
        if L < 0.2:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        # (segment, point, outward direction)
        ends.append((i, x0, y0, -ux, -uy))
        ends.append((i, x1, y1, ux, uy))
    cos_t = _m.cos(_m.radians(max_turn))

    def search(cands, grid, cell, limit, ok=None):
        out = []
        for k in cands:
            i, px, py, dx, dy = ends[k]
            best, bd = None, limit
            gx, gy = int(px // cell), int(py // cell)
            for cx in (gx - 1, gx, gx + 1):
                for cy in (gy - 1, gy, gy + 1):
                    for k2 in grid.get((cx, cy), ()):
                        j, qx, qy, ex, ey = ends[k2]
                        if j == i:
                            continue
                        gxv, gyv = qx - px, qy - py
                        g = _m.hypot(gxv, gyv)
                        if g < 1e-6 or g > bd:
                            continue
                        if dx * -ex + dy * -ey < cos_t:
                            continue      # must face back at us, same way
                        if (gxv * dx + gyv * dy) / g < cos_t:
                            continue
                        if ok is not None and not ok(k, k2):
                            continue
                        best, bd = k2, g
            if best is not None:
                out.append((k, best))
        return out
    grid = defaultdict(list)
    for k, (_i, px, py, _dx, _dy) in enumerate(ends):
        grid[(int(px // max_gap), int(py // max_gap))].append(k)
    pairs = search(range(len(ends)), grid, max_gap, max_gap)
    if texts and text_gap > max_gap and probe > 0:
        # ends that run into a text box just ahead
        tc = 50.0
        tgrid = defaultdict(list)
        for bi, t in enumerate(texts):
            for cx in range(int(t.x0 // tc), int(t.x1 // tc) + 1):
                for cy in range(int(t.y0 // tc), int(t.y1 // tc) + 1):
                    tgrid[(cx, cy)].append(bi)
        box_of = {}
        for k, (_i, px, py, dx, dy) in enumerate(ends):
            qx, qy = px + dx * probe, py + dy * probe
            for bi in tgrid.get((int(qx // tc), int(qy // tc)), ()):
                if texts[bi].contains(fitz.Point(qx, qy)):
                    box_of[k] = bi
                    break
        if box_of:
            g2 = defaultdict(list)
            for k in box_of:
                _i, px, py, _dx, _dy = ends[k]
                g2[(int(px // text_gap), int(py // text_gap))].append(k)
            pairs += search(list(box_of), g2, text_gap, text_gap,
                            ok=lambda a, b: box_of.get(a) == box_of.get(b))
    out, done = [], set()
    for k, k2 in pairs:
        key = (min(k, k2), max(k, k2))
        if key in done:
            continue
        done.add(key)
        _i, px, py, _a, _b = ends[k]
        _j, qx, qy, _c, _d = ends[k2]
        out.append((px, py, qx, qy))
    return out


def _parallel(d, pt, pts, tol=0.9):
    """Does text running in direction d follow the run's segment nearest
    to pt?"""
    best, seg = 1e18, None
    for a, b in zip(pts, pts[1:]):
        dd = tt._seg_dist(pt[0], pt[1], a[0], a[1], b[0], b[1])
        if dd < best:
            best, seg = dd, (a, b)
    if seg is None:
        return False
    (ax, ay), (bx, by) = seg
    L = math.hypot(bx - ax, by - ay)
    if L == 0:
        return False
    return abs((bx - ax) / L * d[0] + (by - ay) / L * d[1]) >= tol


def _circles(groups, max_d=40.0):
    """Small round closed shapes (manhole and cleanout symbols):
    [(cx, cy, r)]."""
    out = []
    for segs in groups.values():
        for r in tt.runs(segs):
            if not _closed(r) or len(r) < 8:
                continue
            xs = [p[0] for p in r]
            ys = [p[1] for p in r]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if 2 < w <= max_d and abs(w - h) <= 0.15 * w:
                out.append(((max(xs) + min(xs)) / 2,
                            (max(ys) + min(ys)) / 2, w / 2))
    return out


def _to_centres(pts, circles, tol=3.0):
    """A pipe drawn to a manhole's rim measures to its centre (how pipe
    is taken off: structure centre to structure centre)."""
    pts = list(pts)
    for i in (0, -1):
        x, y = pts[i]
        for cx, cy, r in circles:
            d = math.hypot(x - cx, y - cy)
            if abs(d - r) <= tol and d > 0.5:
                if i == 0:
                    pts.insert(0, (cx, cy))
                else:
                    pts.append((cx, cy))
                break
    return pts


def _closed(pts, tol=2.0):
    """A closed shape (manhole circle, building outline), not a pipe."""
    return len(pts) > 3 and math.hypot(pts[0][0] - pts[-1][0],
                                       pts[0][1] - pts[-1][1]) < tol


_CL = re.compile(r"\bC\.?L\.?\s*[:=]?\s*(?:EL(?:EV)?\.?\s*)?"
                 r"(\d{1,4}\.\d{1,3})(?!\s*%)", re.I)


def centerlines(page):
    """[(centre, elevation)] for pipe centerline callouts ("CL: 15.00",
    "8\" TWAS, CL: 15.00") - how plant yard piping plans give pipe
    elevations."""
    out = []
    for text, r in lines(page):
        for m in _CL.finditer(text):
            out.append((_c(r), float(m.group(1))))
    return out


def _cl_depth(pts, cls, grade, size_in, reach):
    """Depth to invert from the centerline callouts along a run and the
    finished grade: grade - (CL - half the pipe). None if none in reach
    or the result isn't a plausible trench depth."""
    els = [el for c, el in cls if tt.dist_to_poly(c, pts) <= reach]
    if not els:
        return None
    cl = sum(els) / len(els)
    d = grade - (cl - (size_in or 0) / 24.0)
    return round(d, 2) if 0 < d < 30 else None


def finished_grade(structs):
    """The site's finished grade for depth estimates: the median rim of
    the structures on the plans (a plant site is close to flat). None
    when no rim is printed."""
    rims = sorted(s["rim"] for s in structs if s.get("rim") is not None)
    if not rims:
        return None
    n = len(rims)
    return rims[n // 2] if n % 2 else (rims[n // 2 - 1] + rims[n // 2]) / 2


def _run_depth(pts, structs, reach):
    """Average depth of the structures at the run's two ends."""
    ds = []
    for end in (pts[0], pts[-1]):
        best, bd = None, reach
        for s in structs:
            if s.get("depth") is None:
                continue
            for c in s["pts"]:
                d = math.hypot(c[0] - end[0], c[1] - end[1])
                if d < bd:
                    best, bd = s, d
        if best is not None:
            ds.append(best["depth"])
    return round(sum(ds) / len(ds), 2) if ds else None


# ------------------------------------------------------------- whole set
class Stopped(Exception):
    """The user pressed Stop during a takeoff."""


def takeoff(doc, pages=None, scales=None, progress=None):
    """The civil takeoff of a set: {"pipes": [... per page, merged by
    name], "structures": [unique across the set], "pages": [...]}.
    `scales` is {page: (ppu, unit)}; pages without one count structures
    but no pipe. `progress(k, n, text)` is called before each sheet of
    each pass (2 passes); returning False stops with Stopped."""
    pages = list(range(doc.page_count) if pages is None else pages)
    scales = scales or {}
    all_structs = {}
    pipes = {}
    used = []
    n_steps = 2 * len(pages) or 1

    def step(k, text):
        if progress is not None and progress(k, n_steps, text) is False:
            raise Stopped()
    per_page = {}
    for i, pno in enumerate(pages):
        step(i, f"Civil: structures on sheet {i + 1} of {len(pages)}")
        per_page[pno] = structures(doc[pno])
    grade = finished_grade([s for st in per_page.values() for s in st])
    for i, pno in enumerate(pages):
        step(len(pages) + i,
             f"Civil: pipe on sheet {i + 1} of {len(pages)}")
        page = doc[pno]
        st = per_page[pno]
        for s in st:
            key = s["id"] + (" (existing)" if s["existing"] else "")
            rec = all_structs.get(key)
            if rec is None:
                all_structs[key] = dict(s, pages=[pno], key=key)
            else:
                rec["pages"].append(pno)
                rec["rim"] = rec["rim"] or s["rim"]
                if s["inverts"] and not rec["inverts"]:
                    rec["inverts"] = s["inverts"]
                if rec["depth"] is None:
                    rec["depth"] = s["depth"]
        sc = scales.get(pno)
        if not sc:
            continue
        systems = pipe_systems(page, sc[0], sc[1], structs=st, grade=grade)
        if systems:
            used.append(pno)
        for g in systems:
            m = pipes.get(g["name"])
            if m is None:
                m = pipes[g["name"]] = dict(g, runs=[], length=0.0,
                                            label_length=0.0, bands={},
                                            pages=[], label_by_page={})
            m["pages"].append(pno)
            m["label_by_page"][pno] = m["label_by_page"].get(pno, 0.0) + \
                g["label_length"]
            for r in g["runs"]:
                m["runs"].append(dict(r, page=pno))
            m["length"] += g["length"]
            m["label_length"] += g["label_length"]
            for b, v in g["bands"].items():
                m["bands"][b] = m["bands"].get(b, 0.0) + v
    # "TIE 8\" ROOF DRAIN" and "8\" PVC ROOF DRAIN" are one pipe: a
    # label that leaves out the material joins the one same-size group of
    # that system that names it
    for name in list(pipes):
        g = pipes[name]
        if g.get("material") or not g.get("system"):
            continue
        twins = [h for h in pipes.values() if h is not g and
                 h.get("material") and h["size"] == g["size"] and
                 h.get("system") == g["system"] and
                 h["existing"] == g["existing"]]
        if len(twins) != 1:
            continue
        h = twins[0]
        h["runs"] += g["runs"]
        h["length"] += g["length"]
        h["label_length"] += g["label_length"]
        _merge_label_pages(h, g)
        h["pages"] = sorted(set(h["pages"]) | set(g["pages"]))
        for b, v in g["bands"].items():
            h["bands"][b] = h["bands"].get(b, 0.0) + v
        del pipes[name]
    _plant_names(pipes)
    structs = sorted(all_structs.values(), key=lambda s: (
        s["existing"], s["kind"], _id_sort(s["id"])))
    checks = []
    for g in pipes.values():
        c = label_check(g)
        if c:
            checks.append(c)
    est = sum(r["length"] for g in pipes.values() if not g["existing"]
              for r in g["runs"] if r.get("depth_est"))
    if est:
        checks.append(f"depth of {est:,.0f} LF of pipe estimated from its "
                      f"centerline elevations (CL) and a finished grade of "
                      f"{grade:.2f} (the middle manhole rim) - check "
                      "against the grading plan")
    services = {}
    for pno in pages:
        try:
            items = service_items(doc[pno])
        except Exception:                                 # noqa: BLE001
            items = []
        for it in items:
            rec = services.setdefault(it["name"], dict(
                it, qty=0, pages=[], texts=[]))
            rec["qty"] += it["qty"]
            rec["pages"].append(pno)
            rec["texts"].append(it["text"])
    loose = [s for s in structs if s.get("unnumbered")]
    if loose:
        checks.append(f"{len(loose)} structure(s) have no number on the "
                      "plan (counted from callouts like \"5' MANHOLE\" or "
                      "\"12\" PLUG VALVE\") - one shown on two sheets "
                      "counts twice; check them")
    return {"pipes": sorted(pipes.values(), key=lambda g: (
        g["existing"], -g["size"], -g["length"])),
        "structures": structs, "pages": used, "checks": checks,
        "grade": grade, "services": sorted(services.values(),
                                           key=lambda v: v["name"])}


def _merge_label_pages(h, g):
    lbp = h.setdefault("label_by_page", {})
    for pg, v in (g.get("label_by_page") or {}).items():
        lbp[pg] = lbp.get(pg, 0.0) + v


def label_check(g, tol=0.15):
    """The measured-vs-labelled length check for one pipe group, or ''."""
    if g["existing"] or not g["label_length"]:
        return ""
    off = (g["length"] - g["label_length"]) / g["label_length"]
    if abs(off) > tol:
        return (f"{g['name']}: measured {g['length']:.0f} LF but "
                f"the labels add up to {g['label_length']:.0f} LF "
                f"({off:+.0%}) - check it on the plan")
    return ""


def _plant_names(pipes):
    """On a treatment-plant set (labels carry service codes like PDG, ML,
    NPW) a bare '24" DIP' or '18" PVC' is process piping, not the water
    main or sanitary sewer its material would suggest on a site plan:
    name it by size and material only."""
    if not any(g.get("system") in ("process", "plant drain")
               for g in pipes.values()):
        return
    for name in list(pipes):
        g = pipes[name]
        if not g.get("guessed"):
            continue
        new = " ".join(x for x in (f"{g['size']:g}\"", g.get("material") or "")
                       if x) + (" (existing)" if g["existing"] else "")
        g["system"], g["guessed"] = "process", False
        del pipes[name]
        h = pipes.get(new)
        if h is None:
            g["name"] = new
            pipes[new] = g
            continue
        h["runs"] += g["runs"]
        h["length"] += g["length"]
        h["label_length"] += g["label_length"]
        _merge_label_pages(h, g)
        h["pages"] = sorted(set(h["pages"]) | set(g["pages"]))
        for b, v in g["bands"].items():
            h["bands"][b] = h["bands"].get(b, 0.0) + v


def _id_sort(sid):
    m = re.search(r"(\d+)([A-Z]?)$", sid)
    return (sid.split("-")[0], int(m.group(1)) if m else 0,
            m.group(2) if m else "")


def structure_summary(structs):
    """{(kind, band): {count, avg_depth, ids}} for new structures."""
    out = {}
    for s in structs:
        if s["existing"]:
            continue
        b = band_of(s["depth"])
        rec = out.setdefault((s["kind"], b), {"count": 0, "depths": [],
                                               "ids": []})
        rec["count"] += 1
        rec["ids"].append(s["id"])
        if s["depth"] is not None:
            rec["depths"].append(s["depth"])
    for rec in out.values():
        d = rec.pop("depths")
        rec["avg_depth"] = round(sum(d) / len(d), 2) if d else None
    return out


# ------------------------------------------------------------- assemblies
DEFAULT_DEPTH = 8.0
_PIPE_ASSEMBLY = {
    "sanitary": "Gravity sewer, PVC SDR-35, trenched",
    "storm": "Storm sewer, RCP, trenched",
    "force main": "Force main, PVC C900, trenched",
    "water": "Water main, PVC C900, trenched",
    "plant drain": "Gravity sewer, PVC SDR-35, trenched",
    "process": "Force main, PVC C900, trenched",
}
_STRUCT_ASSEMBLY = {
    "manhole": 'Sanitary manhole, 48" precast, by depth',
    "manhole 60": 'Sanitary manhole, 60" precast, by depth',
    "storm manhole": 'Storm manhole, 48" precast, by depth',
    "catch basin": "Catch basin, precast",
    "inlet": "Catch basin, precast",
    "cleanout": "Sewer cleanout",
}


def group_name(pipe, band):
    return f"{pipe['name']}, {band_name(band)}"


def _mid_depth(pipe, band):
    ds = [r["depth"] for r in pipe["runs"] if band_of(r["depth"]) == band
          and r["depth"] is not None]
    if ds:
        return round(sum(r["length"] * r["depth"] for r in pipe["runs"]
                         if band_of(r["depth"]) == band and
                         r["depth"] is not None) /
                     max(1e-9, sum(r["length"] for r in pipe["runs"]
                                   if band_of(r["depth"]) == band and
                                   r["depth"] is not None)), 2)
    return DEFAULT_DEPTH


def assemblies_for(result, library=None):
    """Job assemblies for the takeoff: {group name: assembly}. Each pipe
    group (size, material, depth band) gets a copy of its catalog trench
    assembly with D and H set; structures likewise by kind and depth."""
    import copy
    from . import assemblies
    lib = library if library is not None else assemblies.library()
    out = {}
    for p in result["pipes"]:
        if p["existing"]:
            continue
        base = lib.get(_PIPE_ASSEMBLY.get(p["system"], "")) or \
            lib.get(_PIPE_ASSEMBLY["sanitary"])
        if not base:
            continue
        for band in p["bands"]:
            a = copy.deepcopy(base)
            a["name"] = group_name(p, band)
            props = dict(a.get("props") or {})
            props["D"] = p["size"]
            props["H"] = _mid_depth(p, band)
            a["props"] = props
            out[a["name"]] = a
    for (kind, band), rec in structure_summary(result["structures"]).items():
        base = lib.get(_STRUCT_ASSEMBLY.get(kind, ""))
        if not base:
            continue
        a = copy.deepcopy(base)
        a["name"] = f"{base['name']}, {band_name(band)}"
        props = dict(a.get("props") or {})
        if "H" in props or band is not None:
            props["H"] = rec["avg_depth"] or DEFAULT_DEPTH
        a["props"] = props
        out[a["name"]] = a
    return out


# ------------------------------------------------------------- marks
def marks(result, unit="ft", pipes=None, structs=None):
    """(page, kind, payload) marks: a length measurement per pipe run in
    its size/depth group, and a numbered count on each structure."""
    out = []
    chosen = result["pipes"] if pipes is None else pipes
    for i, p in enumerate(chosen):
        col = tt.PALETTE[i % len(tt.PALETTE)]
        for r in p["runs"]:
            pts = [list(q) for q in r["pts"]]
            out.append((r["page"], "add_polyline" if len(pts) > 2 else
                        "add_line", {
                            "pts": pts, "color": list(col), "width": 3,
                            "opacity": 0.6,
                            "measure": {"type": "length",
                                        "value": round(r["length"], 4),
                                        "unit": unit,
                                        "group": group_name(
                                            p, band_of(r["depth"])),
                                        "method": "civil takeoff"}}))
    sts = [s for s in result["structures"] if not s["existing"]] \
        if structs is None else structs
    names = {}
    for (kind, band), rec in structure_summary(sts).items():
        base = _STRUCT_ASSEMBLY.get(kind)
        for sid in rec["ids"]:
            names[sid] = (f"{_struct_base_name(kind)}, {band_name(band)}"
                          if base else kind.title())
    counters = defaultdict(int)
    for s in sts:
        pno = s["pages"][0] if s.get("pages") else s.get("page", 0)
        counters[pno] += 1
        x, y = s["center"]
        out.append((pno, "add_count", {
            "pt": [x, max(12, y - 14)], "n": counters[pno],
            "color": [0.85, 0.2, 0.1],
            "measure": {"type": "count", "value": 1, "unit": "ea",
                        "group": names.get(s["id"], s["kind"].title()),
                        "method": "civil takeoff",
                        "label": s["id"]}}))
    return out


def _struct_base_name(kind):
    return _STRUCT_ASSEMBLY.get(kind, kind.title())


def apply(doc, result, unit="ft"):
    """Put the takeoff into the PDF (CLI/tests): job assemblies and
    measurements. Returns the number of marks."""
    from . import annotate, assemblies
    for a in assemblies_for(result).values():
        assemblies.set_job_assembly(doc, a)
    ms = marks(result, unit)
    for pno, kind, payload in ms:
        annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    return len(ms)
