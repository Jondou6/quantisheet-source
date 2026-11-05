"""Structural takeoff for AI Takeoff: steel members and footings from the
S plans, counted once.

* Steel (members): every shape tag (W8X21, HSS6X6X1/4, L4X4X1/2) is
  read with tradetakeoff.steel_members, then checked:
    - a tag whose line is a leader (it starts at the text and runs off
      at an angle) belongs to what the leader points at. A column
      symbol there (a small square / I shape) makes it a COLUMN: counted,
      its height taken from a column schedule or a note ("H=10'-3\"",
      "COLUMN HEIGHT 10'-3\""), else "height unknown" - the leader's
      length is never the member length.
    - a beam or joist takes the length of the member line itself (the
      line the leader points at, or the line the tag is written along).
    - anything else goes to review.
  Members shown on more than one plan (a column on the foundation plan
  and again on the roof framing plan) are counted once: the same mark at
  the same grid location (grid bubbles read from the sheet; without a
  grid, the same position on the sheet).
  Weight in LB from tradetakeoff.steel_weight, only when the length is
  known.
* Footings (footings): the footing schedule's marks counted on the plans
  (schedules.takeoff) times each mark's size -> CY with
  calculators.concrete. A continuous / wall footing (no length in the
  schedule) or a size that can't be read goes to review.

All page work is in the page's own (unrotated) coordinates, like
get_drawings() and tradetakeoff.
"""
import math
import re

from . import schedules as sch
from . import tradetakeoff as tt

_FTIN = re.compile(r"(\d{1,3})\s*'\s*-?\s*(?:(\d{1,2}(?:\.\d+)?)"
                   r"(?:\s*-?\s*(\d)/(\d{1,2}))?\s*(?:\"|''))?")
_IN_ONLY = re.compile(r"^(\d{1,3}(?:\.\d+)?)\s*(?:\"|''|IN\.?)$", re.I)
_H_NEAR = re.compile(r"\(?\s*(?:H|HT\.?|HEIGHT|LENGTH|L)\s*=\s*(\d{1,3}\s*'"
                     r"[^)]*)\)?", re.I)
_H_NOTE = re.compile(r"\b(?:STEEL\s+)?COL(?:UMN)?S?\.?\s+(?:HEIGHTS?|"
                     r"LENGTHS?)\s*(?:IS|ARE|=|:)?\s*(\d{1,3}\s*'[^,;.]*)",
                     re.I)
_SECONDARY = re.compile(r"\b(?:ENLARGED|PARTIAL|DETAILS?|SECTIONS?)\b", re.I)


def feet(text):
    """"10'-3\"" -> 10.25, "4'-0\"" -> 4.0, "12\"" -> 1.0, else None."""
    t = (text or "").translate(sch._QUOTES).strip()
    m = _FTIN.search(t)
    if m:
        v = float(m.group(1))
        if m.group(2):
            v += float(m.group(2)) / 12
        if m.group(3):
            v += float(m.group(3)) / float(m.group(4)) / 12
        return v
    m = _IN_ONLY.match(t)
    if m:
        return float(m.group(1)) / 12
    return None


def dims(text):
    """Footing size "4'-0\" x 4'-0\" x 1'-0\"" (or "4'-0\" SQ x 12\"")
    -> [feet, ...] in the order written."""
    t = (text or "").translate(sch._QUOTES).upper()
    parts = re.split(r"\s*[X×]\s*", t)
    out = []
    for p in parts:
        sq = bool(re.search(r"\bSQ(?:UARE|\.)?\b", p))
        v = feet(p)
        if v is None:
            m = re.match(r"^\s*(\d{1,3}(?:\.\d+)?)\s*$", p)
            v = float(m.group(1)) / 12 if m else None
        if v is None:
            return None
        out += [v, v] if sq else [v]
    return out


# ------------------------------------------------------------- geometry
def _angle_ok(a, b, tol_deg=5.0):
    """The line a-b runs horizontal or vertical (within tol)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return False
    ang = abs(math.degrees(math.atan2(dy, dx))) % 90
    return ang <= tol_deg or ang >= 90 - tol_deg


def _rect_dist(rc, p):
    x0, y0, x1, y1 = rc
    dx = max(x0 - p[0], 0, p[0] - x1)
    dy = max(y0 - p[1], 0, p[1] - y1)
    return math.hypot(dx, dy)


def column_symbols(page, per_ft):
    """Small column symbols: [(cx, cy, w, h)] for paths that are a rect,
    or axis-aligned lines only, between 0.2 and 2.5 ft across and not
    much longer than wide (an HSS square, a W column's I, a pier)."""
    try:
        paths = page.get_drawings()
    except Exception:                                 # noqa: BLE001
        return []
    out = []
    lo, hi = 0.2 * per_ft, 2.5 * per_ft
    for p in paths:
        r = p.get("rect")
        if r is None:
            continue
        w, h = r.width, r.height
        if not (lo <= w <= hi and lo <= h <= hi):
            continue
        if max(w, h) / max(1e-6, min(w, h)) > 2.5:
            continue
        items = p.get("items", ())
        if not items:
            continue
        kinds = {it[0] for it in items}
        if kinds <= {"re", "qu"}:
            pass
        elif kinds == {"l"} and len(items) >= 4 and all(
                _angle_ok((it[1].x, it[1].y), (it[2].x, it[2].y), 2.0)
                for it in items):
            pass
        else:
            continue
        out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, w, h))
    # one symbol drawn as several paths: keep one per spot
    keep = []
    for s in sorted(out, key=lambda s: -s[2] * s[3]):
        if any(abs(s[0] - k[0]) < max(k[2], 2) / 2 and
               abs(s[1] - k[1]) < max(k[3], 2) / 2 for k in keep):
            continue
        keep.append(s)
    return keep


def grid(cells, segs):
    """Grid bubbles: ({label: x}, {label: y}) - one- or two-character
    labels in circles, in a row (the lettered or numbered lines across)
    or a column."""
    bub = [c for c in cells if len(c["text"]) <= 3 and
           re.match(r"^[A-Z]{1,2}\.?\d?$|^\d{1,2}(?:\.\d)?$", c["text"]) and
           sch._circled(c, segs)]
    xs, ys = {}, {}
    for c in bub:
        row = [d for d in bub if d is not c and abs(d["cy"] - c["cy"]) < 3]
        col = [d for d in bub if d is not c and abs(d["cx"] - c["cx"]) < 3]
        if len(row) >= 1 and len(row) >= len(col):
            xs.setdefault(c["text"], c["cx"])
        elif len(col) >= 1:
            ys.setdefault(c["text"], c["cy"])
    return xs, ys


def location(pt, gx, gy, per_ft, tol_ft=3.0):
    """(x grid label, y grid label) of a point, or None off the grid."""
    def near(d, v):
        best = min(d.items(), key=lambda kv: abs(kv[1] - v), default=None)
        if best is None or abs(best[1] - v) > tol_ft * per_ft:
            return None
        return best[0]
    a, b = near(gx, pt[0]), near(gy, pt[1])
    if a is None or b is None:
        return None
    return (a, b)


def _tags(page):
    out = []
    for text, r in tt.phrases(page, 3):
        t = text.strip().strip(",;()").replace(" ", "").upper()
        if tt.STEEL_RE.match(t):
            out.append((t, (r.x0, r.y0, r.x1, r.y1)))
    out.sort(key=lambda t: -(t[1][2] - t[1][0]))
    kept = []
    for t in out:
        if not any(k[1][0] <= t[1][0] + 0.1 and k[1][2] >= t[1][2] - 0.1 and
                   k[1][1] <= t[1][1] + 0.1 and k[1][3] >= t[1][3] - 0.1
                   for k in kept):
            kept.append(t)
    return kept


def _height_near(page_lines, tag_rect, h):
    """A height written with the tag ("HSS4X4X1/4 (H=10'-3\")" or on the
    line under it)."""
    x0, y0, x1, y1 = tag_rect
    for text, r in page_lines:
        if r[1] > y1 + 2.5 * h or r[3] < y0 - 0.5 * h:
            continue
        if r[2] < x0 - 4 * h or r[0] > x1 + 20 * h:
            continue
        m = _H_NEAR.search(text)
        if m:
            v = feet(m.group(1))
            if v and 2 <= v <= 60:
                return v
    return None


def _height_note(text):
    m = _H_NOTE.search(text or "")
    if m:
        v = feet(m.group(1))
        if v and 2 <= v <= 60:
            return v
    return None


def _height_table(name, tables):
    """A column schedule row for this shape (by its size column or mark)
    with a height / length column."""
    for t in tables or []:
        if t.get("kind") != "column" or not t.get("rows"):
            continue
        hcol = next((c for c in t["columns"] if sch._H_HDR.search(c)), None)
        if not hcol:
            continue
        for r in t["rows"]:
            vals = " ".join(v for k, v in r.items() if k != "_key_rect")
            if name in vals.replace(" ", "").upper():
                v = feet(r.get(hcol, ""))
                if v and 2 <= v <= 60:
                    return v
    return None


def members(page, ppu, unit="ft", tables=None, note_text=""):
    """The steel on one plan: [{name, kind ('column' | 'beam' |
    'review'), pt (where it is), length (ft or None), pts (the member
    line, beams), lb_ft, why}]."""
    per_ft = tt._per_ft(ppu, unit)
    if per_ft <= 0:
        return []
    groups = tt.steel_members(page, ppu, unit)
    tags = _tags(page)
    if not tags:
        return []
    cols = column_symbols(page, per_ft)
    # every run, any style, to find what a leader points at
    allruns = []
    for _st, segs in tt.styled_segments(page).items():
        for r in tt.runs(segs):
            if tt.poly_len(r) >= 2.0 * per_ft:
                allruns.append(r)
    lines_ = []
    try:
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            for ln in b.get("lines", []):
                t = " ".join(sp.get("text", "") for sp in ln.get("spans", []))
                if t.strip():
                    lines_.append((t.strip(), tuple(ln["bbox"])))
    except Exception:                                 # noqa: BLE001
        pass
    note_h = _height_note(note_text)
    # pair each member line steel_members chose with its tag
    pairs = []
    free = list(tags)
    for g in groups:
        for m in g["members"]:
            mine = [t for t in free if t[0] == g["name"]]
            if not mine:
                continue
            t = min(mine, key=lambda t: tt.dist_to_poly(
                ((t[1][0] + t[1][2]) / 2, (t[1][1] + t[1][3]) / 2), m["pts"]))
            free.remove(t)
            pairs.append((t, m["pts"]))
    pairs += [(t, None) for t in free]
    out = []
    for (name, rc), pts in pairs:
        h = max(rc[3] - rc[1], 4.0)
        lb_ft = tt.steel_weight(name)
        c = ((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2)
        rec = {"name": name, "kind": "review", "pt": c, "length": None,
               "pts": None, "lb_ft": lb_ft, "why": "", "tag_rect": rc}
        tip = None
        leader = False
        if pts:
            a, b = pts[0], pts[-1]
            da, db = _rect_dist(rc, a), _rect_dist(rc, b)
            near_end = min(da, db) <= 2.0 * h
            straight = len(pts) == 2 or all(_angle_ok(p, q) for p, q in
                                            zip(pts, pts[1:]))
            horiz = (rc[2] - rc[0]) >= (rc[3] - rc[1])
            ux, uy = tt._unit(b[0] - a[0], b[1] - a[1])
            along = abs(ux) if horiz else abs(uy)
            if near_end and (not straight or along < 0.94):
                leader = True
                tip = b if da <= db else a
        # a column symbol at the leader's tip, or right by the tag
        probe = [tip] if tip is not None else [c]
        reach = 1.0 * per_ft if tip is not None else 3.0 * per_ft
        col = None
        for p in probe:
            near = [s for s in cols if _rect_dist(
                (s[0] - s[2] / 2, s[1] - s[3] / 2, s[0] + s[2] / 2,
                 s[1] + s[3] / 2), p) <= reach]
            if near:
                col = min(near, key=lambda s: math.hypot(s[0] - p[0],
                                                         s[1] - p[1]))
        square = bool(re.match(r"^HSS(\d+(?:\.\d+)?)X\1X", name)) or \
            name.startswith("W") and col is not None
        if col is not None and (square or tip is not None or
                                not pts or tt.poly_len(pts) < 3 * per_ft):
            rec.update(kind="column", pt=(col[0], col[1]))
            ht = _height_near(lines_, rc, h) or _height_table(name, tables) \
                or note_h
            rec["length"] = ht
            if ht is None:
                rec["why"] = "height unknown"
            out.append(rec)
            continue
        if leader:
            # the beam line the leader points at
            hit = None
            for r in allruns:
                if r is pts or len(r) < 2:
                    continue
                if tt.dist_to_poly(tip, r) > 1.5:
                    continue
                if not all(_angle_ok(p, q) for p, q in zip(r, r[1:])):
                    continue
                L = tt.poly_len(r)
                if L < 4 * per_ft:
                    continue
                if hit is None or L > tt.poly_len(hit):
                    hit = r
            if hit is None:
                rec["why"] = ("tag points with a leader at no member line "
                              "or column - measure it by hand")
                out.append(rec)
                continue
            pts = hit
        elif not pts:
            rec["why"] = "no member line at this tag"
            out.append(rec)
            continue
        L = tt.poly_len(pts) / per_ft
        if L < 3.0:
            rec["why"] = f"member line only {L:.1f} ft - check by hand"
            out.append(rec)
            continue
        rec.update(kind="beam", length=L, pts=pts,
                   pt=((pts[0][0] + pts[-1][0]) / 2,
                       (pts[0][1] + pts[-1][1]) / 2))
        out.append(rec)
    return out


def dedupe(per_sheet, rows_by_page, per_ft_of):
    """{page: {"members", "gx", "gy"}} -> (kept [(page, member)], dups
    [(page, member, kept page, 'grid' | 'position')]). The same mark at the
    same grid location on several plans is one member; plans with
    'ENLARGED' / 'PARTIAL' in their titles come last."""
    def rank(p):
        t = (rows_by_page.get(p) or {}).get("title") or ""
        return (bool(_SECONDARY.search(t)), p)
    kept, dups, seen = [], [], {}
    for p in sorted(per_sheet, key=rank):
        g = per_sheet[p]
        for m in g["members"]:
            if m["kind"] == "review":
                kept.append((p, m))
                continue
            loc = location(m["pt"], g["gx"], g["gy"], per_ft_of[p])
            if loc is not None:
                key = (m["name"], m["kind"], "grid", loc)
            else:
                cell = 3.0 * per_ft_of[p]
                key = (m["name"], m["kind"], "pos",
                       round(m["pt"][0] / cell), round(m["pt"][1] / cell))
            if m["kind"] == "beam" and loc is None:
                key = key + (round((m["length"] or 0) / 2.0),)
            if key in seen and seen[key] != p:
                dups.append((p, m, seen[key], key[2] == "grid" and "grid"
                             or "position"))
                continue
            seen.setdefault(key, p)
            kept.append((p, m))
    return kept, dups


def footings(lines, tables):
    """CY for the footing marks counted on the plans: [{name, mark, count,
    cy, dims, status, why, page}] from the schedules result lines of kind
    'footing' and the footing schedule tables."""
    from . import calculators
    rows = {}
    for t in tables or []:
        if t.get("kind") != "footing":
            continue
        for r in t["rows"]:
            rows.setdefault(sch.norm_key(r[t["key"]]), (t, r))
    out = []
    for ln in lines:
        if ln.get("kind") != "footing":
            continue
        k = sch.norm_key(ln["key"])
        t, r = rows.get(k, (None, None))
        rec = {"name": f"Footing {ln['key']}", "mark": ln["key"],
               "count": ln["qty"], "cy": None, "dims": None,
               "status": "review", "why": "", "page": ln.get("page")}
        if r is None:
            rec["why"] = "mark not in a footing schedule"
            out.append(rec)
            continue
        size = None
        scol = next((c for c in t["columns"] if sch._SIZE_HDR.search(c)),
                    None)
        if scol and r.get(scol):
            size = dims(r[scol])
        if size is None:
            wc = next((c for c in t["columns"] if sch._W_HDR.search(c)), None)
            lc = next((c for c in t["columns"] if sch._L_HDR.search(c)), None)
            dc = next((c for c in t["columns"] if sch._D_HDR.search(c)), None)
            vals = [feet(r.get(c, "")) if c else None for c in (lc, wc, dc)]
            if all(v is not None for v in vals):
                size = vals
            elif vals[0] is None and vals[1] is not None and \
                    vals[2] is not None:
                size = [vals[1], vals[2]]          # width x depth only
        cont = re.search(r"\b(?:CONT(?:INUOUS)?|WALL|STRIP|THICKENED)\b",
                         " ".join(str(v) for kk, v in r.items()
                                  if kk != "_key_rect"), re.I)
        if size is None:
            rec["why"] = "footing size not read from the schedule"
        elif len(size) == 2 or cont:
            rec["dims"] = size
            rec["why"] = ("continuous footing - its length isn't in the "
                          "schedule; measure it on the foundation plan")
        elif len(size) >= 3 and not ln.get("status") == "taken off":
            rec["dims"] = size[:3]
            rec["why"] = "footing count not confirmed: " + (ln.get("why") or
                                                            "see review")
        else:
            L, W, D = size[:3]
            rec["dims"] = [L, W, D]
            rec["cy"] = calculators.concrete(
                "slab", qty=ln["qty"], waste_pct=0.0, length=L, width=W,
                thick_in=D * 12)["cy"]
            rec["status"] = "taken off"
            reinf = next((v for kk, v in r.items() if kk != "_key_rect" and
                          re.search(r"REINF|REBAR|BARS?", kk, re.I)), "")
            rb = footing_rebar(reinf, L, W)
            if rb:
                rec["rebar"] = dict(rb, lb=round(rb["lb_each"] * ln["qty"],
                                                 2))
        out.append(rec)
    return out


BAR_LB_FT = {3: 0.376, 4: 0.668, 5: 1.043, 6: 1.502, 7: 2.044, 8: 2.670,
             9: 3.400, 10: 4.303, 11: 5.313}
FOOTING_COVER_FT = 0.25          # 3" clear: concrete cast against earth
_REINF = re.compile(r"\(?(\d{1,2})\)?\s*#\s*(\d{1,2})\s*(E\.?\s*W\.?|EACH\s+WAY)?"
                    r"\s*(T\s*&\s*B|TOP\s*(?:&|AND)\s*BOT(?:TOM)?)?", re.I)


def footing_rebar(text, L, W):
    """Reinforcing of one pad footing from its schedule text ('(5) #5 EW
    T&B') and its plan size in ft: {bar, bars, lb_each, basis}, or None.
    Bars run the footing less 3" cover at each end."""
    m = _REINF.search(text or "")
    if not m:
        return None
    n, bar = int(m.group(1)), int(m.group(2))
    if bar not in BAR_LB_FT:
        return None
    ew = 2 if m.group(3) else 1
    layers = 2 if m.group(4) else 1
    lens = [L - 2 * FOOTING_COVER_FT, W - 2 * FOOTING_COVER_FT][:ew]
    total_ft = sum(n * x for x in lens) * layers
    lb = total_ft * BAR_LB_FT[bar]
    return {"bar": bar, "bars": n * ew * layers, "lb_each": lb,
            "basis": f"'{m.group(0).strip()}': {n * ew * layers} #{bar} bars "
                     f"x {' / '.join(f'{x:g}' for x in lens)} ft (3\" cover "
                     f"each end) x {BAR_LB_FT[bar]} lb/ft"}
