"""AI Takeoff: a whole plan set taken off in one go.

1. Read the set (plan_set): every sheet's number, title and scale (Auto
   Scale - only standard scales are trusted), and what kind of sheet it is
   - discipline from the sheet number prefix (A-, C-, P-, M-, E-...) or,
   failing that, the words on it; details, sections, schedules, covers and
   notes are left out.
2. Take it off (run): the right automatic takeoff on each sheet -
     architectural plans  -> rooms (floor areas from the room tags)
     civil / utility      -> pipe LF by size and depth, manholes, cleanouts,
                             valves, with trench assemblies
     plumbing / mechanical / fire protection -> labelled pipe runs
     electrical / plumbing / mechanical      -> fixtures and devices
                             counted from the sheet legends
     mechanical           -> ductwork by size tag (Trade Takeoff > Ducts,
                             kept only where tag and width agree)
     structural           -> steel members: columns counted, beams by
                             their member line, LB when the length is
                             known; each member once across the S plans
     any sheet with schedules (detail / schedule sheets too) -> the
                             schedules read (schedules.py) and their keys
                             counted on the plans: doors, hardware sets,
                             fixtures, air devices, lights, equipment,
                             plants; footing marks -> CY
     architectural plans, one per floor level -> walls: LF per wall type
                             (tags keyed to the WALL TYPES legend, CMU
                             04 22 00, partitions 09 21 16), the exterior
                             wall as its outer face loop, SF where the
                             legend or a note gives the height
     the rooms kept (each once) x the finish schedule -> finishes: floor
                             SF, base LF, ceiling SF, wall finish SF per
                             code (room_finishes)
   Raster-only sheets are reported "raster sheet, measure by hand"; wall
   types, details, sections, furniture plans and sheets drawn at a detail
   scale (larger than 1" = 1'-0") don't go to the rooms engine.
   Everything becomes ordinary measurements (one undo step), each marked
   with how it was found, ready for Check Takeoff.
3. Summary (summary_text): what was found, sheet by sheet and in total,
   and what needs a person - sheets without a usable scale, rooms not
   found, odd scales. With the local AI model (Ollama) running, it also
   writes a short scope narrative.
"""
import logging
import math
import re
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

DISCIPLINE_PREFIX = [
    ("FP", "fire protection"), ("FA", "fire alarm"), ("ID", "interiors"),
    ("CU", "civil"), ("CS", "civil"), ("CG", "civil"), ("CD", "civil"),
    ("CV", "civil"), ("SW", "civil"), ("SS", "civil"), ("WS", "civil"),
    ("LP", "landscape"), ("MP", "mechanical"), ("MH", "mechanical"),
    ("PL", "plumbing"), ("EP", "electrical"), ("EL", "electrical"),
    ("AD", "architectural"), ("AE", "architectural"),
    ("A", "architectural"), ("C", "civil"), ("L", "landscape"),
    ("S", "structural"), ("M", "mechanical"), ("P", "plumbing"),
    ("E", "electrical"), ("G", "general"), ("T", "telecom"),
    ("I", "interiors"), ("Q", "equipment"), ("F", "fire protection"),
    ("D", "process"), ("X", "other"), ("H", "hazmat"), ("V", "survey"),
    ("B", "geotech"), ("R", "resource"), ("W", "civil"), ("O", "operations"),
]
KEYWORDS = [
    ("civil", r"\b(SEWER|SANITARY|STORM|WATER\s*MAIN|FORCE\s*MAIN|"
              r"PLAN\s*(AND|&)\s*PROFILE|UTILIT(Y|IES)|GRADING|PAVING|"
              r"SITE\s*PLAN|MANHOLE|LIFT\s*STATION|DRAINAGE)\b"),
    ("plumbing", r"\b(PLUMBING|DOMESTIC\s*WATER|WASTE\s*(AND|&)\s*VENT|"
                 r"SANITARY\s*RISER)\b"),
    ("mechanical", r"\b(MECHANICAL|HVAC|DUCT(WORK)?|PIPING\s*PLAN|"
                   r"PROCESS\s*MECHANICAL)\b"),
    ("electrical", r"\b(ELECTRICAL|POWER\s*PLAN|LIGHTING|PANEL\s*"
                   r"SCHEDULE|ONE[-\s]LINE)\b"),
    ("fire protection", r"\b(FIRE\s*PROTECTION|SPRINKLER)\b"),
    ("structural", r"\b(STRUCTURAL|FOUNDATION|FRAMING)\b"),
    ("architectural", r"\b(FLOOR\s*PLAN|ARCHITECTURAL|REFLECTED\s*"
                      r"CEILING|ROOM\s*FINISH)\b"),
]
NOT_A_PLAN = re.compile(
    r"\b(DETAILS?|SECTIONS?|ELEVATIONS?|SCHEDULES?|COVER|TITLE\s*SHEET|"
    r"WALL\s+TYPES?|PARTITION\s+TYPES?|"
    r"INDEX|GENERAL\s*NOTES|NOTES|LEGENDS?|ABBREVIATIONS|DIAGRAMS?|"
    r"RISER|SPECIFICATIONS?|ISOMETRIC)\b", re.I)
PLAN_WORD = re.compile(r"\bPLAN\b", re.I)

# what each discipline is taken off with
ENGINES = {
    "architectural": ["rooms"],
    "interiors": ["rooms"],
    "civil": ["civil"],
    "plumbing": ["pipes", "devices"],
    "mechanical": ["pipes", "ducts", "devices"],
    "process": ["pipes", "civil"],
    "fire protection": ["pipes", "devices"],
    "electrical": ["devices"],
    "fire alarm": ["devices"],
    "telecom": ["devices"],
    "structural": ["steel"],
}
DEVICE_TIME_LIMIT = 180        # seconds for legend symbol counting
# seconds one sheet's room finding may take before it is stopped and the
# sheet listed as not finished (the whole run is then bounded by about
# sheets x SHEET_TIME_LIMIT + DEVICE_TIME_LIMIT + the civil pass)
SHEET_TIME_LIMIT = 90

ENGINE_NAMES = {"rooms": "rooms (floor areas)",
                "civil": "pipe by size & depth, structures",
                "pipes": "pipe runs", "devices": "fixtures & devices",
                "ducts": "ductwork by size",
                "steel": "steel members (count / length / weight)",
                "schedules": "schedules read, keys counted on the plans",
                "walls": "walls by type, exterior wall (outer face)",
                "finishes": "floor / base / ceiling / wall finishes"}
# engines run once for the whole set, not per sheet
SET_ENGINES = ("civil", "devices", "schedules")
# a scale larger than 1" = 1'-0" (72 pt per foot) is a detail scale
DETAIL_PT_PER_FT = 72.0
# not a plan for the rooms engine (3c C8): wall types, details,
# sections and furniture plans
NO_ROOMS = re.compile(r"\b(WALL\s+TYPES?|PARTITION\s+TYPES?|DETAILS?|"
                      r"SECTIONS?|FURNITURE)\b", re.I)
_HAS_SCHEDULE = re.compile(r"SCHEDULE|HARDWARE\s+SETS?|PLANT(?:ING)?\s+"
                           r"LIST", re.I)
# ductwork kept from Trade Takeoff > Ducts (N7)
DUCT_MIN_LF = 1.0
DUCT_MAX_IN = 60.0


def _full_glyph_boxes(fn):
    """Run `fn` with PyMuPDF's small-glyph-heights switch off.

    The switch is process-wide; PyMuPDF's own table finder turns it on
    and back off, and if it is left on every word box is about a third
    shorter, which moves the schedule, title and room-tag readers (a
    door schedule read 0 rows instead of 8 on a test set). AI Takeoff
    reads every sheet with full word boxes, the way it was measured,
    and puts the switch back as it found it."""
    import functools

    @functools.wraps(fn)
    def wrapped(*a, **k):
        try:
            import fitz
            prev = fitz.TOOLS.set_small_glyph_heights()
        except Exception:
            return fn(*a, **k)
        if not prev:
            return fn(*a, **k)
        fitz.TOOLS.set_small_glyph_heights(False)
        try:
            return fn(*a, **k)
        finally:
            fitz.TOOLS.set_small_glyph_heights(prev)
    return wrapped


def discipline(number, title, text=""):
    n = (number or "").upper().strip()
    m = re.match(r"^([A-Z]{1,2})[-.]?\d", n)
    if m:
        pre = m.group(1)
        for p, d in DISCIPLINE_PREFIX:
            if pre == p:
                return d
        for p, d in DISCIPLINE_PREFIX:
            if len(p) == 1 and pre.startswith(p):
                return d
    hay = f"{title or ''} {text or ''}".upper()
    for d, rx in KEYWORDS:
        if re.search(rx, hay):
            return d
    return "unknown"


def sheet_kind(title, text=""):
    """'plan' or 'detail' (details, sections, schedules, covers, notes)."""
    t = (title or "").upper()
    if t and NOT_A_PLAN.search(t) and not PLAN_WORD.search(t):
        return "detail"
    if not t and NOT_A_PLAN.search((text or "")[:200]) and \
            not PLAN_WORD.search((text or "")[:400]):
        return "detail"
    return "plan"


def raster_only(page, max_items=40):
    """True for a sheet that is a picture (a scan, a raster export): its
    images cover a good part of the page and there is (next to) no
    vector linework over them. Nothing can be measured from its lines."""
    try:
        imgs = page.get_image_info()
    except Exception:                                    # noqa: BLE001
        return False
    if not imgs:
        return False
    pr = page.rect
    area = pr.width * pr.height or 1.0
    boxes = []
    cover = 0.0
    for im in imgs:
        b = im.get("bbox")
        if not b:
            continue
        x0, y0, x1, y1 = (max(b[0], 0), max(b[1], 0), min(b[2], pr.width),
                          min(b[3], pr.height))
        if x1 > x0 and y1 > y0:
            cover += (x1 - x0) * (y1 - y0)
            boxes.append((x0, y0, x1, y1))
    if cover < 0.3 * area:
        return False
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return False
    n = 0
    for p in paths:
        r = p.get("rect")
        if r is None:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            n += len(p.get("items", ()))
            if n > max_items:
                return False
    return True


LOW_DPI = 150                  # a scan under this is too coarse to trust


def scan_dpi(page):
    """The resolution of the biggest picture on the sheet, in dots per
    inch as printed (pixels across / inches across), or None when the
    sheet has no picture covering a good part of it. A scan saved as
    strips or tiles is read from the pieces together."""
    try:
        imgs = page.get_image_info()
    except Exception:                                    # noqa: BLE001
        return None
    area = page.rect.width * page.rect.height or 1.0
    best = None
    parts = []                    # (area, dpi) of every picture on it
    for im in imgs:
        b = fitz_rect(im.get("bbox"))
        if b is None or b.width <= 0 or b.height <= 0:
            continue
        w = im.get("width") or 0
        h = im.get("height") or 0
        if not w or not h:
            continue
        dpi = min(w / (b.width / 72.0), h / (b.height / 72.0))
        parts.append((b.width * b.height, dpi))
        if b.width * b.height < 0.3 * area:
            continue
        if best is None or b.width * b.height > best[0]:
            best = (b.width * b.height, dpi)
    if best:
        return best[1]
    # a scan saved as strips or tiles: together they cover the sheet; the
    # DPI is the one most of the covered area has (area-weighted median)
    if parts and sum(a for a, _ in parts) >= 0.3 * area:
        parts.sort(key=lambda x: x[1])
        half, run = sum(a for a, _ in parts) / 2.0, 0.0
        for a, dpi in parts:
            run += a
            if run >= half:
                return dpi
    return None


def fitz_rect(b):
    if not b:
        return None
    import fitz
    try:
        return fitz.Rect(b)
    except Exception:                                    # noqa: BLE001
        return None


def pt_per_ft(scale):
    """Points per foot of a (label, ppu, unit) scale, or None."""
    if not scale:
        return None
    from . import tradetakeoff as tt
    return tt._per_ft(scale[1], scale[2])


def rooms_reason(title, scale):
    """Why a plan isn't one for the rooms engine (wall types, details,
    sections, a furniture plan, a detail scale), or ''."""
    t = title or ""
    if NO_ROOMS.search(t) and not re.search(r"\bFLOOR\s+PLANS?\b", t, re.I):
        return f"'{t}' is not a plan for the rooms engine"
    ppf = pt_per_ft(scale)
    if ppf and ppf > DETAIL_PT_PER_FT * 1.01:
        return (f"drawn at {scale[0]} - a detail scale (larger than "
                "1\" = 1'-0\"), not a plan for the rooms engine")
    return ""


_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$")


def sheet_date(words, width, height):
    """The latest date printed in the title block or revision block
    (right-hand strip or bottom band of the sheet) as (y, m, d), or None.
    A revised sheet carries its new revision date and plot date there."""
    best = None
    for w in words:
        if not (w[0] > 0.7 * width or w[1] > 0.85 * height):
            continue
        m = _DATE.match(w[4].strip(",;()"))
        if not m:
            continue
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if not (1 <= mo <= 12 and 1 <= d <= 31 and 1990 <= y <= 2100):
            continue
        if best is None or (y, mo, d) > best:
            best = (y, mo, d)
    return best


def _norm_number(n):
    return re.sub(r"[\s.\-]", "", (n or "").upper())


def _same_title(a, b):
    wa = set(re.findall(r"[A-Z0-9]+", (a or "").upper()))
    wb = set(re.findall(r"[A-Z0-9]+", (b or "").upper()))
    if not wa or not wb:
        return True
    return len(wa & wb) / len(wa | wb) >= 0.5


def _fmt_date(d):
    return f"{d[1]:02d}/{d[2]:02d}/{d[0]}" if d else "no date"


def mark_duplicates(rows):
    """Sheets with the same number (a sheet bound twice, or an earlier
    revision left in the set): only the latest is taken off - the one
    with the latest title-block date, else the later page - and each
    other copy gets kind 'superseded', no engines and a note saying which
    page replaces it. Copies whose titles differ are both kept but
    flagged (`dup_warning`), since the number may have been misread.
    Changes `rows` in place and returns [(number, kept page, [other
    pages], how)]."""
    by = {}
    for r in rows:
        n = _norm_number(r.get("number"))
        if n:
            by.setdefault(n, []).append(r)
    found = []
    for n, rs in by.items():
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: (r.get("date") or (0, 0, 0),
                                       r["page"]))
        keep = rs[-1]
        others = rs[:-1]
        same = [r for r in others if _same_title(r["title"], keep["title"])]
        differ = [r for r in others if r not in same]
        dated = keep.get("date") and all(
            r.get("date") and r["date"] < keep["date"] for r in same)
        how = (f"latest date {_fmt_date(keep.get('date'))}" if dated else
               "can't tell from the dates - took the later page")
        for r in same:
            r["kind"] = "superseded"
            r["engines"], r["wanted"] = [], []
            r["superseded_by"] = keep["page"]
            r["note"] = (f"superseded - the same sheet {keep['number']} is "
                         f"on page {keep['page'] + 1} ({how}); not taken "
                         "off")
        for r in differ:
            r["dup_warning"] = (f"sheet number {r['number']} is also on page "
                                f"{keep['page'] + 1} with another title - "
                                "both kept; check the number")
        if same:
            keep["copies"] = [r["page"] for r in same]
            found.append((keep["number"], keep["page"],
                          [r["page"] for r in same], how))
        if differ:
            keep["dup_warning"] = (
                f"sheet number {keep['number']} is also on page(s) " +
                ", ".join(str(r["page"] + 1) for r in differ) +
                " with another title - both kept; check the number")
    return found


@_full_glyph_boxes
def plan_set(doc, progress=None):
    """One row per sheet: {page, number, title, discipline, kind, scale
    (label, ppu, unit) or None, scale_from ('sheet', 'read', 'odd' or
    ''), engines, note, date}. A sheet number found twice is taken off
    once, from its latest issue (mark_duplicates); the other copies have
    kind 'superseded'."""
    from . import annotate, sheets
    have = annotate.read_scales(doc)
    rows = []
    for i in range(doc.page_count):
        if progress and progress(i, doc.page_count) is False:
            break
        rows += sheets.scan(doc, [i], numbers=False, keep_words=True)
    if len(rows) > 2:
        sheets.fix_numbers(rows, doc)
    out = []
    for r in rows:
        words = r.pop("words", None) or []
        pno = r["page"]
        try:
            date = sheet_date(words, doc[pno].rect.width,
                              doc[pno].rect.height)
        except Exception:                                # noqa: BLE001
            date = None
        full = doc[pno].get_text()
        text = full[:3000]
        disc = discipline(r["number"], r["title"], text)
        kind = sheet_kind(r["title"], text)
        raster = raster_only(doc[pno])
        sched = bool(_HAS_SCHEDULE.search(full)) and not raster
        sc, frm = None, ""
        if pno in have and have[pno].get("ppu"):
            h = have[pno]
            sc, frm = (h.get("name") or "set", h["ppu"], h["unit"]), "sheet"
        elif r["scale"]:
            sc, frm = r["scale"], "read"
        elif r.get("odd"):
            frm = "odd"
        engines = list(ENGINES.get(disc, [])) if kind == "plan" else []
        note = ""
        why_rooms = rooms_reason(r["title"], sc) if "rooms" in engines \
            else ""
        if why_rooms:
            engines.remove("rooms")
        dpi = scan_dpi(doc[pno]) if raster else None
        if raster:
            # 3c C9: a picture - nothing to measure from its lines
            kind, engines = "raster", []
            note = "raster sheet, measure by hand (no vector linework)"
            if dpi and dpi < LOW_DPI:
                note += (f"; scanned at about {dpi:.0f} DPI - under "
                         f"{LOW_DPI} DPI, check every number closely")
            elif dpi:
                note += f"; scanned at about {dpi:.0f} DPI"
        elif kind != "plan":
            note = ("schedule sheet - schedules read" if sched else
                    "detail / schedule sheet - not taken off")
        elif why_rooms and not engines:
            note = why_rooms
        elif not engines and not sched:
            note = "no automatic takeoff for this kind of sheet"
        elif engines and sc is None:
            note = ("scale on the sheet isn't a standard one - set it, "
                    "then run again" if frm == "odd" else
                    "no scale found - set it, then run again")
        elif why_rooms:
            note = why_rooms
        extra = ["schedules"] if sched else []
        ev = _scale_evidence(doc[pno], sc, frm, raster, dpi,
                             engines if sc else [])
        out.append({"page": pno, "number": r["number"], "title": r["title"],
                    "discipline": disc, "kind": kind, "scale": sc,
                    "scale_from": frm,
                    "engines": (engines if sc else []) + extra,
                    "wanted": engines + extra, "note": note, "date": date,
                    "raster": raster,
                    "source": "scan" if raster else "vector",
                    "dpi": round(dpi) if dpi else None, **ev})
    mark_duplicates(out)
    return out


# engines whose quantities are lengths or areas (they depend on the scale);
# devices and schedules count things
MEASURE_ENGINES = ("rooms", "civil", "pipes", "ducts", "steel")


def _scale_evidence(page, sc, frm, raster, dpi, engines):
    """The sheet's scale confidence and evidence (scale_evidence.py) as row
    fields: scale_conf 0-100, scale_why [reasons], scale_rect (where the
    printed words are), scale_text, scale_review (the sheet is measured,
    or is a scan, and the score is under 60)."""
    from . import scale_evidence as se
    measured = any(e in MEASURE_ENGINES for e in engines)
    try:
        if raster:
            ev = se.evidence(page, None, source="scan", dpi=dpi)
        elif sc is None:
            return {"scale_conf": 0, "scale_why": [], "scale_rect": None,
                    "scale_text": "", "scale_review": False}
        else:
            # printed dimensions are only measured on sheets that are
            # measured (the check costs time on dense sheets)
            ev = se.evidence(page, tuple(sc), user=frm == "sheet",
                             dims=None if measured else {})
    except Exception:                                    # noqa: BLE001
        log.info("scale evidence", exc_info=True)
        return {"scale_conf": None, "scale_why": [], "scale_rect": None,
                "scale_text": "", "scale_review": False}
    if sc is not None and not raster and not measured:
        ev["reasons"] = [r for r in ev["reasons"] if not r.startswith(
            "no printed dimensions")] + [
            "not checked against printed dimensions (nothing is measured "
            "on this sheet)"]
    return {"scale_conf": ev["score"], "scale_why": ev["reasons"],
            "scale_rect": [_c2(c) for c in ev["rect"]] if ev["rect"]
            else None, "scale_text": ev["text"],
            "scale_review": bool(ev["review"] and (measured or raster))}


SCALE_HOLD = "Rooms (scale to check)"


def scale_review(rows, res):
    """A doubtful scale goes to review (AI Takeoff v3): for every sheet
    taken off whose scale scored under 60, one review item (kind "scale",
    with the score, the reasons and where the printed words are), and the
    sheet's lengths and areas wait: its AI outlines and lines carry the
    review mark (not in the drawing's totals until accepted), its
    measured sheet totals and length / area quantities are pending. Counts
    don't depend on the scale and stay. A scanned sheet gets the item too
    (its scale has to be set by hand)."""
    from . import annotate
    held = []
    for r in rows:
        if not r.get("scale_review") or not r.get("engines"):
            continue                 # sure enough, or not taken off
        pno = r["page"]
        sc = r.get("scale")
        measured = [e for e in r.get("engines") or () if e in
                    MEASURE_ENGINES]
        if not measured and r.get("source") != "scan":
            continue
        name = (f"Scale {sc[0]} on {r.get('number') or pno + 1}" if sc else
                f"Scale not read on {r.get('number') or pno + 1}")
        res.setdefault("review", []).append({
            "sheet": r.get("number") or "", "page": pno, "name": name,
            "qty": None, "unit": "", "engine": "scale", "kind": "scale",
            "confidence": (r.get("scale_conf") or 0) / 100.0,
            "why": "; ".join(r.get("scale_why") or ()) or
            "scale not sure", "rect": r.get("scale_rect"),
            "scale": sc[0] if sc else None,
            "source": r.get("source")})
        if not measured:
            continue
        held.append(pno)
        for p, kind, pl in res.get("marks") or ():
            m = pl.get("measure") if isinstance(pl, dict) else None
            if p != pno or not isinstance(m, dict) or \
                    m.get("type") not in ("area", "length"):
                continue
            meth = str(m.get("method") or "")
            if meth.startswith("AI takeoff") and not meth.endswith(
                    annotate.REVIEW_SUFFIX):
                m["method"] = meth + annotate.REVIEW_SUFFIX
                m["scale_hold"] = True
        sh = (res.get("sheets") or {}).get(pno)
        if isinstance(sh, dict):
            sh["scale_review"] = True
        for q in res.get("quantities") or ():
            if q.get("page") == pno and q.get("status") == "taken off" and \
                    str(q.get("unit") or "").lower() not in ("ea", "each"):
                q["status"] = "pending review"
                q["scale_hold"] = True
    res["scale_held"] = held
    return held


def release_scale(res, pno):
    """The person confirmed a doubtful scale: the sheet's measured totals
    and quantities held for it count again. (Its outlines on the drawing
    are each accepted in the review queue.)"""
    sh = (res.get("sheets") or {}).get(pno)
    if isinstance(sh, dict):
        sh["scale_review"] = False
    for q in res.get("quantities") or ():
        if q.get("page") == pno and q.pop("scale_hold", False):
            q["status"] = "taken off"
    if pno in (res.get("scale_held") or []):
        res["scale_held"].remove(pno)


# ------------------------------------------------------------- run
def _room_marks(doc, pno, found):
    from . import annotate
    page = doc[pno]
    out = []
    for room in found:
        pts = [annotate.to_page(page, q) for q in room["pts"]]
        label = f"{room['value']:,.0f} {room['unit']}"
        if room.get("per_tag"):
            label += f" (per tag; traced {room['traced_value']:,.0f})"
        if room.get("name"):
            label = f"{room['name']}: {label}"
        out.append((pno, "add_polygon", {
            "pts": [[q.x, q.y] for q in pts], "color": [0.1, 0.45, 0.85],
            "fill": [0.1, 0.45, 0.85], "opacity": 0.25, "label": label,
            "measure": {"type": "area", "value": round(room["value"], 4),
                        "unit": room["unit"],
                        "group": room.get("name") or "Room",
                        # not sure: kept out of the totals until accepted
                        "method": "AI takeoff: rooms" + (
                            annotate.REVIEW_SUFFIX if room.get("review")
                            else "")}}))
    return out


# ------------------------------------------------------------- rooms
_ROOM_NO = re.compile(r"^\d{1,4}(?:\.\d{1,2})?[A-Z]?$")
_DEMO_PLAN = re.compile(r"\bDEMO(?:LITION)?\b", re.I)
_OTHER_PLAN = re.compile(r"\b(DIMENSION|FINISH|ENLARGED|FURNITURE|EQUIPMENT|"
                         r"REFLECTED|CEILING|RCP|DEMO(?:LITION)?|LIFE\s+SAFETY|"
                         r"CODE|SIGNAGE|POWER|LIGHTING|ROOF|FRAMING|"
                         r"FOUNDATION|PARTITION|KEY\s+PLAN)\b", re.I)


def room_key(name):
    """(room number or '', set of name words) from a room's name:
    'PUBLIC DOG INTAKE 108' -> ('108', {'PUBLIC', 'DOG', 'INTAKE'})."""
    toks = re.findall(r"[A-Z0-9.&/']+", (name or "").upper())
    num = ""
    for t in reversed(toks):
        t = t.strip(".")
        if _ROOM_NO.match(t):
            num = t
            break
    words = {t for t in toks if not re.search(r"\d", t) and len(t) > 1}
    return num, words


def _norm_room_no(n):
    return str(n or "").strip().upper().strip(".")


def _same_room(a, b):
    """Two room takeoffs from different sheets are the same room: the
    same number (or, unnumbered, the same name), names that agree, and
    areas within 15% (or the same tagged area)."""
    na, wa = room_key(a.get("name"))
    nb, wb = room_key(b.get("name"))
    # the room number all_rooms read ("115.1"), when it gave one
    na = _norm_room_no(a.get("number")) or na
    nb = _norm_room_no(b.get("number")) or nb
    if na or nb:
        if na != nb:
            return False
        if wa and wb and not (wa <= wb or wb <= wa or
                              len(wa & wb) / len(wa | wb) >= 0.5):
            return False
    elif not wa or wa != wb:
        return False
    ta, tb = a.get("tag_sf"), b.get("tag_sf")
    if ta and tb and abs(ta - tb) < 0.5:
        return True
    sa, sb = a.get("sqft") or 0, b.get("sqft") or 0
    return sa > 0 and sb > 0 and abs(sa - sb) <= 0.15 * max(sa, sb)


def _same_tag(a, b):
    """Two rooms carry the same room tag: the same room number (read by
    all_rooms, or the last number in the name) and names that agree (one
    holds the other's words, or half of them are shared). Unnumbered
    rooms never match this way."""
    na, wa = room_key(a.get("name"))
    nb, wb = room_key(b.get("name"))
    na = _norm_room_no(a.get("number")) or na
    nb = _norm_room_no(b.get("number")) or nb
    if not na or na != nb:
        return False
    if not wa or not wb:
        return True
    # half the shorter name's words shared: 'MEN'S PUBLIC TOILET ROOM 111'
    # and 'MEN'S PUBLIC RESTROOM 111' on the ADA plan (HMB, Oct 31)
    return wa <= wb or wb <= wa or len(wa & wb) / len(wa | wb) >= 0.5 \
        or len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def plan_rank(row):
    """Which sheet a room is taken from when several plans show it: the
    floor plan first, then other plans, then enlarged plans, then finish,
    ceiling and the like."""
    t = (row.get("title") or "").upper()
    # a demolition plan shows what comes out - never the floor plan for
    # rooms or walls while another plan of that floor is there (Oct 31)
    if _DEMO_PLAN.search(t) or re.match(r"^AD[-.]?\d",
                                         (row.get("number") or "").upper()):
        return 4
    if re.search(r"\bFLOOR\s+PLANS?\b", t) and not _OTHER_PLAN.search(t):
        return 0
    if re.search(r"\bENLARGED\b", t):
        return 2
    if re.search(r"\b(FINISH|REFLECTED|CEILING|RCP|FURNITURE|EQUIPMENT|"
                 r"SIGNAGE)\b", t):
        return 3
    return 1


def dedupe_rooms(per_page, rows_by_page):
    """per_page {page: [room]} -> ({page: [room kept]}, [(room, kept page,
    [other pages])]). A room shown on several plans (floor plan,
    dimension plan, enlarged plan, finish plan all carry the room tags)
    is taken off once, from its floor-plan instance (plan_rank)."""
    inst = []
    for pno, found in per_page.items():
        rk = plan_rank(rows_by_page.get(pno, {}))
        for i, r in enumerate(found):
            inst.append((rk, pno, i, r))
    inst.sort(key=lambda x: (x[0], x[1], x[2]))
    keys = {pno: _level_key((rows_by_page.get(pno) or {}).get("title"))
            for pno in per_page}

    def same_floor(p, q):
        # levels and plan areas agree, or one sheet doesn't say
        return all(not a or not b or a == b
                   for a, b in zip(keys[p], keys[q]))

    def twin_of(k, pno, r):
        if k[1] == pno or not same_floor(k[1], pno):
            return False
        # the room tag is the truth: the same room number with names
        # that agree is the same room on another plan of that floor,
        # whatever its trace there measures (equipment and ceiling
        # plans are traced around casework and soffits)
        return _same_room(k[3], r) or _same_tag(k[3], r)
    kept, dups = [], {}
    for rk, pno, i, r in inst:
        twin = next((k for k in kept if twin_of(k, pno, r)), None)
        if twin is not None:
            dups.setdefault(id(twin[3]), (twin, []))[1].append(pno)
            continue
        kept.append((rk, pno, i, r))
    out = {pno: [] for pno in per_page}
    for rk, pno, i, r in sorted(kept, key=lambda x: (x[1], x[2])):
        out[pno].append(r)
    report = [(tw[3], tw[1], sorted(set(pp))) for tw, pp in dups.values()]
    return out, report


def _sheet_name(rows_by_page, pno):
    r = rows_by_page.get(pno) or {}
    return r.get("number") or f"page {pno + 1}"


# ------------------------------------------------------------- civil
_UTIL_SHEET = re.compile(r"\bUTILIT(?:Y|IES)\b", re.I)
_PIPE_TITLE = re.compile(r"\b(?:SEWER|SANITARY|WATER|STORM|PIPING|"
                         r"PIPELINE|FORCE\s*MAIN)\b", re.I)
_SITE_TITLE = re.compile(r"\b(?:GRADING|DRAINAGE|PAVING|SITE|LAYOUT|"
                         r"STAKING|EROSION)\b", re.I)


def civil_rank(title):
    """Which civil sheet pipe is taken from when it is drawn on several:
    0 a utility plan, 1 a sewer / water / storm plan, 2 anything else
    (grading and drainage, paving, site plans)."""
    t = title or ""
    if _UTIL_SHEET.search(t):
        return 0
    if _PIPE_TITLE.search(t) and not _SITE_TITLE.search(t):
        return 1
    return 2


def civil_pipe_pages(doc, civil_pages, rows_by_page):
    """(pages pipe is read from, message): heavy.pipe_plan_pages' pick of
    the civil sheets (no details, erosion control, covers...). The
    message names the sheets read and the ones left out, so it is true
    (3c C6). A pipe drawn on two of the sheets read is taken once, from
    the better sheet, by civil_same_pipe after the takeoff."""
    from . import heavy
    pp = heavy.pipe_plan_pages(doc, civil_pages, loose=True)
    if not pp:
        return [], ""
    left = [p for p in civil_pages if p not in pp]
    if not left:
        return pp, ""
    names = ", ".join(_sheet_name(rows_by_page, p) for p in pp)
    return pp, (f"civil pipe read from {names}; {len(left)} other civil "
                "sheet(s) not read for pipe: " +
                ", ".join(_sheet_name(rows_by_page, p) for p in left[:10]))


def civil_same_pipe(cres, rows_by_page):
    """A pipe size drawn on more than one civil sheet (the 8\" storm on the
    grading plan and again on the utility plan) is taken from the best
    sheet (civil_rank: utility plan first) only. Sheets of the same rank
    (two utility plans of different areas) are added up. Changes
    `cres` in place; returns the messages."""
    from . import civiltakeoff
    msgs = []
    dropped = set()

    def title(p):
        return (rows_by_page.get(p) or {}).get("title") or ""
    for g in cres.get("pipes", []):
        pages = sorted({rr["page"] for rr in g["runs"]})
        if len(pages) < 2:
            continue
        ranks = {p: civil_rank(title(p)) for p in pages}
        best = min(ranks.values())
        keep = [p for p in pages if ranks[p] == best]
        drop = [p for p in pages if ranks[p] != best]
        if not drop:
            continue
        lost = sum(rr["length"] for rr in g["runs"] if rr["page"] in drop)
        g["runs"] = [rr for rr in g["runs"] if rr["page"] in keep]
        g["length"] = sum(rr["length"] for rr in g["runs"])
        bands = {}
        for rr in g["runs"]:
            b = civiltakeoff.band_of(rr.get("depth"))
            bands[b] = bands.get(b, 0.0) + rr["length"]
        g["bands"] = bands
        g["pages"] = keep
        lbp = g.get("label_by_page")
        if lbp:
            g["label_length"] = sum(v for pg, v in lbp.items() if pg in keep)
        dropped.add(g["name"])
        msgs.append(
            f"{g['name']}: drawn on " + ", ".join(
                _sheet_name(rows_by_page, p) for p in pages) +
            " - taken from " + ", ".join(_sheet_name(rows_by_page, p)
                                         for p in keep) +
            f" only ({g['length']:,.0f} LF); {lost:,.0f} LF on " +
            ", ".join(_sheet_name(rows_by_page, p) for p in drop) +
            " not counted again")
    if dropped:
        # the label check again, on what is kept
        checks = [c for c in cres.get("checks", [])
                  if not any(c.startswith(n + ":") for n in dropped)]
        for g in cres["pipes"]:
            if g["name"] in dropped:
                c = civiltakeoff.label_check(g)
                if c:
                    checks.append(c)
        cres["checks"] = checks
    return msgs


# ------------------------------------------------------------- ducts
def duct_groups(page, ppu, unit):
    """Ducts on one M plan, kept only where it is sure (N7): (kept groups,
    review [(name, length, why)], dropped count). Each size printed on
    the sheet is looked for as two lines that size apart
    (tradetakeoff.ducts_by_tag), taken from its tag and followed along
    the run, so a duct face never pairs with a wall or another duct.
    Pieces under DUCT_MIN_LF are dropped; tagged sizes over DUCT_MAX_IN
    and duct-width lines no tag reaches go to review."""
    from . import tradetakeoff as tt
    info = {}
    groups, unassigned = tt.ducts_by_tag(page, ppu, unit, info=info)
    # the ductwork's own line styles (the pens its tagged runs are drawn
    # in): double lines in other pens are walls, casework, equipment
    duct_styles = set(info.get("styles") or ())
    kept, review, dropped = [], [], 0
    for g in groups:
        good = []
        for pc in g["pieces"]:
            if pc.get("length_ft", pc["length"]) < DUCT_MIN_LF and \
                    not pc.get("fitting"):
                dropped += 1
                continue
            good.append(pc)
        # a fitting gap counts only between two pieces that are kept
        ends = {(round(q["p0"][0], 1), round(q["p0"][1], 1))
                for q in good if not q.get("fitting")} | \
            {(round(q["p1"][0], 1), round(q["p1"][1], 1))
             for q in good if not q.get("fitting")}
        good = [q for q in good if not q.get("fitting") or (
            (round(q["p0"][0], 1), round(q["p0"][1], 1)) in ends and
            (round(q["p1"][0], 1), round(q["p1"][1], 1)) in ends)]
        big = max(g.get("w") or 0, g.get("h") or 0)
        if big > DUCT_MAX_IN:
            review.append((g["name"], sum(pc["length"] for pc in good),
                           f"duct over {DUCT_MAX_IN:.0f} in wide - check it"))
            continue
        if not good:
            continue
        W, H = g.get("w") or 0, g.get("h")
        per = 2 * (W + H) / 12 if H else math.pi * W / 12
        L = sum(pc["length"] for pc in good)
        Lft = sum(pc.get("length_ft", pc["length"]) for pc in good)
        kept.append(dict(g, pieces=good, length=L, sf=per * Lft,
                         lb=per * Lft * g.get("lbsf", 0.0)))
    for u in unassigned:
        review.append((u["name"], u["length"], u["why"]))
    # double-line ducts no size tag reaches (any width): listed, never
    # taken off - nothing is dropped unseen
    try:
        loose = tt.ducts(page, ppu, unit)
    except Exception:                                     # noqa: BLE001
        loose = []
    have = {(round(pc["p0"][0]), round(pc["p0"][1]))
            for g in kept for pc in g["pieces"]}
    for g in loose:
        if g.get("tagged"):
            continue
        L = 0.0
        for pc in g["pieces"]:
            if pc.get("length_ft", pc["length"]) < DUCT_MIN_LF or \
                    (pc.get("width") or 0) > DUCT_MAX_IN:
                dropped += 1
                continue
            if (round(pc["p0"][0]), round(pc["p0"][1])) in have:
                continue
            if duct_styles and pc.get("style") is not None and \
                    pc["style"] not in duct_styles:
                continue                     # not drawn in the duct pen
            L += pc["length"]
        if L > 0:
            review.append((g["name"], L, "no size tag at this duct - "
                                         "measure it by hand"))
    return kept, review, dropped


def _ducts(doc, pno, name, ppu, unit, res, sheet):
    from . import tradetakeoff as tt
    kept, review, dropped = duct_groups(doc[pno], ppu, unit)
    ms = tt.duct_marks(pno, kept, unit)
    for m in ms:
        m[2]["measure"]["method"] = "AI takeoff: ducts"
        m[2]["measure"]["group"] = re.sub(r"^Duct ", "",
                                          m[2]["measure"]["group"])
        m[2]["measure"]["csi"] = "23 31 00"
    res["marks"] += ms
    sheet["ducts"] = {g["name"]: g["length"] for g in kept}
    # flex run-outs to the air devices (untagged; size read from the drawing)
    fx = tt.flex_runs(doc[pno], ppu, unit)
    for f in fx:
        pts = f["pts"]
        for a, b in zip(pts, pts[1:]):
            res["marks"].append((pno, "add_line", {
                "pts": [list(a), list(b)], "color": [0.85, 0.35, 0.0],
                "width": 3, "opacity": 0.55,
                "measure": {"type": "length", "value":
                            round(f["length"] / max(len(pts) - 1, 1), 4),
                            "unit": unit, "group": f["name"],
                            "method": "AI takeoff: ducts",
                            "csi": "23 33 46"}}))
        sheet.setdefault("ducts", {})
        sheet["ducts"][f["name"]] = _c2(
            sheet["ducts"].get(f["name"], 0) + f["length"])
    try:
        from . import fittings
        fc = fittings.count_ducts(kept, tt._per_ft(ppu, unit), fx)
        acc = res.setdefault("_duct_fittings", {})
        for kk, n in fc.items():
            e = acc.setdefault(kk, [0, []])
            e[0] += n
            if name not in e[1]:
                e[1].append(name)
    except Exception:                                    # noqa: BLE001
        log.info("duct fittings on %s", name, exc_info=True)
    if fx:
        res["problems"].append(
            f"{name}: {len(fx)} flex run-out(s) measured along their curve - "
            "size read from the drawn width (no tag), check it")
    for nm, L, why in review:
        res["review"].append({"sheet": name, "page": pno, "name": nm,
                              "qty": L, "unit": unit, "why": why,
                              "engine": "ducts", "csi": "23 31 00"})
    if review:
        res["problems"].append(
            f"{name}: {len(review)} duct group(s) not taken off - " +
            "; ".join(f"{n} ({w})" for n, _l, w in review[:5]))
    if dropped:
        res["problems"].append(
            f"{name}: {dropped} duct fragment(s) under {DUCT_MIN_LF:g} LF "
            f"or over {DUCT_MAX_IN:.0f} in wide left out")


# ------------------------------------------------------------- steel
def _steel_sheet(doc, pno, ppu, unit, rows):
    """One S plan's members, with its grid for de-duplication."""
    from . import structural, schedules
    from . import tradetakeoff as tt
    page = doc[pno]
    text = page.get_text()
    try:
        tables = schedules.read_page(page, "structural")
    except Exception:                                    # noqa: BLE001
        tables = []
    ms = structural.members(page, ppu, unit, tables=tables, note_text=text)
    words = page.get_text("words")
    cells = schedules.make_cells([tuple(w[:8]) for w in words])
    segs = [sg for v in tt.styled_segments(page).values() for sg in v]
    gx, gy = structural.grid(cells, segs)
    # 3c C11: a member tagged again in a second view on the sheet (an
    # attic framing view, an enlarged or partial plan, a section) is the
    # same steel - listed for review, not counted twice
    w, h = page.rect.width, page.rect.height
    if page.rotation in (90, 270):
        w, h = h, w                    # words and lines are unrotated
    ex = schedules.title_block(w, h, segs)
    vs = schedules.views(cells, ex)
    if len(vs) > 1:
        own = {}
        for m in ms:
            rc = m.get("tag_rect")
            if not rc:
                continue
            c = {"cx": (rc[0] + rc[2]) / 2, "cy": (rc[1] + rc[3]) / 2,
                 "h": max(rc[3] - rc[1], 4.0)}
            own[id(m)] = schedules.view_of(c, vs, w)
        counts = {}
        for v in own.values():
            if v is not None:
                counts[id(v)] = counts.get(id(v), 0) + 1
        mains = {id(v) for v in schedules.main_views(vs, counts)}
        for m in ms:
            v = own.get(id(m))
            if v is not None and mains and id(v) not in mains and \
                    m["kind"] != "review":
                m["kind"] = "review"
                m["why"] = (f"tagged in the view '{v['title']}' - a second "
                            "view of the sheet; not counted twice, check it")
    return {"members": ms, "gx": gx, "gy": gy, "ppu": ppu, "unit": unit,
            "per_ft": tt._per_ft(ppu, unit)}


def _steel_set(doc, found, rows_by_page, res):
    """Steel across the S plans, each member once (same mark at the same
    grid location), as marks (column counts, beam lengths) and LB
    quantities - weight only when the length is known."""
    from . import structural
    per_ft = {p: g["per_ft"] for p, g in found.items()}
    kept, dups = structural.dedupe(found, rows_by_page, per_ft)
    res["steel_dup"] = [(m["name"], p, kp, how) for p, m, kp, how in dups]
    if dups:
        by = {}
        for p, m, kp, how in dups:
            by.setdefault((p, kp, how), 0)
            by[(p, kp, how)] += 1
        for (p, kp, how), n in sorted(by.items()):
            res["problems"].append(
                f"{n} steel member(s) on {_sheet_name(rows_by_page, p)} are "
                f"also on {_sheet_name(rows_by_page, kp)} (same mark, " +
                ("same grid location" if how == "grid" else
                 "same place on the sheet") + ") - taken off once")
    nogrid = [p for p, g in found.items() if not (g["gx"] and g["gy"])]
    if nogrid and len(found) > 1:
        res["problems"].append(
            "no grid read on " + ", ".join(_sheet_name(rows_by_page, p)
                                           for p in nogrid) +
            " - steel shown on two plans matched by its position on the "
            "sheet; check")
    tot = {}
    for p, m in kept:
        sh = _sheet_name(rows_by_page, p)
        unit = found[p]["unit"]
        if m["kind"] == "review":
            res["review"].append({"sheet": sh, "page": p, "name": m["name"],
                                  "qty": None, "unit": "ea",
                                  "why": m["why"], "engine": "steel",
                                  "csi": "05 12 00"})
            continue
        t = tot.setdefault(m["name"], {"ea": 0, "lf": 0.0, "lb": 0.0,
                                       "nolen": 0, "page": p,
                                       "lb_ft": m["lb_ft"]})
        if m["kind"] == "column":
            x, y = m["pt"]
            res["marks"].append((p, "add_count", {
                "pt": [x, max(12, y - 2)], "n": t["ea"] + 1,
                "color": [0.55, 0.3, 0.1],
                "measure": {"type": "count", "value": 1, "unit": "ea",
                            "group": m["name"], "csi": "05 12 00",
                            "method": "AI takeoff: steel"}}))
            t["ea"] += 1
            if m["length"]:
                t["lf"] += m["length"]
            else:
                t["nolen"] += 1
        else:
            pts = [list(q) for q in m["pts"]]
            L = m["length"] * found[p]["per_ft"] / found[p]["ppu"]
            res["marks"].append((p, "add_polyline" if len(pts) > 2 else
                                 "add_line", {
                                     "pts": pts, "color": [0.55, 0.3, 0.1],
                                     "width": 2.5, "opacity": 0.6,
                                     "measure": {"type": "length",
                                                 "value": round(L, 4),
                                                 "unit": unit,
                                                 "group": m["name"],
                                                 "csi": "05 12 00",
                                                 "method":
                                                 "AI takeoff: steel"}}))
            t["lf"] += m["length"]
        res["sheets"].setdefault(p, {}).setdefault("steel", {}).setdefault(
            m["name"], 0)
        res["sheets"][p]["steel"][m["name"]] += 1
    for name, t in sorted(tot.items()):
        sh = _sheet_name(rows_by_page, t["page"])
        if t["nolen"]:
            res["review"].append({
                "sheet": sh, "page": t["page"], "name": name,
                "qty": t["nolen"], "unit": "ea", "engine": "steel",
                "csi": "05 12 00",
                "why": f"{t['nolen']} column(s) counted, height unknown - "
                       "no weight; find the column height (schedule / "
                       "section) and weigh by hand"})
            continue
        if not t["lb_ft"]:
            continue
        res["quantities"].append({
            "engine": "steel", "name": name, "qty": round(t["lf"] *
                                                          t["lb_ft"], 1),
            "unit": "LB", "status": "taken off", "page": t["page"],
            "sheet": sh, "csi": "05 12 00",
            "basis": f"{t['lf']:,.1f} LF x {t['lb_ft']:g} lb/ft"})


# ------------------------------------------------------------- pipe drops
def _pipe_drops(page, pno, name, unit, res):
    """Drops to fixtures from the sheet's DOWN / UP keynotes, as quantity
    lines marked as an assumption (the drop height is not drawn); rises in
    waste / vent piping are listed for review, never given a length."""
    from . import settings
    from . import tradetakeoff as tt
    try:
        drop_ft = float(settings.get("pipe_drop_ft", tt.DROP_FT_DEFAULT))
    except (TypeError, ValueError):
        drop_ft = tt.DROP_FT_DEFAULT
    drops = tt.keynote_drops(page, drop_ft)
    to_unit = 1.0 if unit in ("ft", "LF", "lf") else 0.3048
    n_assumed = 0
    for g in drops:
        if g["length_ft"] is None:
            res["review"].append({"sheet": name, "page": pno,
                                  "name": g["name"] + " rises",
                                  "qty": g["drops"], "unit": "ea",
                                  "engine": "pipes", "why": g["basis"]})
            continue
        n_assumed += 1
        res["quantities"].append({
            "engine": "pipe drops", "name": g["name"] + " drops",
            "qty": _c2(g["length_ft"] * to_unit),
            "unit": "LF" if to_unit == 1.0 else "M",
            "status": "taken off", "page": pno, "sheet": name,
            "csi": "22 11 00", "basis": g["basis"], "assumption": True})
    if n_assumed:
        res["problems"].append(
            f"{name}: pipe drops at DOWN/UP keynotes use an ASSUMED "
            f"{drop_ft:g} ft drop height - check it (setting "
            "'pipe_drop_ft')")


# ------------------------------------------------------------- schedules
def _schedules(doc, rows, pages, res):
    """Schedules read on `pages`, their keys counted on the plans; lines
    become count marks (at the plan tags, or at the schedule rows for
    hardware sets and panels) or review entries; footing marks become
    CY."""
    from . import schedules, structural
    from . import autocount
    sres = schedules.takeoff(doc, rows, pages=set(pages))
    res["schedules"] = sres
    res["problems"] += sres["problems"]
    res["review"] += sres["review"]
    by_page = {r["page"]: r for r in rows}
    for ln in sres["lines"]:
        if ln["status"] == "taken off" and ln.get("from_qty") and \
                not ln.get("hits"):
            # taken from the schedule's QTY column: no tags to mark, so it
            # is a quantity line of its own (it would vanish otherwise)
            res["quantities"].append({
                "engine": "schedules", "name": ln["name"][:60],
                "qty": ln["qty"], "unit": "EA", "status": "taken off",
                "page": ln.get("page"),
                "sheet": _sheet_name(by_page, ln["page"])
                if ln.get("page") is not None else "schedule",
                "csi": ln.get("csi", ""),
                "basis": f"schedule QTY {ln['qty']} (no tags on the plans; "
                         "the other keys' tags agree with the QTY column)"})
            continue
        if ln["status"] != "taken off" or not ln.get("hits"):
            continue
        hits = []
        for h in ln["hits"]:
            rect = schedules.to_page(doc[h["page"]], h["rect"])
            hits.append({"page": h["page"], "rect": rect,
                         "method": "AI takeoff: schedules"})
        ms = autocount.count_marks(hits, ln["name"][:60], doc)
        for m in ms:
            m[2]["measure"]["csi"] = ln["csi"]
            m[2]["measure"]["basis"] = ln.get("basis", "")
        res["marks"] += ms
        for h in hits:
            res["sheets"].setdefault(h["page"], {}).setdefault(
                "schedules", {}).setdefault(ln["name"][:60], 0)
            res["sheets"][h["page"]]["schedules"][ln["name"][:60]] += 1
    for f in structural.footings(sres["lines"], sres["tables"]):
        sh = _sheet_name({r["page"]: r for r in rows}, f["page"]) \
            if f.get("page") is not None else "footing schedule"
        if f["status"] == "taken off":
            res["quantities"].append({
                "engine": "footings", "name": f["mark"], "qty":
                round(f["cy"], 3), "unit": "CY", "status": "taken off",
                "page": f["page"], "sheet": sh, "csi": "03 30 00",
                "basis": f"{f['count']} x " + " x ".join(
                    f"{d:g}'" for d in f["dims"])})
            rb = f.get("rebar")
            if rb:
                res["quantities"].append({
                    "engine": "footings", "name": f"{f['mark']} rebar "
                    f"#{rb['bar']}", "qty": rb["lb"], "unit": "LB",
                    "status": "taken off", "page": f["page"], "sheet": sh,
                    "csi": "03 21 00",
                    "basis": f"{f['count']} footing(s) x {rb['basis']}"})
        else:
            res["review"].append({"sheet": sh, "page": f["page"],
                                  "name": f["name"] + " concrete",
                                  "qty": None, "unit": "CY",
                                  "why": f["why"], "engine": "footings",
                                  "csi": "03 30 00"})


# ------------------------------------------------------------- finishes
FINISH_CSI_UNKNOWN = "09 00 00"
# finish code (its letters, "EPX" from "EPX-1") -> CSI, per finish kind
_FINISH_CSI = {
    "floor": [
        (r"EPX|EP|EPOXY|RES|RESIN|RESF|ERF|URE|MMA", "09 67 23"),
        (r"PC|POL|PCC|SC|SCC|SEALED|CONC|CONCRETE", "03 35 00"),
        (r"RF|RT|VCT|LVT|LVP|VT|SV|LIN|LINO|RUB|RSF|VF|SPF|RES[A-Z]*V",
         "09 65 00"),
        (r"CT|PT|PTF|QT|POR|PORC|TILE|MOS|CPT?L", "09 30 00"),
        (r"CPT|CP|CARPET|CPT[A-Z]", "09 68 00"),
        (r"WD|WOOD|WAF|HWD", "09 64 00")],
    "base": [
        (r"EPX|EP|EPOXY|RES|IC", "09 67 23"),
        (r"CTB|PTB|QTB|TB|PORC|CT|PT", "09 30 00"),
        (r"RB|VB|VRB|RUB|RBB|B|WB|RCB", "09 65 13")],
    "ceiling": [
        (r"ACT|AC|APC|ACP|ACOUS|LAY|LAYIN|SAT|ACM", "09 51 13"),
        (r"GB|GYP|GWB|GYPBD|GYPSUM|HC|GBC|MRGB|GWB[A-Z]*", "09 29 00")],
    "walls": [
        (r"PT|P|PNT|PAINT|EPP|EP|EPT|EPOXY", "09 91 00"),
        (r"CWT|PWT|CT|WT|TILE|CTW|PTW", "09 30 00"),
        (r"WC|VWC", "09 72 00")],
}
FINISH_LABEL = {"floor": "Floor", "base": "Base", "ceiling": "Ceiling",
                "walls": "Wall finish"}
FINISH_UNIT = {"floor": "SF", "base": "LF", "ceiling": "SF", "walls": "SF"}


def finish_csi(kind, code):
    """(CSI, note) for a finish code of a kind ('floor', 'base', 'ceiling',
    'walls'): EPX -> 09 67 23, PC -> 03 35 00, RB base -> 09 65 13, ACT ->
    09 51 13, GB ceiling -> 09 29 00, PT-1 -> 09 91 00... A code made of
    several ("ACT / GB", "PT-1 / CWT") takes its first part's division and
    says so; a code not known is 09 00 00, with a note."""
    from .room_finishes import UNKNOWN
    if not code or code == UNKNOWN:
        return FINISH_CSI_UNKNOWN, "finish code unknown"
    parts = [p.strip() for p in re.split(r"[/,;&+]", str(code)) if p.strip()]
    got = []
    for p in parts:
        m = re.match(r"[A-Z]+", p.upper())
        letters = m.group(0) if m else ""
        csi = next((c for rx, c in _FINISH_CSI.get(kind, ())
                    if re.fullmatch(rx, letters)), None)
        got.append(csi)
    if not got or got[0] is None:
        return FINISH_CSI_UNKNOWN, (f"{FINISH_LABEL.get(kind, kind).lower()}"
                                    f" code '{code}' not recognised - CSI "
                                    f"{FINISH_CSI_UNKNOWN}")
    if len(set(got)) > 1:
        return got[0], (f"'{code}' mixes finishes - all under {got[0]}; "
                        "split by hand")
    return got[0], ""


def _hdr_words(h):
    return set(re.findall(r"[A-Z]+", str(h).upper()))


_FIN_ROLES = {"ceiling": {"CEILING", "CLG", "CEIL"},
              "base": {"BASE"}, "floor": {"FLOOR", "FLR", "FLOORING"},
              "walls": {"WALL", "WALLS"}}
_FIN_VOCAB = set().union(*_FIN_ROLES.values()) | {
    "FINISH", "FINISHES", "MATERIAL", "TYPE", "SYSTEM", "MAT", "HEIGHT", "HT",
    "HGT", "NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E", "W", "ROOM",
    "NAME", "NO", "NUMBER", "2", "FINISH 2", "COVE", "TOP", "PAINT",
    "COLOR", "TRIM"}


def _legend_columns(names, hw):
    """Columns of a finish legend read into the schedule beside it: when a
    role (ceiling, base, floor, walls) has a column whose header is only
    schedule words ('CEILING FINISH', 'BASE'), another column naming the
    same role inside a description ('ACOUSTICAL CEILING TILE', 'PORCELAIN
    TILE BASE') is legend text, not a schedule column."""
    out = set()
    for role, ws in _FIN_ROLES.items():
        cand = [(nm, w) for nm, w in zip(names, hw) if w & ws and
                not (role == "ceiling" and w & {"HEIGHT", "HT", "HGT"})]
        pure = [nm for nm, w in cand if w <= _FIN_VOCAB]
        if pure:
            out |= {nm for nm, w in cand if nm not in pure}
    return out


def finish_rows(tables):
    """The finish schedule rows (schedules.takeoff tables of kind
    'finish') as room_finishes reads them: {"room", "name", "floor",
    "base", "walls", "ceiling", "ceiling_height"} from the table's header
    names - "CEILING MATERIAL" over "CEILING FINISH" (the ceiling's
    paint), walls by side when the schedule has N / E / S / W columns.
    Returns (rows, [(table, why)] for tables not read with confidence)."""
    out, bad = [], []
    for t in tables or ():
        if t.get("kind") != "finish":
            continue
        if not t.get("confident"):
            bad.append((t, t.get("why") or "not read with confidence"))
            continue
        cols = [c for c in (t.get("columns") or [])]
        if not cols and t.get("rows"):
            cols = [k for k in t["rows"][0] if not k.startswith("_")]
        names = [c if isinstance(c, str) else c.get("name", "") for c in cols]
        ceil_mat = any({"CEILING", "CLG", "CEIL"} & _hdr_words(n) and
                       {"MATERIAL", "TYPE", "SYSTEM", "MAT"} & _hdr_words(n)
                       for n in names)
        # a two-row header whose upper row (FLOOR / WALLS / CEILING) was
        # not read leaves bare "FINISH" / "MATERIAL" columns: finish
        # schedules run floor, base, walls, ceiling, so a bare one before
        # the base or walls is the floor, the first after the walls the
        # ceiling - only when the table has no named floor / ceiling column
        hw = [_hdr_words(nm) for nm in names]
        bare = {"FINISH", "MATERIAL", "TYPE", "MAT", "FINISH 2", "2"}
        has_floor = any(w & {"FLOOR", "FLR", "FLOORING"} for w in hw)
        has_ceil = any(w & {"CEILING", "CLG", "CEIL"} for w in hw)
        i_base = next((i for i, w in enumerate(hw) if "BASE" in w), None)
        i_wall = next((i for i, w in enumerate(hw)
                       if w & {"WALL", "WALLS"}), None)
        pos = {}
        for i, (nm, w) in enumerate(zip(names, hw)):
            if not w or not w <= bare or nm == t.get("key"):
                continue
            first = min(x for x in (i_base, i_wall) if x is not None) \
                if (i_base is not None or i_wall is not None) else None
            if not has_floor and first is not None and i < first and \
                    "floor" not in pos.values():
                pos[nm] = "floor"
            elif not has_ceil and i_wall is not None and i > i_wall and \
                    "ceiling" not in pos.values():
                pos[nm] = "ceiling"
        legend = _legend_columns(names, hw)
        for r in t.get("rows") or ():
            row = {"_page": t.get("page")}
            walls = {}
            for k, v in r.items():
                if k.startswith("_") or v in (None, "") or k in legend:
                    continue
                w = _hdr_words(k)
                if k in pos:
                    row.setdefault(pos[k], v)
                elif k == t.get("key"):
                    row["room"] = v
                elif "NAME" in w:
                    row["name"] = v
                elif w & {"CEILING", "CLG", "CEIL"}:
                    if w & {"HEIGHT", "HT", "HGT"}:
                        row["ceiling_height"] = v
                    elif w & {"MATERIAL", "TYPE", "SYSTEM", "MAT"} or \
                            not ceil_mat:
                        row.setdefault("ceiling", v)
                elif w & {"HEIGHT", "HT", "HGT"}:
                    row.setdefault("ceiling_height", v)
                elif "BASE" in w:
                    row["base"] = v
                elif w & {"FLOOR", "FLR", "FLOORING"}:
                    row["floor"] = v
                elif w & {"NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E",
                          "W"} and (w & {"WALL", "WALLS"} or len(w) == 1):
                    walls[k] = v
                elif w & {"WALL", "WALLS"}:
                    row["walls"] = v
            if walls and "walls" not in row:
                row["walls"] = walls
            out.append(row)
    return out, bad


def door_rows(tables):
    """Door schedule rows as room_finishes reads them: {"number",
    "width", "room"/"from"/"to"} - the width from a WIDTH column or the
    first dimension of a SIZE ("3'-0\" x 7'-0\"")."""
    out = []
    for t in tables or ():
        if t.get("kind") != "door" or not t.get("confident"):
            continue
        for r in t.get("rows") or ():
            d = {"number": r.get(t.get("key")) or ""}
            for k, v in r.items():
                if k.startswith("_") or not v:
                    continue
                w = _hdr_words(k)
                if "WIDTH" in w or k.strip().upper() == "W":
                    d["width"] = v
                elif w & {"SIZE", "DIMENSIONS"} and "width" not in d:
                    d["width"] = re.split(r"\s*[Xx×]\s*", str(v))[0]
                elif w & {"ROOM", "LOCATION"} and k != t.get("key"):
                    d["room"] = v
                elif "FROM" in w:
                    d["from"] = v
                elif w == {"TO"}:
                    d["to"] = v
            out.append(d)
    return out


_NO_FINISH = {"", "-", "--", "FF", "N/A", "NA", "NONE", "PREFIN",
              "PREFINISHED", "FACTORY", "FACTORY FINISH"}


def _ft_in(ft):
    w = int(ft)
    i = int(round((ft - w) * 12))
    if i == 12:
        w, i = w + 1, 0
    return f"{w}'-{i}\""


_SWPPP_T = re.compile(r"S\.?\s*W\.?\s*P\.?\s*P\.?\s*P|EROSION|SEDIMENT",
                      re.I)


def _silt_fence(doc, rows, res):
    """Silt fence off the erosion control (SWPPP) plans: a line labelled
    'SF' along its length, or a line carrying small squares / circles at
    intervals (the posts as most civil linetypes draw them). Phase plans
    redraw the same fence, so the longest phase is taken, not the sum.
    The 6\" x 6\" trench and the posts at 6' are the usual detail - CHECK
    lines unless the set's detail says otherwise."""
    from . import sitelines, tradetakeoff as tt
    best = None
    for r in rows:
        t = f"{r.get('title') or ''}"
        if r.get("kind") != "plan" or not _SWPPP_T.search(t) or \
                not r.get("scale"):
            continue
        _l, ppu, unit = r["scale"]
        pf = tt._per_ft(ppu, unit)
        page = doc[r["page"]]
        how, L = None, 0.0
        lab = sitelines.labelled(page, pf, r"S\.?F\.?")
        if lab.get("labels", 0) >= 3 and lab.get("length_ft"):
            L = lab["length_ft"]
            how = (f"the line its {lab['labels']} 'SF' labels are written "
                   "along, dash and label gaps closed")
        else:
            gs = [g for g in sitelines.marker_chains(page, pf)
                  if g.get("drawn_ft") and 4.0 <= g["spacing_ft"] <= 15.0]
            # existing work is drawn screened (grey): new fence is not
            def grey(c):
                return bool(c) and max(c) - min(c) < 0.05 and \
                    0.15 < max(c) < 0.85
            gs = [g for g in gs if not grey(g.get("color"))] or gs
            if gs:
                g = max(gs, key=lambda g: g["markers"])
                L = g["length_ft"]
                how = (f"the line drawn with a small square every "
                       f"{g['spacing_ft']:.1f} ft ({g['markers']} of them, "
                       f"{len(g['chains'])} run(s)), measured square to "
                       "square plus half a spacing at each end")
        if L and (best is None or L > best[0]):
            best = (L, how, r.get("number") or f"p{r['page'] + 1}", r["page"])
    if not best:
        return None
    L, how, sheet, pno = best
    _ai_line(res, "civil", "Silt fence", L, "LF", pno, sheet, "31 25 00",
             f"{how} on {sheet} (the longest of the erosion control "
             "phases) - check that this line type is the silt fence in the "
             "SWPPP legend", 0.62)
    _ai_line(res, "civil", "Silt fence posts @ 6' OC", math.ceil(L / 6.0),
             "EA", pno, sheet, "31 25 00",
             f"{L:,.1f} LF / 6 ft (the usual post spacing - check the "
             "silt fence detail)", REVIEW_BELOW - 0.05)
    _ai_line(res, "civil", "Silt fence trench 6\" x 6\" (and backfill)",
             L * 0.25 / 27.0, "CY", pno, sheet, "31 25 00",
             f"{L:,.1f} LF x 6\" x 6\" (the usual toe-in trench - check the "
             "silt fence detail)", REVIEW_BELOW - 0.05)
    return L


_SPACES = re.compile(r"^\s*(\d{1,3})\s+(?:PARKING\s+)?SPACES?\s*$", re.I)
_WHEEL = re.compile(r"\b(?:WHEEL|CAR|TIRE)\s*STOPS?\b|\bPARKING\s+BUMPERS?\b",
                    re.I)
_ACCESSIBLE = re.compile(r"\bPROVIDED\b[^.]{0,80}?\b(\d{1,2})\s+(?:ADA\s+|"
                         r"H\.?C\.?\s+|HANDICAP(?:PED)?\s+)?ACCESSIBLE\b",
                         re.I)


def _parking(doc, rows, res):
    """Parking off the site layout plan: the stalls its '7 SPACES' labels
    count, a wheel stop at each where the set details wheel stops, and the
    accessible stall emblem(s) the parking note gives."""
    civ = [r for r in rows if (r.get("discipline") or "") == "civil" and
           r.get("kind") not in ("superseded", "raster")]
    if not civ:
        return None
    best, wheel, acc = None, None, None
    for r in civ:
        try:
            page = doc[r["page"]]
            lines = page.get_text("text").splitlines()
        except Exception:                                 # noqa: BLE001
            continue
        txt = "\n".join(lines)
        if wheel is None and _WHEEL.search(txt):
            wheel = r.get("number") or f"p{r['page'] + 1}"
        if r.get("kind") != "plan":
            continue
        n = [int(m.group(1)) for ln in lines for m in [_SPACES.match(ln)]
             if m]
        if n and (best is None or sum(n) > best[0]):
            best = (sum(n), len(n), r.get("number") or f"p{r['page'] + 1}",
                    r["page"])
            m = _ACCESSIBLE.search(txt)
            acc = int(m.group(1)) if m else None
    if not best:
        return None
    n, k, sheet, pno = best
    if wheel:
        _ai_line(res, "site", "Wheel stops (one per parking space)", n,
                 "EA", pno, sheet, "32 17 13",
                 f"{n} parking spaces from the {k} 'SPACES' label(s) on "
                 f"{sheet}; wheel stops are detailed on {wheel} - check "
                 "which stalls get one", 0.62)
    if acc:
        _ai_line(res, "site", "Accessible parking space emblem", acc, "EA",
                 pno, sheet, "32 17 23",
                 f"{acc} accessible space(s) in the parking note on {sheet}",
                 0.62)
    return n


def window_head_lines(res):
    """Head flashing over the windows / storefronts drawn as elevations:
    each type's overall width (read off its elevation) x the windows of
    that type tagged on the plans, plus 4\" past each jamb (end dams) -
    a CHECK line: the flashing's run past the jambs is the usual detail,
    not read from this set."""
    widths = {}
    for t in (res.get("schedules") or {}).get("tables") or ():
        if t.get("kind") != "window" or not t.get("elevations"):
            continue
        for r in t.get("rows") or ():
            if r.get("_width_ft"):
                widths[f"Window {r['MARK']}"] = r["_width_ft"]
    if not widths:
        return None
    n = {}
    for _p, _k, pl in res.get("marks") or ():
        m = pl.get("measure") or {}
        g = m.get("group") or ""
        if m.get("method") == "AI takeoff: schedules" and g in widths and \
                m.get("type") == "count":
            n[g] = n.get(g, 0) + 1
    if not n:
        return None
    lf = sum(k * (widths[g] + 8 / 12.0) for g, k in n.items())
    parts = "; ".join(f"{k} x {widths[g]:g} ft ({g})"
                      for g, k in sorted(n.items()))
    missing = sorted(set(widths) - set(n))
    _ai_line(res, "envelope", "Window head flashing", lf, "LF", None, "set",
             "07 62 00", f"{parts}, each plus 4\" past both jambs"
             + (f"; not tagged on the plans: {', '.join(missing)}"
                if missing else "")
             + " - check the head detail", REVIEW_BELOW - 0.05)
    return lf


def door_finish_lines(res):
    """Door and frame finishes from a confident door schedule (FINISH and
    FRAME FINISH columns): doors counted by finish, size and door type
    ('Door finish ST-1: 3'-0" x 7'-0" type F'); frame paint LF = 2 x
    height + width per opening; trim LF both faces = 2 x that. Doors
    finished at the factory (FF, prefinished) are left out."""
    from .room_finishes import parse_feet
    doors, frames = {}, {}
    for t in (res.get("schedules") or {}).get("tables") or ():
        if t.get("kind") != "door" or not t.get("confident"):
            continue
        for r in t.get("rows") or ():
            W = H = None
            fin = ffin = typ = ""
            for k, v in r.items():
                if k.startswith("_") or v is None:
                    continue
                ku = re.sub(r"\s+", " ", k.upper()).strip()
                v = str(v).strip()
                if ku == "WIDTH" or ku == "W":
                    W = parse_feet(v)
                elif ku == "HEIGHT" or ku == "H":
                    H = parse_feet(v)
                elif ku == "FINISH" or ku == "DOOR FINISH":
                    fin = v.upper()
                elif ku == "FRAME FINISH":
                    ffin = v.upper()
                elif ku == "TYPE" or ku == "DOOR TYPE":
                    typ = v.upper()
            if not W or not H:
                continue
            if fin.split(" ")[0] not in _NO_FINISH:
                key = (fin.split(" ")[0], W, H, typ)
                doors[key] = doors.get(key, 0) + 1
            fc = ffin.split(" ")[0]
            if fc and fc not in _NO_FINISH:
                frames[fc] = frames.get(fc, 0.0) + 2 * H + W
    for (fin, W, H, typ), n in sorted(doors.items()):
        res["quantities"].append({
            "engine": "schedules", "status": "taken off", "unit": "EA",
            "name": f"Door finish {fin}: {_ft_in(W)} x {_ft_in(H)}"
                    + (f" type {typ}" if typ else ""),
            "qty": n, "page": None, "sheet": "door schedule",
            "csi": "09 91 00",
            "basis": f"{n} door(s) of this size and type with finish {fin} "
                     "in the door schedule"})
    for fc, lf in sorted(frames.items()):
        res["quantities"].append({
            "engine": "schedules", "status": "taken off", "unit": "LF",
            "name": f"Door frame finish {fc}", "qty": _c2(lf),
            "page": None, "sheet": "door schedule", "csi": "09 91 00",
            "basis": "2 x height + width of each frame with that finish "
                     "in the door schedule"})
        res["quantities"].append({
            "engine": "schedules", "status": "taken off", "unit": "LF",
            "name": f"Door trim finish {fc} (both faces)",
            "qty": _c2(2 * lf), "page": None, "sheet": "door schedule",
            "csi": "09 91 00",
            "basis": "the frame length on both faces of the wall"})
        res["quantities"].append({
            "engine": "schedules", "status": "taken off", "unit": "LF",
            "name": "Sealant & backer rod at door frames",
            "qty": _c2(2 * lf), "page": None, "sheet": "door schedule",
            "csi": "07 92 00",
            "basis": "around each frame with that finish, both faces"})


_DECK = re.compile(r"\b(\d(?:\.\d)?\s*[BNF]\s*\d{2}|\d(?:\.\d)?\s*VL[IR]?"
                   r"\s*\d{2})\s+(?:GALV\.?\s+)?(?:METAL|STEEL|ROOF)\s+DECK",
                   re.I)


def _two_materials(code):
    """'ACT-1 / PT-4' (two different finishes in one room) -> True;
    'PT-1' or 'EPX' -> False."""
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*&\s*", code or "")
             if p.strip()]
    fam = {re.sub(r"[-\s]*\d+[A-Z]?$", "", p.upper()) for p in parts}
    return len(parts) > 1 and len(fam) > 1


_GB_CEIL = re.compile(r"^(?:PT|EPP|EP|GB|GYP|GWB|P)-?\d*$", re.I)


def _gb_ceilings(out, res, sheet, pending=None):
    """Painted ceilings (PT-4, EPP-1) are gypsum board: the board SF and
    its sheets, tape, compound and screws, like a partition's. A room
    listing two ceilings (ACT-1 / PT-4) isn't split here - it is in the
    review list already. `pending` {code: SF}: ceilings of rooms still in
    review - not taken off, one pending-review line instead."""
    from . import wall_assembly as wa
    sf = 0.0
    codes = []
    for src in (out.get("ceiling") or {}, out.get("ceiling_split") or {}):
        for code, q in src.items():
            if q and _GB_CEIL.match(str(code).strip()):
                sf += q
                if code not in codes:
                    codes.append(code)
    held = sum(q for code, q in (pending or {}).items()
               if q and _GB_CEIL.match(str(code).strip()))
    held = min(held, sf)
    sf -= held
    if held > 0.05:
        res["quantities"].append({
            "engine": "finishes", "name": "Gypsum board ceiling",
            "qty": round(held, 1), "unit": "SF",
            "status": "pending review", "page": None, "sheet": sheet,
            "csi": "09 21 16", "basis": "ceilings of rooms in review - "
                                         "not taken off until accepted"})
    if sf <= 0.05:
        return
    basis = (f"ceilings finished {', '.join(sorted(codes))} "
             f"({sf:,.0f} SF) are painted gypsum board")
    for nm, q, u in (
            ("Gypsum board ceiling", sf, "SF"),
            ("Gypsum board ceiling - 4'x8' sheets",
             math.ceil(sf / wa.SHEET_SF), "SHEETS"),
            ("Gypsum board ceiling - joint tape (500' rolls)",
             math.ceil(sf * wa.TAPE_FT_PER_SF / 500.0), "ROLLS"),
            ("Gypsum board ceiling - joint compound",
             math.ceil(sf * wa.COMPOUND_LB_PER_SF), "LB"),
            ("Gypsum board ceiling - 1-1/4\" drywall screws",
             math.ceil(sf * wa.SCREWS_PER_SF), "EA")):
        res["quantities"].append({
            "engine": "finishes", "name": nm, "qty": round(q, 1),
            "unit": u, "status": "taken off", "page": None,
            "sheet": sheet, "csi": "09 21 16", "basis": basis})


_TO_STRUCT = re.compile(r"\bDEFLECTION\s+TRACK\b|\bTO\s+(?:THE\s+)?(?:UNDERSIDE"
                        r"\s+OF\s+)?(?:(?:ROOF\s+)?DECK|STRUCTURE)\b|"
                        r"\bFULL\s+HEIGHT\b", re.I)


def _paint_height(doc, rows, res):
    """(ft, why) - the height walls are painted to when the partitions
    run to the structure (the wall-type legend draws a deflection track /
    'to deck'): the gypsum board goes up to the roof structure, so does
    the paint. A sloped roof between two level marks (10'-8" bearing,
    15'-0" top) gives their average. None when the legend doesn't say
    so, the elevations show no level marks, or the setting is off
    (Takeoff > paint to ceiling height)."""
    from . import envelope, settings
    if not settings.get("paint_to_structure", True):
        return None
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    if not any(_TO_STRUCT.search(d or "") for d in legend.values()):
        return None
    ep = [r["page"] for r in rows if _ELEV_T.search(r.get("title") or "")]
    if not ep:
        return None
    hs = [h for h in envelope.wall_heights_from_levels([doc[p] for p in ep])
          if 6 <= h <= 30]
    if not hs:
        return None
    lo, hi = min(hs), max(hs)
    if hi - lo < 0.5:
        return lo, (f"walls painted full height to the structure (the "
                    f"partitions run to it): {_c2(lo):.2f} ft from the level "
                    "marks on the elevations")
    h = (lo + hi) / 2
    return h, (f"walls painted full height to the structure (the "
               f"partitions run to it), under a roof sloping from "
               f"{_c2(lo):.2f} to {_c2(hi):.2f} ft: {_c2(h):.2f} ft average - check rooms "
               "at the high or low side")


_RCP_T = re.compile(r"\bREFLECTED\s+CEILING\s+PLAN\b|\bR\.?C\.?P\b", re.I)


def _act_grid(doc, rows):
    """(SF, why, sheet) of the lay-in ceiling grid drawn on the set's
    reflected ceiling plan(s), or None (no RCP, no scale, no grid)."""
    from . import actgrid, tradetakeoff as tt
    total, whys, sheets = 0.0, [], []
    for r in rows:
        t = f"{r.get('title') or ''}"
        if r.get("kind") in ("superseded", "detail") or \
                not _RCP_T.search(t) or not r.get("scale"):
            continue
        try:
            _l, ppu, unit = r["scale"]
            g = actgrid.grid_area(doc[r["page"]], tt._per_ft(ppu, unit))
        except Exception:                                 # noqa: BLE001
            log.info("act grid", exc_info=True)
            continue
        if g and g["sf"] > 0:
            total += g["sf"]
            whys.append(g["why"])
            sheets.append(r.get("number") or f"p{r['page'] + 1}")
    if not total:
        return None
    return total, "; ".join(whys), "/".join(sheets)


def _split_ceiling(code, qty, n, out, res, act_grid, sheet):
    """Rooms listing two ceilings ('ACT-1 / PT-4') split with the lay-in
    grid measured on the RCP: the grid is every lay-in ceiling in the set,
    so the lay-in part of these rooms is the grid less the rooms that are
    all lay-in; the rest of them is the other ceiling. False (left for
    review) when there's no grid, or it doesn't fit between the two."""
    if not act_grid:
        return False
    parts = [p.strip() for p in re.split(r"\s*/\s*", code) if p.strip()]
    lay = [p for p in parts if re.match(r"^(?:ACT|ACP|AC|LAY)", p, re.I)]
    other = [p for p in parts if p not in lay]
    if len(parts) != 2 or len(lay) != 1 or len(other) != 1:
        return False
    a, b = lay[0], other[0]
    ceil = out.get("ceiling") or {}
    pure = sum(q or 0.0 for c, q in ceil.items()
               if re.match(r"^(?:ACT|ACP|AC|LAY)", str(c), re.I) and
               not _two_materials(c))
    mixed_lay = sum(q or 0.0 for c, q in ceil.items()
                    if _two_materials(c) and
                    re.search(r"(?:^|/)\s*(?:ACT|ACP|AC|LAY)", str(c), re.I))
    grid, gwhy, gsheet = act_grid
    part = grid - pure
    # the grid has to reach past the all lay-in rooms and stay inside them
    # and the two-ceiling rooms together (5% for the cut tiles)
    if part <= 0.05 * qty or grid > 1.05 * (pure + mixed_lay):
        res["problems"].append(
            f"finishes: the lay-in grid on {gsheet} ({grid:,.0f} SF) "
            f"doesn't fit the ceilings the finish schedule lists "
            f"({pure:,.0f} SF all lay-in + {mixed_lay:,.0f} SF in rooms "
            f"with two) - {code} rooms left for review")
        return False
    part = min(part * (qty / mixed_lay if mixed_lay else 1.0), qty)
    rest = qty - part
    basis = (f"{n} room(s) list {code}: the {a} part is the lay-in grid "
             f"measured on {gsheet} ({grid:,.0f} SF) less the rooms that "
             f"are all {a} ({pure:,.0f} SF); the rest is {b} - {gwhy}")
    for c, q in ((a, part), (b, rest)):
        if q <= 0:
            continue
        split = out.setdefault("ceiling_split", {})
        split[c] = (split.get(c) or 0.0) + q
        csi, _note = finish_csi("ceiling", c)
        res["quantities"].append({
            "engine": "finishes", "name": f"Ceiling {c} (rooms with {code})",
            "qty": round(q, 1), "unit": FINISH_UNIT["ceiling"],
            "status": "taken off", "page": None, "sheet": gsheet,
            "csi": csi, "ai_derived": True, "confidence": 0.62,
            "basis": f"AI-derived (confidence 0.62): {basis}"})
    return True


def _finishes(kept, res, rows_by_page, paint_h=None, act_grid=None):
    """room_finishes on the rooms kept (each room once, from its floor
    plan) and the finish / door schedules read: res["finishes"], result
    lines in res["quantities"] (engine 'finishes'), unknown codes and
    rooms not sure in res["review"]."""
    from . import room_finishes as rf
    rooms, page_of = [], []
    for pno in sorted(kept):
        for r in kept[pno]:
            rooms.append(r)
            page_of.append(pno)
    if not rooms:
        return
    if paint_h:
        res["problems"].append(f"finishes: rooms with no ceiling height "
                               f"in the schedule: {paint_h[1]}")
    tables = (res.get("schedules") or {}).get("tables") or []
    fs, bad = finish_rows(tables)
    ds = door_rows(tables)
    for t, why in bad:
        res["problems"].append(
            f"{t.get('sheet') or 'finish schedule'}: {t.get('title')} - "
            f"{why} - finish codes not taken from it")
    out = rf.room_finishes(rooms, finish_schedule=fs or None,
                           doors=ds or None, open_height=paint_h)
    res["finishes"] = out
    sched_page = next((r.get("_page") for r in fs
                       if r.get("_page") is not None), None)
    sched_sheet = _sheet_name(rows_by_page, sched_page) \
        if sched_page is not None else "rooms"
    for f in out["flags"]:
        res["problems"].append(f"finishes: {f}")
    if fs:
        for rec, room, pno in zip(out["rooms"], rooms, page_of):
            if not rec.get("review"):
                continue
            res["review"].append({
                "sheet": _sheet_name(rows_by_page, pno), "page": pno,
                "name": f"{room.get('name') or 'Room'} finishes",
                "qty": rec.get("floor_sf"), "unit": "sq ft",
                "why": "; ".join(rec.get("flags") or []) or "check",
                "engine": "finishes", "csi": FINISH_CSI_UNKNOWN})
    # rooms per code, for the basis
    key_of = {"floor": "floor_code", "base": "base_code",
              "ceiling": "ceiling_code", "walls": "wall_code"}
    qty_of = {"floor": "floor_sf", "base": "base_lf",
              "ceiling": "ceiling_sf", "walls": "wall_sf"}
    first = page_of[0]
    for kind in ("floor", "base", "ceiling", "walls"):
        for code, qty in sorted((out.get(kind) or {}).items()):
            if not qty:
                continue
            n = sum(1 for rec in out["rooms"]
                    if (rec.get(key_of[kind]) or rf.UNKNOWN) == code and
                    rec.get(qty_of[kind]))
            csi, note = finish_csi(kind, code)
            label = FINISH_LABEL[kind]
            unit = FINISH_UNIT[kind]
            if code == rf.UNKNOWN:
                res["review"].append({
                    "sheet": sched_sheet, "page": sched_page
                    if sched_page is not None else first,
                    "name": f"{label} (code unknown)", "qty": round(qty, 1),
                    "unit": unit, "engine": "finishes",
                    "csi": FINISH_CSI_UNKNOWN,
                    "why": f"{n} room(s) with no {label.lower()} code in a "
                           "finish schedule - not taken off"})
                continue
            if kind == "ceiling" and _two_materials(code) and \
                    _split_ceiling(code, qty, n, out, res, act_grid,
                                   sched_sheet):
                continue
            if kind in ("floor", "ceiling") and _two_materials(code):
                # 'ACT-1 / PT-4' in one room: two ceilings, and the split
                # between them is drawn on the RCP / floor plan, not here
                res["review"].append({
                    "sheet": sched_sheet, "page": sched_page
                    if sched_page is not None else first,
                    "name": f"{label} {code}", "qty": round(qty, 1),
                    "unit": unit, "engine": "finishes", "csi": csi,
                    "why": f"{n} room(s) list two {label.lower()} finishes "
                           f"({code}) - split the area between them from "
                           "the " + ("reflected ceiling plan"
                                     if kind == "ceiling" else "floor plan")})
                continue
            if note:
                res["problems"].append(f"finishes: {note}")
            # the part from rooms still in review is not taken off until
            # those rooms are accepted (Jon, Oct 31): a pending line
            pq = sum(rec.get(qty_of[kind]) or 0.0
                     for rec, room in zip(out["rooms"], rooms)
                     if room.get("review") and
                     (rec.get(key_of[kind]) or rf.UNKNOWN) == code)
            pn = sum(1 for rec, room in zip(out["rooms"], rooms)
                     if room.get("review") and rec.get(qty_of[kind]) and
                     (rec.get(key_of[kind]) or rf.UNKNOWN) == code)
            pq = min(pq, qty)
            page_ = sched_page if sched_page is not None else first
            if qty - pq > 0.05:
                res["quantities"].append({
                    "engine": "finishes", "name": f"{label} {code}",
                    "qty": round(qty - pq, 1), "unit": unit,
                    "status": "taken off", "page": page_,
                    "sheet": sched_sheet, "csi": csi,
                    "basis": f"{n - pn} room(s), finish schedule on "
                             f"{sched_sheet}" + (f"; {note}" if note
                                                 else "")})
            if pq > 0.05:
                res["quantities"].append({
                    "engine": "finishes", "name": f"{label} {code}",
                    "qty": round(pq, 1), "unit": unit,
                    "status": "pending review", "page": page_,
                    "sheet": sched_sheet, "csi": csi,
                    "basis": f"{pn} room(s) in review - not taken off "
                             "until they are accepted"})
    if not fs:
        res["problems"].append(
            "finishes: no finish schedule read - floor SF and base LF are "
            "listed for review with their codes unknown")
    pend_ceil = {}
    for rec, room in zip(out["rooms"], rooms):
        if room.get("review") and rec.get("ceiling_sf"):
            c = rec.get("ceiling_code") or rf.UNKNOWN
            pend_ceil[c] = pend_ceil.get(c, 0.0) + rec["ceiling_sf"]
    _gb_ceilings(out, res, sched_sheet, pend_ceil)


# ------------------------------------------------------------- walls
_NO_WALLS = re.compile(r"\b(ROOF|REFLECTED|CEILING|RCP|DEMO(?:LITION)?|"
                       r"ENLARGED|CLEARANCE|ADA|ACCESSIBILITY|"
                       r"LIFE\s+SAFETY|SITE|FRAMING|FOUNDATION|SIGNAGE|"
                       r"KEY\s+PLAN|FURNITURE|EQUIPMENT|FINISH|POWER|"
                       r"LIGHTING)\b", re.I)
_AREA = re.compile(r"\b(?:AREA|PART|ZONE|WING|BUILDING|BLDG|PHASE|POD)\s+"
                   r"([A-Z0-9]{1,3})\b", re.I)
_WALL_TITLE = re.compile(r"\b(?:WALL|PARTITION)\s+(?:TYPES?|LEGEND|"
                         r"ASSEMBL(?:Y|IES))\b", re.I)
_DETAIL_TYPE = re.compile(r"^(?:\d{1,2}\s+)?(?:WALL|PARTITION)\s+TYPE\s+"
                          r"([A-Z]{0,3}-?\d{1,3}[A-Z]{0,2}|[A-Z]{1,2})$",
                          re.I)
_CMU = re.compile(r"\bCMU\b|\bCONC(?:RETE)?\.?\s+MASONRY\b|\bMASONRY\s+"
                  r"UNITS?\b|\bCONC(?:RETE)?\.?\s+BLOCK\b", re.I)
_HT = r"(\d{1,2}\s*'\s*-?\s*\d{0,2}(?:\s+\d/\d{1,2})?\s*\"?)"
_TYPE_HT = re.compile(r"(?:\bH\s*=\s*|\bHEIGHT\s*[:=]?\s*|\bHT\.?\s*[:=]?\s*"
                      r"|\bTO\s+)" + _HT + r"(?:\s*A\.?F\.?F\.?)?", re.I)
_NOTE_HT = re.compile(r"\b(?:WALL|PARTITION)S?\s+HEIGHTS?\s*(?:SHALL\s+BE\s+"
                      r"|ARE\s+|IS\s+|[:=]\s*)?" + _HT, re.I)
_EXT_HT = re.compile(r"\bEXTERIOR\s+WALLS?\s+(?:HEIGHTS?\s*)?(?:SHALL\s+BE\s+"
                     r"|IS\s+|ARE\s+|[:=]\s*)?" + _HT, re.I)
_FT_PER = {"ft": 1.0, "in": 1 / 12.0, "m": 3.28084, "yd": 3.0}


def _level_key(title):
    from . import schedules
    t = title or ""
    m = _AREA.search(t)
    return (schedules.level_of(t), m.group(1).upper() if m else "")


def walls_pages(rows):
    """(pages, [(page left out, page kept)]): the plans the walls engine
    runs on - of the sheets the rooms engine takes off, one per floor
    level (and area: "AREA A"), the best by plan_rank (the floor plan
    before a dimension, enlarged or finish plan), so a floor drawn on
    A-101 and again on A-102 is counted once. Roof, ceiling, demolition,
    framing and similar plans are left out."""
    cand = [r for r in rows if "rooms" in (r.get("engines") or ()) and
            r.get("scale") and r.get("kind", "plan") == "plan"]
    good = [r for r in cand if not _NO_WALLS.search(r.get("title") or "")
            or plan_rank(r) == 0]
    cand = good or cand
    by = {}
    for r in cand:
        by.setdefault(_level_key(r.get("title")), []).append(r)
    # a plan with no level in its title (ADA CLEARANCE PLAN) is the same
    # floor when the set names only one level (Oct 31: its walls were
    # added on top of MAIN LEVEL PLAN's, doubling the exterior wall)
    named = {k for k in by if k[0]}
    if len(named) == 1:
        lvl = next(iter(named))
        for k in [k for k in by if not k[0] and k[1] == lvl[1]]:
            by[lvl] += by.pop(k)
    keep, skipped = [], []
    for rs in by.values():
        rs.sort(key=lambda r: (plan_rank(r), r["page"]))
        keep.append(rs[0]["page"])
        skipped += [(r["page"], rs[0]["page"]) for r in rs[1:]]
    return sorted(keep), sorted(skipped)


def detail_legend(page):
    """{code: description} from wall-type details ("WALL TYPE 1A" under
    each drawn detail, its notes above the title) - a G- / A-sheet of
    wall-type details with no tagged legend."""
    from . import autowalls
    try:
        lines = autowalls._lines_of(page.get_text("words"))
    except Exception:                                    # noqa: BLE001
        return {}
    titles = []
    for rect, text in lines:
        m = _DETAIL_TYPE.match(text.strip())
        if m:
            titles.append((rect, m.group(1).upper()))
    out = {}
    if not titles:
        return out
    desc = {code: [] for _r, code in titles}
    for (x0, y0, x1, y1), text in lines:
        if _DETAIL_TYPE.match(text.strip()):
            continue
        cx = (x0 + x1) / 2
        best = None
        for (tx0, ty0, tx1, ty1), code in titles:
            if not (ty0 - 8 * 72 <= y1 <= ty0 + 2):
                continue
            d = abs(cx - (tx0 + 1.5 * 72))
            if d <= 3 * 72 and (best is None or d < best[0]):
                best = (d, code, y0)
        if best:
            desc[best[1]].append((best[2], text.strip()))
    for code, parts in desc.items():
        out.setdefault(code, " ".join(t for _y, t in sorted(parts))[:400])
    return out


def wall_legend(doc, rows):
    """({code: description}, [pages]) - the wall-type legend of the set:
    a G- or A-sheet titled WALL TYPES / PARTITION TYPES (or carrying that
    heading), read with autowalls.type_legend, or from its wall-type
    details when it has no tagged legend. The first sheet to describe a
    code wins."""
    from . import autowalls
    found = []
    for r in rows:
        if r.get("kind") in ("superseded", "raster"):
            continue
        num = (r.get("number") or "").upper()
        if r.get("discipline") not in ("general", "architectural",
                                       "interiors") and \
                not re.match(r"^[GA]", num):
            continue
        by_title = bool(_WALL_TITLE.search(r.get("title") or ""))
        if not by_title:
            if r.get("kind") == "plan":
                continue                 # a plan's own legend is read there
            try:
                txt = doc[r["page"]].get_text()
            except Exception:                            # noqa: BLE001
                continue
            if not autowalls._WALL_LEGEND.search(txt.upper()):
                continue
        found.append((0 if by_title else 1, r["page"]))
    legend, pages = {}, []
    for _k, p in sorted(found):
        try:
            leg = autowalls.type_legend(doc[p])[0]
        except Exception:                                # noqa: BLE001
            leg = {}
        if not leg:
            leg = detail_legend(doc[p])
        if leg:
            pages.append(p)
            for code, d in leg.items():
                legend.setdefault(str(code).upper(), d)
    return legend, pages


def _feet(s):
    from .room_finishes import parse_feet
    return parse_feet(re.sub(r"\s+", " ", s or "").strip())


def wall_heights(legend, text):
    """{"types": {code: ft}, "all": ft or None, "exterior": ft or None}:
    a type's height from its legend description ("H= 11'-0\"", "HEIGHT
    10'-8\"", "TO 12'-0\" AFF"), a general note ("WALL HEIGHTS: 10'-0\"")
    and an exterior wall height note. Sill, ceiling, base and head heights
    are not wall heights."""
    out = {"types": {}, "all": None, "exterior": None}
    for code, d in (legend or {}).items():
        for m in _TYPE_HT.finditer(d or ""):
            before = (d or "")[max(0, m.start() - 12):m.start()].upper()
            if re.search(r"SILL|CEIL|CLG|BASE|HEAD|WAINSCOT", before):
                continue
            v = _feet(m.group(1))
            if v and 3 <= v <= 40:
                out["types"][code] = v
                break
    t = text or ""
    m = _EXT_HT.search(t)
    if m:
        out["exterior"] = _feet(m.group(1))
    m = _NOTE_HT.search(t)
    if m:
        v = _feet(m.group(1))
        out["all"] = v if v and 3 <= v <= 40 else None
    return out


_MEZZ = re.compile(r"\bMEZZ(?:ANINE)?\b", re.I)
# another floor level named in the same title ("FIRST FLOOR AND MEZZANINE
# PLAN"): the sheet is a floor plan that also shows the mezzanine (H5)
_OTHER_LEVEL = re.compile(
    r"\b(?:FIRST|1ST|GROUND|MAIN|LOWER|UPPER|SECOND|2ND|THIRD|3RD|"
    r"FOURTH|4TH|BASEMENT|CELLAR|LEVEL\s*\d+|FLOOR\s*\d+|L\d)\b", re.I)


def mezzanine_only(title):
    """True when a sheet title names a mezzanine and no other floor level
    ("MEZZANINE PLAN"); False for a combined plan ("FIRST FLOOR AND
    MEZZANINE PLAN") or a title with no mezzanine."""
    t = title or ""
    # 'LEVEL 2 MEZZANINE PLAN' names the mezzanine's own level
    t = re.sub(r"^\s*LEVEL\s*\d+\s+(?=MEZZ)", "", t, flags=re.I)
    # 'MEZZANINE AND ROOF PLAN': another plan shares the sheet
    if re.search(r"(?:\bAND\b|&|/|\+)\s*(?:THE\s+)?(?:ROOF|FLOOR|SITE|"
                 r"FOUNDATION|FRAMING)\b", t, re.I):
        return False
    return bool(_MEZZ.search(t)) and not _OTHER_LEVEL.search(t)


def no_exterior_pages(wall_pages, rows_by_page):
    """Wall sheets whose exterior pass is skipped: mezzanine-only plans,
    when the set has another wall sheet (the floor below, whose outline
    is the same full-height exterior wall)."""
    mezz = {p for p in wall_pages
            if mezzanine_only((rows_by_page.get(p) or {}).get("title"))}
    return mezz if any(p not in mezz for p in wall_pages) else set()


def _opening_keys(res):
    """Keys of the door and window schedules read in this run: the tags
    on the plan that are openings, not wall types."""
    out = set()
    for t in (res.get("schedules") or {}).get("tables") or []:
        if t.get("kind") in ("door", "window") and t.get("key"):
            for r in t.get("rows") or []:
                # its first word: 'D01 MEN'S' when the columns ran together
                k = str(r.get(t["key"]) or "").strip().upper().split()
                if k:
                    out.add(k[0])
    return out


def _walls_sheet(doc, row, legend, leg_pages, res, rows_by_page,
                 exterior=True):
    """One floor plan's walls: LF per wall type (autowalls.wall_types,
    keyed to the set's legend), the exterior wall as the outer face loop
    (wall_roles.find_ex), wall SF where a height is given; flags, classes
    that aren't sure and untagged walls to review."""
    from . import autowalls, wall_roles
    pno = row["page"]
    page = doc[pno]
    name = _sheet_name(rows_by_page, pno)
    _label, ppu, unit = row["scale"]
    sc = {"ppu": ppu, "unit": unit}
    k = _FT_PER.get(unit, 1.0)
    winfo = {}
    ws = autowalls.walls(page, ppu, unit, info=winfo)
    types = autowalls.wall_types(page, ppu, unit, ws=ws,
                                 legend=legend or None,
                                 not_codes=_opening_keys(res))
    leg = types.get("legend") or {}
    text = page.get_text()
    for p in leg_pages:
        try:
            text += "\n" + doc[p].get_text()
        except Exception:                                # noqa: BLE001
            pass
    hts = wall_heights(leg, text)
    cmu = {c for c, d in leg.items() if _CMU.search(d or "")}

    def csi_of(code):
        return "04 22 00" if code in cmu else "09 21 16"

    def review(nm, qty, u, why, csi="09 21 16"):
        res["review"].append({"sheet": name, "page": pno, "name": nm,
                              "qty": qty, "unit": u, "why": why,
                              "engine": "walls", "csi": csi})
    sheet = res["sheets"].setdefault(pno, {})
    tot = {}
    # partitions by type: marks for the typed walls only (untagged walls
    # are for review, not the takeoff)
    typed = [w for w in types["walls"] if w.get("type")]
    for m in autowalls.type_marks(pno, typed, sc):
        meas = m[2]["measure"]
        code = re.sub(r"^Wall Type ", "", meas["group"])
        meas["method"] = "AI takeoff: walls"
        meas["csi"] = csi_of(code)
        res["marks"].append(m)
    for code, b in sorted(types["by_type"].items()):
        lf = (b["lf"] + b["lf_inferred"]) * k
        g = f"Wall Type {code}"
        tot[g] = lf
        h = hts["types"].get(code) or hts["all"]
        if h:
            res["quantities"].append({
                "engine": "walls", "name": f"{g} wall area",
                "qty": round(lf * h, 1), "unit": "SF",
                "status": "taken off", "page": pno, "sheet": name,
                "csi": csi_of(code),
                "basis": f"{lf:,.1f} LF x {h:g} ft high" + (
                    "" if code in hts["types"] else
                    " (wall height note)") + (
                    f"; {b['description'][:60]}" if b.get("description")
                    else "")})
        else:
            review(f"{g} wall area", None, "SF",
                   f"height unknown - {lf:,.1f} LF of {g} taken off, no "
                   "height in the legend or notes for its area",
                   csi_of(code))
    for lab, lf in sorted((types.get("untagged") or {}).items()):
        review(f"{lab} - untagged", round(lf * k, 1), "ft",
               "wall with no wall-type tag - give it a type by hand")
    for f in types.get("flags") or []:
        if f.startswith("walls with no type"):
            continue                   # each untagged class is listed
        review("Wall types", None, "ft", f)
    classes = winfo.get("classes") or []
    for c in classes:
        if not c.get("confident"):
            review(f"{c['label']} walls", round(c["lf"] * k, 1), "ft",
                   "; ".join(c.get("flags") or []) or
                   "thickness class not sure")
    # the exterior wall: the outer face loop
    roles = None
    if not exterior:
        # a mezzanine plan shows the building's outline again: its walls
        # are the full-height exterior walls already taken off below
        res["problems"].append(
            f"walls: {name} is a mezzanine plan - its outline is the "
            "exterior wall already taken off from the floor plan, not "
            "counted again")
    try:
        if exterior:
            roles = wall_roles.find_ex(page, ppu, unit)
    except Exception as e:                               # noqa: BLE001
        log.exception("wall roles on page %d", pno)
        review("Exterior Walls", None, "ft",
               f"exterior wall not found ({e}) - measure it by hand", "")
    if roles is not None:
        ext = roles.get("exterior") or {}
        ext_csi = "04 22 00" if cmu else ""
        if ext.get("outer_face_lf"):
            for m in wall_roles.exterior_marks(pno, ext, sc):
                m[2]["measure"]["method"] = "AI takeoff: walls"
                if ext_csi:
                    m[2]["measure"]["csi"] = ext_csi
                res["marks"].append(m)
            elf = ext["outer_face_lf"] * k
            tot["Exterior Walls"] = elf
            gq = _gross_area_line(ext, k, pno, name, unit)
            if gq:
                res["quantities"].append(gq)
            cmu_h = [hts["types"][c] for c in cmu if c in hts["types"]]
            h = hts["exterior"] or (cmu_h[0] if len(set(cmu_h)) == 1
                                    else None)
            if h:
                res["quantities"].append({
                    "engine": "walls", "name": "Exterior Walls wall area",
                    "qty": round(elf * h, 1), "unit": "SF",
                    "status": "taken off", "page": pno, "sheet": name,
                    "csi": ext_csi,
                    "basis": f"{elf:,.1f} LF outer face x {h:g} ft high"})
            else:
                review("Exterior Walls wall area", None, "SF",
                       f"height unknown - {elf:,.1f} LF of exterior wall "
                       "(outer face) taken off, no height for its area",
                       ext_csi)
        else:
            pieces = (roles.get("summary") or {}).get("Exterior")
            review("Exterior Walls", round(pieces * k, 1) if pieces else None,
                   "ft", "no closed building outline - exterior wall not "
                   "taken off; the exterior wall pieces are listed", ext_csi)
        for f in roles.get("flags") or []:
            if f.startswith("no building outline"):
                continue
            review("Exterior Walls", None, "ft", f, ext_csi)
    sheet["walls"] = {g: _c2(v) for g, v in tot.items()}
    sheet["wall_untagged"] = {lab: _c2(v * k) for lab, v in
                              (types.get("untagged") or {}).items()}
    sheet["wall_classes"] = [{"label": c["label"], "lf": _c2(c["lf"] * k),
                              "assembly": c.get("assembly"),
                              "confident": c.get("confident")}
                             for c in classes]
    sheet["wall_roles"] = {r: _c2(v * k) for r, v in
                           ((roles or {}).get("summary") or {}).items()}
    res["walls"][pno] = {"types": types["by_type"], "legend": leg,
                         "heights": hts, "classes": classes,
                         "exterior": (roles or {}).get("exterior")}


def _gross_area_line(ext, k, pno, name, unit):
    """The gross floor area quantity from the exterior wall's outer face
    loop (wall_roles.exterior_outline "gross_area"), or None."""
    a = (ext or {}).get("gross_area")
    if not a:
        return None
    sf = a * k * k
    n = (ext or {}).get("loops") or 1
    return {"engine": "walls", "name": "Gross floor area",
            "qty": round(sf, 1), "unit": "SF", "status": "taken off",
            "page": pno, "sheet": name, "csi": "",
            "basis": f"area inside the exterior wall outer face loop"
                     f"{'s' if n > 1 else ''} on {name} (to the outside "
                     "face of the exterior walls)"}


# ------------------------------------------------- r34 stage 3 lines
STAGE3_ENGINES = ("envelope", "roof", "site", "earthwork", "landscape")
# an AI-derived line under this confidence is listed for review, not
# taken off
REVIEW_BELOW = 0.6
_ROOF_T = re.compile(r"\bROOF\s+PLAN\b", re.I)
_LAND_T = re.compile(r"\b(LANDSCAP\w*|PLANTING|PLANT\s+LIST|TREE)\b", re.I)
_SITE_T = re.compile(r"\b(SITE|LAYOUT|STAKING|PAVING|DIMENSION\w*)\b", re.I)
_GRADE_T = re.compile(r"\b(GRADING|EARTHWORK|DRAINAGE)\b", re.I)
_ELEV_T = re.compile(r"\b(ELEVATIONS?|SECTIONS?)\b", re.I)
_NOT_PLAN_T = re.compile(r"\b(DETAILS?|NOTES|COVER|INDEX|DEMOLITION|"
                         r"EXISTING\s+CONDITIONS|EROSION)\b", re.I)
_EXT_DOOR = re.compile(r"\b(EXTERIOR|EXT\.?|OUTSIDE)\b", re.I)


def _roof_sheet(title):
    """A roof plan to take the roof off (not a framing plan or details)."""
    t = title or ""
    return bool(_ROOF_T.search(t)) and not _NOT_PLAN_T.search(t) and \
        not re.search(r"\bFRAMING\b", t, re.I)


def _ai_line(res, engine, name, qty, unit, pno, sheet, csi, basis, conf):
    """One AI-derived line: a quantity (ai_derived, confidence, the basis
    saying so) when conf >= REVIEW_BELOW, else a review entry carrying
    the confidence."""
    conf = _c2(float(conf))
    if qty is not None and conf >= REVIEW_BELOW:
        res["quantities"].append({
            "engine": engine, "name": name, "qty": round(float(qty), 1),
            "unit": unit, "status": "taken off", "page": pno,
            "sheet": sheet, "csi": csi, "ai_derived": True,
            "confidence": conf,
            "basis": f"AI-derived (confidence {_c2(conf):.2f}): {basis}"})
    else:
        res["review"].append({
            "sheet": sheet, "page": pno, "name": name,
            "qty": None if qty is None else round(float(qty), 1),
            "unit": unit, "ai_derived": True, "confidence": conf,
            "engine": engine, "csi": csi,
            "why": f"AI-derived, confidence {_c2(conf):.2f} - {basis}; check it"})


def _openings(res):
    """[(w_ft, h_ft)] of doors marked exterior in a confident door
    schedule (FROM/TO/ROOM/LOCATION/TYPE text) and every window of a
    window schedule; None when neither tells."""
    from .room_finishes import parse_feet
    out, told = [], False
    for t in (res.get("schedules") or {}).get("tables") or ():
        if t.get("kind") not in ("door", "window") or not t.get("confident"):
            continue
        for r in t.get("rows") or ():
            w = h = None
            ext = t.get("kind") == "window"
            for k, v in r.items():
                if k.startswith("_") or not v:
                    continue
                ku = k.upper()
                if "WIDTH" in ku or ku.strip() == "W":
                    w = parse_feet(v)
                elif "HEIGHT" in ku or ku.strip() == "H":
                    h = parse_feet(v)
                elif "SIZE" in ku:
                    p = re.split(r"\s*[Xx\u00d7]\s*", str(v))
                    if len(p) >= 2:
                        w, h = w or parse_feet(p[0]), h or parse_feet(p[1])
                if _EXT_DOOR.search(str(v)):
                    ext = True
            if ext and w and h:
                told = True
                q = 1
                for k, v in r.items():
                    if k.upper().strip() in ("QTY", "QTY.", "QUANTITY") and \
                            str(v).strip().isdigit():
                        q = int(str(v).strip())
                out += [(w, h)] * q
    return out if told else None


_INSUL_GLASS = re.compile(r"\b(?:ID|IG|INSUL(?:ATED)?|IGU)\b", re.I)


def _ext_doors(res):
    """[(w_ft, why)] of the exterior doors in a confident door schedule:
    marked EXTERIOR, glazed with insulated glass (only exterior doors get
    it), or sharing a hardware set with one of those (exterior doors get
    their own sets - thresholds, weatherstripping). None when none is
    found."""
    from .room_finishes import parse_feet
    doors = []
    for t in (res.get("schedules") or {}).get("tables") or ():
        if t.get("kind") != "door" or not t.get("confident"):
            continue
        for r in t.get("rows") or ():
            w, hw, ext = None, None, None
            for k, v in r.items():
                if k.startswith("_") or not v:
                    continue
                ku, sv = k.upper(), str(v)
                if "WIDTH" in ku or ku.strip() == "W":
                    w = parse_feet(v)
                elif "HARDWARE" in ku or ku.strip() in ("HW", "HDW"):
                    hw = sv.strip().upper()
                if _EXT_DOOR.search(sv):
                    ext = ext or "marked exterior"
                elif ("GLAZ" in ku or ku.startswith("TYPE ")) and \
                        _INSUL_GLASS.search(sv):
                    ext = ext or "insulated glass"
            if w:
                doors.append([w, hw, ext])
    sets = {d[1] for d in doors if d[2] and d[1]}
    for d in doors:
        if not d[2] and d[1] and d[1] in sets:
            d[2] = f"hardware {d[1].title()}, as the exterior doors"
    out = [(d[0], d[2]) for d in doors if d[2]]
    return out or None


def _page_text(doc, pnos):
    t = []
    for p in pnos:
        try:
            t.append(doc[p].get_text())
        except Exception:                                # noqa: BLE001
            pass
    return "\n".join(t)


def _stage3(doc, rows, res):
    """Envelope / roof / site / earthwork / landscape lines (r34 stage 3)
    from the sheets their titles name; every line AI-derived."""
    from . import envelope, sitework
    named = [r for r in rows if r.get("kind") == "plan" or r.get("scale")]

    def title(r):
        return (r.get("title") or "")
    # ---- roof: scaled roof plans only
    for r in rows:
        if not _roof_sheet(title(r)):
            continue
        pno, nm = r["page"], r["number"] or f"page {r['page'] + 1}"
        if not r.get("scale"):
            _ai_line(res, "roof", "Roof area", None, "SF", pno, nm,
                     "07 00 00", "roof plan has no scale - set it", 0.0)
            continue
        _l, ppu, unit = r["scale"]
        rt = envelope.roof_takeoff(doc[pno], ppu, unit)
        if not rt["by_pitch"]:
            _ai_line(res, "roof", "Roof area", None, "SF", pno, nm,
                     "07 00 00", "no roof plane with a pitch label found",
                     0.0)
            continue
        cf = 0.75 if rt["unlabelled_sf"] < 0.05 * rt["plan_sf"] else 0.6
        _ai_line(res, "roof", "Roof area (plan)", rt["plan_sf"], "SF", pno,
                 nm, "07 00 00", "roof planes on the scaled roof plan, "
                 "horizontal projection", cf)
        for b in rt["by_pitch"]:
            _ai_line(res, "roof", f"Roof area {b['pitch']:g}:12 (sloped)",
                     b["sloped_sf"], "SF", pno, nm, "07 00 00",
                     f"{b['plan_sf']:,.0f} SF plan x slope factor of "
                     f"{b['pitch']:g}:12, planes bounded by the roof "
                     "outline pen on the scaled roof plan", cf)
        _ai_line(res, "roof", "Roof edge (eave + rake)", rt["edge_lf"], "LF",
                 pno, nm, "07 62 00", "outline of the roof planes (plan "
                 "length)", 0.65)
        sub = next((x.get("number") for x in rows
                    if (x.get("discipline") or "") == "architectural" and
                    x.get("kind") != "superseded" and re.search(
                        r"\bSUB-?\s?FASCIA\b", doc[x["page"]].get_text(),
                        re.I)), None)
        if sub:
            _ai_line(res, "roof", "Sub-fascia (roof edge)", rt["edge_lf"],
                     "LF", pno, nm, "06 10 00", "outline of the roof planes "
                     f"(plan length); {sub} details a sub-fascia behind the "
                     "fascia", 0.6)
        if rt.get("eave_lf"):
            _ai_line(res, "roof", "Roof eave (gutter line)", rt["eave_lf"],
                     "LF", pno, nm, "07 71 23", "roof outline less the gable "
                     f"ends ({rt.get('rake_lf', 0):,.1f} LF of rake, plan "
                     "length)", 0.6)
        if rt.get("downspouts"):
            _ai_line(res, "roof", "Downspouts", rt["downspouts"], "EA", pno,
                     nm, "07 71 23", "'DS' tags on the roof plan (each "
                     "downspout's length is its drop to grade - not drawn "
                     "here)", 0.65)
            ep = [x["page"] for x in rows
                  if _ELEV_T.search(f"{x.get('title') or ''}")]
            try:
                hs = [h for h in envelope.wall_heights_from_levels(
                    [doc[q] for q in ep]) if 6 <= h <= 40]
            except Exception:                             # noqa: BLE001
                hs = []
            if hs:
                _ai_line(res, "roof", "Downspouts (length)",
                         rt["downspouts"] * min(hs), "LF", pno, nm,
                         "07 71 23", f"{rt['downspouts']} downspouts x "
                         f"{_c2(min(hs)):.2f} ft (the eave / bearing level on the "
                         "elevations, to the floor) - add the drop below the "
                         "floor to grade and the offsets at the gutter",
                         REVIEW_BELOW - 0.05)
        for key, nmx, csi in (("ridge_lf", "Ridge", "07 62 00"),
                              ("hip_lf", "Hip", "07 62 00"),
                              ("valley_lf", "Valley", "07 62 00"),
                              ("flashing_lf", "Flashing", "07 62 00")):
            if rt[key]:
                _ai_line(res, "roof", f"{nmx} (plan length)", rt[key], "LF",
                         pno, nm, csi, f"line nearest each {nmx.upper()} "
                         "label", 0.6)
    # ---- roof assembly layers from the sections, over the roof plan area
    roof_q = [q for q in res["quantities"] if q.get("engine") == "roof" and
              q.get("name") == "Roof area (plan)"]
    if roof_q:
        rarea = sum(q["qty"] for q in roof_q)
        for r in rows:
            if (r.get("discipline") or "") != "architectural" or \
                    not _ELEV_T.search(title(r)) and \
                    not re.search(r"\bDETAILS?\b", title(r), re.I):
                continue
            lys = [ly for ly in envelope.roof_layers(doc[r["page"]])
                   if ly["layer"] != "ice & water shield"]   # valleys only
            if not lys:
                continue
            nm = r["number"] or f"page {r['page'] + 1}"
            for ly in lys:
                th = ly.get("thickness_in")
                _ai_line(res, "roof", "Roof - " + ly["layer"] +
                         (f" ({th:g} in)" if th else ""), rarea, "SF",
                         r["page"], nm, "07 22 00" if "insul" in ly["layer"]
                         else "07 26 00",
                         f"'{ly['text'][:40]}' beside the roofing in the "
                         f"section on {nm}, over the roof plan area", 0.6)
            break
    # ---- roof deck named on the structural sheets ('1.5B20 METAL DECK'),
    # over the roof plan area (sloped roof planes are not added on top)
    if roof_q:
        rarea = sum(q["qty"] for q in roof_q)
        for r in rows:
            if (r.get("discipline") or "") != "structural":
                continue
            try:
                txt = doc[r["page"]].get_text()
            except Exception:                             # noqa: BLE001
                continue
            m = _DECK.search(txt)
            if not m:
                continue
            nm = r["number"] or f"page {r['page'] + 1}"
            _ai_line(res, "roof", f"Metal roof deck {m.group(1).upper()}",
                     rarea, "SF", r["page"], nm, "05 31 00",
                     f"deck type '{m.group(0).strip()}' on {nm}, over the "
                     "roof plan area (horizontal projection)", 0.6)
            break
    # ---- landscape: plant schedule counts and seed / sod areas
    # plant lines are named like the schedules engine names them
    # ('Plant <key> <description>'); a key it already took off is skipped
    seen_keys = {m.group(1) for q in res["quantities"]
                 for m in [re.match(r"Plant (\S+)", q.get("name") or "")]
                 if m}
    sched_area = False
    for r in rows:
        if not _LAND_T.search(title(r)):
            continue
        pno, nm = r["page"], r["number"] or f"page {r['page'] + 1}"
        for p in sitework.plant_schedule(doc[pno]):
            if p["key"] in seen_keys:
                continue
            seen_keys.add(p["key"])
            sched_area |= p["unit"] == "SF"
            _ai_line(res, "schedules", f"Plant {p['key']}"
                     + (f" {p['desc']}" if p.get("desc") else ""),
                     p["qty"], p["unit"], pno, nm, "32 90 00",
                     "QTY column of the plant schedule (not counted on "
                     "the plan)", 0.7)
    # ---- site: paving, sidewalk, seed / sod, curb
    for r in rows:
        t = title(r)
        if not r.get("scale") or _NOT_PLAN_T.search(t) or not (
                _SITE_T.search(t) or _LAND_T.search(t)) or \
                _ROOF_T.search(t):
            continue
        pno, nm = r["page"], r["number"] or f"page {r['page'] + 1}"
        _l, ppu, unit = r["scale"]
        kinds = None if _SITE_T.search(t) else ("sod / seed",)
        if sched_area:
            # seed / sod areas come from the plant schedule: not twice
            kinds = tuple(k_ for k_, _rx in sitework.SITE_KINDS
                          if k_ != "sod / seed" and (kinds is None or
                                                     k_ in kinds))
            if not kinds:
                continue
        tot = {}
        open_ = {}
        for a in sitework.site_areas(doc[pno], ppu, unit, kinds=kinds,
                                     report_unclosed=True):
            if a["area"] is None:
                open_[a["kind"]] = open_.get(a["kind"], 0) + 1
            else:
                tot[a["kind"]] = tot.get(a["kind"], 0.0) + a["area"]
        csis = {"asphalt paving": "32 12 16", "concrete sidewalk": "32 13 13",
                "concrete paving": "32 13 13", "gravel paving": "32 11 23",
                "sod / seed": "32 92 00"}
        for kd, a in tot.items():
            _ai_line(res, "site", kd.capitalize(), a, "SF", pno, nm,
                     csis[kd], "closed shape around each material label",
                     0.65 if not open_.get(kd) else 0.55)
        for kd, n in open_.items():
            if kd not in tot:
                _ai_line(res, "site", kd.capitalize(), None, "SF", pno, nm,
                         csis[kd], f"{n} label(s) not inside a closed shape",
                         0.0)
        if _SITE_T.search(t):
            cl = sum(c["length"] for c in sitework.curb_lengths(
                doc[pno], ppu, unit))
            if cl:
                _ai_line(res, "site", "Curb", cl, "LF", pno, nm, "32 16 13",
                         "the run each CURB label lies along", 0.6)
    # ---- the pavement section's layers under the asphalt paving: each
    # layer the section detail calls out, over the paved area
    asph = [q for q in res["quantities"] if q.get("engine") == "site" and
            q.get("name") == "Asphalt paving"]
    if asph:
        area = sum(q["qty"] for q in asph)
        conf = min(q.get("confidence", 0.65) for q in asph)
        for r in rows:
            if (r.get("discipline") or "") != "civil" and not \
                    (r.get("number") or "").upper().startswith("C"):
                continue
            layers = sitework.pavement_layers(doc[r["page"]])
            if not layers:
                continue
            nm = r["number"] or f"page {r['page'] + 1}"
            for ly in layers:
                if ly["layer"] == "surface course":
                    continue                  # the paving line itself
                th = ly.get("thickness_in")
                _ai_line(res, "site", "Asphalt paving - " + ly["layer"] +
                         (f" ({th:g} in)" if th else ""), area, "SF",
                         r["page"], nm, "32 12 16",
                         f"'{ly['text'][:40]}' in the pavement section "
                         f"detail on {nm}, over the asphalt paving area",
                         conf)
            break                             # one pavement section
    # ---- earthwork
    for r in rows:
        t = title(r)
        if not _GRADE_T.search(t) or _NOT_PLAN_T.search(t):
            continue
        pno, nm = r["page"], r["number"] or f"page {r['page'] + 1}"
        if not r.get("scale"):
            continue
        _l, ppu, unit = r["scale"]
        ew = sitework.earthwork(doc[pno], ppu, unit)
        if ew["rfi"]:
            res["review"].append({
                "sheet": nm, "page": pno, "name": "Earthwork cut / fill",
                "qty": None, "unit": "CY", "ai_derived": True,
                "confidence": 0.0, "rfi": True,
                "why": f"RFI: {ew['rfi']}"})
            continue
        # cut / fill from a contour grid is a check on the civil engineer's
        # earthwork numbers, not a takeoff to price from (on a real job it
        # came out 34% over on cut and 4x over on fill): always to review
        for k2, nmx in (("cut_cy", "Earthwork cut"),
                        ("fill_cy", "Earthwork fill")):
            _ai_line(res, "earthwork", nmx, ew[k2], "CY", pno, nm,
                     "31 23 16", f"grid between existing and proposed "
                     f"contours over {ew['area_sf']:,.0f} SF - compare with "
                     "the civil engineer's earthwork quantities",
                     min(ew["confidence"], REVIEW_BELOW - 0.05))
        d = sitework.strip_depth_in(doc[pno].get_text())
        if d and ew["area_sf"]:
            _ai_line(res, "earthwork", "Topsoil strip",
                     ew["area_sf"] * d / 12 / 27, "CY", pno, nm, "31 14 13",
                     f"{d:g} in from the notes over the graded area",
                     ew["confidence"])
    # ---- envelope: exterior wall area by system, openings deducted
    ext_lf = sum((sh.get("walls") or {}).get("Exterior Walls", 0.0)
                 for sh in res.get("sheets", {}).values())
    if ext_lf:
        gross = [q for q in res["quantities"]
                 if q.get("name") == "Exterior Walls wall area"]
        h, hs = None, []
        if gross:
            h = sum(q["qty"] for q in gross) / ext_lf
        else:
            ep = [r["page"] for r in rows if _ELEV_T.search(title(r))]
            hs = envelope.wall_heights_from_levels([doc[p] for p in ep])
            h = hs[0] if hs else None
        arch = [r["page"] for r in rows
                if (r.get("discipline") or "") == "architectural"]
        notes = _page_text(doc, arch)
        if h:
            op = _openings(res)
            ev = envelope.wall_envelope(ext_lf, h, op or [], notes,
                                        "Exterior wall")
            cf = ev["confidence"] if op is not None else 0.5
            for ln in ev["lines"]:
                _ai_line(res, "envelope", ln["name"], ln["qty"], "SF", None,
                         "set", "07 20 00" if "insul" in ln["name"] else
                         "07 27 00" if "barrier" in ln["name"] else
                         "04 20 00",
                         f"{ext_lf:,.1f} LF x {_c2(h):.2f} ft - "
                         f"{ev['openings_sf']:,.0f} SF of openings"
                         + ("" if op is not None else
                            " (openings unknown - none deducted)")
                         + (f"; higher wall marks also shown "
                            f"({', '.join(f'{_c2(x):.2f}' for x in hs[1:])} ft) "
                            "- dormer / parapet walls not added"
                            if not gross and len(hs) > 1 else ""), cf)
        else:
            _ai_line(res, "envelope", "Exterior wall - net wall area", None,
                     "SF", None, "set", "04 20 00",
                     f"{ext_lf:,.1f} LF of exterior wall, no height found",
                     0.0)
    _wall_assemblies(doc, rows, res, title)
    if ext_lf:
        _exterior_cmu(doc, rows, res, ext_lf, title)
        _exterior_veneer(res, ext_lf)
        _exterior_inside_face(doc, rows, res, ext_lf, title)
    _slab_on_grade(doc, rows, res)
    _wall_footings(doc, rows, res)
    del named


_SECTION_CMU = re.compile(r"(\d{1,2})\s*(?:\"|'')\s*CMU\b|\bEXT(?:ERIOR)?\s+FACE\s*/\s*"
                          r"CMU\b|\bCMU\s+(?:WALLS?|BACK[-\s]?UP)\b", re.I)
_SECTION_T = re.compile(r"\bSECTIONS?\b|\bDETAILS?\b", re.I)


def _exterior_cmu(doc, rows, res, ext_lf, title):
    """The masonry back-up of the exterior wall, when the exterior wall
    types draw it (joint reinforcement in the wall-type detail) and the
    wall sections name it ('8\" CMU'): the outer wall length times the top
    wall mark on the elevations. The detail doesn't say how high the
    block goes, so it is a line to check, with the other height's
    quantity in its note; the per-type guesses it replaces are dropped."""
    from . import envelope, wall_assembly
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    ext_codes, size = [], None
    for code, d in legend.items():
        comps = wall_assembly.components(d)
        kinds = {c["kind"] for c in comps}
        if kinds & {"siding", "brick", "sheathing"}:
            ext_codes.append(code)
            for c in comps:
                if c["kind"] == "cmu":
                    size = size or c["size_in"]
    if not ext_codes or not size:
        return
    said = []
    for r in rows:
        num = (r.get("number") or "").upper()
        if not num.startswith("A") or not _SECTION_T.search(title(r)):
            continue
        try:
            t = doc[r["page"]].get_text()
        except Exception:                                # noqa: BLE001
            continue
        if any(m.group(1) in (None, str(size))
               for m in _SECTION_CMU.finditer(t)):
            said.append(r.get("number"))
    if not said:
        return
    ep = [r["page"] for r in rows if _ELEV_T.search(title(r))]
    hs = [h for h in envelope.wall_heights_from_levels([doc[p] for p in ep])
          if 6 <= h <= 30]
    # the per-type guesses (an exterior type's inferred block at the plate
    # height) are replaced by this one line
    res["review"] = [x for x in res["review"]
                     if not (x.get("engine") == "assembly" and
                             "CMU" in (x.get("name") or "") and
                             any((x.get("name") or "").startswith(
                                 f"Wall Type {c} - ") for c in ext_codes))]
    if not hs:
        _ai_line(res, "envelope", f"Exterior wall - {size}\" CMU back-up",
                 None, "SF", None, "set", "04 22 00",
                 f"{ext_lf:,.1f} LF of exterior wall; the sections "
                 f"({', '.join(said[:3])}) show {size}\" CMU, no wall "
                 "height on the elevations", 0.0)
        return
    top = max(hs)
    sf = ext_lf * top
    alt = "; ".join(f"at {_c2(h):.2f} ft: {ext_lf * h:,.0f} SF" for h in hs
                    if h != top)
    basis = (f"{ext_lf:,.1f} LF of exterior wall x {_c2(top):.2f} ft (the top "
             f"wall mark on the elevations); the wall-type detail draws the "
             f"block back-up and the sections ({', '.join(said[:3])}) name "
             f"{size}\" CMU - how high the block goes isn't written"
             + (f"; {alt}" if alt else "") + " - openings not deducted")
    _ai_line(res, "envelope", f"Exterior wall - {size}\" CMU back-up", sf,
             "SF", None, "set", "04 22 00", basis, REVIEW_BELOW - 0.05)
    _ai_line(res, "envelope", f"Exterior wall - {size}\" CMU block",
             math.ceil(sf * wall_assembly.CMU_PER_SF), "EA", None, "set",
             "04 22 00", f"{sf:,.0f} SF x {wall_assembly.CMU_PER_SF} block "
             "per SF; " + basis, REVIEW_BELOW - 0.05)


def _exterior_inside_face(doc, rows, res, ext_lf, title):
    """The inside face of the exterior wall when its wall-type detail
    furs it out (7/8" furring channels): furring along the whole outer
    wall at 24" rows up to the bearing height, and the board the furring
    is there to carry - the interior partitions' board (5/8" type X) -
    with its sheets, tape, compound and screws. Furring only exists to
    carry board, so the board is taken off too, its basis saying which
    board was assumed."""
    from . import envelope, wall_assembly as wa
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    fur = board = None
    ext_codes = []
    for code, d in legend.items():
        comps = wa.components(d)
        kinds = {c["kind"] for c in comps}
        if kinds & {"siding", "brick", "sheathing"}:
            ext_codes.append(code)
            for c in comps:
                if c["kind"] == "furring":
                    fur = fur or c["size_in"]
        else:
            for c in comps:
                if c["kind"] == "gwb":
                    board = board or c["thk_in"]
    if not fur:
        return
    ep = [r["page"] for r in rows if _ELEV_T.search(title(r))]
    hs = [h for h in envelope.wall_heights_from_levels([doc[p] for p in ep])
          if 6 <= h <= 30]
    if not hs:
        return
    h = min(hs)                    # the bearing / plate height
    rows_ = h / 2.0
    fs = wa._frac(fur)
    _ai_line(res, "envelope", f"Exterior wall inside face - {fs} metal "
             "furring channels", ext_lf * rows_, "LF", None, "set",
             "09 22 16", f"{ext_lf:,.1f} LF of exterior wall x {_c2(rows_):.2f} "
             f"rows (24\" OC up {_c2(h):.2f} ft, the bearing height); the "
             "wall-type detail draws the furring", 0.62)
    # the exterior types' own furring / board lines (from their tagged
    # length) are the same material: this whole-wall line replaces them
    inner = re.compile(r"furring|gypsum board|joint tape|joint compound|"
                       r"drywall screws|sealant \(top and bottom", re.I)

    def dup(x):
        n = x.get("name") or ""
        return x.get("engine") == "assembly" and inner.search(n) and any(
            n.startswith(f"Wall Type {c} - ") for c in ext_codes)
    res["quantities"] = [x for x in res["quantities"] if not dup(x)]
    res["review"] = [x for x in res["review"] if not dup(x)]
    if not board:
        return
    sf = ext_lf * h
    bs = wa._frac(board)
    why = (f"{ext_lf:,.1f} LF x {_c2(h):.2f} ft; the board on the furring isn't "
           f"named in the exterior wall detail - taken as the partitions' "
           f"{bs} type X; openings not deducted")
    for nm, q, u in (
            (f"{bs} type X gypsum board", sf, "SF"),
            ("gypsum board 4'x8' sheets", math.ceil(sf / wa.SHEET_SF),
             "SHEETS"),
            ("joint tape (500' rolls)",
             math.ceil(sf * wa.TAPE_FT_PER_SF / 500.0), "ROLLS"),
            ("joint compound", math.ceil(sf * wa.COMPOUND_LB_PER_SF), "LB"),
            ("1-1/4\" drywall screws", math.ceil(sf * wa.SCREWS_PER_SF),
             "EA"),
            ("sealant (top and bottom of the board)", 2 * ext_lf, "LF")):
        _ai_line(res, "envelope", f"Exterior wall inside face - {nm}", q, u,
                 None, "set", "09 21 16", why, REVIEW_BELOW)


_THRU_FLASH = re.compile(r"\bTHRU[-\s]*WALL\s+FLASHING\b|\bTHROUGH[-\s]*WALL\s+"
                         r"FLASHING\b", re.I)
_WEEP = re.compile(r"\bWEEPS?\s*@\s*(\d{1,2})\s*(?:\"|'')\s*O\.?\s*C", re.I)
_CAP = re.compile(r"\bPRECAST\s+(?:CONC(?:RETE)?\.?\s+)?(?:SILL|CAP)\b|"
                  r"\bROWLOCK\b", re.I)
_DIM_FT = re.compile(r"(\d{1,2})'\s*-\s*(\d{1,2})(?:\s+\d/\d)?\"")


def _exterior_veneer(res, ext_lf):
    """The brick wainscot of the exterior wall types that draw one (BRICK
    VENEER with its height, 3'-4\"), its cap (precast sill / rowlock) and
    the through-wall flashing at its base, from the outer wall length:
    the flashing runs the full length; the brick and its cap stop at the
    exterior doors."""
    from . import wall_assembly
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    brick_h, flash, cap, weep, angle = None, False, False, None, False
    sill = False
    for code, d in legend.items():
        kinds = {c["kind"] for c in wall_assembly.components(d)}
        if not kinds & {"siding", "brick", "sheathing"}:
            continue
        flash = flash or bool(_THRU_FLASH.search(d))
        if "brick" in kinds:
            cap = cap or bool(_CAP.search(d))
            m = _WEEP.search(d)
            if m and not weep:
                weep = int(m.group(1))
            angle = angle or bool(re.search(r"\bANGLE\b", d))
            # a second flashing in a brick build-up: the one under the cap
            sill = sill or len(re.findall(r"\bFLASHING\b", d, re.I)) >= 2
            for m in _DIM_FT.finditer(d):
                v = int(m.group(1)) + int(m.group(2)) / 12.0
                if 2.0 <= v <= 8.0:
                    brick_h = brick_h or v
                    break
    if flash:
        _ai_line(res, "envelope", "Exterior wall - through-wall flashing",
                 ext_lf, "LF", None, "set", "07 62 00",
                 f"{ext_lf:,.1f} LF of exterior wall (the wall-type "
                 "detail draws through-wall flashing at the base)", 0.62)
    if not brick_h:
        return
    op = _openings(res)
    doors = [w for w, h in (op or []) if h and h >= 6.5]
    dnote = (f"less {len(doors)} exterior door(s) ({sum(doors):,.1f} LF)"
             if op is not None else "exterior doors unknown - none taken out")
    if op is None:
        ed = _ext_doors(res)
        if ed:
            doors = [w for w, _y in ed]
            why = sorted({y for _w, y in ed})
            dnote = (f"less {len(doors)} exterior door(s) "
                     f"({sum(doors):,.1f} LF; exterior from the door "
                     f"schedule: {'; '.join(why)})")
    net = max(0.0, ext_lf - sum(doors))
    hs = f"{int(brick_h)}'-{round((brick_h % 1) * 12)}\""
    _ai_line(res, "envelope", "Exterior wall - brick veneer wainscot",
             net * brick_h, "SF", None, "set", "04 21 13",
             f"{ext_lf:,.1f} LF of exterior wall {dnote} x {hs} (the brick "
             "height drawn in the wall-type detail) - check it against the "
             "elevations (brick on columns or piers isn't added)",
             REVIEW_BELOW - 0.05)
    if cap:
        _ai_line(res, "envelope", "Exterior wall - brick wainscot cap "
                 "(precast sill / rowlock)", net, "LF", None, "set",
                 "04 21 13", f"{ext_lf:,.1f} LF of exterior wall {dnote}",
                 REVIEW_BELOW - 0.05)
    if cap and sill:
        _ai_line(res, "envelope", "Sill flashing under the brick cap", net,
                 "LF", None, "set", "07 62 00",
                 f"{net:,.1f} LF of brick wainscot ({dnote}) - the wall-type "
                 "detail draws a second flashing at the precast sill / cap",
                 REVIEW_BELOW - 0.05)
    if weep and 12 <= weep <= 48:
        n = math.ceil(net / (weep / 12.0))
        _ai_line(res, "envelope", f"Brick weeps @ {weep}\" OC", n, "EA",
                 None, "set", "04 21 13",
                 f"{net:,.1f} LF of brick wainscot ({dnote}) / {weep}\" "
                 "(the spacing drawn in the wall-type detail)", 0.62)
    if angle:
        _ai_line(res, "envelope", "Steel angle at the brick (size per the "
                 "wall detail)", net, "LF", None, "set", "05 50 00",
                 f"{net:,.1f} LF of brick wainscot ({dnote}) - the wall-type "
                 "detail draws an angle at the flashing but no size; check "
                 "the size on the details", REVIEW_BELOW - 0.05)
    area = net * brick_h
    _ai_line(res, "envelope", "Brick ties (spacing not shown - 16\" x 16\" "
             "used)", math.ceil(area / (16 * 16 / 144.0)), "EA", None, "set",
             "04 05 19", f"{area:,.1f} SF of brick wainscot at one tie per "
             "1.78 SF (16\" OC each way, the usual spacing) - the drawings "
             "don't give the tie spacing; check the spec", REVIEW_BELOW - 0.1)


_SOG = re.compile(r"(\d{1,2})\s*(?:\"|'')\s*(?:THICK\s+)?(?:CONC(?:RETE)?\.?\s+)?"
                  r"SLAB[-\s]+ON[-\s]+GRADE", re.I)
_SOG_BASE = re.compile(r"(\d{1,2})\s*(?:\"|''|IN\.?)\s*(?:THICK\s+|MIN\.?\s+)?"
                       r"(?:LAYER\s+OF\s+)?(?:COMPACTED\s+)?"
                       r"(GRADED\s+AGGREGATE\s+BASE|G\.?A\.?B\.?|#\s*57\s+STONE|"
                       r"CRUSHED\s+STONE|AGGREGATE\s+BASE(?:\s+COURSE)?|"
                       r"GRANULAR\s+(?:FILL|BASE)|ABC\b)", re.I)
_WWF = re.compile(r"(\d{1,2}\s*[xX]\s*\d{1,2}\s*[-\s]?\s*W\s*\d(?:\.\d)?\s*[xX]"
                  r"\s*W\s*\d(?:\.\d)?)", re.I)


_FT_IN = r"(\d{1,2})'\s*-?\s*(\d{1,2})\"?"
_STRIP = [re.compile(_FT_IN + r"\s*WIDE\s*[xX]\s*" + _FT_IN +
                     r"\s*DEEP\s+(?:WALL|CONT|STRIP)", re.I),
          re.compile(_FT_IN + r"\s*DEEP\s*[xX]\s*" + _FT_IN +
                     r"\s*WIDE\s+(?:WALL|CONT|STRIP)", re.I)]
_STRIP_BARS = re.compile(r"\((\d)\)\s*#(\d)'?S?\s*CONT\.?\s*\(" + _FT_IN +
                         r"\s*WIDE\)", re.I)


def _wall_footings(doc, rows, res):
    """The continuous wall footing the foundation plan names ('2'-0" WIDE
    x 1'-0" DEEP WALL FOOTING') under the exterior walls and the CMU
    walls, with its continuous bars from the sections ('(2) #5's CONT
    (2'-0" WIDE)'). For review: its length is taken from the walls above
    it, not traced on the foundation plan."""
    from . import structural, wall_assembly
    size = bars = None
    sheet = None
    for r in rows:
        if (r.get("discipline") or "") != "structural":
            continue
        try:
            txt = re.sub(r"\s+", " ", doc[r["page"]].get_text())
        except Exception:                                 # noqa: BLE001
            continue
        if size is None:
            for i, rx in enumerate(_STRIP):
                m = rx.search(txt)
                if m:
                    a = int(m.group(1)) + int(m.group(2)) / 12.0
                    b = int(m.group(3)) + int(m.group(4)) / 12.0
                    size = (a, b) if i == 0 else (b, a)      # (wide, deep)
                    sheet = r.get("number") or f"page {r['page'] + 1}"
                    break
        for m in _STRIP_BARS.finditer(txt):
            w = int(m.group(3)) + int(m.group(4)) / 12.0
            if size and abs(w - size[0]) < 0.01:
                bars = (int(m.group(1)), int(m.group(2)))
    if not size:
        return
    ext = sum((sh.get("walls") or {}).get("Exterior Walls", 0.0)
              for sh in (res.get("sheets") or {}).values())
    legend = {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
    cmu = 0.0
    for sh in (res.get("sheets") or {}).values():
        for g, v in (sh.get("walls") or {}).items():
            m = re.match(r"Wall Type (\S+)$", g)
            if m and any(c["kind"] == "cmu" and not c.get("inferred")
                         for c in wall_assembly.components(
                             legend.get(m.group(1), ""))):
                cmu += v
    L = ext + cmu
    if not L:
        return
    wide, deep = size
    cy = L * wide * deep / 27.0
    basis = (f"{L:,.0f} LF ({ext:,.0f} LF exterior walls + {cmu:,.0f} LF "
             f"CMU walls) x {wide:g}' wide x {deep:g}' deep, footing named "
             f"on {sheet} - check the length on the foundation plan")
    cf = REVIEW_BELOW - 0.05
    _ai_line(res, "footings", f"Wall footing {wide:g}' x {deep:g}'", cy,
             "CY", None, sheet, "03 30 00", basis, cf)
    if bars:
        n, bar = bars
        lb = n * L * structural.BAR_LB_FT.get(bar, 0.0)
        _ai_line(res, "footings", f"Wall footing rebar #{bar} continuous",
                 lb, "LB", None, sheet, "03 21 00",
                 f"({n}) #{bar} continuous x {L:,.0f} LF x "
                 f"{structural.BAR_LB_FT.get(bar, 0.0)} lb/ft (laps not "
                 "added); " + basis, cf)


def _slab_on_grade(doc, rows, res):
    """The slab on grade named on the foundation plan ('4\" SLAB-ON-GRADE
    w/ 6x6 W2.9xW2.9 WWF'): slab, concrete, WWF and vapor barrier over the
    room areas on the floor plan - listed for review (the slab plan's own
    outline, thickened edges and exterior slabs are not measured)."""
    thk = wwf = base = None
    vb = False
    sheet = None
    for r in rows:
        if (r.get("discipline") or "") != "structural":
            continue
        try:
            txt = re.sub(r"\s+", " ", doc[r["page"]].get_text())
        except Exception:                                 # noqa: BLE001
            continue
        m = _SOG.search(txt)
        w = _WWF.search(txt)
        # the plan callout that names the slab and its WWF together first
        if m and (thk is None or (w and not wwf)):
            thk = int(m.group(1))
            sheet = r.get("number") or f"page {r['page'] + 1}"
            wwf = re.sub(r"\s+", "", w.group(1)).upper() if w else wwf
        if re.search(r"\bVAPOU?R\s+(?:BARRIER|RETARDER)\b", txt, re.I):
            vb = True
        for b in _SOG_BASE.finditer(txt):
            pre = txt[max(0, b.start() - 2):b.start()]
            if not base and 2 <= int(b.group(1)) <= 24 and "-" not in pre \
                    and "'" not in pre:
                base = (int(b.group(1)), b.group(2).strip().upper())
    if not thk:
        return
    area = totals(res).get("rooms_sf") or 0.0
    if not area:
        return
    cf = REVIEW_BELOW - 0.05
    why = (f"{area:,.0f} SF of rooms on the floor plan (slab named on "
           f"{sheet}) - check against the slab plan: wall footprints, "
           "thickened edges and exterior slabs are not in it")
    _ai_line(res, "slab", f'Slab on grade {thk}"', round(area, 1), "SF",
             None, sheet, "03 30 00", why, cf)
    _ai_line(res, "slab", f'Slab on grade {thk}" - concrete',
             round(area * thk / 12.0 / 27.0, 1), "CY", None, sheet,
             "03 30 00", f"{area:,.0f} SF x {thk} in / 27; " + why, cf)
    if wwf:
        _ai_line(res, "slab", f"Slab on grade - WWF {wwf}", round(area, 1),
                 "SF", None, sheet, "03 21 00", why, cf)
    if vb:
        _ai_line(res, "slab", "Slab on grade - vapor barrier", round(area, 1),
                 "SF", None, sheet, "07 26 00", why, cf)
    if base:
        _ai_line(res, "slab", f"Slab on grade - {base[0]}\" {base[1].lower()}",
                 _c2(area * base[0] / 12.0 / 27.0), "CY", None, sheet,
                 "31 23 23", f"{area:,.0f} SF x {base[0]} in / 27 (the base "
                 "under the slab named on the structural notes); " + why, cf)


def _wall_assemblies(doc, rows, res, title):
    """Each wall type's materials (wall_assembly) from its legend text, its
    LF over the floor plans, and its height: the legend's / notes' height
    for the type, else the top-of-wall mark on the elevations."""
    from . import envelope, wall_assembly
    lfs, legend, hts = {}, {}, {}
    for w in (res.get("walls") or {}).values():
        legend.update(w.get("legend") or {})
        hts.update((w.get("heights") or {}).get("types") or {})
    for sh in (res.get("sheets") or {}).values():
        for g, v in (sh.get("walls") or {}).items():
            m = re.match(r"Wall Type (\S+)$", g)
            if m:
                lfs[m.group(1)] = lfs.get(m.group(1), 0.0) + v
    if not lfs:
        return
    plate = None
    ep = [r["page"] for r in rows if _ELEV_T.search(title(r))]
    if ep:
        hs = envelope.wall_heights_from_levels([doc[p] for p in ep])
        plate = hs[0] if hs else None
    for code, lf in sorted(lfs.items()):
        comps = wall_assembly.components(legend.get(code, ""))
        h = hts.get(code) or plate
        if not comps:
            continue
        if not h:
            _ai_line(res, "assembly", f"Wall Type {code} - materials", None,
                     "LF", None, "set", "09 21 16",
                     f"{lf:,.1f} LF; no wall height in the legend, notes or "
                     "elevations", 0.0)
            continue
        src = "legend / notes" if hts.get(code) else \
            "top-of-wall mark on the elevations"
        for ln in wall_assembly.lines(code, lf, h, comps):
            _ai_line(res, "assembly", ln["name"], ln["qty"], ln["unit"],
                     None, "set", "09 21 16" if "CMU" not in ln["name"]
                     else "04 22 00",
                     f"{ln['basis']}; height from the {src}",
                     REVIEW_BELOW - 0.05 if ln.get("review") else 0.6)


# ------------------------------------------------------------- run
@_full_glyph_boxes
def run(doc, rows, progress=None, engines=None, sheet_time_limit=None,
        device_time_limit=None):
    """Take off every sheet in `rows` (from plan_set; rows with no engines
    are skipped). Returns {"marks": [(page, kind, payload)], "scales":
    [(page, label, ppu, unit)] to set first, "assemblies": {name:
    assembly} for the job, "sheets": {page: {engine: summary}},
    "problems": [text], "existing": [{sheet, page, name, length, unit,
    source}] (existing work: listed, never in the totals), "review":
    [{sheet, page, name, qty, unit, why}] (found but not measured with
    confidence: not taken off, for a person), "unfinished": [{sheet,
    page, engine, why}] (work not done - nothing is dropped unseen),
    "rooms_dup": [(room, kept page, [pages])], "timing": {text: s},
    "quantities": [{engine, name, qty, unit, status, page, sheet, csi,
    basis}] (quantities that are not marks: steel LB, footing CY),
    "schedules": schedules.takeoff() result, "steel_dup": [...],
    "finishes": room_finishes() result or None, "walls": {page: {types,
    legend, heights, classes, exterior}}}. Finish lines (engine
    'finishes') and wall areas (engine 'walls', SF) are in "quantities";
    wall LF are marks ("Wall Type <code>", "Exterior Walls").

    Each sheet's room finding stops after `sheet_time_limit` seconds
    (SHEET_TIME_LIMIT) and device counting after `device_time_limit`
    (DEVICE_TIME_LIMIT); what didn't finish is in "unfinished"."""
    import time as _time
    from . import autotakeoff, civiltakeoff, tradetakeoff as tt
    from . import autocount
    sheet_limit = SHEET_TIME_LIMIT if sheet_time_limit is None \
        else sheet_time_limit
    dev_limit = DEVICE_TIME_LIMIT if device_time_limit is None \
        else device_time_limit
    res = {"marks": [], "scales": [], "assemblies": {}, "sheets": {},
           "problems": [], "existing": [], "review": [], "unfinished": [],
           "rooms_dup": [], "timing": {}, "quantities": [],
           "schedules": None, "steel_dup": [], "finishes": None,
           "walls": {}}
    rows_by_page = {r["page"]: r for r in rows}
    _grade_scales(doc, rows, res)
    todo = [r for r in rows if r["engines"]]
    steps = sum(len([e for e in r["engines"] if e not in SET_ENGINES])
                for r in todo)
    for e in SET_ENGINES:
        steps += any(e in r["engines"] for r in todo)
    if engines is None or "walls" in engines:
        steps += bool(walls_pages(todo)[0])
    steps = steps or 1
    k = 0
    done = set()                        # (page, engine) finished

    def tick(text):
        nonlocal k
        k += 1
        if progress:
            return progress(k, steps, text)
        return True

    def stopped():
        res["problems"].append("Stopped before the end.")
        for r in todo:
            for e in r["engines"]:
                if (r["page"], e) not in done and \
                        (engines is None or e in engines):
                    res["unfinished"].append({
                        "sheet": r["number"] or f"page {r['page'] + 1}",
                        "page": r["page"], "engine": e,
                        "why": "stopped before it was reached"})
        for p in wall_pages:
            if (p, "walls") not in done:
                res["unfinished"].append({
                    "sheet": _sheet_name(rows_by_page, p), "page": p,
                    "engine": "walls",
                    "why": "stopped before it was reached"})
        if room_kept and res.get("finishes") is None:
            res["unfinished"].append({
                "sheet": "finish schedule", "page": None,
                "engine": "finishes",
                "why": "stopped before the finishes were taken off"})
        return res
    for r in rows:
        if r["scale_from"] == "read" and r["scale"]:
            label, ppu, unit = r["scale"]
            res["scales"].append((r["page"], label, ppu, unit))
    civil_pages = []
    device_pages = []
    schedule_pages = []
    steel_found = {}
    room_found, room_missed = {}, {}
    room_kept = {}
    # walls: one floor plan per floor level (of the sheets the rooms
    # engine takes off), run once the sheets are done
    want_walls = engines is None or "walls" in engines
    wall_pages, wall_skipped = walls_pages(todo) if want_walls else ([], [])
    halt = False
    for r in todo:
        if halt:
            break
        pno = r["page"]
        if "schedules" in r["engines"] and (engines is None or
                                            "schedules" in engines):
            schedule_pages.append(pno)
        if not r["scale"]:
            continue                     # schedules only: no scale needed
        label, ppu, unit = r["scale"]
        sc = {"ppu": ppu, "unit": unit}
        sheet = res["sheets"].setdefault(pno, {})
        name = r["number"] or f"page {pno + 1}"
        for eng in r["engines"]:
            if engines is not None and eng not in engines:
                continue
            if eng == "schedules":
                continue
            if eng not in SET_ENGINES:
                if tick(f"{name}: {ENGINE_NAMES.get(eng, eng)}") is False:
                    stopped()
                    halt = True
                    break
            t0 = _time.perf_counter()
            try:
                if eng == "rooms":
                    over = []

                    def room_prog(i, n, t0=t0, over=over):
                        if sheet_limit and \
                                _time.perf_counter() - t0 > sheet_limit:
                            over.append(True)
                            return False
                        return True
                    rinfo = {}
                    found, missed = autotakeoff.all_rooms(
                        doc[pno], sc, progress=room_prog,
                        budget_s=sheet_limit or None, info=rinfo)
                    if over or rinfo.get("stopped"):
                        why = rinfo.get("why") or "time limit"
                        part = len(rinfo.get("partial") or [])
                        res["unfinished"].append({
                            "sheet": name, "page": pno, "engine": "rooms",
                            "why": f"time limit ({sheet_limit:g} s; {why})"
                                   + (f", {part} room(s) traced before it "
                                      "stopped, not checked" if part else "")
                                   + " - run Auto Rooms on this sheet by "
                                   "hand"})
                        res["problems"].append(
                            f"{name}: rooms not finished in "
                            f"{sheet_limit:g} s - not taken off; run "
                            "Auto Rooms on it by hand")
                        continue
                    if rinfo.get("overlaps"):
                        res["problems"].append(
                            f"{name}: {rinfo['overlaps']} pair(s) of room "
                            "traces overlap - both rooms of each pair sent "
                            "to review")
                    from . import settings
                    if autotakeoff.scale_looks_wrong(found):
                        res["problems"].append(
                            f"{name}: rooms measure about "
                            f"{_c2(autotakeoff.scale_ratio(found)):.2f}x their "
                            "tagged areas - the sheet scale looks wrong")
                    elif settings.get("rooms_use_tag_area", True):
                        n_tag = autotakeoff.prefer_tags(found)
                        if n_tag:
                            res["problems"].append(
                                f"{name}: {n_tag} room(s) used the area in "
                                "the room tag (trace more than 5% off)")
                    room_found[pno] = found
                    room_missed[pno] = missed
                elif eng == "civil":
                    civil_pages.append(pno)
                    continue
                elif eng == "pipes":
                    systems = tt.mep_runs(doc[pno], ppu, unit)
                    chosen = [g for g in systems if g["suggested"]]
                    res["marks"] += [
                        (p, kind, dict(pl, measure=dict(
                            pl["measure"], method="AI takeoff: pipe runs")))
                        for p, kind, pl in tt.run_marks(pno, chosen, unit)]
                    # one size can come from several line styles (solid
                    # and dashed): add them up, never overwrite
                    pipes = {}
                    for g in chosen:
                        pipes[g["name"]] = pipes.get(g["name"], 0.0) + \
                            g["length"]
                    sheet["pipes"] = pipes
                    try:
                        from . import fittings
                        fc = fittings.count(chosen, tt._per_ft(ppu, unit))
                        acc = res.setdefault("_fittings", {})
                        for kk, n in fc.items():
                            e = acc.setdefault(kk, [0, []])
                            e[0] += n
                            if name not in e[1]:
                                e[1].append(name)
                    except Exception:                    # noqa: BLE001
                        log.info("fittings on %s", name, exc_info=True)
                    _pipe_drops(doc[pno], pno, name, unit, res)
                    orph = [g for g in systems if g.get("orphan")]
                    if orph:
                        res["problems"].append(
                            f"{name}: size tag(s) with no pipe line at them "
                            "- not taken off: " + ", ".join(
                                f"{g['name']} ({g['orphan']})"
                                for g in orph[:8]))
                    for g in systems:
                        if not g["labelled"]:
                            continue
                        if g.get("orphan"):
                            res["review"].append({
                                "sheet": name, "page": pno,
                                "name": g["name"], "qty": None,
                                "unit": unit, "why": g["flag"]})
                        elif g.get("existing"):
                            res["existing"].append({
                                "sheet": name, "page": pno,
                                "name": g["name"], "length": g["length"],
                                "unit": unit, "source": "pipe runs"})
                        elif g.get("flag"):
                            res["review"].append({
                                "sheet": name, "page": pno,
                                "name": g["name"], "qty": g["length"],
                                "unit": unit, "why": g["flag"]})
                            res["problems"].append(
                                f"{name}: {g['name']} not taken off - "
                                f"{g['flag']}")
                elif eng == "devices":
                    device_pages.append(pno)
                    continue
                elif eng == "ducts":
                    _ducts(doc, pno, name, ppu, unit, res, sheet)
                elif eng == "steel":
                    steel_found[pno] = _steel_sheet(doc, pno, ppu, unit,
                                                    rows)
                done.add((pno, eng))
            except Exception as e:                 # one sheet never stops
                log.exception("AI takeoff %s on page %d", eng, pno)
                res["problems"].append(f"{name}: {eng} failed ({e})")
                res["unfinished"].append({"sheet": name, "page": pno,
                                          "engine": eng,
                                          "why": f"failed ({e})"})
            finally:
                if eng not in SET_ENGINES:
                    res["timing"][f"{name} {eng}"] = _c2(
                        _time.perf_counter() - t0)
    _fitting_lines(res)
    # rooms: each room once, from its floor plan
    if room_found:
        kept, dups = dedupe_rooms(room_found, rows_by_page)
        res["rooms_dup"] = dups
        kept_all = [r for rs in kept.values() for r in rs]

        def taken(t):
            num, words = room_key(t.get("name"))
            for x in kept_all:
                xn, xw = room_key(x.get("name"))
                if num and num == xn or not num and words and words == xw:
                    return True
            return False
        # a tag not found anywhere is reported once, on its best plan;
        # one taken off from another sheet isn't missing at all
        miss_at = {}
        for pno in sorted(room_missed, key=lambda q: (
                plan_rank(rows_by_page.get(q, {})), q)):
            for t in room_missed[pno]:
                if taken(t):
                    continue
                num, words = room_key(t.get("name"))
                key = num or " ".join(sorted(words))
                if key and key in miss_at and miss_at[key] != pno:
                    continue
                if key:
                    miss_at[key] = pno
                miss_at.setdefault(("page", pno), []).append(t)
        room_kept = kept
        for pno, found in kept.items():
            name = _sheet_name(rows_by_page, pno)
            res["marks"] += _room_marks(doc, pno, found)
            # rooms the tracer isn't sure of (tag disagrees, overlaps,
            # holds another tag...): measured, and listed for a person -
            # once, from the sheet each room is taken off
            for x in found:
                if x.get("review"):
                    res["review"].append({
                        "sheet": name, "page": pno,
                        "name": x.get("name") or "Room",
                        "qty": x.get("net_sf", x.get("sqft")),
                        "unit": "sq ft",
                        "why": "; ".join(x.get("flags") or []) or
                               "room trace not sure",
                        "engine": "rooms", "csi": "09 00 00",
                        "confidence": x.get("trace_confidence")})
            missed = miss_at.get(("page", pno), [])
            # rooms in review are not in the total until accepted (Jon,
            # Oct 31): their own pending subtotal
            sure = [x for x in found if not x.get("review")]
            res["sheets"].setdefault(pno, {})["rooms"] = {
                "found": len(sure), "missed": len(missed),
                "sf": sum(x["sqft"] for x in sure),
                "pending": len(found) - len(sure),
                "pending_sf": sum(x["sqft"] for x in found
                                  if x.get("review")),
                "repeats": len(room_found[pno]) - len(found)}
            if missed:
                res["problems"].append(
                    f"{name}: {len(missed)} room(s) not found - "
                    + ", ".join(t.get("name") or "?" for t in missed[:6]))
        if dups:
            by_kept = {}
            for room, kp, pages in dups:
                by_kept.setdefault(kp, set()).update(pages)
            for kp, pages in sorted(by_kept.items()):
                n = sum(1 for _r, k2, _p in dups if k2 == kp)
                res["problems"].append(
                    f"{n} room(s) also shown on " + ", ".join(
                        _sheet_name(rows_by_page, p) for p in sorted(pages))
                    + f" - taken off once, from "
                    f"{_sheet_name(rows_by_page, kp)}")
    if halt:
        if steel_found:
            _steel_done(doc, steel_found, rows_by_page, res)
        if room_kept:
            res["unfinished"].append({
                "sheet": "finish schedule", "page": None,
                "engine": "finishes",
                "why": "stopped before the finishes were taken off"})
        return res
    if civil_pages:
        if tick("civil takeoff across the set") is False:
            return stopped()
        t0 = _time.time()
        scales = {r["page"]: (r["scale"][1], r["scale"][2])
                  for r in todo if r["page"] in civil_pages}
        try:
            # pipe is shown again on layout, erosion-control and
            # grading sheets: take it from the utility plans when the
            # set has them
            pp, msg = civil_pipe_pages(doc, civil_pages, rows_by_page)
            if pp:
                if msg:
                    res["problems"].append(msg)
                civil_pages = pp

            def civ(i, n, text):
                return progress(k, steps, text) if progress else True
            try:
                cres = civiltakeoff.takeoff(doc, civil_pages, scales,
                                            progress=civ)
            except civiltakeoff.Stopped:
                return stopped()
            unit = next(iter(scales.values()))[1]
            for msg in civil_same_pipe(cres, rows_by_page):
                res["problems"].append(msg)
            new = [p for p in cres["pipes"] if not p["existing"]]
            ms = civiltakeoff.marks(cres, unit, pipes=new)
            for m in ms:
                m[2]["measure"]["method"] = "AI takeoff: civil"
            res["marks"] += ms
            res["assemblies"].update(civiltakeoff.assemblies_for(cres))
            res["civil"] = cres
            for p in new:
                for rr in p["runs"]:
                    res["sheets"].setdefault(rr["page"], {}).setdefault(
                        "civil pipe", {}).setdefault(p["name"], 0.0)
                    res["sheets"][rr["page"]]["civil pipe"][
                        p["name"]] += rr["length"]
            # existing utilities: listed, never in the new-work totals
            for p in cres["pipes"]:
                if not p["existing"]:
                    continue
                for pg in sorted(set(rr["page"] for rr in p["runs"])):
                    res["existing"].append({
                        "sheet": _sheet_name(rows_by_page, pg), "page": pg,
                        "name": p["name"], "length": sum(
                            rr["length"] for rr in p["runs"]
                            if rr["page"] == pg),
                        "unit": unit, "source": "civil"})
            res["problems"] += cres.get("checks", [])
            # water service fittings from callouts that state a count
            for sv in cres.get("services") or []:
                pg = sv["pages"][0]
                res["quantities"].append({
                    "engine": "civil", "name": sv["name"][:1].upper() +
                    sv["name"][1:], "qty": sv["qty"], "unit": "EA",
                    "status": "taken off", "page": pg,
                    "sheet": _sheet_name(rows_by_page, pg), "csi": "33 10 00",
                    "basis": f"{sv['qty']} in the callout(s) '" +
                             "'; '".join(t[:60] for t in sv["texts"][:3]) +
                             "'" + (" - size from the tap above it in the "
                                    "same callout stack"
                                    if sv.get("size_from_tap") else "")})
            nostr = [s for s in cres["structures"]
                     if not s["existing"] and s["depth"] is None]
            if nostr:
                res["problems"].append(
                    f"{len(nostr)} structure(s) without rim/invert "
                    "elevations - priced at 8 ft deep: " +
                    ", ".join(s["id"] for s in nostr[:8]))
            for pg in civil_pages:
                done.add((pg, "civil"))
        except Exception as e:
            log.exception("AI takeoff civil")
            res["problems"].append(f"Civil takeoff failed ({e})")
            for pg in civil_pages:
                res["unfinished"].append({
                    "sheet": _sheet_name(rows_by_page, pg), "page": pg,
                    "engine": "civil", "why": f"failed ({e})"})
        res["timing"]["civil"] = _c2(_time.time() - t0)
    if device_pages:
        if tick("fixtures & devices from the legends") is False:
            return stopped()
        t0 = _time.time()

        def sub(k, n, name):
            return progress(steps, steps, f"Counting \"{name[:40]}\" "
                            f"({k + 1} of {n})") if progress else True
        try:
            rep = {}
            # the floor plans and life safety plans: fire extinguishers and
            # the like are drawn there, not on the trade sheets (Nov 1)
            plan_pages = [r["page"] for r in rows
                          if "rooms" in (r.get("engines") or []) or
                          tt._LIFE_SAFETY_PLAN.search(r.get("title") or "")]
            found = tt.legend_counts(
                doc, device_pages, progress=sub, time_limit=dev_limit,
                report=rep, disciplines={r["page"]: r.get("discipline", "")
                                         for r in rows},
                titles={r["page"]: r.get("title") or "" for r in rows},
                pictures=picture_count_on(), plan_pages=plan_pages)
            for f in found:
                ok_pages = set(device_pages)
                if tt.life_safety_device(f["name"]):
                    ok_pages |= set(plan_pages)
                hits = [h for h in f["hits"] if h["page"] in ok_pages]
                hits, again = _one_sheet_per_level(hits, rows_by_page,
                                                   f["name"])
                if again:
                    res["review"].append({
                        "sheet": ", ".join(_sheet_name(rows_by_page, p)
                                           for p in again),
                        "page": next(iter(again)), "name": f["name"],
                        "qty": sum(again.values()), "unit": "ea",
                        "engine": "devices",
                        "why": "the same symbol is drawn on another plan of "
                               "the same floor - counted once, from the "
                               "plan that shows the most of them"})
                for h in hits:
                    h["method"] = "AI takeoff: devices"
                res["marks"] += autocount.count_marks(hits, f["name"], doc)
                for h in hits:
                    res["sheets"].setdefault(h["page"], {}).setdefault(
                        "devices", {}).setdefault(f["name"], 0)
                    res["sheets"][h["page"]]["devices"][f["name"]] += 1
            left = rep.get("not_counted") or []
            if left:
                res["problems"].append(
                    f"{len(left)} legend symbol(s) not counted - " +
                    "; ".join(f"{n[:30]} ({why})" for n, why in left[:6]) +
                    " - count them with Count Symbols / Count by Label")
                for n, why in left:
                    res["unfinished"].append({
                        "sheet": "legend", "page": None,
                        "engine": "devices", "why": f"{n}: {why}"})
            rej = rep.get("rejected") or []
            if rej:
                res["problems"].append(
                    f"{len(rej)} legend line(s) with a symbol were not "
                    "read as devices (a note, a list or a long "
                    "description) - check: " +
                    "; ".join(t[:40] for _p, t, _w in rej[:5]))
                for pg, t, why in rej:
                    if _legend_note(t):
                        continue          # a note line, a size or a ref
                    res["review"].append({
                        "sheet": _sheet_name(rows_by_page, pg), "page": pg,
                        "name": t[:80], "qty": None, "unit": "ea",
                        "why": f"legend line not counted: {why}"})
            for pg in device_pages:
                done.add((pg, "devices"))
        except Exception as e:
            log.exception("AI takeoff devices")
            res["problems"].append(f"Device counts failed ({e})")
            for pg in device_pages:
                res["unfinished"].append({
                    "sheet": _sheet_name(rows_by_page, pg), "page": pg,
                    "engine": "devices", "why": f"failed ({e})"})
        res["timing"]["devices"] = _c2(_time.time() - t0)
    if schedule_pages:
        if tick("schedules and their keys on the plans") is False:
            return stopped()
        t0 = _time.time()
        try:
            _schedules(doc, rows, schedule_pages, res)
            for pg in schedule_pages:
                done.add((pg, "schedules"))
        except Exception as e:                           # noqa: BLE001
            log.exception("AI takeoff schedules")
            res["problems"].append(f"Schedules failed ({e})")
            for pg in schedule_pages:
                res["unfinished"].append({
                    "sheet": _sheet_name(rows_by_page, pg), "page": pg,
                    "engine": "schedules", "why": f"failed ({e})"})
        res["timing"]["schedules"] = _c2(_time.time() - t0)
    # walls by type and the exterior wall loop, one floor plan per level
    if wall_pages:
        if tick("walls by type and the exterior wall") is False:
            return stopped()
        t0 = _time.time()
        for p, kp in wall_skipped:
            res["problems"].append(
                f"walls: {_sheet_name(rows_by_page, p)} shows the same "
                f"floor as {_sheet_name(rows_by_page, kp)} - walls taken "
                f"from {_sheet_name(rows_by_page, kp)} only")
        legend, leg_pages = wall_legend(doc, rows)
        no_ext = no_exterior_pages(wall_pages, rows_by_page)
        for p in wall_pages:
            nm = _sheet_name(rows_by_page, p)
            t1 = _time.perf_counter()
            try:
                _walls_sheet(doc, rows_by_page[p], legend, leg_pages, res,
                             rows_by_page,
                             exterior=p not in no_ext)
                done.add((p, "walls"))
            except Exception as e:                       # noqa: BLE001
                log.exception("AI takeoff walls on page %d", p)
                res["problems"].append(f"{nm}: walls failed ({e})")
                res["unfinished"].append({"sheet": nm, "page": p,
                                          "engine": "walls",
                                          "why": f"failed ({e})"})
            res["timing"][f"{nm} walls"] = _c2(_time.perf_counter() - t1)
        res["timing"]["walls"] = _c2(_time.time() - t0)
    # finishes: floor / base / ceiling / wall paint from the rooms kept
    # (each room once) and the finish schedule
    if room_kept:
        try:
            _finishes(room_kept, res, rows_by_page,
                      paint_h=_paint_height(doc, rows, res),
                      act_grid=_act_grid(doc, rows))
        except Exception as e:                           # noqa: BLE001
            log.exception("AI takeoff finishes")
            res["problems"].append(f"Finishes failed ({e})")
            res["unfinished"].append({"sheet": "finish schedule",
                                      "page": None, "engine": "finishes",
                                      "why": f"failed ({e})"})
    # r34 stage 3: envelope, roof, site, earthwork, landscape - lines
    # labelled AI-derived with a confidence; low ones go to review
    if engines is None or any(e in engines for e in STAGE3_ENGINES):
        t1 = _time.time()
        try:
            _stage3(doc, rows, res)
        except Exception as e:                           # noqa: BLE001
            log.exception("AI takeoff envelope/site")
            res["problems"].append(f"Envelope / site takeoff failed ({e})")
        try:
            _silt_fence(doc, rows, res)
        except Exception:                                # noqa: BLE001
            log.info("silt fence", exc_info=True)
        try:
            _parking(doc, rows, res)
        except Exception:                                # noqa: BLE001
            log.info("parking", exc_info=True)
        res["timing"]["envelope/site"] = _c2(_time.time() - t1)
    # steel: each member once across the S plans (3c C3, N10), column
    # heights from a column schedule when the set has one
    if steel_found:
        _steel_done(doc, steel_found, rows_by_page, res)
    _devices_in_schedules(res)
    _panel_names(res)
    try:
        door_finish_lines(res)
    except Exception:                                    # noqa: BLE001
        log.info("door finishes", exc_info=True)
    try:
        window_head_lines(res)
    except Exception:                                    # noqa: BLE001
        log.info("window heads", exc_info=True)
    # an independent check: quantities worked out a second way
    try:
        from . import crosscheck
        crosscheck.run(res)
    except Exception:                                    # noqa: BLE001
        log.info("cross-check", exc_info=True)
    try:
        scale_review(rows, res)
    except Exception:                                    # noqa: BLE001
        log.info("scale review", exc_info=True)
    mark_sources(rows, res)
    return res


def mark_sources(rows, res):
    """Every CHECK item and quantity says whether its sheet is vector
    linework or a scan ("source"), so review can treat scans as less sure
    and accuracy can be told apart for the two."""
    src = {r["page"]: r.get("source") or (
        "scan" if r.get("raster") or r.get("kind") == "raster" else
        "vector") for r in rows}
    for key in ("review", "quantities"):
        for x in res.get(key) or ():
            if isinstance(x, dict) and "source" not in x:
                p = x.get("page")
                if p in src:
                    x["source"] = src[p]
    return res


def skip_repeats(doc, marks):
    """(marks to add, how many left out): an AI measurement already on its
    page from an earlier run - same item, same label, same place - isn't
    added a second time (Oct 31: running AI Takeoff again doubled every
    quantity). Labelled shapes match on label and box; wall lines (no
    label) on their item and end points, within REPEAT_PT. Nothing already
    on the drawing is changed."""
    from . import annotate
    have = {}
    pages = {p for p, _k, _pl in marks if isinstance(p, int) and
             0 <= p < doc.page_count}
    for p in pages:
        got = []
        for a in annotate.iter_annots(doc[p]):
            info = a.info or {}
            subj = str(info.get("subject", ""))
            if not subj.startswith(annotate.TAKEOFF):
                continue
            parts = subj.split(":")
            group = ":".join(parts[4:]) if len(parts) > 4 else ""
            r = a.rect
            if a.type[1] == "FreeText":          # a count's number
                c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                got.append(("", group, (r.x0, r.y0, r.x1, r.y1), [c]))
                continue
            got.append((str(info.get("content") or ""), group,
                        (r.x0, r.y0, r.x1, r.y1),
                        [tuple(v) for v in (a.vertices or [])]))
        have[p] = got

    def near(a, b):
        return len(a) == len(b) and all(
            abs(x0 - x1) <= REPEAT_PT and abs(y0 - y1) <= REPEAT_PT
            for (x0, y0), (x1, y1) in zip(a, b))
    kept, dropped = [], 0
    for m in marks:
        p, kind, pl = m
        pts = pl.get("pts") if isinstance(pl, dict) else None
        if not pts and isinstance(pl, dict) and kind == "add_count" and \
                pl.get("pt"):
            pts = [pl["pt"]]                   # a count: its number's centre
        hit = False
        if have.get(p) and pts:
            label = str(pl.get("label") or "")
            group = str((pl.get("measure") or {}).get("group") or "")
            verts = [(float(q[0]), float(q[1])) for q in pts]
            xs = [q[0] for q in verts]
            ys = [q[1] for q in verts]
            r = (min(xs), min(ys), max(xs), max(ys))
            for lab, grp, rc, vs in have[p]:
                if label:
                    if lab == label and (all(
                            abs(a - b) <= REPEAT_PT for a, b in zip(rc, r))
                            or near(vs, verts)):
                        hit = True
                        break
                elif group and grp == group and near(vs, verts):
                    hit = True
                    break
        if hit:
            dropped += 1
            continue
        kept.append(m)
    return kept, dropped


REPEAT_PT = 3.0          # how close a repeat's points are, page points


def strip_ai_marks(doc):
    """Take the AI's own measurements off `doc` (the engines' working
    copy, never the open drawing): a run reads the drawing as drawn, so a
    second run finds the same things and skip_repeats() can leave them
    out. A person's measurements stay (rooms they measured are still
    skipped). Returns how many were taken off."""
    from . import annotate
    n = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        tags = set()
        for a in annotate.iter_annots(page):
            subj = str((a.info or {}).get("subject", ""))
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue
            method = str(annotate.audit_of(doc, a).get("method") or "")
            if method.startswith("AI takeoff"):
                tag = annotate.tag_of(a)
                if tag:
                    tags.add(tag)
        for tag in tags:
            if annotate.apply_op(doc, annotate.new_op(
                    "delete_annot", pno, target=tag)):
                n += 1
    return n


_LEG_NOTE = re.compile(
    r"^\s*(?:[\d\s/\"'.,x-]+(?:IN\.?)?\s*(?:TO\s*[\d\s/\"'.-]+(?:IN\.?)?)?"
    r"|\(?\s*SEE\b.*|.*\bhttps?://.*|.*\.\s*|U\.N\.O.*|.*\bTYP\.?\s*"
    r"(?:U\.?N\.?O\.?)?\)?)\s*$", re.I)


def _legend_note(t):
    """A legend line that is not an item to count or check: a sentence of
    a note, a bare size or number ('1 1/2\"', '4'), a reference ('(SEE
    DETAIL)', 'SEE PLAN') or a web address."""
    t = (t or "").strip()
    if not t or _LEG_NOTE.match(t):
        return True
    words = re.findall(r"[A-Za-z]+", t)
    return len(words) >= 9 and "," in t


# the plan a device belongs on, by its name: a fire alarm device is
# counted on the fire alarm plan when the floor has one (the power plan
# shows the panel again where it is fed)
_PLAN_FOR = (
    (re.compile(r"FIRE\s*ALARM|SMOKE|HEAT\s+DET|PULL\s+STATION|HORN|"
                r"STROBE|ANNUNCIATOR|FACP", re.I),
     re.compile(r"FIRE\s*ALARM", re.I)),
    (re.compile(r"OUTLET|RECEPTACLE|DATA|TELE|MOTOR|DISCONNECT|JUNCTION",
                re.I),
     re.compile(r"POWER", re.I)),
    (re.compile(r"LIGHT|FIXTURE|LUMINAIRE|EXIT\s+SIGN|OCCUPANCY|VACANCY|"
                r"SWITCH|DIMMER", re.I),
     re.compile(r"LIGHTING", re.I)),
)


def _home_plan(name, titles):
    """Of the plans of one level ({page: title}), the pages that are the
    natural home of the device `name`, or [] when none is."""
    for dev, plan in _PLAN_FOR:
        if dev.search(name or ""):
            return [p for p, t in titles.items() if plan.search(t or "")]
    return []


def _fitting_lines(res):
    """Elbows and tees per system and size, counted from the pipe layout
    (fittings.count) - offered for review: drops and risers drawn as
    circles, and fittings under text, aren't seen."""
    from . import fittings
    dacc = res.pop("_duct_fittings", None) or {}
    for key, (n, sheets) in sorted(dacc.items(), key=lambda kv: str(kv[0])):
        nm = fittings.duct_names({key: n})[0][0]
        _ai_line(res, "fittings", nm, n, "EA", None, "/".join(sheets[:3]),
                 "23 31 00",
                 f"{n} counted from the drawn ductwork on "
                 f"{', '.join(sheets[:3])} (turns, size changes and branches "
                 "of the duct runs; flex connections one per flex run-out)",
                 REVIEW_BELOW - 0.05)
    acc = res.pop("_fittings", None) or {}
    for (sys_, size, kind, br), (n, sheets) in sorted(
            acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2],
                                         kv[0][3] or 0)):
        nm = fittings.names({(sys_, size, kind, br): n})[0][0]
        _ai_line(res, "fittings", nm, n, "EA", None,
                 "/".join(sheets[:3]), "22 13 16" if sys_ != "water"
                 else "22 11 16",
                 f"{n} counted from the drawn {sys_} piping on "
                 f"{', '.join(sheets[:3])} (corners and branches of the "
                 "pipe lines; drops and risers drawn as circles not seen)",
                 REVIEW_BELOW - 0.05)


def _other_scales(page):
    """Per-foot of the detail scales printed on the sheet (autotakeoff.
    detail_scales) - their views' dimensions are not this scale's."""
    from . import autotakeoff, tradetakeoff as tt
    try:
        return sorted({round(tt._per_ft(ppu, unit), 4) for _pt, ppu, unit,
                       _l in autotakeoff.detail_scales(page)})
    except Exception:                                    # noqa: BLE001
        return []


def _grade_scales(doc, rows, res):
    """Each sheet to take off has its scale graded against its own printed
    dimensions (scalecheck) before anything is measured: grade F (they
    measure well off their values at this scale) stops the sheet - every
    quantity on it would be wrong - and says why; A / B / not graded go
    ahead, B with a note. res["scale_grades"] = {sheet: grade record}."""
    from . import scalecheck, settings, tradetakeoff as tt
    if not settings.get("scale_check", True):
        return
    out = res.setdefault("scale_grades", {})
    measuring = {"rooms", "pipes", "ducts", "civil", "steel", "walls"}
    for r in rows:
        if not r.get("scale") or not measuring & set(r.get("engines") or ()):
            continue                     # schedules, counts: no scale used
        _l, ppu, unit = r["scale"]
        try:
            g = scalecheck.grade(doc[r["page"]], tt._per_ft(ppu, unit),
                                 others=_other_scales(doc[r["page"]]))
        except Exception:                                # noqa: BLE001
            log.info("scale check on page %s", r["page"], exc_info=True)
            continue
        name = r.get("number") or f"page {r['page'] + 1}"
        out[name] = {k: g[k] for k in ("grade", "ratio", "n", "why")}
        if g["grade"] == "F":
            res["unfinished"].append({
                "sheet": name, "page": r["page"],
                "engine": ", ".join(r["engines"]),
                "why": f"scale check failed: {g['why']} - set the scale, "
                       "then run again"})
            res["problems"].append(f"{name}: not taken off - scale check "
                                   f"failed: {g['why']}")
            r["engines"] = []
        elif g["grade"] == "B":
            res["problems"].append(f"{name}: scale check: {g['why']}")


def _one_sheet_per_level(hits, rows_by_page, name=""):
    """A device drawn on two different plans of one floor (the fire alarm
    panel on the power plan and on the fire alarm plan) is one device: per
    level, the plan with the most hits of the symbol keeps them; on another
    kind of plan of that level, a hit at the same spot is dropped. Plans
    with the same title (two areas of one floor) are counted in full.
    Returns (hits kept, {page: hits dropped})."""
    from . import schedules
    by_page = {}
    for h in hits:
        by_page.setdefault(h["page"], []).append(h)
    if len(by_page) < 2:
        return hits, {}

    def title(p):
        return re.sub(r"[^A-Z]+", " ", ((rows_by_page.get(p) or {})
                                         .get("title") or "").upper()).strip()

    def spot(h):
        r = h["rect"]
        return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2,
                max(r[2] - r[0], r[3] - r[1], 4.0))

    by_lv = {}
    for p, hs in by_page.items():
        by_lv.setdefault(schedules.level_of(
            (rows_by_page.get(p) or {}).get("title") or ""), []).append((p, hs))
    keep, drop = [], {}
    for lv, lst in by_lv.items():
        home = _home_plan(name, {p: (rows_by_page.get(p) or {}).get("title")
                                 for p, _hs in lst})
        if home and len(home) < len(lst):
            for p, hs in lst:
                if p in home:
                    keep += hs
                else:
                    drop[p] = len(hs)
            continue
        lst.sort(key=lambda x: (-len(x[1]), x[0]))
        base_t = title(lst[0][0])
        base = [spot(h) for h in lst[0][1]]
        keep += lst[0][1]
        for p, hs in lst[1:]:
            if title(p) == base_t:
                keep += hs
                continue
            n = 0
            for h in hs:
                cx, cy, sz = spot(h)
                if any(abs(cx - bx) <= sz and abs(cy - by) <= sz
                       for bx, by, _s in base):
                    n += 1
                else:
                    keep.append(h)
            if n:
                drop[p] = n
    return keep, drop


_DEV_WORDS = re.compile(r"\b(EXIT|EMERGENCY|OCCUPANCY|VACANCY|DOWN\s*LIGHT|"
                        r"WALL\s*PACK|SCONCE|TROFFER|STRIP)\b", re.I)


def _panel_names(res):
    """Panelboards whose schedules are headed by name ('PANEL LP1') on an
    electrical schedule sheet but whose circuit tables aren't text: one
    each, the breakers left for the estimator to count off the schedule."""
    sch = res.get("schedules") or {}
    names = sch.get("panel_names") or {}
    done = {str(r.get("PANEL") or "").upper()
            for t in sch.get("tables") or () if t.get("kind") == "panel"
            for r in t.get("rows") or ()}
    n = 0
    for nm, (p, sheet) in sorted(names.items()):
        if nm in done:
            continue
        _ai_line(res, "schedules", f"Panel {nm}", 1, "EA", p, sheet,
                 "26 24 16", f"panel schedule headed 'PANEL {nm}' on "
                 f"{sheet}; its circuit table is drawn, not text - count "
                 "the breakers off the schedule", 0.62)
        n += 1
    if n:
        res["review"].append({
            "sheet": ", ".join(sorted({v[1] for v in names.values()})),
            "page": next(iter(names.values()))[0],
            "name": "Panel breakers", "qty": None, "unit": "EA",
            "engine": "schedules", "csi": "26 24 16",
            "why": f"{n} panel schedule(s) whose circuits aren't text - "
                   "count the breakers by size and poles off the schedule"})
    return n


def _devices_in_schedules(res):
    """A legend symbol for a thing the fixture schedule already counts by
    its tag ('CEILING / WALL MOUNTED EXIT SIGN' and light type X 'EXIT
    SIGN') is one item: the legend count goes to review, the schedule
    count stands."""
    lines = (res.get("schedules") or {}).get("lines") or []
    descs = " | ".join(ln.get("name", "") for ln in lines
                       if ln.get("kind") == "light fixtures" and
                       ln.get("status") == "taken off").upper()
    if not descs:
        return
    moved = {}
    keep = []
    for mk in res.get("marks") or ():
        m = (mk[2] or {}).get("measure") or {}
        g = m.get("group") or ""
        if m.get("method") == "AI takeoff: devices":
            w = _DEV_WORDS.search(g)
            if w and re.search(r"\b" + re.escape(w.group(1).upper()) +
                               r"\b", descs):
                moved[g] = moved.get(g, 0) + 1
                continue
        keep.append(mk)
    if not moved:
        return
    res["marks"] = keep
    for g, n in moved.items():
        res["review"].append({
            "sheet": "legend", "page": None, "name": g, "qty": n,
            "unit": "ea", "engine": "devices", "csi": "26 51 00",
            "why": "the light fixture schedule counts this by its tag - "
                   "the legend count isn't added again"})


def _steel_done(doc, steel_found, rows_by_page, res):
    from . import structural
    try:
        tabs = [t for t in (res.get("schedules") or {}).get("tables", [])
                if t["kind"] == "column"]
        if tabs:
            for g in steel_found.values():
                for m in g["members"]:
                    if m["kind"] == "column" and not m["length"]:
                        m["length"] = structural._height_table(m["name"],
                                                               tabs)
                        if m["length"]:
                            m["why"] = ""
        _steel_set(doc, steel_found, rows_by_page, res)
    except Exception as e:                               # noqa: BLE001
        log.exception("AI takeoff steel")
        res["problems"].append(f"Steel takeoff failed ({e})")


def picture_count_on():
    """The 'picture_count' setting: counting a symbol by matching its
    picture (a raster template) - on unless turned off. A switch kept for
    the patent design rules (see tests/test_patent_design_rules.py): with
    it off, symbols are counted only from vector shapes, letters and tags,
    never from a picture."""
    try:
        from . import settings
        return bool(settings.get("picture_count", True))
    except Exception:                                    # noqa: BLE001
        return True


# a quantity line measured but held for a person: not in the totals,
# in the pending-review subtotal
PENDING_STATUS = ("review", "pending review")


def totals(res):
    """Set totals: {"rooms_sf", "rooms", "pipe": {name: length},
    "structures": {kind: count}, "devices": {name: count}, "existing":
    {name: length} (not part of the other totals), "schedules": {name:
    count}, "ducts": {name: length}, "steel": {name: count}, "quantities":
    {(name, unit): qty} (steel LB, footing CY), "finishes": {(name, unit):
    qty} (floor SF / base LF / ceiling SF / wall finish SF per code),
    "walls": {(name, unit): qty} (LF per wall type and of the exterior
    wall, ft; SF where a height was given), "pending": {(name, unit): qty}
    (measured but in review - rooms not sure, finishes of those rooms, a
    gross area the cross-check doubts - not in any total above)}."""
    out = {"rooms_sf": 0.0, "rooms": 0, "pipe": {}, "structures": {},
           "devices": {}, "existing": {}, "schedules": {}, "ducts": {},
           "steel": {}, "quantities": {}, "finishes": {}, "walls": {},
           "pending": {}}
    pend = out["pending"]
    for sh in res["sheets"].values():
        if sh.get("scale_review"):
            # scale to check (scale_review): lengths and areas wait
            if "rooms" in sh and sh["rooms"].get("sf"):
                k = (SCALE_HOLD, "SF")
                pend[k] = pend.get(k, 0.0) + sh["rooms"]["sf"]
            if sh.get("rooms", {}).get("pending"):
                k = ("Rooms in review", "SF")
                pend[k] = pend.get(k, 0.0) + sh["rooms"]["pending_sf"]
            for key in ("walls", "pipes", "civil pipe", "ducts"):
                for n, v in (sh.get(key) or {}).items():
                    k = (n, "LF")
                    pend[k] = pend.get(k, 0.0) + v
            for n, v in (sh.get("devices") or {}).items():
                out["devices"][n] = out["devices"].get(n, 0) + v
            for key in ("schedules", "steel"):
                for n, v in (sh.get(key) or {}).items():
                    out[key][n] = out[key].get(n, 0) + v
            continue
        if "rooms" in sh:
            out["rooms_sf"] += sh["rooms"]["sf"]
            out["rooms"] += sh["rooms"]["found"]
            if sh["rooms"].get("pending"):
                k = ("Rooms in review", "SF")
                pend[k] = pend.get(k, 0.0) + sh["rooms"]["pending_sf"]
        for n, v in (sh.get("walls") or {}).items():
            out["walls"][(n, "LF")] = out["walls"].get((n, "LF"), 0.0) + v
        for key in ("pipes", "civil pipe"):
            for n, v in (sh.get(key) or {}).items():
                out["pipe"][n] = out["pipe"].get(n, 0.0) + v
        for n, v in (sh.get("devices") or {}).items():
            out["devices"][n] = out["devices"].get(n, 0) + v
        for key in ("schedules", "ducts", "steel"):
            for n, v in (sh.get(key) or {}).items():
                out[key][n] = out[key].get(n, 0) + v
    for q in res.get("quantities") or []:
        if q.get("status") in PENDING_STATUS and \
                isinstance(q.get("qty"), (int, float)):
            k = (q["name"], q["unit"])
            pend[k] = pend.get(k, 0.0) + q["qty"]
            continue
        if q.get("status") != "taken off":
            continue
        if q["engine"] in ("finishes", "walls"):
            k = (q["name"], q["unit"])
            d = out[q["engine"]]
        else:
            k = (f"{q['engine']}: {q['name']}", q["unit"])
            d = out["quantities"]
        d[k] = d.get(k, 0.0) + q["qty"]
    for s in (res.get("civil") or {}).get("structures", []):
        if not s["existing"]:
            out["structures"][s["kind"]] = \
                out["structures"].get(s["kind"], 0) + 1
    for e in res.get("existing") or []:
        out["existing"][e["name"]] = out["existing"].get(e["name"], 0.0) + \
            e["length"]
    return out


def summary_text(rows, res, unit="ft"):
    t = totals(res)
    took = sum(1 for r in rows if r["engines"])
    lines = [f"AI Takeoff read {len(rows)} sheet(s) and took off {took}."]
    if t["rooms"]:
        lines.append(f"Rooms: {t['rooms']} rooms, {t['rooms_sf']:,.0f} SF.")
    if t["pending"]:
        lines.append("Pending review (not in the totals until accepted in "
                     "Check Takeoff):")
        lines += [f"   {n}: {v:,.0f} {u}" for (n, u), v in
                  sorted(t["pending"].items())]
    if t["finishes"]:
        lines.append("Finishes (rooms x finish schedule):")
        order = {"Floor": 0, "Base": 1, "Ceiling": 2, "Wall": 3}
        lines += [f"   {n}: {v:,.0f} {u}" for (n, u), v in
                  sorted(t["finishes"].items(), key=lambda kv: (
                      order.get(kv[0][0].split()[0], 9), kv[0][0]))]
    if t["walls"]:
        lines.append("Walls (one floor plan per level):")
        lines += [f"   {n}: {v:,.0f} {u}" for (n, u), v in
                  sorted(t["walls"].items(), key=lambda kv: (
                      kv[0][1] != "LF", kv[0][0]))]
    if t["pipe"]:
        lines.append("Pipe:")
        lines += [f"   {n}: {v:,.0f} {unit}" for n, v in
                  sorted(t["pipe"].items(), key=lambda kv: -kv[1])]
    if t["structures"]:
        lines.append("Structures: " + ", ".join(
            f"{v} {k}{'s' if v != 1 else ''}" for k, v in
            sorted(t["structures"].items())))
    if t["devices"]:
        lines.append("Fixtures & devices:")
        lines += [f"   {n}: {v}" for n, v in
                  sorted(t["devices"].items(), key=lambda kv: -kv[1])]
    if t["schedules"]:
        lines.append("From the schedules (keys counted on the plans):")
        lines += [f"   {n}: {v}" for n, v in sorted(t["schedules"].items())]
    if t["ducts"]:
        lines.append("Ductwork:")
        lines += [f"   {n}: {v:,.0f} {unit}" for n, v in
                  sorted(t["ducts"].items(), key=lambda kv: -kv[1])]
    if t["steel"]:
        lines.append("Steel members (count):")
        lines += [f"   {n}: {v}" for n, v in sorted(t["steel"].items())]
    if t["quantities"]:
        lines.append("Weights and volumes:")
        lines += [f"   {n}: {v:,.1f} {u}" for (n, u), v in
                  sorted(t["quantities"].items())]
    if t["existing"]:
        lines.append("\nExisting work (listed only - not in the totals):")
        lines += [f"   {n}: {v:,.0f} {unit}" for n, v in
                  sorted(t["existing"].items(), key=lambda kv: -kv[1])]
    sup = [r for r in rows if r.get("kind") == "superseded"]
    if sup:
        lines.append(f"\nSuperseded / duplicate sheets, not taken off "
                     f"({len(sup)}):")
        lines += [f"   p.{r['page'] + 1} {r['number']}: {r['note']}"
                  for r in sup[:15]]
    warn = [r for r in rows if r.get("dup_warning")]
    if warn:
        lines.append("Sheet numbers to check:")
        lines += [f"   p.{r['page'] + 1}: {r['dup_warning']}"
                  for r in warn[:10]]
    skipped = [r for r in rows if r["kind"] == "plan" and
               any(e not in r["engines"] for e in r["wanted"])]
    raster = [r for r in rows if r.get("kind") == "raster"]
    if rows:
        nv = sum(1 for r in rows if (r.get("source") or "vector") ==
                 "vector" and r.get("kind") != "raster")
        lines.append(f"Sheets: {nv} vector, {len(rows) - nv} scanned "
                     "(scans are measured by hand and checked more "
                     "closely).")
    if raster:
        lines.append(f"\nRaster sheets, measure by hand ({len(raster)}): " +
                     ", ".join(r["number"] or f"p.{r['page'] + 1}"
                               for r in raster[:15]))
        low = [r for r in raster if r.get("dpi") and r["dpi"] < LOW_DPI]
        if low:
            lines.append(f"   Scanned under {LOW_DPI} DPI ({len(low)}): " +
                         ", ".join(f"{r['number'] or 'p.%d' % (r['page'] + 1)}"
                                   f" ({r['dpi']} DPI)" for r in low[:15]))
    if skipped:
        lines.append(f"\nNeeds a scale first ({len(skipped)}): " + ", ".join(
            r["number"] or f"p.{r['page'] + 1}" for r in skipped[:15]))
    rev = [x for x in res.get("review") or [] if x.get("qty") is not None
           and isinstance(x.get("qty"), (int, float))]
    if rev:
        from . import review as _rv
        rev = sorted(rev, key=lambda x: (_rv.is_repeat(x), _rv.score(x)))
        lines.append("\nFound but not measured with confidence - not taken "
                     "off, check by hand (least sure first):")
        lines += [f"   {x['sheet']}: {x['name']} ({x['qty']:,.0f} "
                  f"{x['unit']}) - score {_rv.score(x)}/100 - {x['why']}"
                  for x in rev[:15]]
    gone = [d for d in res.get("decisions") or ()
            if d.get("action") in ("deleted", "missed")]
    if gone:
        lines.append(f"\nRemoved or missed in review ({len(gone)}):")
        for d in gone[:20]:
            what = ("missed" if d["action"] == "missed" else
                    "deleted" + (f" ({d['reason']})" if d.get("reason")
                                 else ""))
            q = d.get("qty") if d["action"] == "missed" else \
                d.get("qty_found")
            qs = (f", {q:,.0f} {d.get('unit') or ''}".rstrip()
                  if isinstance(q, (int, float)) else "")
            lines.append(f"   {d.get('sheet') or '-'}: {d.get('name')} - "
                         f"{what}{qs}")
    unf = res.get("unfinished") or []
    if unf:
        lines.append(f"\nNot finished ({len(unf)}):")
        lines += [f"   {u['sheet']} {u['engine']}: {u['why']}"
                  for u in unf[:20]]
    if res["problems"]:
        lines.append("\nCheck these:")
        lines += [f"   {p}" for p in res["problems"][:30]]
    lines.append("\nEvery quantity is an ordinary measurement marked "
                 "'AI takeoff' - step through them with Check Takeoff.")
    return "\n".join(lines)


def narrative(rows, res):
    """A short scope narrative from the local AI model, or '' when it
    isn't running."""
    try:
        from .ai import review
    except Exception:
        return ""
    t = totals(res)
    sheets = "; ".join(f"{r['number']} {r['title']} ({r['discipline']})"
                       for r in rows[:60] if r["number"] or r["title"])
    prompt = (
        "You are a construction estimator. From this drawing set and its "
        "automatic quantities, write a short scope-of-work summary (5-8 "
        "bullet points) and list anything an estimator should check by "
        "hand. Be concrete; don't invent quantities.\n\n"
        f"Sheets: {sheets}\n\nQuantities: {t}\n\nProblems: "
        f"{res['problems'][:15]}")
    try:
        return review._ollama(prompt).strip()
    except Exception as e:
        log.info("no AI narrative: %s", e)
        return ""


# ------------------------------------------------------------- specs
_PIPE_NAME = re.compile(r'^(\d+(?:[- ]\d/\d)?|\d/\d)"\s+([A-Z]{1,4})'
                        r'(?:\s+drops)?$')
_DUCT_NAME = re.compile(r'^(?:(\d{1,2})"\s+round|(\d{1,2})x(\d{1,2}))$')


def _sz(t):
    t = t.strip()
    m = re.match(r"^(\d+)[- ](\d)/(\d)$", t)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r"^(\d)/(\d)$", t)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(t)


def spec_quantities(res, spec):
    """What the specifications add to the takeoff (an estimator reads the
    project manual where the drawings stop):
      res["materials"] {line name: 'material (Spec 22 11 16)'} for pipe
        and duct lines the drawings name only by size and system;
      pipe insulation (LF by material and thickness) from the plumbing
        insulation schedule over the pipe taken off;
      duct insulation (SF) from the duct insulation schedule over the
        duct surface taken off - for review, since exhaust ducts are not
        wrapped and the plans don't always say which run is exhaust.
    `spec` is a spec_materials.Spec. Returns the number of lines added."""
    if spec is None:
        return 0
    pipes, ducts = {}, {}
    for _p, _k, pl in res.get("marks") or ():
        m = pl.get("measure") or {}
        g = m.get("group") or ""
        meth = m.get("method") or ""
        if meth == "AI takeoff: pipe runs" and _PIPE_NAME.match(g):
            pipes[g] = pipes.get(g, 0.0) + float(m.get("value") or 0)
        elif meth == "AI takeoff: ducts" and _DUCT_NAME.match(g):
            ducts[g] = ducts.get(g, 0.0) + float(m.get("value") or 0)
    for q in res.get("quantities") or ():
        if q.get("engine") == "pipe drops" and _PIPE_NAME.match(q["name"]) \
                and q.get("status", "taken off") == "taken off":
            pipes[q["name"]] = pipes.get(q["name"], 0.0) + q["qty"]
    mats = res.setdefault("materials", {})
    res["spec_sections"] = {n: v["title"] for n, v in spec.sections.items()}
    added = 0
    ins = {}
    for name, lf in sorted(pipes.items()):
        m = _PIPE_NAME.match(name)
        size, sysc = _sz(m.group(1)), m.group(2)
        pm = spec.pipe_material(sysc, size)
        if pm:
            mats[name] = f"{pm[0]} (Spec {_fmt_sec(pm[1])})"
        pi = spec.pipe_insulation(sysc, size)
        if pi:
            k = (pi[0], pi[1], pi[2])
            rec = ins.setdefault(k, {"lf": 0.0, "pipes": []})
            rec["lf"] += lf
            rec["pipes"].append(f"{name} {lf:,.0f} LF")
    for (mat, thk, sec), rec in sorted(ins.items(), key=lambda kv: kv[0][1]):
        _ai_line(res, "spec", f'Pipe insulation - {mat}, {thk:g}" thick',
                 rec["lf"], "LF", None, "spec", "22 07 19",
                 f"Spec {_fmt_sec(sec)} insulation schedule over the pipe "
                 f"taken off: {'; '.join(rec['pipes'][:8])}", 0.65)
        added += 1
    dm = spec.duct_material()
    sf_by = {}
    for name, lf in sorted(ducts.items()):
        m = _DUCT_NAME.match(name)
        if dm:
            mats[name] = f"{dm[0]} (Spec {_fmt_sec(dm[1])})"
        if m.group(1):
            per, shape = math.pi * int(m.group(1)) / 12.0, "round"
        else:
            per = 2 * (int(m.group(2)) + int(m.group(3))) / 12.0
            shape = "rectangular"
        di = spec.duct_insulation(shape, "supply")
        if di:
            k = (di[0], di[1], di[2])
            rec = sf_by.setdefault(k, {"sf": 0.0, "n": 0})
            rec["sf"] += per * lf
            rec["n"] += 1
    for (mat, thk, sec), rec in sf_by.items():
        _ai_line(res, "spec", f'Duct insulation - {mat}, {thk:g}" thick',
                 rec["sf"], "SF", None, "spec", "23 07 13",
                 f"Spec {_fmt_sec(sec)} insulation schedule over the outside "
                 f"of {rec['n']} duct size(s) taken off - concealed supply, "
                 "return and outdoor air are wrapped, exhaust is not: deduct "
                 "the exhaust runs", REVIEW_BELOW - 0.05)
        added += 1
    added += _trenches(res, spec)
    added += _shades(res, spec)
    return added


def _shades(res, spec):
    """Window shades where the spec puts them 'At exterior windows' (or
    'at all windows'): one per window counted from the window tags."""
    loc = spec.shade_locations()
    if not loc or not re.search(r"\b(?:exterior|all)\s+windows\b", loc[0],
                                re.I):
        return 0
    wins = {}
    for _p, _k, pl in res.get("marks") or ():
        m = pl.get("measure") or {}
        g = m.get("group") or ""
        if m.get("method") == "AI takeoff: schedules" and \
                g.startswith("Window ") and m.get("type") == "count":
            wins[g] = wins.get(g, 0) + 1
    n = 0
    for g, k in sorted(wins.items()):
        _ai_line(res, "spec", f"Window shade at {g}", k, "EA", None, "spec",
                 "12 24 13", f"Spec {_fmt_sec(loc[1])}: shade locations "
                 f"'{loc[0]}' - one per {g} ({k} tagged)", 0.65)
        n += 1
    return n


def _trenches(res, spec):
    """Trench excavation, bedding and backfill for each new site pipe, from
    its length, its depth (the inverts where read, else the minimum cover
    the project manual sets) and the manual's trench rules (clearance each
    side, bedding under the pipe). Always for review: the trench is built
    from rules, not drawn."""
    n = 0
    for g in (res.get("civil") or {}).get("pipes") or ():
        if g.get("existing") or not g.get("length"):
            continue
        sysn = g.get("system") or ""
        if sysn not in ("sanitary", "storm", "water"):
            continue
        size = float(g.get("size") or 0)
        if not size:
            continue
        rules = spec.trench_rules(sysn)
        clear = rules["clear_in"]
        if clear is None:
            continue
        L = float(g["length"])
        w_in = max(size + 2 * clear, rules["min_w_in"] or 0)
        bed = rules["bed_in"] or 0
        known = [(r["length"], r["depth"]) for r in g.get("runs") or ()
                 if r.get("depth")]
        src = ", ".join(_fmt_sec(x) if x[:1].isdigit() else x
                        for x in rules["src"])
        name = re.sub(r",\s*depth unknown$", "", g["name"])
        cf = REVIEW_BELOW - 0.05
        if known and sum(l for l, _d in known) >= 0.5 * L:
            kl = sum(l for l, _d in known)
            depth = sum(l * d for l, d in known) / kl + bed / 12.0
            how = f"average depth {depth:.1f} ft from the inverts read"
        elif rules["cover_in"]:
            depth = (rules["cover_in"] + size + bed) / 12.0
            how = (f"depth {depth:.1f} ft = the {rules['cover_in']}\" "
                   f"minimum cover + the pipe + {bed}\" bedding (no "
                   "profile read - check the invert elevations)")
        else:
            _ai_line(res, "trench", f"Trench excavation - {name}", None,
                     "CY", None, "spec", "31 23 33",
                     f"{L:,.0f} LF; depth not read and the spec gives no "
                     "minimum cover for it", 0.0)
            n += 1
            continue
        w = w_in / 12.0
        exc = L * w * depth / 27.0
        bedcy = L * w * bed / 12.0 / 27.0
        pipe = L * math.pi * (size / 24.0) ** 2 / 27.0
        base = (f"{L:,.0f} LF x {_c2(w):.2f} ft wide ({size:g}\" pipe + "
                f"{clear}\" each side"
                + (f", {rules['min_w_in']}\" minimum" if rules["min_w_in"]
                   and rules["min_w_in"] > size + 2 * clear else "")
                + f") x {how}; Spec {src}")
        _ai_line(res, "trench", f"Trench excavation - {name}", exc, "CY",
                 None, "spec", "31 23 33", base, cf)
        if bed:
            _ai_line(res, "trench", f"Trench bedding - {name}", bedcy, "CY",
                     None, "spec", "31 23 33",
                     f"{bed}\" under the pipe x the trench width; " + base,
                     cf)
        _ai_line(res, "trench", f"Trench backfill - {name}",
                 max(0.0, exc - bedcy - pipe), "CY", None, "spec",
                 "31 23 33", "excavation less bedding and the pipe; " + base,
                 cf)
        n += 3 if bed else 2
    return n


def _fmt_sec(sec):
    s = re.sub(r"\D", "", sec.split(".")[0])
    out = f"{s[:2]} {s[2:4]} {s[4:6]}" if len(s) >= 6 else sec
    return out + (("." + sec.split(".")[1]) if "." in sec else "")
