"""Auto takeoff: find a room's floor area from the drawing.

Click inside a room and its outline is traced along the inside face of the
walls; or take off every room on a sheet at once, each area named after its
room tag ("LOBBY  245 SF").

DESIGN RULES (Oct 31 2026, patent review - enforced by
tests/test_patent_design_rules.py):
* a room's area is computed whole and shown finished in one step - never
  drawn growing or step by step; text is left out automatically (no
  "pick the lines to ignore" step);
* every room is measured to its own wall faces: wall or shared boundary
  area is never handed out between neighbouring rooms by a rank or
  priority, and there is no even-split tie rule.

How it works (numpy + OpenCV, no AI):

* The page is rendered in grey at about 24 pixels per foot, with text and
  markups left out and the words' boxes blanked, so only linework is left.
* Walls are thick lines: closing then opening the ink keeps solid walls
  and drops thin lines (dimensions, hatching, door swings, furniture).
* Door openings are bridged by "growing" the walls by half a door width;
  the room is the connected open space around the seed, then grown back
  to the wall faces. Several door widths are tried. If the room tag gives
  a square footage, the width whose result matches it best wins;
  otherwise a standard 3'-6" opening is assumed.
* A result that runs off the page or swallows another room's tag is
  rejected. Areas already measured on the page count as walls, so rooms
  next to them can't leak into them.

Speed (dense plans): the page's drawings and text are read once per run
(cached_page); each open space is traced once per door width and shared by
every tag in it, and a space already holding another room's tag, or far
bigger than the tag says, is turned down before any tracing. The work per
room no longer grows with the size of the building.

Checks on every result (score_room, flag_overlaps): a trace must hold
exactly one room tag and may not overlap another trace; each room gets a
trace confidence, its difference from the tag and flags, and anything
unsure is marked for review rather than taken as is.
"""
import logging
import math
import os
import re
import time

try:
    import numpy as np
except ImportError:              # pragma: no cover
    np = None
try:
    import cv2
except ImportError:              # pragma: no cover
    cv2 = None

import fitz

from . import annotate

log = logging.getLogger(__name__)

TARGET_PPF = 24.0                 # render resolution, pixels per foot
MIN_PPF = 10.0
MAX_PIXELS = 48_000_000
DOOR_STEPS = (1.4, 2.2, 3.0, 3.6, 4.6, 6.2, 8.2)   # door widths tried, ft
SMALL_ROOM_SF = 60          # closets: also look around the tag (detect)
CLOSET_DOORS = (0.9, 1.4, 2.2)
DEFAULT_DOOR = 3.6
DOOR_ORDER = tuple(sorted(DOOR_STEPS, key=lambda d: abs(d - DEFAULT_DOOR)))
EARLY_DIFF = 0.02          # a trace this close to its tag ends the search
INK_LEVEL = 200                   # MuPDF draws hairlines in light grey
CLOSE_FT, OPEN_FT = 0.5, 0.35
SIMPLIFY_FT = 0.2
ISLAND_FT = 5.0                   # free-standing blobs smaller than this
FILL_NOTCH_FT = (2.5, 4.0, 6.0, 8.0)  # fixture notches tried when a tag says
FINE_PEN_PT = 0.35               # line weights up to this are "fine" pens
GOOD = 0.12                       # within 12% of its tag = a sure match
TRACE_INSET_PX = 0.25             # traced outline inside filled walls
NAMED_MAX_SF = 5000               # a room named without an area: at most
NOTE_DIFF, REVIEW_DIFF = 0.02, 0.05   # trace vs tag: noted / for review
OVERLAP_SF = 4.0                  # traces overlapping more: both flagged
DOORWAY_FT = 1.5                  # an opening through a wall this thick

FT_PER_UNIT = {"ft": 1.0, "in": 1 / 12, "yd": 3.0, "m": 3.28084,
               "cm": 0.0328084, "mm": 0.00328084}

_TAG_NUM = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^\d+(?:\.\d+)?$")
_TAG_UNIT = {"SF", "S.F.", "SQ.FT.", "SQFT", "SQ.FT", "S.F", "SF."}
_TAG_JOINED = re.compile(r"^(\d[\d,]*(?:\.\d+)?)(SF|S\.F\.)$", re.I)


class AutoTakeoffError(Exception):
    pass


class _Stop(Exception):
    """The caller (progress returned False) or the sheet's time budget
    stopped the run."""


def available():
    return np is not None and cv2 is not None


# ---- one read of the page ------------------------------------------------------

class _CachedPage:
    """A page whose drawings and text are read once. get_drawings() on a
    dense CAD sheet takes seconds, and room finding used to ask for it
    eight times or more per sheet (and again for each detail scale).
    Everything else is the page's own."""

    def __init__(self, page):
        self._page = page
        self._drawings = None
        self._text = {}
        self._memo = {}

    def get_drawings(self, *a, **k):
        if a or k:
            return self._page.get_drawings(*a, **k)
        if self._drawings is None:
            self._drawings = self._page.get_drawings()
        return self._drawings

    def get_text(self, opt="text", *a, **k):
        if a or k:
            return self._page.get_text(opt, *a, **k)
        if opt not in self._text:
            self._text[opt] = self._page.get_text(opt)
        return self._text[opt]

    def __getattr__(self, name):
        return getattr(self._page, name)


def cached_page(page):
    """`page` with its drawings and text read once (see _CachedPage)."""
    return page if isinstance(page, _CachedPage) else _CachedPage(page)


def _real_page(page):
    return page._page if isinstance(page, _CachedPage) else page


def _memo(page, key, fn):
    if isinstance(page, _CachedPage):
        if key not in page._memo:
            page._memo[key] = fn()
        return page._memo[key]
    return fn()


# ---- room tags ---------------------------------------------------------------

def _num(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


class _Line:
    """A line of text: its box (reading-frame points: unrotated page
    points on most sheets, see _reading_frame), words and tokens."""
    __slots__ = ("rect", "words", "toks", "key")

    def __init__(self, rect, words, key):
        self.rect, self.words, self.key = rect, words, key
        self.toks = [w[4].strip() for w in words]

    @property
    def text(self):
        return " ".join(self.toks)


READING_FRAME_SHARE = 0.6     # share of text lines that must run one way


def _reading_frame(page):
    """The turn (a Matrix) from unrotated page points to the frame the
    sheet's text reads left to right in. Identity for most sheets; a
    drawing laid out sideways in the file (its words run up or down the
    unrotated page) gets the quarter or half turn that stands them up, so
    room names stack above their numbers as on screen (Oct 31)."""
    def build():
        n = {}
        for b in page.get_text("dict").get("blocks", []):
            for ln in b.get("lines", []):
                d = (round(ln["dir"][0]), round(ln["dir"][1]))
                n[d] = n.get(d, 0) + 1
        total = sum(n.values())
        if not total:
            return fitz.Identity
        best = max(n, key=n.get)
        if best == (1, 0) or n[best] < READING_FRAME_SHARE * total:
            return fitz.Identity
        for deg in (90, 180, 270):
            v = fitz.Point(best) * fitz.Matrix(deg)
            if abs(v.x - 1) < 0.01 and abs(v.y) < 0.01:
                return fitz.Matrix(deg)
        return fitz.Identity
    return _memo(page, "reading_frame", build)


def _frame_words(page):
    """page.get_text("words") with each box in the reading frame."""
    def build():
        m = _reading_frame(page)
        words = page.get_text("words")
        if m == fitz.Identity:
            return words
        out = []
        for w in words:
            r = fitz.Rect(w[:4]) * m
            out.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:]))
        return out
    return _memo(page, "frame_words", build)


def _frame_to_screen(page):
    """Matrix from reading-frame points to screen (rotated) points."""
    return ~_reading_frame(page) * page.rotation_matrix


def _text_lines(page):
    """The page's text lines, read once: words grouped by their (block,
    line), then pieces of one line split over several blocks (CAD text
    often is) joined when they sit on the same baseline right next to each
    other. Boxes are in the reading frame (see _reading_frame)."""
    def build():
        groups = {}
        for w in _frame_words(page):
            groups.setdefault((w[5], w[6]), []).append(w)
        lines = []
        for key, ws in groups.items():
            ws.sort(key=lambda w: w[0])
            r = fitz.Rect(ws[0][:4])
            for w in ws[1:]:
                r |= fitz.Rect(w[:4])
            lines.append(_Line(r, ws, key))
        lines.sort(key=lambda ln: ((ln.rect.y0 + ln.rect.y1) / 2,
                                   ln.rect.x0))
        out = []
        for ln in lines:
            h = ln.rect.height or 6
            yc = (ln.rect.y0 + ln.rect.y1) / 2
            hit = None
            for o in reversed(out[-12:]):
                oyc = (o.rect.y0 + o.rect.y1) / 2
                if abs(oyc - yc) > 0.3 * h:
                    continue
                gap = ln.rect.x0 - o.rect.x1
                if -0.2 * h <= gap <= 0.9 * h and \
                        abs(o.rect.height - ln.rect.height) <= 0.3 * h:
                    hit = o
                    break
            if hit is None:
                out.append(ln)
            else:
                hit.words = hit.words + ln.words
                hit.toks = hit.toks + ln.toks
                hit.rect = hit.rect | ln.rect
        return out
    return _memo(page, "lines", build)


class _LineIndex:
    """Text lines bucketed by position, for the "what is stacked above
    this" lookups (one pass over the page instead of one per tag)."""
    G = 48.0

    def __init__(self, lines):
        self.grid = {}
        for i, ln in enumerate(lines):
            r = ln.rect
            for gx in range(int(r.x0 // self.G), int(r.x1 // self.G) + 1):
                for gy in range(int(r.y0 // self.G), int(r.y1 // self.G) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)
        self.lines = lines

    def near(self, rect, pad):
        seen = set()
        for gx in range(int((rect.x0 - pad) // self.G),
                        int((rect.x1 + pad) // self.G) + 1):
            for gy in range(int((rect.y0 - pad) // self.G),
                            int((rect.y1 + pad) // self.G) + 1):
                for i in self.grid.get((gx, gy), ()):
                    if i not in seen:
                        seen.add(i)
                        yield self.lines[i]


def _line_index(page):
    return _memo(page, "line_index", lambda: _LineIndex(_text_lines(page)))


# a room tag's sample in a legend or a template: never a room
_PLACEHOLDER = re.compile(r"\b(ROOM\s+NAME|ROOM\s+NO\b|ROOM\s+NUMBER|RM\s+NAME|"
                          r"NAME|X{3,}|#{2,}|TAG)\b")
# "RO" / "R.O." (rough opening) written by a door or window tag (Oct 31)
_ROUGH_OPENING = re.compile(r"^R\.?\s?O\.?(?:\s+[A-Z]{0,2}-?\d{1,3}[A-Z]?)?$")
_LEGEND_HEAD = re.compile(r"\b(LEGEND|LEGENDS|SYMBOLS?|ABBREVIATIONS|"
                          r"ROOM\s+TAGS?|TAG\s+TYPES?)\b")
LEGEND_W_IN, LEGEND_H_IN = 5.0, 6.0          # a legend's extent, paper inches


def legend_zones(page):
    """Rectangles (reading-frame points) taken up by legends: from a
    short heading line ("SYMBOLS LEGEND", "ROOM TAG", "ABBREVIATIONS")
    down and to the right, about 5" x 6" of paper. Tags drawn there are
    samples, not rooms."""
    def build():
        out = []
        for ln in _text_lines(page):
            if len(ln.toks) > 5:
                continue
            t = ln.text.upper()
            if not _LEGEND_HEAD.search(t):
                continue
            r = ln.rect
            out.append(fitz.Rect(r.x0 - 18, r.y0 - 4,
                                 r.x0 + LEGEND_W_IN * 72,
                                 r.y1 + LEGEND_H_IN * 72))
        return out
    return _memo(page, "legend_zones", build)


def _in_title_block(page, pt):
    """Is the screen point in the title block (the right-hand strip or the
    bottom-right corner)?"""
    W, H = page.rect.width, page.rect.height
    return pt.x > W * 0.8 and pt.y > H * 0.55 or pt.x > W * 0.86


def _not_a_room(page, name, upt, pt, title_block=True):
    """Why a tag is not a room (a legend or title-block sample), or ''.
    `upt`: the tag's point in the reading frame, `pt` on screen."""
    if name and _PLACEHOLDER.search(name.upper()):
        return "a sample tag (placeholder name)"
    if name and _ROUGH_OPENING.match(name.upper()):
        return "a rough-opening note at a door or window, not a room"
    if any(z.contains(upt) for z in legend_zones(page)):
        return "in a legend"
    if title_block and _in_title_block(page, pt):
        return "in the title block"
    return ""


def room_tags(page, info=None):
    """Room tags on the page: [{"name", "sf", "pt"}], `pt` in screen
    (rotated) coordinates at the area figure, `sf` the printed area.

    A tag is a number followed by "SF" ("245 SF" or "245SF"); its name is
    the lines of text stacked above it ("DOG INTAKE 108", "WOMEN / TLT &
    SHOWER / 114"). Samples in legends and the title block are left out
    (listed in info["ignored"] when `info` is given).

    Text extraction gives unrotated coordinates; names are found in those
    (the text reads normally there), and the point is turned to screen."""
    page = cached_page(page)
    words = _frame_words(page)
    rot = _frame_to_screen(page)
    idx = _line_index(page)
    tags = []
    for i, w in enumerate(words):
        text = w[4].strip()
        m = _TAG_JOINED.match(text)
        if m:
            sf, box, num_i = _num(m.group(1)), fitz.Rect(w[:4]), i
        elif text.upper() in _TAG_UNIT and i > 0 and \
                words[i - 1][5] == w[5] and words[i - 1][6] == w[6] and \
                _TAG_NUM.match(words[i - 1][4].strip()):
            sf = _num(words[i - 1][4].strip())
            box, num_i = fitz.Rect(w[:4]), i - 1
        else:
            continue
        if not sf or sf <= 0:
            continue
        name = _stack_name(idx, fitz.Rect(words[num_i][:4]) | box)
        upt = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        tag = {"name": name, "sf": sf, "pt": upt * rot}
        # (area tags were always read anywhere on the sheet: plans can run
        # into the right-hand strip; only legend samples are left out)
        why = _not_a_room(page, name, upt, tag["pt"], title_block=False)
        if why:
            if info is not None:
                info.setdefault("ignored", []).append(dict(tag, why=why))
            continue
        tags.append(tag)
    return tags


_ROOM_NO = re.compile(r"^[A-Z]?\d{2,4}(?:\.\d{1,2})?[A-Z]?$")
_ROOM_NO_WORD = {"EXT", "EXT."}           # "COVERED PATIO / EXT." (outside)
_ROOM_WORD = re.compile(r"^(?:[A-Z][A-Z&/.'()-]+|&|/|\+)$")
_NOT_ROOM = {"SCALE", "SHEET", "DATE", "DRAWN", "PROJECT", "NORTH", "SEE",
             "DETAIL", "SECTION", "ELEVATION", "TYP", "TYP.", "NTS",
             "PLAN", "FLOOR", "NOTES", "NOTE", "REV", "NO", "NO.",
             # revision / addendum markers ("ASI 0042", "RFI 012")
             "ASI", "RFI", "CCD", "PR", "CO", "COR", "ADDENDUM", "ADD",
             "BULLETIN", "REVISION", "SK", "KEYNOTE", "GRID", "SIM", "SIM.",
             "VERIFY", "SHALL", "ALL", "AT", "THE", "AND", "OF", "TO", "WITH"}


# floor-and-letter room numbers ("03L" = floor 3, room L); a bare "01" or
# "003" stays a keynote
_ROOM_NO_ZERO = re.compile(r"^0\d{1,2}[A-Z]$")


def _is_room_no(tok):
    t = tok.strip(",:;")
    return (_ROOM_NO.match(t) and
            (not t.startswith("0") or _ROOM_NO_ZERO.match(t))) or \
        t.upper() in _ROOM_NO_WORD


def room_number(name):
    """The room number in a room's name: 'PREP STORAGE 115.1' -> '115.1',
    'OFFICE 102A' -> '102A', 'COVERED PATIO EXT.' -> 'EXT', '' if none."""
    toks = (name or "").upper().replace(",", " ").split()
    for t in reversed(toks):
        t2 = t.strip(":;")
        if _ROOM_NO.match(t2.rstrip(".")):
            return t2.rstrip(".")
        if t2 in _ROOM_NO_WORD:
            return "EXT"
    return ""


def _name_line(ln, max_toks=4):
    """Is this text line part of a room name (words only, no notes)?"""
    toks = [t.strip(",:;") for t in ln.toks]
    return 0 < len(toks) <= max_toks and len(ln.text) <= 32 and \
        all(_ROOM_WORD.match(t) for t in toks) and \
        not any(t in _NOT_ROOM for t in toks) and \
        any(len(t) > 1 for t in toks)


def _stack_name(idx, tag, max_lines=4, names_only=False):
    """The room name stacked above a tag's figure ("PUBLIC DOG" / "INTAKE"
    / "108" -> "PUBLIC DOG INTAKE 108"). Found by position: drawings often
    split one tag over several text blocks. Only short lines count (a
    room name, never a line of a note); `names_only`: words only, no
    room number line."""
    h = tag.height or 8
    cx = (tag.x0 + tag.x1) / 2
    top, got = tag.y0, []
    used = set()
    for _ in range(max_lines):
        best = None
        q = fitz.Rect(tag.x0 - 4 * h, top - 2 * h, tag.x1 + 4 * h, top)
        for ln in idx.near(q, h):
            if ln.key in used:
                continue
            r = ln.rect
            gap = top - r.y1
            lcx = (r.x0 + r.x1) / 2
            if not (-0.5 * h <= gap <= 0.8 * h and r.y0 < top - 0.3 * h and
                    abs(lcx - cx) <= max(r.width, tag.width) / 2 + h):
                continue
            if len(ln.toks) > 5 or len(ln.text) > 36 or \
                    r.width > max(6 * tag.width, 30 * h):
                continue                       # a note, not a room name
            if names_only and not _name_line(ln):
                continue
            if best is None or gap < best[0]:
                best = (gap, ln)
        if best is None:
            break
        ln = best[1]
        used.add(ln.key)
        got.insert(0, ln.text)
        top = ln.rect.y0
    return " ".join(got).strip()


def _tag_name(words, tag, max_lines=4):
    """The room name stacked above a tag's area figure, from a list of
    words (kept for callers that have words, not a page)."""
    groups = {}
    for w in words:
        groups.setdefault((w[5], w[6]), []).append(w)
    lines = []
    for key, ws in groups.items():
        ws.sort(key=lambda w: w[0])
        r = fitz.Rect(ws[0][:4])
        for w in ws[1:]:
            r |= fitz.Rect(w[:4])
        lines.append(_Line(r, ws, key))
    return _stack_name(_LineIndex(lines), tag, max_lines)


def room_labels(page, skip=(), info=None):
    """Rooms named without an area: a line like "OFFICE 102" or "EXAM
    ROOM 3" (words, then a room number), possibly under more name lines
    ("WOMEN" / "TLT & SHOWER 114"), or a room number on its own line
    under its name ("CORRIDOR" / "102", "PREP STORAGE" / "115.1",
    "COVERED" / "PATIO" / "EXT."). [{"name", "sf": None, "pt"}] in screen
    coordinates. Lines near `skip` points (rooms that already have an SF
    tag), the title block and legend samples are left out."""
    page = cached_page(page)
    rot = _frame_to_screen(page)
    idx = _line_index(page)
    out = []
    for ln in _text_lines(page):
        toks = [t.strip(",:;") for t in ln.toks]
        if not toks or len(toks) > 5 or not _is_room_no(toks[-1]):
            continue
        name = toks[:-1]
        if name and (not all(_ROOM_WORD.match(t) for t in name) or
                     any(t in _NOT_ROOM for t in name) or
                     not any(len(t) > 1 for t in name)):
            continue
        # more of the name stacked above (or all of it, over a lone number)
        above = _stack_name(idx, ln.rect, max_lines=3, names_only=True)
        if not name and not above:
            continue
        full = " ".join(([above] if above else []) + [ln.text]).strip()
        r = ln.rect
        upt = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        pt = upt * rot
        if any(abs(pt.x - q.x) < 60 and abs(pt.y - q.y) < 40 for q in skip):
            continue
        why = _not_a_room(page, full, upt, pt)
        if why:
            if info is not None:
                info.setdefault("ignored", []).append(
                    {"name": full, "sf": None, "pt": pt, "why": why})
            continue
        out.append({"name": full, "sf": None, "pt": pt})
    # a name line that is itself over a number line was read twice ("WOMEN
    # / TLT & SHOWER 114" and "TLT & SHOWER 114" can't both come out: the
    # second is a line the first stacked) - keep the longest name per spot
    keep = []
    for t in sorted(out, key=lambda t: -len(t["name"])):
        if any(abs(t["pt"].x - k["pt"].x) < 30 and
               abs(t["pt"].y - k["pt"].y) < 30 and
               k["name"].endswith(t["name"]) for k in keep):
            continue
        keep.append(t)
    keep.sort(key=lambda t: (t["pt"].y, t["pt"].x))
    return keep


# ---- the picture -----------------------------------------------------------------

class Plan:
    """A page rendered for room finding. Points in and out are screen
    (rotated) page coordinates (page.get_text() gives unrotated ones)."""

    def __init__(self, page, scale, claimed=True, check=None):
        page = cached_page(page)
        # check(): called between the slow steps; raises _Stop to end the
        # run (the caller's progress said stop, or the time budget is up)
        self.check = check or (lambda: None)
        if not available():
            raise AutoTakeoffError(
                "Auto takeoff needs numpy and OpenCV (pip install numpy "
                "opencv-python-headless).")
        if not scale or scale.get("ppu", 0) <= 0:
            raise AutoTakeoffError("Set the scale for this page first.")
        unit = scale.get("unit", "ft")
        if unit not in FT_PER_UNIT:
            raise AutoTakeoffError(f"Auto takeoff can't use {unit!r} units.")
        self.unit = unit
        self.ppu = scale["ppu"]                     # points per unit
        pts_per_ft = self.ppu / FT_PER_UNIT[unit]
        self.pts_per_ft = pts_per_ft
        r = page.rect
        zoom = TARGET_PPF / pts_per_ft
        zoom = min(zoom, math.sqrt(MAX_PIXELS / max(1.0, r.width * r.height)))
        self.zoom = zoom
        self.ppf = zoom * pts_per_ft                # pixels per foot
        if self.ppf < MIN_PPF:
            raise AutoTakeoffError(
                "This sheet's scale is too small for auto takeoff.")
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                              colorspace=fitz.csGRAY, annots=False,
                              alpha=False)
        gray = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.stride)[:, :pix.width]
        self.shape = gray.shape
        # words come unrotated; the picture is of the page as displayed
        m = page.rotation_matrix
        # A CAD sheet is drawn from its linework alone - no text at all, so
        # dimension strings and tags sitting on walls can't cut holes in
        # them. A scan (or a sheet that is mostly a picture) uses the
        # rendered page with the text boxes blanked.
        ink = vector_ink(page, zoom, gray.shape, m,
                         box_pts=2.5 * pts_per_ft,
                         gray_walls=(GRAY_WALL_FT[0] * pts_per_ft,
                                     GRAY_WALL_FT[1] * pts_per_ft))
        self.from_vectors = ink is not None
        self.check()
        # a second picture without the finest pen: fixtures, casework,
        # hatching and tag boxes are drawn with it, walls aren't. Each room
        # is looked for in both and the one that fits its tag is kept.
        heavy = None
        if ink is not None:
            pen = fine_pen(page)
            if pen:
                heavy = vector_ink(page, zoom, gray.shape, m,
                                   box_pts=2.5 * pts_per_ft,
                                   min_width=pen * 1.15)
        # linework that isn't on the sheet as printed - under a white mask
        # or cut off by a viewport clip (a legend left in the model under
        # the plan) - is not a wall (Oct 31, public bid set)
        if ink is not None:
            ink = visible_only(ink, gray)
        if heavy is not None:
            heavy = visible_only(heavy, gray)
        base = None
        if ink is not None:
            base = wall_mask(None, self.ppf, ink=ink)
            self.walls = base.copy()
        else:
            boxes = [(fitz.Rect(w[:4]) * m).normalize() * zoom
                     for w in page.get_text("words")]
            self.walls = wall_mask(gray, self.ppf, boxes)
        self.check()
        # CAD drawings draw walls hollow (two face lines). Closing and
        # opening the picture can't keep those reliably - thin partitions
        # are opened away and thick ones never fill - and text sitting on a
        # wall blanks a piece of it. The wall faces read from the linework
        # are drawn back in solid.
        self.vector_walls = 0
        # how far inside the wall face a trace runs (pixels): a quarter
        # pixel against filled (poche) walls, half the pen plus half a
        # pixel against stroked face lines (set by _vector_walls), half a
        # pixel on a scan
        self.inset_px = TRACE_INSET_PX if ink is not None else 0.5
        try:
            self._vector_walls(page, m)
        except Exception:
            log.warning("vector walls skipped", exc_info=True)
        # a sheet whose PDF keeps its walls on their own layers (A-WALL,
        # WALL-EXTR...): only what lies on those layers is a wall - not
        # fixture outlines, toilet partitions, dimensions or legend tables
        # paired into "faces" (Oct 31, public bid set: rooms came out at a
        # third of their dimensioned size)
        self.wall_layers = None
        self.wl = None
        self.partition_layers = []
        if ink is not None:
            names = wall_layers(page)
            if names:
                # toilet partitions are not room bounds (stall model)
                part = partition_layers(page, names, pts_per_ft)
                self.partition_layers = sorted(part)
                names = frozenset(names) - part
            if names:
                wl = vector_ink(page, zoom, gray.shape, m, layers=names)
                wl = visible_only(wl, gray) if wl is not None else None
                if wl is not None and wl.any():
                    self.wl = wl                # wall-layer ink only
                    k = max(3, int(round(WALL_LAYER_REACH_FT * self.ppf))
                            | 1)
                    near = cv2.dilate(wl, np.ones((k, k), np.uint8))
                    self.walls = (self.walls & near) | wall_mask(
                        None, self.ppf, ink=wl, island_ft=0)
                    base = base & near
                    if heavy is not None:
                        heavy = heavy & near
                    self.wall_layers = sorted(names)
        # a door drawn open (leaf + swing) leaves a gap in the wall; close
        # it along the door's closed position so the rooms on either side
        # stay apart
        self.doors_closed = 0
        try:
            self._close_doors(page, m, pts_per_ft)
        except Exception:
            log.warning("door closing skipped", exc_info=True)
        self.check()
        self.layers = [self.walls]
        if heavy is not None and heavy.any():
            hw = wall_mask(None, self.ppf, ink=heavy)
            # what the wall faces and closed doors added goes in both
            added = self.walls & (1 - base)
            self.layers.append(hw | added)
        self.layer = 0
        self._caches = [{} for _ in self.layers]
        self._cache = self._caches[0]
        if claimed:
            self.claim(existing_areas(page), grow=1)

    def use(self, i):
        """Work on wall picture i (0: every line, 1: without the finest
        pen)."""
        self.layer = i
        self.walls = self.layers[i]
        self._cache = self._caches[i]

    def _vector_walls(self, page, m):
        from . import autowalls
        unit = {"ft": "ft", "in": "in", "yd": "yd", "m": "m"}.get(self.unit)
        if unit is None:
            return
        # pair face lines drawn in the same style only: a wall's two faces
        # share a layer, while furniture or casework beside a wall doesn't
        from .tradetakeoff import styled_segments
        ws = []
        styled = _memo(page, "styled", lambda: styled_segments(page))
        pen = {}
        # the sheet's minor pen draws fixtures, casework and furniture: a
        # desk edge 6" from a chair edge is not a wall
        fine = fine_pen(page)
        for style, segs in styled.items():
            if len(segs) < 2:
                continue
            try:
                if fine and float(style[1]) <= fine * 1.15:
                    continue
            except (TypeError, ValueError, IndexError):
                pass
            try:
                got = autowalls.walls(page, self.ppu, unit, segs=segs)
            except autowalls.AutoWallsError:
                continue
            ws += got
            try:
                th = max(1, int(round(float(style[1]) * self.zoom)))
            except (TypeError, ValueError, IndexError):
                th = 1
            pen[th] = pen.get(th, 0.0) + sum(w["length"] for w in got)
        if pen:
            th = max(pen, key=pen.get)          # the pen most walls use
            self.inset_px = 0.5 + th / 2.0
        z = self.zoom
        for w in ws:
            (x0, y0), (x1, y1) = w["p0"], w["p1"]
            a = fitz.Point(x0, y0) * m
            b = fitz.Point(x1, y1) * m
            L = math.hypot(b.x - a.x, b.y - a.y)
            if L <= 0:
                continue
            th = w.get("measured", w["thickness"])
            half = th / 12 * self.ppf / 2 / z                 # in points
            ux, uy = (b.x - a.x) / L, (b.y - a.y) / L
            nx, ny = -uy * half, ux * half
            ex, ey = ux * half, uy * half                     # into corners
            poly = np.array([[(a.x - ex + nx) * z, (a.y - ey + ny) * z],
                             [(b.x + ex + nx) * z, (b.y + ey + ny) * z],
                             [(b.x + ex - nx) * z, (b.y + ey - ny) * z],
                             [(a.x - ex - nx) * z, (a.y - ey - ny) * z]],
                            np.int32)
            cv2.fillPoly(self.walls, [poly.reshape(-1, 1, 2)], 1)
            self.vector_walls += 1

    def _close_doors(self, page, m, pts_per_ft):
        z = self.zoom
        width = max(2, int(round(0.25 * self.ppf)))       # a 3 in line
        H, Wd = self.walls.shape
        near = max(2, int(round(0.4 * self.ppf)))

        def on_wall(x, y):
            return self.walls[max(0, y - near):min(H, y + near + 1),
                              max(0, x - near):min(Wd, x + near + 1)].any()
        for c, ends in door_swings(page, pts_per_ft):
            cc = c * m
            pts = [(int((e * m).x * z), int((e * m).y * z)) for e in ends]
            # the arc's latch end meets the far jamb; the other end is the
            # open leaf's tip, out on the floor - closing the door along
            # the leaf too would leave a 3' stub of wall in the room. When
            # it can't be told which is which, both are closed.
            touch = [p for p in pts if on_wall(*p)]
            for p in (touch if len(touch) == 1 else pts):
                cv2.line(self.walls, (int(cc.x * z), int(cc.y * z)), p, 1,
                         width)
            self.doors_closed += 1
        # bifold and accordion doors: zig-zag leaves across the opening -
        # close the opening from jamb to jamb when both ends touch a wall
        h, w = self.walls.shape
        near = max(2, int(0.5 * self.ppf))
        for a, b in bifolds(page, pts_per_ft):
            aa, bb = a * m, b * m
            ends = [(int(aa.x * z), int(aa.y * z)),
                    (int(bb.x * z), int(bb.y * z))]
            # one end on a jamb (two bifold pairs meet mid-opening)
            if any(self.walls[max(0, y - near):min(h, y + near + 1),
                              max(0, x - near):min(w, x + near + 1)].any()
                   for x, y in ends):
                cv2.line(self.walls, ends[0], ends[1], 1, width)
                self.doors_closed += 1

    # coordinates
    def to_px(self, pt):
        return pt.x * self.zoom, pt.y * self.zoom

    def to_pt(self, xy):
        return fitz.Point(float(xy[0]) / self.zoom, float(xy[1]) / self.zoom)

    def sqft(self, px_area):
        return px_area / self.ppf ** 2

    def to_units(self, sqft):
        return sqft / FT_PER_UNIT[self.unit] ** 2

    def claim(self, polys, grow=1):
        """Treat these polygons (screen points) as solid: rooms already
        measured become walls for the rooms around them."""
        if not polys:
            return
        m = np.zeros(self.shape, np.uint8)
        for poly in polys:
            arr = np.array([self.to_px(p) for p in poly], np.int32)
            cv2.fillPoly(m, [arr.reshape(-1, 1, 2)], 1)
        if grow:
            m = cv2.dilate(m, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
        cur = self.layer
        for i in range(len(self.layers)):
            self.layers[i] = self.layers[i] | m
            self._caches[i] = {}
        self.use(cur)

    def inside_walls(self, pt):
        x, y = (int(v) for v in self.to_px(pt))
        h, w = self.shape
        return not (0 <= x < w and 0 <= y < h) or bool(self.walls[y, x])

    # rooms
    def _dist(self):
        if "dist" not in self._cache:
            self._cache["dist"] = cv2.distanceTransform(
                (self.walls == 0).astype(np.uint8), cv2.DIST_L2,
                cv2.DIST_MASK_PRECISE)
        return self._cache["dist"]

    def _free(self, door):
        if door not in self._cache:
            self.check()
            r = int(math.ceil(door / 2 * self.ppf))
            # open floor at least half a door width from any wall (the
            # same as growing the walls by a disk, but one pass for all)
            free = (self._dist() > r).view(np.uint8)
            try:
                n, labels, stats, _c = \
                    cv2.connectedComponentsWithStatsWithAlgorithm(
                        free, 4, cv2.CV_32S, cv2.CCL_SAUF)
            except Exception:                  # older OpenCV
                n, labels, stats, _c = cv2.connectedComponentsWithStats(
                    free, connectivity=4)
            h, w = free.shape
            x, y, bw, bh = (stats[:, i] for i in range(4))
            leak = (x <= 0) | (y <= 0) | (x + bw >= w) | (y + bh >= h)
            self._cache[door] = (free, labels, stats, leak, r)
        return self._cache[door]

    def _region(self, seed, door, oth=None, max_px=None):
        """The room's outline (a contour, pixels) from the open space at
        `seed` with doors up to `door` ft bridged, or None. The tracing is
        done once per open space and shared by every seed in it.

        oth: int array (n, 2) of other rooms' tag pixels - a space holding
        one of them is turned down before any tracing (its outline would
        hold that tag). max_px: a space with more open floor than this
        (pixels; its outline can only be bigger) is turned down too."""
        free, labels, stats, leak, r = self._free(door)
        h, w = free.shape
        sx, sy = int(seed[0]), int(seed[1])
        if not (0 <= sx < w and 0 <= sy < h):
            return None
        if not free[sy, sx]:
            x0, y0 = max(0, sx - 3 * r), max(0, sy - 3 * r)
            ys, xs = np.nonzero(free[y0:sy + 3 * r, x0:sx + 3 * r])
            if len(xs) == 0:
                return None
            i = int(np.argmin((xs + x0 - sx) ** 2 + (ys + y0 - sy) ** 2))
            sx, sy = int(xs[i] + x0), int(ys[i] + y0)
        lab = int(labels[sy, sx])
        if lab == 0 or leak[lab]:
            return None
        if max_px is not None and stats[lab, cv2.CC_STAT_AREA] > max_px:
            return None
        if oth is not None and len(oth) and \
                (labels[oth[:, 1], oth[:, 0]] == lab).any():
            return None
        key = ("region", door, lab)
        if key not in self._cache:
            self._cache[key] = self._trace(labels, stats, lab, r)
        return self._cache[key]

    def _trace(self, labels, stats, lab, r):
        h, w = labels.shape
        bx, by, bw, bh = (int(v) for v in stats[lab, :4])
        x0, y0 = max(0, bx - r - 2), max(0, by - r - 2)
        x1, y1 = min(w, bx + bw + r + 2), min(h, by + bh + r + 2)
        region = (labels[y0:y1, x0:x1] == lab).astype(np.uint8)
        # grow back out to the wall faces; a square keeps corners square.
        # Open doorways are shut straight across the wall line first: the
        # square would otherwise push the room out through each doorway
        # (most of a foot at a 3' opening) and into the room beyond.
        sq = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
        stop = self.walls[y0:y1, x0:x1] | \
            self._doorways(x0, y0, x1, y1, 2 * r + 1)
        grown = cv2.dilate(region, sq) & (stop == 0)
        _n, lab2 = cv2.connectedComponents(grown, connectivity=4)
        hits = lab2[region > 0]
        hits = hits[hits > 0]
        if not len(hits):
            return None
        room = (lab2 == np.bincount(hits).argmax()).astype(np.uint8)
        cnts, _ = cv2.findContours(room, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        return c + np.array([[[x0, y0]]], dtype=c.dtype)

    def _doorways(self, x0, y0, x1, y1, k):
        """0/1 picture of the window (x0, y0)-(x1, y1): the openings in the
        walls narrower than k pixels, filled across the wall's thickness -
        what closing the walls with a k x k square adds, keeping only the
        thin fills (no deeper than DOORWAY_FT: a doorway through a wall,
        not a closet or a corridor narrower than the bridging)."""
        h, w = self.walls.shape
        X0, Y0 = max(0, x0 - k), max(0, y0 - k)
        X1, Y1 = min(w, x1 + k), min(h, y1 + k)
        W = self.walls[Y0:Y1, X0:X1]
        closed = cv2.morphologyEx(W, cv2.MORPH_CLOSE,
                                  np.ones((k, k), np.uint8))
        added = closed & (1 - W)
        out = np.zeros((y1 - y0, x1 - x0), np.uint8)
        if not added.any():
            return out
        n, lab, st, _c = cv2.connectedComponentsWithStats(added,
                                                          connectivity=8)
        thin = np.zeros(n, np.uint8)
        thin[1:] = np.minimum(st[1:, 2], st[1:, 3]) <= DOORWAY_FT * self.ppf
        bar = thin[lab]
        return bar[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0]

    def _near(self, seed, oth, expected, oth_px=None):
        """Candidates from points around `seed` (see detect)."""
        out = []
        cur = self.layer
        max_px = 3 * expected * self.ppf ** 2
        seen = set()
        for li in range(len(self.layers)):
            self.use(li)
            for d in CLOSET_DOORS:
                for sp in _near_seeds(seed, self.ppf):
                    c = self._region(sp, d, oth_px, max_px)
                    if c is None or id(c) in seen:
                        continue
                    seen.add(id(c))
                    a = self.sqft(cv2.contourArea(c))
                    if a > 3 * expected or _holds_any(c, oth):
                        continue
                    out.append((d, c, a, li))
        self.use(cur)
        return out

    def _fill_notches(self, c, ft):
        x, y, w, h = cv2.boundingRect(c)
        k = max(3, int(round(ft * self.ppf)) | 1)
        pad = k + 2
        m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
        cv2.drawContours(m, [c - np.array([[[x - pad, y - pad]]],
                                          dtype=c.dtype)], -1, 1, -1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c2 = max(cnts, key=cv2.contourArea)
        return c2 + np.array([[[x - pad, y - pad]]], dtype=c2.dtype)

    def _fill_to_faces(self, c, oth=()):
        """(contour, SF added): an untagged room's trace grown out to the
        wall-layer faces - into the notches fixtures, benches and casework
        built against the walls cut out of it, and the strip a trace leaves
        inside a face. Only floor within FACE_BAND_FT of the trace that no
        wall-layer ink bounds off; openings in a wall up to FACE_GAP_FT
        (doorways) are closed first, along the wall, so it never runs out
        through a door. Holding another room's tag, or adding more than
        FACE_MAX_GAIN of the room, leaves the trace as it was."""
        if self.wl is None:
            return c, 0.0
        band = max(2, int(round(FACE_BAND_FT * self.ppf)))
        k = max(3, int(round(FACE_GAP_FT * self.ppf)) | 1)
        x, y, w, h = cv2.boundingRect(c)
        pad = band + k + 2
        H, W = self.wl.shape[:2]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        off = np.array([[[x0, y0]]], dtype=c.dtype)
        t = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.drawContours(t, [c - off], -1, 1, -1)
        ink = cv2.dilate((self.wl[y0:y1, x0:x1] > 0).astype(np.uint8),
                         np.ones((3, 3), np.uint8))
        # openings up to FACE_GAP_FT are shut as doorways only between
        # wall-thick ink: filled poche, or two face lines up to
        # FACE_WALL_FT apart (a hollow-drawn wall). Thin wall-layer lines -
        # bench and seat outlines, door leaves and swings, grab bars,
        # shower curtains - still stop the fill, but a gap beside one is
        # floor, not a doorway (Oct 31, HMB 109: the 2'-9" passage beside a
        # shower bench was shut as a door and its floor left out)
        if FACE_WALL_FT:
            thick = wall_mask(None, self.ppf, ink=ink.copy(),
                              close_ft=FACE_WALL_FT, island_ft=0)
        else:
            thick = ink
        shut = np.maximum(
            cv2.morphologyEx(thick, cv2.MORPH_CLOSE, np.ones((1, k), np.uint8)),
            cv2.morphologyEx(thick, cv2.MORPH_CLOSE, np.ones((k, 1), np.uint8)))
        if FACE_WALL_FT and FACE_THIN_GAP_FT:
            # ...and narrow slots beside thin lines (a counter or curtain
            # line a few inches off a wall face) stay shut, as before
            k2 = max(3, int(round(FACE_THIN_GAP_FT * self.ppf)) | 1)
            shut = np.maximum(shut, np.maximum(
                cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                                 np.ones((1, k2), np.uint8)),
                cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                                 np.ones((k2, 1), np.uint8))))
        shut = np.maximum(shut, ink)
        grow = cv2.dilate(t, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * band + 1, 2 * band + 1)))
        cand = np.maximum(grow & (1 - shut) & (1 - ink), t)
        n, lab = cv2.connectedComponents(cand, connectivity=4)
        keep = [i for i in np.unique(lab[t > 0]) if i]
        r = np.isin(lab, keep).astype(np.uint8)
        bench = 0
        if BENCH_MAX_SF:
            r0 = int(r.sum())
            r = _with_benches(r, ink, thick, self.ppf)
            bench = int(r.sum()) - r0        # never counted against the gain
        cnts, _ = cv2.findContours(r, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return c, 0.0
        c2 = max(cnts, key=cv2.contourArea) + off
        a0, a2 = cv2.contourArea(c), cv2.contourArea(c2)
        if a2 <= a0 or a2 - bench > a0 * (1 + FACE_MAX_GAIN) or \
                _holds_any(c2, oth):
            return c, 0.0
        return c2, self.sqft(a2 - a0)

    def detect(self, seed_pt, others=(), expected=None, door=None,
               max_sf=None, strict=False):
        """The room around `seed_pt` (screen point). `others`: tag points
        of other rooms, which it may not swallow; `expected`: the room's
        tagged area in sq ft; `max_sf`: no bigger than this (a room named
        without an area). `strict`: every other tag counts, even one
        printed on a wall (normally those are let through: such a tag
        can't say which room it's in). Returns {"pts", "sqft", "door",
        "perim_ft"} or None."""
        seed = self.to_px(seed_pt)
        dist = self._dist()
        h, w = self.shape
        oth = []
        for p in others:
            x, y = self.to_px(p)
            # a tag printed on or against a wall can't say which room it's in
            if 0 <= int(x) < w and 0 <= int(y) < h and \
                    (strict or dist[int(y), int(x)] > 0.75 * self.ppf):
                oth.append((float(x), float(y)))
        oth_px = np.array(oth, np.int32).reshape(-1, 2) if oth else None
        cap = 3 * expected if expected else max_sf
        max_px = cap * self.ppf ** 2 if cap else None
        cands = []
        cur = self.layer
        seen = set()
        # door widths nearest the standard opening first; stop at a trace
        # that already matches its tag (untagged: the first one found - the
        # one nearest the standard opening is the one kept anyway). With
        # the doorways shut across the wall line every width that closes a
        # room gives the same outline, and each width's open-space map is a
        # pass over the whole sheet, so widths no room needs are never
        # worked out.
        steps = (door,) if door else DOOR_ORDER
        done = False
        for li in (range(len(self.layers)) if expected else (cur,)):
            self.use(li)
            for d in steps:
                self.check()
                c = self._region(seed, d, oth_px, max_px)
                if c is None or id(c) in seen:
                    continue
                seen.add(id(c))
                if _holds_any(c, oth):
                    continue
                a = self.sqft(cv2.contourArea(c))
                cands.append((d, c, a, li))
                if not expected or abs(a - expected) <= EARLY_DIFF * expected:
                    done = True
                    break
            if done:
                break
        self.use(cur)
        if expected and expected <= SMALL_ROOM_SF and not any(
                abs(t[2] - expected) <= 0.5 * expected for t in cands):
            # a closet: its tag often sits on or across a wall, and the
            # room is narrower than the usual door bridging - look a few
            # feet around the tag, with narrower bridging too
            cands += self._near(seed, oth, expected, oth_px)
        if not cands:
            return None
        face_sf = 0.0
        if expected:
            d, c, _a, li = min(cands, key=lambda t: abs(t[2] - expected))
            self.use(li)
            # fixtures and casework built against the walls (toilets,
            # counters) bite notches out of the floor; the tag counts that
            # floor, so try filling notches narrower than a few feet
            for ft in FILL_NOTCH_FT:
                c2 = self._fill_notches(c, ft)
                a2 = self.sqft(cv2.contourArea(c2)) if c2 is not None else 0
                if c2 is not None and abs(a2 - expected) < \
                        abs(self.sqft(cv2.contourArea(c)) - expected):
                    c = c2
        else:
            d, c, _a, li = min(cands, key=lambda t: abs(t[0] - DEFAULT_DOOR))
            if door is None:
                # stalls: bridge only narrow gaps and keep the pockets that
                # open off the room (stalls_join)
                self.use(li)
                for dn in STALL_DOORS:
                    if dn >= d:
                        break
                    c2 = self._region(seed, dn, oth_px, max_px)
                    if c2 is None or _holds_any(c2, oth):
                        continue
                    if stalls_join(c, c2, self.ppf):
                        d, c = dn, c2
                        break
                c = join_pockets(c, self.walls, self.ppf, oth)
            # out to the wall-layer faces (fixture notches, edge strip)
            c, face_sf = self._fill_to_faces(c, oth)
        self.use(cur)
        poly = cv2.approxPolyDP(c, SIMPLIFY_FT * self.ppf, True).reshape(-1, 2)
        if len(poly) < 3:
            return None
        arr = poly.reshape(-1, 1, 2)
        area_px = cv2.contourArea(arr)
        perim_px = cv2.arcLength(arr, True)
        # the outline runs through the centres of the room's edge pixels,
        # which start inside the wall face by half the face line's pen (a
        # stroke is drawn centred on the face) and half a pixel: put back
        # that strip all round, or a 10' x 10' room drawn with a heavy pen
        # comes out short by a square foot or two
        area_px += perim_px * self.inset_px
        perim_px += 8 * self.inset_px
        sqft = self.sqft(area_px)
        if sqft < 4:
            return None
        return {"pts": [self.to_pt(p) for p in poly], "sqft": sqft,
                "door": d, "perim_ft": perim_px / self.ppf,
                "face_fill_sf": round(face_sf, 1)}


FACE_BAND_FT = 2.0      # an untagged trace grows at most this far to a face
FACE_GAP_FT = 3.0       # wall openings up to this are closed first (doors)
FACE_MAX_GAIN = 0.15    # ...and never by more than this share of the room
FACE_FLAG_PCT = 4.0     # a fill this big (% of the room) is flagged
FACE_WALL_FT = 1.0      # face lines this close make a wall a doorway is shut in (0: any ink)
FACE_THIN_GAP_FT = 1.0  # gaps up to this beside any wall-layer line stay shut
BENCH_MAX_SF = 8.0      # a space closed off by a thin outline up to this is a
BENCH_MAX_DEPTH_FT = 3.0  # built-in bench (no deeper than this): its floor counts
BENCH_EDGE_SHARE = 0.4  # ...when this much of its edge is that outline
BENCH_LINE_FT = 0.25    # an outline no wider than this (3") parts it from the floor
STALL_DOORS = (1.4, 2.2, 3.0)  # narrow bridging tried for an untagged room
STALL_MAX_SF = 40.0          # a stall / shower / alcove pocket, at most
POCKET_SF = 40.0             # a usual trace under this is the tag's pocket
POCKET_ROOM_MAX_SF = 400.0   # ...and the room found instead at most this


def stalls_join(usual, narrow, ppf):
    """Partition / stall model (Oct 31, round 2): does the trace with only
    narrow gaps bridged (`narrow`, a contour) stand for the room better
    than the one at the usual door width (`usual`)? Yes when everything it
    adds comes in stall-sized pockets (toilet and shower stalls, alcoves
    entered through an opening with no door), or when the usual trace is
    too small to be a named room (the tag sat in a pocket) and the narrow
    one is room-sized. A big space beyond a narrow gap is another room."""
    a_u = cv2.contourArea(usual) / ppf ** 2
    a_n = cv2.contourArea(narrow) / ppf ** 2
    if a_n <= a_u:
        return False
    x0, y0, w0, h0 = cv2.boundingRect(np.vstack([usual, narrow]))
    off = np.array([[[x0 - 4, y0 - 4]]], dtype=usual.dtype)
    mu = np.zeros((h0 + 8, w0 + 8), np.uint8)
    mn = np.zeros_like(mu)
    cv2.drawContours(mu, [usual - off], -1, 1, -1)
    cv2.drawContours(mn, [narrow - off.astype(narrow.dtype)], -1, 1, -1)
    mu = cv2.dilate(mu, np.ones((5, 5), np.uint8))
    extra = (mn & (1 - mu)).astype(np.uint8)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(extra, connectivity=4)
    pieces = [st[i, cv2.CC_STAT_AREA] / ppf ** 2 for i in range(1, n)]
    if all(p <= STALL_MAX_SF for p in pieces):
        return True
    return a_u < POCKET_SF and a_n <= POCKET_ROOM_MAX_SF


THIN_LINE_FT = 0.2           # a line this thin is a curtain / sill, not a wall
STALL_MIN_FT = 2.0           # a pocket narrower than this is a wall's core


def join_pockets(c, walls, ppf, others=()):
    """Stall model, part 2: the room outline `c` (contour, pixels) with
    the closed pockets just behind a thin line - a shower curtain across a
    stall, a sill line - added: each pocket at most STALL_MAX_SF, at least
    STALL_MIN_FT across (a hollow wall's core is not a stall), not open to
    the sheet's edge and holding no other room's tag (`others`, pixels).
    A real wall (thicker than THIN_LINE_FT) keeps the space behind it out.
    Returns the new contour (or `c` unchanged)."""
    h, w = walls.shape
    x, y, bw, bh = cv2.boundingRect(c)
    pad = int(math.ceil(math.sqrt(STALL_MAX_SF) * 2 * ppf))
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(w, x + bw + pad), min(h, y + bh + pad)
    W = walls[Y0:Y1, X0:X1]
    off = np.array([[[X0, Y0]]], dtype=c.dtype)
    room = np.zeros(W.shape, np.uint8)
    cv2.drawContours(room, [c - off], -1, 1, -1)
    reach = max(2, int(round(THIN_LINE_FT * ppf)))
    ring = cv2.dilate(room, np.ones((2 * reach + 1, 2 * reach + 1),
                                    np.uint8)) & (1 - room)
    free = ((W == 0) & (room == 0)).astype(np.uint8)
    n, lab, st, _cc = cv2.connectedComponentsWithStats(free, connectivity=4)
    hit = np.unique(lab[(ring > 0) & (free > 0)])
    H, Wd = W.shape
    add = np.zeros_like(room)
    oth = [(int(px - X0), int(py - Y0)) for px, py in others or ()
           if 0 <= px - X0 < Wd and 0 <= py - Y0 < H]
    for k in hit:
        if k == 0:
            continue
        bx, by, ww, hh, area = (int(v) for v in st[k])
        if bx <= 0 or by <= 0 or bx + ww >= Wd or by + hh >= H:
            continue                      # open to the window's edge
        if area / ppf ** 2 > STALL_MAX_SF or \
                min(ww, hh) < STALL_MIN_FT * ppf:
            continue
        if any(lab[py, px] == k for px, py in oth):
            continue
        add |= (lab == k).astype(np.uint8)
    if not add.any():
        return c
    # the thin line between them is part of the room's floor
    k3 = 2 * reach + 1
    joined = cv2.morphologyEx(room | add, cv2.MORPH_CLOSE,
                              np.ones((k3, k3), np.uint8))
    joined &= (room | add | ((W > 0) & (cv2.dilate(add, np.ones(
        (k3, k3), np.uint8)) > 0) & (cv2.dilate(room, np.ones(
            (k3, k3), np.uint8)) > 0))).astype(np.uint8)
    cnts, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return c
    best = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(best) <= cv2.contourArea(c - off):
        return c
    return best + off


def _holds_any(c, pts):
    """Does contour `c` (pixels) hold any of the points (x, y)?"""
    if not pts:
        return False
    x, y, w, h = cv2.boundingRect(c)
    for p in pts:
        if x <= p[0] <= x + w and y <= p[1] <= y + h and \
                cv2.pointPolygonTest(c, (float(p[0]), float(p[1])),
                                     False) >= 0:
            return True
    return False


def _zigzags(page):
    """Line chains of 3-9 points that zig-zag (every turn 90-170 degrees,
    alternating): [(start, end, shortest leaf, longest leaf)], read once
    per page (bifolds filters them by the sheet's scale)."""
    def build():
        try:
            paths = page.get_drawings()
        except Exception:
            return []
        out = []
        for p in paths:
            for chain in _line_chains(p.get("items", ())):
                if not 3 <= len(chain) <= 9:
                    continue
                segs = [abs(chain[i + 1] - chain[i])
                        for i in range(len(chain) - 1)]
                turns = []
                for i in range(1, len(chain) - 1):
                    a, b, c = chain[i - 1], chain[i], chain[i + 1]
                    t = math.degrees(math.atan2(c.y - b.y, c.x - b.x) -
                                     math.atan2(b.y - a.y, b.x - a.x))
                    turns.append((t + 180) % 360 - 180)
                if not all(90 <= abs(t) <= 170 for t in turns):
                    continue
                if any((turns[i] > 0) == (turns[i + 1] > 0)
                       for i in range(len(turns) - 1)):
                    continue                    # must zig, then zag
                out.append((chain[0], chain[-1], min(segs), max(segs)))
        return out
    return _memo(page, "zigzags", build)


def _straight_lines(page):
    """Every straight line item on the page: (n, 4) array x0 y0 x1 y1 and
    their lengths, read once."""
    def build():
        try:
            paths = page.get_drawings()
        except Exception:
            paths = []
        ab = [(it[1].x, it[1].y, it[2].x, it[2].y) for p in paths
              for it in p.get("items", ()) if it[0] == "l"]
        arr = np.array(ab, float).reshape(-1, 4)
        return arr, np.hypot(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1])
    return _memo(page, "straight", build)


def bifolds(page, pts_per_ft, leaf=(0.6, 2.5), span=(2.0, 8.0)):
    """Bifold / accordion door symbols: zig-zag runs of 2-8 straight
    leaves, each 0.6-2.5 ft, turning sharply back and forth. Returns
    [(start, end)] page points - the opening they cover."""
    lo, hi = leaf[0] * pts_per_ft, leaf[1] * pts_per_ft
    out = []
    for a, b, smin, smax in _zigzags(page):
        if lo <= smin and smax <= hi:
            L = abs(b - a)
            if span[0] * pts_per_ft <= L <= span[1] * pts_per_ft:
                out.append((a, b))
    # a pair of leaves drawn as a "V" (often two separate strokes): two
    # leaf-long lines meeting at the fold - the opening is between their
    # far ends
    arr, lens = _straight_lines(page)
    sel = arr[(lens >= lo) & (lens <= hi)]
    segs = [(fitz.Point(s[0], s[1]), fitz.Point(s[2], s[3])) for s in sel]
    tip = {}
    snap = max(0.5, 0.04 * pts_per_ft)
    for i, (a, b) in enumerate(segs):
        for end, far in ((a, b), (b, a)):
            tip.setdefault((round(end.x / snap), round(end.y / snap)),
                           []).append((i, far, end))
    seen = set()
    for hits in tip.values():
        if len(hits) != 2 or hits[0][0] == hits[1][0]:
            continue
        (i, f1, apex), (j, f2, _e) = hits
        key = tuple(sorted((i, j)))
        if key in seen:
            continue
        seen.add(key)
        v1, v2 = f1 - apex, f2 - apex
        n1, n2 = abs(v1), abs(v2)
        if not n1 or not n2 or abs(n1 - n2) > 0.25 * max(n1, n2):
            continue                       # the leaves are the same size
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (v1.x * v2.x +
                                                         v1.y * v2.y) /
                                                     (n1 * n2)))))
        L = abs(f2 - f1)
        if 15 <= ang <= 80 and 1.0 * pts_per_ft <= L <= span[1] * \
                pts_per_ft:
            out.append((f1, f2))
    return out


def _near_seeds(seed, ppf, rings=(1.0, 2.0, 3.0), n=8):
    out = []
    for r in rings:
        for k in range(n):
            ang = 2 * math.pi * k / n
            out.append((seed[0] + r * ppf * math.cos(ang),
                        seed[1] + r * ppf * math.sin(ang)))
    return out


def _circle3(a, b, c):
    """Centre and radius of the circle through three points, or None."""
    ax, ay, bx, by, cx, cy = a.x, a.y, b.x, b.y, c.x, c.y
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    ctr = fitz.Point(ux, uy)
    return ctr, abs(ctr - a)


def _line_chains(items):
    """Runs of straight lines joined end to end: [[Point, ...], ...]."""
    out, cur = [], []
    for it in items:
        if it[0] != "l":
            if len(cur) > 2:
                out.append(cur)
            cur = []
            continue
        a, b = it[1], it[2]
        if cur and abs(cur[-1] - a) < 0.05:
            cur.append(b)
        else:
            if len(cur) > 2:
                out.append(cur)
            cur = [a, b]
    if len(cur) > 2:
        out.append(cur)
    return out


def _bends(chain, lo=0.5, hi=30.0):
    """Pieces of a polyline that bend steadily one way (an arc drawn as
    short lines): lists of 4 or more points."""
    turns = []
    for i in range(1, len(chain) - 1):
        a, b, c = chain[i - 1], chain[i], chain[i + 1]
        t = math.degrees(math.atan2(c.y - b.y, c.x - b.x)
                         - math.atan2(b.y - a.y, b.x - a.x))
        t = (t + 180) % 360 - 180
        turns.append(t)
    runs, start = [], None
    for i, t in enumerate(turns + [0.0]):
        ok = lo <= abs(t) <= hi and (start is None or
                                     (t > 0) == (turns[start] > 0))
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            pts = chain[start:i + 2]
            if len(pts) >= 4:
                runs.append(pts)
            start = i if lo <= abs(t) <= hi else None
    return runs


def _arc_fit(pts, rmin, rmax):
    """[centre, radius, [end, end], sweep] when the points lie on a circle
    of radius rmin..rmax, else None."""
    got = _circle3(pts[0], pts[len(pts) // 2], pts[-1])
    if got is None:
        return None
    ctr, r = got
    if not rmin <= r <= rmax:
        return None
    if any(abs(abs(q - ctr) - r) > 0.04 * r for q in pts):
        return None
    sweep = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.atan2(b.y - ctr.y, b.x - ctr.x) - \
            math.atan2(a.y - ctr.y, a.x - ctr.x)
        sweep += abs((d + math.pi) % (2 * math.pi) - math.pi)
    return [ctr, r, [pts[0], pts[-1]], sweep]


SWING_R_PT = (3.0, 1500.0)     # radii (points) kept when arcs are read


def _swing_arcs(page):
    """Every circular arc on the page 3-1500 points in radius, the pieces
    of one arc merged: [[centre, radius, [ends], sweep]], read once per
    page (door_swings filters it by the sheet's scale). Pieces are matched
    through a grid on their centres, not against every arc found so far
    (that was quadratic on sheets with many arcs)."""
    def build():
        try:
            paths = page.get_drawings()
        except Exception:
            return []
        rmin, rmax = SWING_R_PT
        arcs = []
        for p in paths:
            for it in p.get("items", ()):
                if it[0] != "c":
                    continue
                p0, p1, p2, p3 = it[1:5]
                mid = (p0 * 0.125 + p1 * 0.375 + p2 * 0.375 + p3 * 0.125)
                got = _circle3(p0, mid, p3)
                if got is None:
                    continue
                ctr, r = got
                if not rmin <= r <= rmax:
                    continue
                a0 = math.atan2(p0.y - ctr.y, p0.x - ctr.x)
                a1 = math.atan2(p3.y - ctr.y, p3.x - ctr.x)
                sweep = abs((a1 - a0 + math.pi) % (2 * math.pi) - math.pi)
                arcs.append([ctr, r, [p0, p3], sweep])
            # many CAD exports (Revit among them) draw arcs as runs of
            # short straight lines
            for chain in _line_chains(p.get("items", ())):
                for run in _bends(chain):
                    got = _arc_fit(run, rmin, rmax)
                    if got:
                        arcs.append(got)
        # pieces of one swing share a centre and radius: merge them
        merged = []
        G = 6.0
        grid = {}
        for ctr, r, ends, sweep in arcs:
            tol = 0.08 * r
            k = int(math.ceil(tol / G))
            gx, gy = int(ctr.x // G), int(ctr.y // G)
            hit = None
            for ix in range(gx - k, gx + k + 1):
                for iy in range(gy - k, gy + k + 1):
                    for q in grid.get((ix, iy), ()):
                        mm = merged[q]
                        if (hit is None or q < hit) and \
                                abs(mm[0] - ctr) < tol and \
                                abs(mm[1] - r) < tol:
                            hit = q
            if hit is not None:
                mm = merged[hit]
                # joined end to end: drop the shared end
                for e in ends:
                    x = next((x for x in mm[2] if abs(x - e) < 0.05 * r),
                             None)
                    if x is not None:
                        mm[2].remove(x)
                    else:
                        mm[2].append(e)
                mm[3] += sweep
            else:
                grid.setdefault((gx, gy), []).append(len(merged))
                merged.append([ctr, r, list(ends), sweep])
        return merged
    return _memo(page, "swing_arcs", build)


def door_swings(page, pts_per_ft, min_ft=1.0, max_ft=4.6):
    """Door swings on the page: [(hinge point, [the two arc ends])] in
    unrotated page points. A swing is a quarter circle (often drawn as
    one or two curves, or many short lines) 1-4.6 ft in radius - bifold
    leaves are small; its centre is the hinge, one end the tip of the open
    leaf, the other the latch side of the opening."""
    out = []
    leaves = None
    lo, hi = min_ft * pts_per_ft, max_ft * pts_per_ft
    for ctr, r, ends, sweep in _swing_arcs(page):
        if len(ends) != 2 or not lo <= r <= hi:
            continue
        if math.radians(70) <= sweep <= math.radians(110):
            out.append((ctr, ends))
        elif math.radians(35) <= sweep < math.radians(70):
            # a leaf drawn part open (pairs of doors, double-acting
            # doors): only when the leaf itself is drawn - a straight line
            # from the hinge to one end of the arc
            if leaves is None:
                arr, lens = _straight_lines(page)
                leaves = arr[lens >= lo]
            tol = 0.08 * r
            if _leaf_at(leaves, ctr, ends, tol):
                out.append((ctr, ends))
    return out


def _leaf_at(leaves, ctr, ends, tol):
    """Is one of the straight lines `leaves` ((n, 4) array of x0 y0 x1 y1)
    drawn from the hinge `ctr` to one of the arc's `ends`?"""
    if np is None or not isinstance(leaves, np.ndarray):
        return any((math.hypot(a0 - ctr.x, a1 - ctr.y) < tol and
                    math.hypot(b0 - e.x, b1 - e.y) < tol) or
                   (math.hypot(b0 - ctr.x, b1 - ctr.y) < tol and
                    math.hypot(a0 - e.x, a1 - e.y) < tol)
                   for a0, a1, b0, b1 in leaves for e in ends)
    if not len(leaves):
        return False
    da = np.hypot(leaves[:, 0] - ctr.x, leaves[:, 1] - ctr.y) < tol
    db = np.hypot(leaves[:, 2] - ctr.x, leaves[:, 3] - ctr.y) < tol
    for e in ends:
        ea = np.hypot(leaves[:, 0] - e.x, leaves[:, 1] - e.y) < tol
        eb = np.hypot(leaves[:, 2] - e.x, leaves[:, 3] - e.y) < tol
        if (da & eb).any() or (db & ea).any():
            return True
    return False


def fine_pen(page):
    """The finest line weight on a CAD sheet (points) when it is a minor
    pen - lighter lines than the walls are drawn with - else None."""
    return _memo(page, "fine_pen", lambda: _fine_pen(page))


def _fine_pen(page):
    from collections import Counter
    try:
        paths = page.get_drawings()
    except Exception:
        return None
    use = Counter()
    for p in paths:
        w = p.get("width")
        if w and p.get("type") in ("s", "fs") and _dark(p.get("color")):
            r = p.get("rect")
            use[round(w, 2)] += (r.width + r.height) if r else 1
    if len(use) < 2:
        return None
    # hairline pens (up to ~0.1 mm) draw fixtures, casework, hatching and
    # tag boxes; walls are drawn heavier
    fine = [k for k in use if k <= FINE_PEN_PT]
    if not fine:
        fine = [min(use)]
    top = max(fine)
    heavier = sum(v for k, v in use.items() if k > top * 1.15)
    if top >= 0.6 or heavier < 0.2 * sum(use.values()):
        return None
    return top


_BEZ_T = None


def _bezier_np(p0, p1, p2, p3, n=10):
    """_bezier as an (n + 1, 2) array."""
    global _BEZ_T
    if _BEZ_T is None or len(_BEZ_T) != n + 1:
        _BEZ_T = np.linspace(0.0, 1.0, n + 1)
    t = _BEZ_T[:, None]
    u = 1 - t
    P = np.array([[p0.x, p0.y], [p1.x, p1.y], [p2.x, p2.y], [p3.x, p3.y]])
    return (u ** 3 * P[0] + 3 * u * u * t * P[1] + 3 * u * t * t * P[2] +
            t ** 3 * P[3])


def _ink_geom(page):
    """The page's linework, read once and kept in page points (unrotated):
    every path's outlines as one array, which paths count as wall ink,
    and for each small closed outline how close a word sits inside it (a
    tag's box). vector_ink only scales and draws it - at each scale the
    sheet is looked at - instead of walking every drawing again (that walk
    is most of the time on a dense sheet)."""
    def build():
        try:
            paths = page.get_drawings()
        except Exception:
            return None
        polys, path_rows = [], []
        for p in paths:
            first = len(polys)
            cur = []

            def flush():
                if len(cur) > 1:
                    polys.append(np.array(cur, float))
            for it in p.get("items", ()):
                k = it[0]
                if k == "l":
                    a = (it[1].x, it[1].y)
                    b = (it[2].x, it[2].y)
                    if cur and abs(cur[-1][0] - a[0]) < 1e-3 and \
                            abs(cur[-1][1] - a[1]) < 1e-3:
                        cur.append(b)
                    else:
                        flush()
                        cur = [a, b]
                elif k == "c":
                    pts = _bezier_np(*it[1:5])
                    if cur and abs(cur[-1][0] - pts[0][0]) < 1e-3 and \
                            abs(cur[-1][1] - pts[0][1]) < 1e-3:
                        cur += [tuple(q) for q in pts[1:]]
                    else:
                        flush()
                        cur = [tuple(q) for q in pts]
                elif k == "re":
                    r = fitz.Rect(it[1])
                    flush()
                    cur = []
                    polys.append(np.array([(r.x0, r.y0), (r.x1, r.y0),
                                           (r.x1, r.y1), (r.x0, r.y1),
                                           (r.x0, r.y0)], float))
                elif k == "qu":
                    qd = it[1]
                    flush()
                    cur = []
                    polys.append(np.array([(q.x, q.y) for q in
                                           (qd.ul, qd.ur, qd.lr, qd.ll,
                                            qd.ul)], float))
            flush()
            if len(polys) == first:
                continue
            width = p.get("width") or 0
            opaque = p.get("fill_opacity") is None or p["fill_opacity"] >= 0.9
            fill = p.get("fill") is not None and \
                p.get("type") in ("f", "fs") and \
                _dark(p.get("fill"), 0.45) and opaque
            if not fill and opaque and p.get("type") == "f" and \
                    p.get("fill") is not None and \
                    _dark(p.get("fill"), GRAY_POCHE_LEVEL) and \
                    _neutral(p.get("fill")):
                # mid-grey solid poche: existing walls drawn grey under the
                # new black ones (Oct 31, held-out courthouse set). Kept as
                # its mean thickness in points; vector_ink fills it only
                # when that is wall-thin at the sheet's scale
                fill = _thickness_pts(polys[first:]) or False
            dashed = str(p.get("dashes") or "[]").replace(" ", "")[:2] != "[]"
            stroke = p.get("type") in ("s", "fs") and \
                _dark(p.get("color")) and not dashed and \
                (p.get("stroke_opacity") is None or
                 p["stroke_opacity"] >= 0.9) and \
                (p.get("fill_opacity") is None or p["fill_opacity"] >= 0.9)
            if fill or stroke:
                path_rows.append((first, len(polys), width, fill, stroke,
                                  p.get("layer") or ""))
        n = len(polys)
        g = {"n_paths": len(paths), "rows": path_rows, "n": n}
        if not n:
            g.update(all=np.zeros((0, 2)), offs=np.zeros(1, int))
            return g
        lens = np.array([len(a) for a in polys])
        g["all"] = np.concatenate(polys)
        g["offs"] = np.concatenate([[0], np.cumsum(lens)])
        lo = np.array([a.min(axis=0) for a in polys])
        hi = np.array([a.max(axis=0) for a in polys])
        g["lo"], g["hi"], g["npts"] = lo, hi, lens
        g["gap"] = np.array([np.abs(a[0] - a[-1]).max() for a in polys])
        # how far a word pokes out of each small closed outline (0: a word
        # lies inside it); only outlines up to 4" across are tag boxes
        need = np.full(n, np.inf)
        size = (hi - lo).max(axis=1)
        cand = np.nonzero((lens >= 4) & (size <= 288))[0]
        if len(cand):
            G = 48.0
            grid = {}
            try:
                for wd in page.get_text("words"):
                    grid.setdefault((int(wd[0] // G), int(wd[1] // G)),
                                    []).append(wd[:4])
            except Exception:
                grid = {}
            for i in cand:
                x0, y0 = lo[i]
                x1, y1 = hi[i]
                best = np.inf
                for gx in range(int(x0 // G) - 1, int(x1 // G) + 1):
                    for gy in range(int(y0 // G) - 1, int(y1 // G) + 1):
                        for w in grid.get((gx, gy), ()):
                            out = max(x0 - w[0], y0 - w[1], w[2] - x1,
                                      w[3] - y1, 0.0)
                            if out < best:
                                best = out
                need[i] = best
        g["need"] = need
        return g
    return _memo(page, "ink_geom", build)


def vector_ink(page, zoom, shape, m=None, min_paths=60, box_pts=0,
               min_width=None, layers=None, gray_walls=None):
    """The page's linework (no text) drawn at `zoom` into a 0/1 image the
    size `shape`, or None when the page isn't vector linework (a scan).
    `box_pts`: boxes drawn round text (room number tags) smaller than this
    many points across are left out - in a closet the tag box can fill
    most of the floor. `layers`: only paths on these PDF layers.
    `gray_walls` (lo, hi points): mid-grey solid fills whose mean
    thickness is in that range are walls too (existing walls drawn grey)."""
    g = _ink_geom(page)
    if g is None or g["n_paths"] < min_paths:
        return None
    try:                                  # mostly a picture: a scan
        area = page.rect.width * page.rect.height
        img = sum(fitz.Rect(i["bbox"]).get_area()
                  for i in page.get_image_info())
        if area and img > 0.5 * area:
            return None
    except Exception:
        pass
    if not g["n"]:
        return None
    m = m if m is not None else page.rotation_matrix
    ink = np.zeros(shape, np.uint8)
    if min_width is None:
        min_width = float(os.environ.get("QUANTISHEET_ROOMS_MINW", "0") or 0)
    R = np.array([[m.a, m.b], [m.c, m.d]], float) * zoom
    t = np.array([m.e, m.f], float) * zoom
    P = np.rint(g["all"] @ R + t).astype(np.int32)
    arrs = np.split(P, g["offs"][1:-1])
    drop = None
    if box_pts:
        # a small closed outline with a word inside: a tag's box (2 pixels
        # of slack, as the outline is drawn); 90-degree turns keep sizes
        px = 2.0 / zoom
        sz = g["hi"] - g["lo"]
        drop = (g["npts"] >= 4) & (sz.max(axis=1) <= box_pts) & \
            (sz.min(axis=1) * zoom >= 2) & (g["gap"] <= px) & \
            (g["need"] <= px)
    strokes = {}
    for first, last, width, fill, stroke, layer in g["rows"]:
        if layers is not None and layer not in layers:
            continue
        keep = [arrs[i].reshape(-1, 1, 2) for i in range(first, last)
                if drop is None or not drop[i]]
        if not keep:
            continue
        # solid poche (near-black, opaque) fills walls; pale or see-through
        # fills are room colours, patterns and masks - not walls
        if fill is True or (fill and gray_walls and
                            gray_walls[0] <= fill <= gray_walls[1]):
            cv2.fillPoly(ink, keep, 1)
        # see-through shapes are markups (flattened takeoff, clouds),
        # never the drawing's own walls
        if stroke and width >= min_width:
            strokes.setdefault(max(1, int(round(width * zoom))),
                               []).extend(keep)
    for th, lst in strokes.items():
        cv2.polylines(ink, lst, False, 1, th)
    if not ink.any():
        return None
    return ink


# PDF layers (optional content) that hold walls: the US National CAD
# Standard A-WALL / I-WALL family and the usual "WALL-EXTR", "WALL-INTR",
# "0 | WALL-PARTITIONS" names. Not wall types, tags, patterns or legends.
WALL_LAYER = re.compile(r"(?:^|[^A-Z])WALLS?(?:[^A-Z]|$)", re.I)
NOT_WALL_LAYER = re.compile(r"PATT|HATCH|IDEN|TAG|TEXT|NOTE|ANNO|DIM|SYMB|"
                            r"LEGEND|ELEV|DEMO|EXIST.*REMOV|TRIM|HEAD|"
                            r"CABINET|CASE", re.I)
WALL_LAYER_MIN_PATHS = 20


def wall_layers(page):
    """The names of this page's PDF layers that hold its walls, or None
    when the sheet has no such layers (most PDFs: the walls are then
    read from all the linework, as before)."""
    def build():
        try:
            paths = page.get_drawings()
        except Exception:                                # noqa: BLE001
            return None
        count = {}
        for p in paths:
            lay = p.get("layer") or ""
            if lay and WALL_LAYER.search(lay) and \
                    not NOT_WALL_LAYER.search(lay):
                count[lay] = count.get(lay, 0) + 1
        if sum(count.values()) < WALL_LAYER_MIN_PATHS:
            return None
        return frozenset(count)
    return _memo(page, "wall_layers", build)


PARTITION_LAYER = re.compile(r"PARTITION|TOILET|STALL|TPTN|PRTN", re.I)
PARTITION_MAX_IN = 2.0       # toilet partitions are about 1" thick


def partition_layers(page, names, pts_per_ft):
    """The wall layers in `names` that hold toilet / shower partitions, not
    walls: named like partitions and drawn thinner than PARTITION_MAX_IN
    (the median of their filled shapes' short side). NCS 'A-WALL-PRTN'
    holds real interior walls (4" and up) and stays a wall layer."""
    sizes = {}
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return set()
    for p in paths:
        lay = p.get("layer") or ""
        if lay in names and PARTITION_LAYER.search(lay) and p.get("fill"):
            r = p["rect"]
            short = min(abs(r.width), abs(r.height))
            if short > 0:
                sizes.setdefault(lay, []).append(short / pts_per_ft * 12)
    out = set()
    for lay, v in sizes.items():
        v.sort()
        if len(v) >= 3 and v[len(v) // 2] <= PARTITION_MAX_IN:
            out.add(lay)
    return out


WALL_LAYER_REACH_FT = 0.5    # wall faces kept this close to wall-layer ink
VISIBLE_LEVEL = 250          # rendered grey darker than this is printed
VISIBLE_SLACK_PX = 2         # pen width and anti-aliasing


def visible_only(ink, gray, level=VISIBLE_LEVEL, slack=VISIBLE_SLACK_PX):
    """`ink` (0/1, from vector_ink) kept only where the rendered sheet
    `gray` (same size) shows something within `slack` pixels. Paths
    under a white mask or outside a clip are in the content stream but
    not on the printed sheet. A page that renders blank is left as is."""
    if ink is None or gray is None or ink.shape != gray.shape:
        return ink
    shown = (gray < level).astype(np.uint8)
    if not shown.any():
        return ink
    k = 2 * int(slack) + 1
    shown = cv2.dilate(shown, np.ones((k, k), np.uint8))
    out = ink & shown
    return out if out.any() else ink


GRAY_POCHE_LEVEL = 0.85      # grey fills darker than this may be walls
GRAY_WALL_FT = (0.25, 2.0)   # ...when their mean thickness is in this range


def _neutral(rgb):
    """A grey (not a colour): channels within 0.06 of each other."""
    try:
        return max(rgb[:3]) - min(rgb[:3]) <= 0.06
    except (TypeError, IndexError, ValueError):
        return False


def _thickness_pts(polys):
    """Mean thickness (points) of a filled shape made of closed outlines:
    twice the area over the perimeter (a long wall of width w gives about
    w). 0 when it has no area."""
    a = p = 0.0
    for q in polys:
        if len(q) < 3:
            continue
        x, y = q[:, 0], q[:, 1]
        a += abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2
        p += float(np.sum(np.hypot(np.diff(x, append=x[0]),
                                   np.diff(y, append=y[0]))))
    return 2.0 * a / p if p > 0 and a > 0 else 0.0


def _dark(rgb, level=INK_LEVEL / 255.0):
    """Would this colour count as ink (not a white mask or a pale fill)?"""
    if rgb is None:
        return True
    try:
        v = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    except (TypeError, IndexError):
        return True
    return v < level


def _bezier(p0, p1, p2, p3, n=10):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(fitz.Point(
            u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x +
            t ** 3 * p3.x,
            u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y +
            t ** 3 * p3.y))
    return out


def _with_benches(r, ink, thick, ppf):
    """The room's floor `r` with the footprint of each built-in bench drawn
    against its walls (Nov 3, Jon: count the floor under a shower bench,
    always): a small space closed off from the floor only by a line (no
    wider than BENCH_LINE_FT - the bench's outline) is floor too. Wall
    cores and anything wall-thick, spaces bigger than BENCH_MAX_SF or
    deeper than BENCH_MAX_DEPTH_FT (a tub, a closet, casework runs) and
    anything reaching the edge of the area looked at are left out."""
    free = (1 - np.maximum(r, ink)) & (1 - thick)
    n, lab, st, _c = cv2.connectedComponentsWithStats(free, connectivity=4)
    if n <= 1:
        return r
    # how far each pixel is from the room's floor
    dist = cv2.distanceTransform((1 - r).astype(np.uint8), cv2.DIST_L2, 3)
    line = max(3.0, BENCH_LINE_FT * ppf)
    H, W = r.shape
    max_px = BENCH_MAX_SF * ppf ** 2
    depth = BENCH_MAX_DEPTH_FT * ppf
    add = np.zeros_like(r)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a > max_px or min(w, h) > depth or x == 0 or y == 0 or \
                x + w >= W or y + h >= H:
            continue
        pad = 2
        m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
        m[pad:pad + h, pad:pad + w] = lab[y:y + h, x:x + w] == i
        ring = cv2.dilate(m, np.ones((3, 3), np.uint8)) & (1 - m)
        ys, xs = np.nonzero(ring)
        ys, xs = ys + y - pad, xs + x - pad
        ok = (ys >= 0) & (xs >= 0) & (ys < H) & (xs < W)
        ys, xs = ys[ok], xs[ok]
        if not len(ys) or r[ys, xs].any():
            continue
        # most of its edge is a line away from the floor (its outline);
        # the rest is the wall it stands against
        if (dist[ys, xs] <= line).mean() < BENCH_EDGE_SHARE:
            continue
        add[y:y + h, x:x + w] |= m[pad:pad + h, pad:pad + w]
    if not add.any():
        return r
    # ...and the outline itself, between the bench and the floor
    out = np.maximum(r, add)
    gap = cv2.morphologyEx(out, cv2.MORPH_CLOSE, np.ones(
        (int(line) * 2 + 1, int(line) * 2 + 1), np.uint8))
    edge = gap & cv2.dilate(add, np.ones((3, 3), np.uint8),
                            iterations=int(line) + 1) & (1 - thick)
    return np.maximum(out, edge)


def wall_mask(gray, ppf, text_boxes=(), ink_level=INK_LEVEL,
              close_ft=CLOSE_FT, open_ft=OPEN_FT, island_ft=ISLAND_FT,
              ink=None):
    """1 where there is wall. `text_boxes` (pixel rects) are blanked.
    Solid blobs smaller than `island_ft` that touch no wall (plumbing
    fixtures, casework, columns) are dropped: they sit on the floor.
    `ink` (0/1) can be given instead of `gray`, e.g. from vector_ink."""
    if ink is None:
        ink = (gray < ink_level).astype(np.uint8)
    h, w = ink.shape
    for b in text_boxes:
        x0, y0 = max(0, int(b[0]) - 1), max(0, int(b[1]) - 1)
        x1, y1 = min(w, int(b[2]) + 2), min(h, int(b[3]) + 2)
        if x1 > x0 and y1 > y0:
            ink[y0:y1, x0:x1] = 0
    k1 = max(3, int(round(close_ft * ppf)) | 1)
    k2 = max(3, int(round(open_ft * ppf)) | 1)
    walls = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((k1, k1), np.uint8))
    walls = cv2.morphologyEx(walls, cv2.MORPH_OPEN,
                             np.ones((k2, k2), np.uint8))
    if island_ft:
        _n, lab, st, _c = cv2.connectedComponentsWithStats(walls,
                                                           connectivity=8)
        small = np.maximum(st[:, 2], st[:, 3]) < island_ft * ppf
        small[0] = False
        if small.any():
            walls[small[lab]] = 0
    return walls


def existing_areas(page):
    """Outlines (screen points) of the area measurements on the page."""
    out = []
    page = _real_page(page)
    m = page.rotation_matrix
    for a in annotate.iter_annots(page):
        subj = (a.info or {}).get("subject", "")
        if not subj.startswith(annotate.TAKEOFF + ":area:"):
            continue
        verts = [fitz.Point(v) * m for v in (a.vertices or [])]
        if len(verts) >= 3:
            out.append(verts)
    return out


def _inside(pt, poly):
    arr = np.array([(p.x, p.y) for p in poly], np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(arr, (float(pt.x), float(pt.y)), False) >= 0


# ---- the two entry points -------------------------------------------------------

def room_at(page, scale, pt):
    """Trace the room clicked at `pt` (screen point).

    Returns {"pts", "sqft", "value", "unit", "name", "tag_sf"}; raises
    AutoTakeoffError with a message for the user if there is no room."""
    page = cached_page(page)
    for poly in existing_areas(page):
        if _inside(pt, poly):
            raise AutoTakeoffError("That spot is already measured.")
    plan = Plan(page, scale)
    tags = room_tags(page)
    # which tag is in this room? Look with the narrowest door bridging
    # that closes it off.
    mine = None
    for door in DOOR_STEPS:
        tight = plan.detect(pt, door=door)
        if tight:
            break
    if tight:
        inside = [t for t in tags if _inside(t["pt"], tight["pts"])]
        if len(inside) == 1:
            mine = inside[0]
    others = [t["pt"] for t in tags if t is not mine]
    res = plan.detect(pt, others, expected=mine["sf"] if mine else None)
    if res is None:
        raise AutoTakeoffError(
            "Couldn't find a closed room there. Click in open floor away "
            "from the walls, or draw the area by hand.")
    out = _result(plan, res, mine)
    out["own_tag_inside"] = True if mine else None
    return score_room(out)


def _result(plan, res, tag):
    pts = res["pts"]
    perim = res.get("perim_ft")
    if perim is None and len(pts) > 2:
        perim = sum(abs(pts[k] - pts[k - 1]) for k in range(len(pts))) / \
            plan.pts_per_ft
    name = tag["name"] if tag else ""
    return {"pts": pts, "sqft": res["sqft"],
            "value": plan.to_units(res["sqft"]),
            "unit": f"sq {plan.unit}",
            "name": name,
            "number": room_number(name),
            "tag_sf": tag["sf"] if tag else None,
            "tag_pt": (float(tag["pt"][0]), float(tag["pt"][1]))
            if tag and tag.get("pt") is not None else None,
            "detail_scale": res.get("detail_scale"),
            # the traced floor (sq ft) and its outline's length (ft);
            # these stay the trace when prefer_tags() swaps in the tag
            "net_sf": res["sqft"],
            "perimeter_lf": perim,
            "face_fill_sf": res.get("face_fill_sf") or 0.0,
            "flags": []}


def score_room(r):
    """Set r's "trace_confidence" (0-1), "tag_diff_sf" / "tag_diff_pct"
    (trace minus tag), "review" and add to its "flags", from how the trace
    compares with the room's tag and how it was found ("tags_held": other
    rooms' tags inside it; "via": ["leader", "retraced"]; "own_tag_inside";
    "detail_scale"). Returns r."""
    flags = r.setdefault("flags", [])
    tag = r.get("tag_sf")
    sf = r.get("net_sf", r.get("sqft"))
    if tag and sf:
        diff = sf - tag
        pct = diff / tag * 100
        r["tag_diff_sf"] = round(diff, 2)
        r["tag_diff_pct"] = round(pct, 2)
        d = abs(diff) / tag
        if d <= NOTE_DIFF:
            conf = 0.95
        elif d <= REVIEW_DIFF:
            conf = 0.85
            flags.append(f"trace {pct:+.1f}% from its tag ({tag:,.0f} SF)")
        elif d <= GOOD:
            conf = 0.65
            flags.append(f"trace {pct:+.1f}% from its tag ({tag:,.0f} SF) "
                         "- check the outline")
        else:
            conf = 0.35
            flags.append(f"trace {pct:+.0f}% from its tag ({tag:,.0f} SF) "
                         "- probably not the right space")
    else:
        r["tag_diff_sf"] = r["tag_diff_pct"] = None
        conf = 0.7
        flags.append("no area in the tag - size check only")
    ff = r.get("face_fill_sf") or 0.0
    if sf and ff >= FACE_FLAG_PCT / 100.0 * sf:
        # the floor came out around fixtures / benches and was filled back
        # to the wall faces (Nov 3: the floor under built-in benches is
        # counted)
        conf *= 0.9
        flags.append(f"outline filled out to the wall faces around fixtures "
                     f"(+{ff:,.0f} SF, floor under built-in benches "
                     "included) - check it")
    held = r.get("tags_held") or []
    if held:
        conf *= 0.3
        flags.append("trace holds another room's tag (" +
                     ", ".join(h or "?" for h in held[:3]) + ")")
    via = r.get("via") or []
    if r.get("own_tag_inside") is False and "leader" not in via:
        conf *= 0.8
        flags.append("its tag is not inside the trace")
    if "leader" in via:
        conf *= 0.9
        flags.append("tag outside the room - found where its leader points")
    if "retraced" in via:
        conf *= 0.9
        flags.append("traced again: the first outline held another room's "
                     "tag")
    if r.get("detail_scale"):
        conf *= 0.95
        flags.append(f"measured at the detail's scale ({r['detail_scale']})")
    r["trace_confidence"] = round(conf, 3)
    r["review"] = conf < 0.8
    return r


RESOLVE_MAX_SF = 25.0      # an overlap up to this (and RESOLVE_MAX_PCT of
RESOLVE_MAX_PCT = 0.10     # the smaller room) is given to one room only
_SCORE_PX_FT = 24.0        # mask resolution for resolve_overlaps (px/ft)


def _poly_mask(arr, off, k, shape):
    import numpy as _np
    m = _np.zeros(shape, _np.uint8)
    cv2.fillPoly(m, [_np.round((arr - off) * k).astype(_np.int32)
                     .reshape(-1, 1, 2)], 1)
    return m


def _shoelace(arr):
    return abs(float(np.dot(arr[:, 0], np.roll(arr[:, 1], 1)) -
                     np.dot(arr[:, 1], np.roll(arr[:, 0], 1)))) / 2.0


def _ring(arr):
    return float(np.sum(np.hypot(*(arr - np.roll(arr, 1, axis=0)).T)))


def _rescore(r, new_pts, sf, perim, note):
    """r with its outline replaced by new_pts (page points), its area `sf`
    (sq ft) and outline `perim` (ft); value follows, and score_room's
    flags are worked out again; other flags stay."""
    import copy
    old = copy.deepcopy(r)
    old["flags"] = []
    gen_old = set(score_room(old)["flags"])
    arr = np.array(new_pts, float)
    ratio = sf / r["sqft"] if r.get("sqft") else 1.0
    keep = [f for f in r.get("flags") or [] if f not in gen_old]
    # the same kind of point the trace had (fitz.Point from the tracer):
    # the marks and the perimeter maths subtract and transform them
    kind = type(r["pts"][0]) if r.get("pts") else tuple
    if kind in (tuple, list):
        r["pts"] = [(float(x), float(y)) for x, y in arr]
    else:
        r["pts"] = [kind(float(x), float(y)) for x, y in arr]
    if r.get("value") is not None:
        r["value"] = r["value"] * ratio
    r["sqft"] = r["net_sf"] = sf
    r["perimeter_lf"] = perim
    r["flags"] = []
    score_room(r)
    r["flags"] = keep + r["flags"] + [note]
    return r


def resolve_overlaps(rooms, pts_per_ft, lines=None):
    """Nov 1 (Collenton A-101): two rooms' traces can both take the same
    small piece of floor - a restroom slipping past its wall end into the
    corridor's alcove, the alcove also traced as corridor - so the floor
    is counted twice and both rooms go to review. A small overlap (up to
    RESOLVE_MAX_SF and RESOLVE_MAX_PCT of the smaller room) goes to one
    room only: it is cut from the room whose trace then comes closer to
    its tag. When neither room gets closer (or neither has a tag area)
    and `lines` ((n, 4) straight drawn lines, page points) has one that
    runs across the shared floor between the two tags, each room ends at
    that line (_split_on_line). Otherwise nothing changes and
    flag_overlaps flags both as before. Returns the number of overlaps
    resolved."""
    if np is None or cv2 is None or not rooms or pts_per_ft <= 0:
        return 0
    k = _SCORE_PX_FT / pts_per_ft
    done = 0
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a, b = rooms[i], rooms[j]
            pa, pb = a.get("pts") or [], b.get("pts") or []
            if len(pa) < 3 or len(pb) < 3:
                continue
            aa, bb = np.array(pa, float), np.array(pb, float)
            lo = np.minimum(aa.min(axis=0), bb.min(axis=0)) - 2
            hi = np.maximum(aa.max(axis=0), bb.max(axis=0)) + 2
            if (np.maximum(aa.min(axis=0), bb.min(axis=0)) >=
                    np.minimum(aa.max(axis=0), bb.max(axis=0))).any():
                continue                               # boxes don't meet
            shape = (int(math.ceil((hi[1] - lo[1]) * k)) + 2,
                     int(math.ceil((hi[0] - lo[0]) * k)) + 2)
            ma, mb = _poly_mask(aa, lo, k, shape), _poly_mask(bb, lo, k, shape)
            both = ma & mb
            ov = float(both.sum()) / (k * k) / pts_per_ft ** 2
            small = min(a.get("sqft") or 0, b.get("sqft") or 0)
            if ov <= OVERLAP_SF:
                continue
            fits_one = ov <= RESOLVE_MAX_SF and ov <= RESOLVE_MAX_PCT * small

            def gain(r):
                tag, sf = r.get("tag_sf"), r.get("net_sf", r.get("sqft"))
                if not tag or not sf:
                    return None
                return abs(sf - tag) - abs(sf - ov - tag)
            ga, gb = gain(a), gain(b)
            cands = [(g, r, m, other) for g, r, m, other in
                     ((ga, a, ma, b), (gb, b, mb, a)) if g is not None and g > 0] \
                if fits_one else []
            if cands:
                g, loser, m, winner = max(cands, key=lambda t: t[0])
                got = _cut_room(loser, m, both, lo, k, pts_per_ft)
                if got is None:
                    continue
                _rescore(loser, *got,
                         f"{ov:,.0f} SF it shared with "
                         f"{winner.get('name') or 'another room'} left to "
                         "that room (closer to both tags)")
                done += 1
                continue
            # neither room alone: a drawn line through the shared floor
            # that has one room's tag on each side (a counter, a low wall
            # or a glass line the trace slipped past) - each room ends at
            # that line, as each room ends at its own wall face
            if lines is not None and ov <= SPLIT_MAX_SF and \
                    ov <= SPLIT_MAX_PCT * small and \
                    _split_on_line(a, b, ma, mb, both, lo, k, pts_per_ft,
                                   lines, ov):
                done += 1
    return done


SPLIT_MAX_SF = 60.0        # shared floor up to this (and SPLIT_MAX_PCT of
SPLIT_MAX_PCT = 0.25       # the smaller room) can end at a line between them


def _cut_room(r, m, cut, lo, k, pts_per_ft):
    """Room r (its mask m on the overlap grid) without the pixels `cut`:
    (new outline page points, net sq ft, perimeter ft) or None."""
    rest = (m & (1 - cut)).astype(np.uint8)
    eps = max(1.0, 0.1 * _SCORE_PX_FT)

    def traced(mask):
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            return None
        q = cv2.approxPolyDP(max(cs, key=cv2.contourArea), eps, True)
        return q.reshape(-1, 2).astype(float) / k + lo \
            if len(q) >= 3 else None
    new = traced(rest)
    was = traced(m)
    if new is None or was is None:
        return None
    # the pixel round trip's own error, measured on the old outline and
    # taken back off: the area and length stay exact
    base = r.get("net_sf") or r["sqft"]
    sf = base - (_shoelace(was) - _shoelace(new)) / pts_per_ft ** 2
    perim = (r.get("perimeter_lf") or _ring(was) / pts_per_ft) \
        + (_ring(new) - _ring(was)) / pts_per_ft
    if not 0 < sf < base:
        return None
    return new, sf, perim


def _split_on_line(a, b, ma, mb, both, lo, k, pts_per_ft, lines, ov):
    """Nov 1 (Aiken A-101, Reception and Lobby either side of a diagonal
    counter): the shared floor `both` is cut by the drawn straight line
    (from `lines`, (n, 4) page points) that crosses it with room a's tag
    on one side and b's on the other; each room keeps only its own side.
    Done only when the two traces come no farther from their tags.
    Returns True when both rooms were cut."""
    ta, tb = a.get("tag_pt"), b.get("tag_pt")
    if not ta or not tb or not len(lines):
        return False
    ys, xs = np.nonzero(both)
    if not len(xs):
        return False
    P = np.stack([(xs + 0.5) / k + lo[0], (ys + 0.5) / k + lo[1]], axis=1)
    pmin, pmax = P.min(axis=0), P.max(axis=0)
    ft = pts_per_ft
    pad = 0.5 * ft
    seg = lines[(np.maximum(lines[:, 0], lines[:, 2]) >= pmin[0] - pad) &
                (np.minimum(lines[:, 0], lines[:, 2]) <= pmax[0] + pad) &
                (np.maximum(lines[:, 1], lines[:, 3]) >= pmin[1] - pad) &
                (np.minimum(lines[:, 1], lines[:, 3]) <= pmax[1] + pad)]
    best = None
    for x0, y0, x1, y1 in seg:
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 2.0 * ft:
            continue
        u = np.array([(x1 - x0) / L, (y1 - y0) / L])
        nrm = np.array([-u[1], u[0]])
        p0 = np.array([x0, y0])
        sa = float(np.dot(np.array(ta) - p0, nrm))
        sb = float(np.dot(np.array(tb) - p0, nrm))
        if sa * sb >= 0 or min(abs(sa), abs(sb)) < 1.0 * ft:
            continue                       # both tags on one side
        d = (P - p0) @ nrm
        if d.min() >= 0 or d.max() <= 0:
            continue                       # misses the shared floor
        t = (P - p0) @ u
        near = np.abs(d) <= 0.75 * ft
        if not near.any():
            continue
        cover = float(np.mean((t[near] >= -0.25 * ft) &
                              (t[near] <= L + 0.25 * ft)))
        if cover < 0.8:
            continue                       # doesn't run across it
        key = (cover, -abs(float(np.mean(d))))
        if best is None or key > best[0]:
            best = (key, p0, nrm, sa)
    if best is None:
        return False
    _key, p0, nrm, sa = best
    h, w = both.shape
    gy, gx = np.mgrid[0:h, 0:w]
    side = ((gx + 0.5) / k + lo[0] - p0[0]) * nrm[0] + \
        ((gy + 0.5) / k + lo[1] - p0[1]) * nrm[1]
    a_side = (side > 0) if sa > 0 else (side < 0)
    cut_a = (both & ~a_side).astype(np.uint8)    # b's side, off a
    cut_b = (both & a_side).astype(np.uint8)     # a's side, off b
    if not cut_a.any() and not cut_b.any():
        return False
    got_a = _cut_room(a, ma, cut_a, lo, k, pts_per_ft) if cut_a.any() \
        else None
    got_b = _cut_room(b, mb, cut_b, lo, k, pts_per_ft) if cut_b.any() \
        else None
    if (cut_a.any() and got_a is None) or (cut_b.any() and got_b is None):
        return False

    def err(r, sf):
        tag = r.get("tag_sf")
        return abs(sf - tag) if tag else 0.0
    sfa = got_a[1] if got_a else (a.get("net_sf") or a["sqft"])
    sfb = got_b[1] if got_b else (b.get("net_sf") or b["sqft"])
    if err(a, sfa) + err(b, sfb) > \
            err(a, a.get("net_sf") or a["sqft"]) + \
            err(b, b.get("net_sf") or b["sqft"]) + 0.5:
        return False
    for r, got, other in ((a, got_a, b), (b, got_b, a)):
        if got:
            gone = (r.get("net_sf") or r["sqft"]) - got[1]
            _rescore(r, *got,
                     f"{gone:,.0f} SF of the {ov:,.0f} SF it shared with "
                     f"{other.get('name') or 'another room'} is past the "
                     "drawn line between them - left to that room")
    return True


def flag_overlaps(rooms, pts_per_ft, min_sf=OVERLAP_SF):
    """Traces that overlap each other (by more than `min_sf` sq ft, or 1%
    of the smaller): both get an "overlaps ..." flag, "overlaps" [(name,
    sf)], a much lower trace_confidence and review. `pts_per_ft`: the
    page scale (points per foot; the outlines are page points). Returns
    the number of overlapping pairs."""
    if np is None or cv2 is None or not rooms or pts_per_ft <= 0:
        return 0
    k = max(0.25, 6.0 / pts_per_ft)            # ~6 pixels per foot
    polys = []
    for r in rooms:
        pts = r.get("pts") or []
        if len(pts) < 3:
            polys.append(None)
            continue
        arr = np.array([(p[0], p[1]) for p in pts], float)
        polys.append((arr, arr.min(axis=0), arr.max(axis=0)))
    pairs = 0
    order = sorted((i for i, p in enumerate(polys) if p is not None),
                   key=lambda i: polys[i][1][0])
    for a_i, i in enumerate(order):
        ai, lo_i, hi_i = polys[i]
        for j in order[a_i + 1:]:
            aj, lo_j, hi_j = polys[j]
            if lo_j[0] > hi_i[0]:
                break                          # sorted by left edge
            x0, y0 = max(lo_i[0], lo_j[0]), max(lo_i[1], lo_j[1])
            x1, y1 = min(hi_i[0], hi_j[0]), min(hi_i[1], hi_j[1])
            if x1 <= x0 or y1 <= y0:
                continue
            w = int(math.ceil((x1 - x0) * k)) + 3
            h = int(math.ceil((y1 - y0) * k)) + 3
            mi = np.zeros((h, w), np.uint8)
            mj = np.zeros((h, w), np.uint8)
            off = np.array([x0, y0])
            cv2.fillPoly(mi, [np.round((ai - off) * k + 1).astype(np.int32)
                              .reshape(-1, 1, 2)], 1)
            cv2.fillPoly(mj, [np.round((aj - off) * k + 1).astype(np.int32)
                              .reshape(-1, 1, 2)], 1)
            both = cv2.erode(mi & mj, np.ones((3, 3), np.uint8))
            sf = float(both.sum()) / (k * k) / pts_per_ft ** 2
            small = min(rooms[i].get("sqft") or 0, rooms[j].get("sqft") or 0)
            if sf <= max(min_sf, 0.01 * small):
                continue
            pairs += 1
            for me, other in ((rooms[i], rooms[j]), (rooms[j], rooms[i])):
                me.setdefault("overlaps", []).append((other.get("name"), sf))
                me.setdefault("flags", []).append(
                    f"overlaps {other.get('name') or 'another room'} by "
                    f"{sf:,.0f} SF")
                me["trace_confidence"] = round(
                    me.get("trace_confidence", 1.0) * 0.4, 3)
                me["review"] = True
    return pairs


def scale_ratio(found):
    """Median traced / tagged area over the tagged rooms found (needs 3 or
    more), or None. Far from 1 means the page scale is wrong - every room
    is off by the same factor."""
    rs = sorted(r["sqft"] / r["tag_sf"] for r in found
                if r.get("tag_sf") and r.get("sqft"))
    if len(rs) < 3:
        return None
    return rs[len(rs) // 2]


def scale_looks_wrong(found, lo=0.8, hi=1.25):
    k = scale_ratio(found)
    return k is not None and not lo <= k <= hi


def prefer_tags(found, tol=0.05):
    """For tagged rooms whose trace differs from the area printed in the
    room tag by more than `tol`, take the tag's area (the architect's
    number) and keep the traced one as "traced_sf". Returns how many were
    changed. Does nothing when the scale looks wrong."""
    if scale_looks_wrong(found):
        return 0
    n = 0
    for r in found:
        sf = r.get("tag_sf")
        if not sf or not r.get("sqft") or \
                abs(r["sqft"] - sf) <= tol * sf:
            continue
        k = sf / r["sqft"]
        r["traced_sf"], r["traced_value"] = r["sqft"], r["value"]
        r["sqft"], r["value"] = float(sf), r["value"] * k
        r["per_tag"] = True
        n += 1
    return n


def _closer(new, old, sf):
    """Is the new result a better fit than the old one? Against the area
    tag when there is one; for a name-only room (sf None), a plausible
    size beats an implausible one."""
    if sf is None:
        ok_new = 15 <= new["sqft"] <= 5000
        ok_old = 15 <= old["sqft"] <= 5000
        return ok_new and not ok_old
    return abs(new["sqft"] - sf) < abs(old["sqft"] - sf)


def detail_scales(page):
    """Scales written under detail titles ("SCALE: 1/2" = 1'-0"") on the
    page: [(point, ppu, unit, label)], points in screen (rotated)
    coordinates at the scale text. The title block is left out."""
    from . import takeoff
    rot = page.rotation_matrix
    W, H = page.rect.width, page.rect.height
    out = []
    try:
        d = page.get_text("dict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            t = " ".join(sp.get("text", "") for sp in ln.get("spans", []))
            if "=" not in t and ":" not in t:
                continue
            sc = takeoff.find_scales(t)
            if not sc:
                continue
            r = fitz.Rect(ln["bbox"]) * rot
            pt = fitz.Point(r.x0, (r.y0 + r.y1) / 2)
            if pt.x > W * 0.8 and pt.y > H * 0.55 or pt.x > W * 0.86:
                continue                               # the title block
            label, ppu, unit = sc[0]
            if takeoff.is_standard(ppu, unit):
                out.append((pt, ppu, unit, label))
    return out


def _thin_lines(page):
    """Thin straight strokes on the page as ((x0, y0), (x1, y1)) in screen
    (rotated) coordinates - candidates for tag leaders."""
    return _memo(page, "thin_lines", lambda: _thin_lines_read(page))


def _thin_lines_read(page):
    rot = page.rotation_matrix
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return out
    for d in drawings:
        if d.get("type") not in ("s", "fs") or (d.get("width") or 0) > 0.6:
            continue
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1] * rot, it[2] * rot
                out.append(((a.x, a.y), (b.x, b.y)))
    return out


def leader_seeds(pt, lines, near=30.0, reach=150.0):
    """Where a room tag's leader points: the far ends of thin lines that
    start right at the tag (within `near` points of its area figure) and
    run off up to `reach` points, plus a point a little past each end."""
    out = []
    px, py = pt.x, pt.y
    if np is not None and not isinstance(lines, np.ndarray):
        lines = np.array([(a[0], a[1], b[0], b[1]) for a, b in lines],
                         float).reshape(-1, 4)
    if np is not None:
        # only lines with an end near the tag (one pass, not one per line)
        da = np.hypot(lines[:, 0] - px, lines[:, 1] - py)
        db = np.hypot(lines[:, 2] - px, lines[:, 3] - py)
        keep = np.nonzero(np.minimum(da, db) <= near)[0]
        lines = [((lines[k, 0], lines[k, 1]), (lines[k, 2], lines[k, 3]))
                 for k in keep]
    for a, b in lines:
        da = math.hypot(a[0] - px, a[1] - py)
        db = math.hypot(b[0] - px, b[1] - py)
        if da > db:
            a, b, da, db = b, a, db, da
        if da > near or not near < db <= reach:
            continue
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 8.0:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        out.append(fitz.Point(b[0], b[1]))
        out.append(fitz.Point(b[0] + 4 * ux, b[1] + 4 * uy))
    return out[:12]


def detail_scale_at(pt, details, page_rect):
    """The detail scale for a room tag at `pt`: the nearest detail title
    below it whose drawing it could be in (titles sit under the bottom
    left of their drawing). None when there's none."""
    W, H = page_rect.width, page_rect.height
    best = None
    for q, ppu, unit, label in details:
        dy = q.y - pt.y
        if dy < 0 or dy > 0.45 * H:
            continue
        if not q.x - 144 <= pt.x <= q.x + 0.5 * W:
            continue
        if best is None or dy < best[0]:
            best = (dy, ppu, unit, label)
    return None if best is None else best[1:]


def all_rooms(page, scale, progress=None, skip_measured=True, budget_s=None,
              info=None):
    """Take off every tagged room on the page.

    Returns (found, missed): found is a list of results as room_at() gives,
    missed the tags no room was found for. Two passes: rooms that come out
    within 12% of their tag are kept and become walls, then the rest are
    tried again.

    Each room found also carries "net_sf" (the trace, sq ft),
    "perimeter_lf" (its outline, ft), "number" (the room number),
    "trace_confidence" (0-1), "tag_diff_sf" / "tag_diff_pct" (trace minus
    tag), "flags" (why it is less than sure) and "review". A trace must
    hold exactly one room tag - one holding another's is traced again
    without letting any tag through, and flagged if that fails - and
    overlapping traces are both flagged. Tag samples in legends and the
    title block are not rooms.

    progress(i, n) is called as the run goes (also during a slow room, a
    few times a second); returning False stops it. `budget_s`: stop after
    that many seconds. A stopped run returns ([], tags) as before, with
    info["stopped"] True, info["why"] and info["partial"] (the rooms
    traced so far, not checked). `info` (a dict) also gets "ignored" (the
    sample tags left out), "overlaps" (pairs) and "elapsed" (s)."""
    page = cached_page(page)
    info = {} if info is None else info
    info.update({"stopped": False, "why": "", "ignored": [], "overlaps": 0,
                 "elapsed": 0.0})
    t_start = time.perf_counter()
    st = {"i": 0, "n": 1, "last": t_start}

    def check(i=None, force=False):
        now = time.perf_counter()
        if i is not None:
            st["i"] = i
        if budget_s is not None and now - t_start > budget_s:
            raise _Stop(f"time budget ({budget_s:g} s) used up")
        if progress and (force or now - st["last"] >= 0.25):
            st["last"] = now
            if progress(st["i"], st["n"]) is False:
                raise _Stop("stopped by the caller")
    tags = room_tags(page, info)
    # rooms named but without an area tag are taken off too (checked by
    # size instead of against a tag)
    tags += room_labels(page, skip=[t["pt"] for t in tags], info=info)
    done = existing_areas(page) if skip_measured else []
    tags = [t for t in tags if not any(_inside(t["pt"], p) for p in done)]
    st["n"] = 2 * len(tags) + 2
    work = {}
    try:
        check(0, force=True)
        plan = Plan(page, scale, claimed=skip_measured, check=check)
        found, missed = _trace_rooms(page, scale, plan, tags, check, work,
                                     skip_measured)
    except _Stop as e:
        info["stopped"], info["why"] = True, str(e)
        out, plans = work.get("out") or [], work.get("plans") or []
        info["partial"] = [_result(plans[i], out[i], tags[i])
                           for i in range(min(len(out), len(plans)))
                           if out[i] is not None]
        info["elapsed"] = round(time.perf_counter() - t_start, 2)
        return [], tags
    info["resolved"] = resolve_overlaps(found, plan.pts_per_ft,
                                        lines=_straight_lines(page)[0])
    info["overlaps"] = flag_overlaps(found, plan.pts_per_ft)
    info["elapsed"] = round(time.perf_counter() - t_start, 2)
    return found, missed


def _trace_rooms(page, scale, plan, tags, check, work, skip_measured):
    """all_rooms' work once the page is read: (found, missed)."""
    n = len(tags)
    out = [None] * n
    via = [[] for _ in range(n)]
    seeds = [t["pt"] for t in tags]
    plans = [plan] * n
    work["out"], work["plans"] = out, plans
    pts = [t["pt"] for t in tags]
    nums = [room_number(t["name"]) for t in tags]

    def others(i, among=None):
        return [pts[j] for j in (range(n) if among is None else among)
                if j != i]

    def cap(t):
        return None if t["sf"] else NAMED_MAX_SF

    def plausible(r, sf):
        if r is None:
            return False
        if sf is None:
            return 15 <= r["sqft"] <= NAMED_MAX_SF
        return sf / 2 <= r["sqft"] <= sf * 2

    def good(i):
        r = out[i]
        if r is None:
            return False
        if tags[i]["sf"] is None:
            return 15 <= r["sqft"] <= NAMED_MAX_SF
        return abs(r["sqft"] - tags[i]["sf"]) <= GOOD * tags[i]["sf"]

    for i, t in enumerate(tags):
        check(i, force=True)
        out[i] = plan.detect(t["pt"], others(i), expected=t["sf"],
                             max_sf=cap(t))
    sure = {i for i in range(n) if good(i)}
    # a room in an enlarged detail drawn at another scale ("ENLARGED
    # JANITOR'S CLOSET, SCALE: 1/2" = 1'-0"" on a 3/8" sheet): try it at
    # the detail's own scale too and keep whichever fits better. Rooms
    # already sure at the sheet's scale aren't tried again; a tagged room
    # the detail's scale fits needs no second pass at the sheet's.
    try:
        details = detail_scales(page)
    except Exception:
        details = []
    alt = {}
    alt_res = {}

    def try_detail(i):
        t = tags[i]
        if i in alt_res:
            return alt_res[i]
        alt_res[i] = None
        ds = detail_scale_at(t["pt"], details, page.rect) if details \
            else None
        if not ds or ds[1] != scale.get("unit", "ft") or \
                abs(ds[0] - scale["ppu"]) <= 0.02 * scale["ppu"]:
            return None
        check()
        key = (round(ds[0], 3), ds[1])
        try:
            if key not in alt:
                alt[key] = Plan(page, {"ppu": ds[0], "unit": ds[1]},
                                claimed=skip_measured, check=check)
            ap = alt[key]
            r = ap.detect(t["pt"], others(i), expected=t["sf"],
                          max_sf=cap(t))
        except AutoTakeoffError:
            return None
        if r is not None:
            r["detail_scale"] = ds[2]
            alt_res[i] = (r, ap)
        return alt_res[i]

    def take_detail(i):
        got = try_detail(i)
        if got is None:
            return
        r, ap = got
        sf = tags[i]["sf"]
        if plausible(r, sf) and (out[i] is None or _closer(r, out[i], sf)):
            out[i], plans[i] = r, ap
    fitted = set()
    for i, t in enumerate(tags):
        if i in sure or not t["sf"]:
            continue
        take_detail(i)
        if plans[i] is not plan and good(i):
            fitted.add(i)
    if len(sure) + len(fitted) < n:
        plan.claim([out[i]["pts"] for i in sorted(sure)], grow=1)
        rest = [j for j in range(n) if j not in sure]
        for i, t in enumerate(tags):
            check(n + i, force=True)
            if i in sure or i in fitted:
                continue
            r = plan.detect(t["pt"], others(i, rest), expected=t["sf"],
                            max_sf=cap(t))
            if r is not None and (out[i] is None or
                                  _closer(r, out[i], t["sf"])):
                out[i], plans[i] = r, plan
    # rooms named without an area: their detail scale is tried after both
    # passes (a plausible size there is no proof, so the sheet's comes
    # first)
    for i, t in enumerate(tags):
        if t["sf"] is None and i not in sure:
            take_detail(i)
    # far off its tag means it found the wrong space: leave it to the user
    for i, t in enumerate(tags):
        if out[i] is not None and not plausible(out[i], t["sf"]):
            out[i] = None
    # still missed: a tag set outside its room on a leader ("JAN 113"
    # beside a closet, an arrow into it) - look where the leader ends
    if any(o is None for o in out):
        try:
            thin = _thin_lines(page)
        except Exception:
            thin = []
        if thin and np is not None:
            thin = np.array([(a[0], a[1], b[0], b[1]) for a, b in thin],
                            float)
        for i, t in enumerate(tags):
            if out[i] is not None or not len(thin):
                continue
            check()
            seeds_i = leader_seeds(t["pt"], thin)
            if not seeds_i:
                continue
            ds = detail_scale_at(t["pt"], details, page.rect) \
                if details else None
            pl = plan
            if ds and ds[1] == scale.get("unit", "ft"):
                pl = alt.get((round(ds[0], 3), ds[1]), plan)
            sf = t["sf"]
            best, best_seed = None, None
            for sp in seeds_i:
                try:
                    r = pl.detect(sp, others(i), expected=sf, max_sf=cap(t))
                except _Stop:
                    raise
                except Exception:
                    r = None
                if plausible(r, sf) and (best is None or
                                         _closer(r, best, sf)):
                    best, best_seed = r, sp
            if best is not None:
                if pl is not plan and ds:
                    best["detail_scale"] = ds[2]
                out[i], plans[i], seeds[i] = best, pl, best_seed
                via[i].append("leader")

    def same_room(i, j):
        if nums[i] or nums[j]:
            return nums[i] == nums[j]
        return tags[i]["name"] == tags[j]["name"]

    # two labels in one room (its tag and a second label): keep it once
    seen = []
    for i in range(n):
        if out[i] is None:
            continue
        a = out[i]["sqft"]
        c = out[i]["pts"]
        cx = sum(p.x for p in c) / len(c)
        cy = sum(p.y for p in c) / len(c)
        if any(abs(a - b) < 0.5 and abs(cx - x) < 2 and abs(cy - y) < 2 and
               same_room(i, k) for b, x, y, k in seen):
            out[i] = None
            continue
        seen.append((a, cx, cy, i))
    # each trace holds exactly one room tag: one holding another room's
    # tag (a tag printed against a wall is let through by detect) is
    # traced again counting every tag; if that fails it is flagged
    held = _held_tags(out, pts, same_room)
    for i in range(n):
        if not held[i]:
            continue
        check()
        sf = tags[i]["sf"]
        try:
            r = plans[i].detect(seeds[i], others(i), expected=sf,
                                max_sf=cap(tags[i]), strict=True)
        except AutoTakeoffError:
            r = None
        if plausible(r, sf) and not any(
                j != i and not same_room(i, j) and _inside(pts[j], r["pts"])
                for j in range(n)):
            if out[i].get("detail_scale"):
                r["detail_scale"] = out[i]["detail_scale"]
            out[i] = r
            via[i].append("retraced")
            held[i] = []
    found = []
    for i, t in enumerate(tags):
        if out[i] is None:
            continue
        res = _result(plans[i], out[i], t)
        res["via"] = via[i]
        res["tags_held"] = [tags[j]["name"] for j in held[i]]
        res["own_tag_inside"] = _inside(pts[i], out[i]["pts"])
        found.append(score_room(res))
    missed = [t for i, t in enumerate(tags) if out[i] is None]
    return found, missed


def _held_tags(out, pts, same_room):
    """For each trace, the other rooms' tags inside it: [[j, ...]]."""
    n = len(out)
    held = [[] for _ in range(n)]
    for i in range(n):
        if out[i] is None:
            continue
        poly = out[i]["pts"]
        x0 = min(p.x for p in poly)
        x1 = max(p.x for p in poly)
        y0 = min(p.y for p in poly)
        y1 = max(p.y for p in poly)
        for j in range(n):
            if j == i or same_room(i, j):
                continue
            q = pts[j]
            if x0 <= q.x <= x1 and y0 <= q.y <= y1 and _inside(q, poly):
                held[i].append(j)
    return held
