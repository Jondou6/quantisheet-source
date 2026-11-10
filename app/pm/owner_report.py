"""Weekly Owner Report (Oct 21, 2026): the weekly progress report a GC
sends the owner - page 1 ("Project Progress Report": work in progress,
logs, inclement weather days, current progress, 10-day forecast), photo
pages (4 a page, framed, fitted automatically), then the RFI log, the
submittal log, the inclement weather log and the forecast.

The DEFAULT output matches the company's current form page for page; every
extra (captions, owner decisions, schedule status, look-ahead, weather gap
line, log counts, manpower and safety, key plan, work areas, before/after
pairs, change-order log) is an option, off by default.

Everything fills from the job: the header from the project settings, the
trades and progress from the week's Daily Logs (or, optionally, rewritten
by the local AI from them - never invented), the photos from the week's
Daily Log attachments, the weather days from the weather history, the logs
from Project Center.

No Qt here. Records live in the store collection "owner_report", one per
week (the week closes on the template's "week_ends" weekday: Tuesday).
Photo fitting and compression are in photofit.py, the log pages in
owner_report_logs.py; this module builds page 1, the photo pages and the
optional pages, and puts the package together.
"""
import copy
import hashlib
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta
from ..dmoney import c2 as _c2

log = logging.getLogger(__name__)

COLL = "owner_report"
DAY = timedelta(days=1)

# ------------------------------------------------------------- page geometry
# Real landscape pages (no rotation). Numbers measured from the form (spec
# 1.1 / 1.2), in points from the top left.
W, H = 792.0, 612.0
FS = 8.2                                  # body text everywhere on page 1
X0, X1 = 39.8, 751.7                      # section bars
BAR_H = 11.7
TITLE_Y1 = 33.0                           # page 1 title baseline
LOGO1 = (533.8, 12.0, 693.1, 92.6)
HEAD_X = (39.8, 108.0, 438.0)             # label | value
HEAD_Y = 40.4
HEAD_ROW = 11.4
WIP_Y = 97.5
BOX_W, BOX_H = 8.9, 8.7
BOX_X = (86.0, 285.5, 424.7, 649.0)
LABEL_X = (110.0, 301.0, 439.0, 662.0)
BOX_Y = (111.7, 126.0, 140.0, 155.1, 168.5, 183.3)
LOGS_Y = 196.1
LOGS_HEAD = (207.8, 219.3)
LOG_ROW = 11.7
LOG_COLS = (384.0, 438.0)
COUNT_COLS = (260.0, 322.0)               # option (f): Open | Overdue | As Of
OPEN_CX = (COUNT_COLS[0] + COUNT_COLS[1]) / 2
OVERDUE_CX = (COUNT_COLS[1] + LOG_COLS[0]) / 2
WEATHER_Y = 254.5
IMPACT_X, CLAIM_X, CLAIM_V = 199.0, 339.0, 442.0
WEATHER_RULE = 277.8
PROGRESS_Y = 289.0
BULLET_X = 41.5
BULLET_Y = 321.0
PITCH = 10.35
WRAP = 690.0
LAST_LINE_Y = 528.5                       # 21 lines on page 1
FORECAST_Y = (545.6, 557.2)
FORECAST_X = (575.3, 655.0)
FORECAST_RULE = 569.8
CONT_BULLET_Y = WIP_Y + BAR_H + (BULLET_Y - PROGRESS_Y - BAR_H)
CONT_LAST_Y = 590.0
# photo pages
TITLE_Y2 = 42.0
LOGO2 = (620.9, 16.5, 717.7, 65.3)
CELLS4 = ((9.0, 65.3, 388.7, 317.0), (403.3, 65.3, 783.0, 317.0),
          (9.0, 334.0, 388.7, 596.6), (403.3, 334.0, 783.0, 596.6))
GRID = (9.0, 65.3, 783.0, 596.6)
GAP6 = (14.6, 16.0)
CAPTION_H = 22.0
PAGE_TOP, PAGE_BOTTOM = 72.0, 592.0       # optional pages' flow area

BLACK = (0, 0, 0)
GREY_TEXT = (0.35, 0.35, 0.35)
RED = (0.80, 0.0, 0.0)
BAR_BLUE = (0.27, 0.45, 0.77)
CRIT_RED = (0.78, 0.12, 0.12)
WEEKEND = (0.88, 0.88, 0.88)
PIN_COLOR = (0.86, 0.15, 0.15)
AREA_COLORS = [(0.96, 0.69, 0.25), (0.35, 0.60, 0.95), (0.40, 0.78, 0.40),
               (0.80, 0.45, 0.85), (0.95, 0.45, 0.45), (0.45, 0.80, 0.80)]

TRADES = [
    ["Site Work", "Utilities/Sewage/Drainage", "Waterproofing",
     "Paving/Landscaping", "Elevators/Stairs", "Demolition"],
    ["Footings/Concrete", "Masonry", "Framing", "Metal Work",
     "Roofing/Flashing"],
    ["Exterior Surfaces/Installation", "Exterior Openings/Glazing",
     "Doors/Hardware", "Plumbing/Sprinkler", "Mechanical/HVAC", "Electrical"],
    ["Carpentry/Millwork", "Finishes", "Drywall", "Flooring", "Painting",
     "Specialties"],
]

# Words in a Daily Log's manpower trade or work text that tick a trade box
# (regular expressions, matched at a word start, case-insensitive). The
# words of the trade's own name always count too.
TRADE_KEYWORDS = {
    "Site Work": [r"site ?work", r"grading", r"rough grade", r"fine grade",
                  r"clear and grub", r"grubbing", r"topsoil", r"strip(ping)? "
                  r"top", r"sitework",
                  r"clearing", r"earthwork", r"excavat", r"backfill",
                  r"compact", r"erosion", r"silt fence", r"stabiliz",
                  r"undercut", r"proof ?roll", r"clear and grub", r"grub",
                  r"topsoil", r"stump", r"swppp", r"construction entrance",
                  r"survey", r"stak(?:e|ed|ing)\b", r"haul"],
    "Utilities/Sewage/Drainage": [r"utilit", r"sewer", r"sewage",
                                  r"storm ?drain", r"drainage", r"water ?main",
                                  r"water ?line", r"catch basin", r"manhole",
                                  r"culvert", r"storm structure", r"retention",
                                  r"detention", r"underground"],
    "Waterproofing": [r"waterproof", r"damp ?proof", r"below.grade membrane",
                      r"vapor barrier", r"vapor retarder"],
    "Paving/Landscaping": [r"pav", r"asphalt", r"curb", r"sidewalk",
                           r"landscap", r"irrigation", r"\bsod", r"seeding",
                           r"planting", r"striping"],
    "Elevators/Stairs": [r"elevator", r"stair"],
    "Demolition": [r"demo\b", r"demolition", r"demolish"],
    "Footings/Concrete": [r"footing", r"concrete", r"slab", r"foundation",
                          r"rebar", r"reinforcing", r"formwork", r"pour",
                          r"stem wall", r"grade beam", r"pier"],
    "Masonry": [r"masonry", r"cmu", r"block wall", r"brick", r"mason",
                r"grout"],
    "Framing": [r"framing", r"framed", r"stud wall", r"truss", r"sheathing",
                r"wall panel"],
    "Metal Work": [r"metal work", r"steel", r"joist", r"metal deck",
                   r"misc\w* metal", r"railing", r"bollard", r"lintel"],
    "Roofing/Flashing": [r"roof", r"flashing", r"shingle", r"coping",
                         r"gutter", r"downspout"],
    "Exterior Surfaces/Installation": [r"siding", r"stucco", r"eifs",
                                       r"cladding", r"exterior finish",
                                       r"veneer", r"soffit", r"fascia",
                                       r"house ?wrap", r"metal panel"],
    "Exterior Openings/Glazing": [r"glazing", r"glass", r"storefront",
                                  r"curtain ?wall", r"window"],
    "Doors/Hardware": [r"door", r"hardware", r"overhead door"],
    "Plumbing/Sprinkler": [r"plumb", r"sprinkler", r"fire protection",
                           r"fire line", r"water heater", r"backflow"],
    "Mechanical/HVAC": [r"hvac", r"mechanical", r"duct", r"rtu",
                        r"air handler", r"mini.?split", r"condens"],
    "Electrical": [r"electric", r"conduit", r"wiring", r"wire pull",
                   r"transformer", r"lighting", r"light fixture",
                   r"switchgear", r"\bpower\b"],
    "Carpentry/Millwork": [r"carpent", r"millwork", r"casework", r"cabinet",
                           r"\btrim", r"blocking"],
    "Finishes": [r"finishes", r"ceiling", r"acoustic", r"\bact\b"],
    "Drywall": [r"drywall", r"gypsum", r"sheetrock", r"gyp\w* board",
                r"tape and finish", r"taping", r"hang\w* board"],
    "Flooring": [r"flooring", r"\btile", r"carpet", r"\blvt", r"\bvct",
                 r"epoxy floor", r"polished concrete"],
    "Painting": [r"paint", r"primer", r"coating"],
    "Specialties": [r"specialt", r"toilet accessor", r"toilet partition",
                    r"signage", r"fire extinguisher", r"locker"],
}

DEFAULT_OPTIONS = {
    "captions": False, "decisions": False, "schedule": False,
    "lookahead": False, "weather_gap": False, "counts": False,
    "open_only": False, "blank_dates": False, "manpower": False,
    "safety": False, "key_plan": False, "work_areas": False,
    "before_after": False, "draft_from_logs": True, "co_log": False,
    "photos_per_page": 4, "size_preset": "email",
    # HELD patch (owner report pack): logs as they stood on the report
    # date, progress drafted by trade, and the owner pack sections
    # (owner_report_pack.py) from rep["pack"]
    "as_of_logs": False, "progress_by_trade": False, "owner_pack": False,
    # with owner_pack: "" (the full report), "weekly" (short weekly update)
    # or "monthly" (the optional monthly appendix) - see
    # owner_report_pack.PRESETS
    "report_preset": "",
    # HELD gaps patch: the pack drawn from the project data
    # (owner_report_auto.py) instead of rep["pack"]; look-ahead weeks
    "auto_pack": False, "lookahead_weeks": 2,
}

# new reports (gaps G01 / G09): logs as they stood on the report date and
# photo captions on. Saved reports keep what they had.
NEW_REPORT_OPTIONS = {"as_of_logs": True, "captions": True}

DEFAULT_TEMPLATE = {
    "title": "Project Progress Report",
    "logo": None,                         # path (copied next to the file)
    "company": {"name": "", "lines": []},
    "trades": TRADES,
    "trade_keywords": TRADE_KEYWORDS,
    "sections": {"wip": "WORK IN PROGRESS", "logs": "LOGS",
                 "weather": "INCLEMENT WEATHER DAYS",
                 "progress": "CURRENT PROGRESS",
                 "forecast": "UPCOMING WEATHER FORECAST - 10 DAY"},
    "colors": {"bar": "#D9D9D9", "head": "#F1F1F1", "frame": "#548235"},
    "frame_width": 1.65,
    "threshold_in": 0.50,                 # a weather day: this much rain
    "week_ends": 1,                       # Python weekday: 1 = Tuesday
    "forecast_mode": "attach",            # Wunderground screenshot
    # a new report's defaults (G01 / G09): logs as of the report date and
    # photo captions on; a saved company template keeps its own choice
    "options": dict(DEFAULT_OPTIONS, **NEW_REPORT_OPTIONS),
}
TEMPLATE_FILE = "owner_report_template.json"


# ============================================================= small helpers
def _day(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def mdy(v):
    """MM/DD/YYYY (the form's style), '' for nothing."""
    d = _day(v)
    return f"{d.month:02d}/{d.day:02d}/{d.year}" if d else ""


def long_date(v):
    d = _day(v)
    return f"{d:%B} {d.day}, {d.year}" if d else ""


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _now():
    return datetime.now().replace(microsecond=0).isoformat()


_ASCII = {"‘": "'", "’": "'", "“": '"', "”": '"',
          "–": "-", "—": "-", "…": "...", "•": "-",
          " ": " ", "−": "-", "′": "'", "″": '"'}


def _clean(text):
    """Text as Latin-1 (what the form has always printed; the embedded
    Liberation Sans covers it)."""
    t = "".join(_ASCII.get(c, c) for c in str(text or ""))
    return t.encode("latin-1", "replace").decode("latin-1")


def _rgb(hexcode, default=(0.85, 0.85, 0.85)):
    try:
        h = str(hexcode).lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (TypeError, ValueError):
        return default


def _tlen(text, size=FS, bold=False):
    from . import owner_report_logs as orl
    return orl.text_width(_clean(text), size, "hebo" if bold else "helv")


def fit_size(text, size, width, bold=False, smallest=0.7):
    """(text, size) that fits `width`: a smaller font first (down to
    `smallest` of the size), cut with '...' only past that (PM review
    NW-06: 'Ridgeview Constructors (fictio...' on every page)."""
    t = _clean(text)
    w = _tlen(t, size, bold)
    if w <= width or not t:
        return t, size
    s2 = max(size * smallest, size * width / w)
    if _tlen(t, s2, bold) <= width:
        return t, s2
    return _fit_text(t, s2, width, bold), s2


def _fit_text(text, size, width, bold=False):
    t = _clean(text)
    if _tlen(t, size, bold) <= width:
        return t
    while t and _tlen(t + "...", size, bold) > width:
        t = t[:-1]
    return (t.rstrip() + "...") if t else ""


def wrap(text, width, size=FS, bold=False):
    """Lines of text no wider than width (long words are split)."""
    out = []
    for para in _clean(text).split("\n"):
        line = ""
        for w in para.split():
            cand = f"{line} {w}" if line else w
            if _tlen(cand, size, bold) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while _tlen(w, size, bold) > width and len(w) > 1:
                k = len(w) - 1
                while k > 1 and _tlen(w[:k], size, bold) > width:
                    k -= 1
                out.append(w[:k])
                w = w[k:]
            line = w
        out.append(line)
    return out


def bullet_lines(text, width=WRAP, size=FS):
    """A progress bullet as printed: '- ' then the text, continuation lines
    indented three spaces (the form's style)."""
    lines = wrap(text, width - _tlen("- ", size), size) or [""]
    return ["- " + lines[0]] + ["   " + ln for ln in lines[1:]]


def _key(text):
    """De-duplication key: case, spaces and punctuation don't count."""
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").lower()).split())


def sentences(text):
    """The sentences of a log entry (lines and '. ' split; bullets and
    numbering stripped)."""
    out = []
    for line in str(text or "").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s*(?:[-*•>]+|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'])", line):
            s = s.strip().rstrip(";").strip()
            if s:
                out.append(s)
    return out


def _photo_key(ref):
    if isinstance(ref, dict):
        return ref.get("sha256") or ref.get("name") or ""
    return str(ref or "")


def _is_image(ref):
    ext = (ref.get("ext") or os.path.splitext(ref.get("name") or "")[1]
           or "").lower()
    return ext in (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif",
                   ".tiff", ".webp", ".bmp")


# ============================================================= template
def _template_path():
    from .. import settings
    return os.path.join(settings.DIR, TEMPLATE_FILE)


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_template():
    """The company template (settings folder), over the defaults."""
    data = {}
    try:
        with open(_template_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.warning("owner report template unreadable; using the default")
    t = _merge(DEFAULT_TEMPLATE, data)
    if "trades" in data:                    # a list replaces, not merges
        t["trades"] = copy.deepcopy(data["trades"])
    return t


def save_template(t):
    """Save the company template. A logo outside the settings folder is
    copied next to the template under a name made from its content, so a
    new logo never overwrites the file an older report still uses."""
    from .. import settings
    t = _merge(DEFAULT_TEMPLATE, t)
    os.makedirs(settings.DIR, exist_ok=True)
    logo = t.get("logo")
    if logo and os.path.isfile(logo):
        with open(logo, "rb") as f:
            data = f.read()
        name = "owner_report_logo_" + hashlib.sha256(data).hexdigest()[:12] \
            + os.path.splitext(logo)[1].lower()
        dest = os.path.join(settings.DIR, name)
        if os.path.abspath(logo) != os.path.abspath(dest):
            if not os.path.exists(dest):
                with open(dest, "wb") as f:
                    f.write(data)
            t["logo"] = dest
    tmp = _template_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=1)
    os.replace(tmp, _template_path())
    return t


def template_hash(t):
    blob = json.dumps(t, sort_keys=True, default=str).encode("utf-8")
    logo = t.get("logo")
    if logo and os.path.isfile(logo):
        with open(logo, "rb") as f:
            blob += f.read()
    return hashlib.sha256(blob).hexdigest()[:16]


def trade_list(t):
    """The template's trades, four columns of at most six (the form)."""
    cols = [list(c or [])[:len(BOX_Y)] for c in (t.get("trades") or TRADES)]
    return (cols + [[], [], [], []])[:4]


def _logo_path(store, t):
    logo = t.get("logo")
    if logo and os.path.isfile(logo):
        return logo
    ref = t.get("logo_ref")
    if ref and store is not None:
        try:
            return store.attachment_path(ref)
        except Exception:
            log.debug("logo attachment missing", exc_info=True)
    return None


def head_for(store, template=None, rep=None):
    """The header block the log pages print (company, project, logo, the
    report's date)."""
    t = template or load_template()
    hdr = (rep or {}).get("header") or {}
    st = store.setting
    d = _day((rep or {}).get("date")) or date.today()
    comp = t.get("company") or {}
    return {
        "company": {"name": comp.get("name") or st("contractor") or
                    st("company_name") or "",
                    "lines": list(comp.get("lines") or [])},
        "project": {"name": hdr.get("job_name") or store.name,
                    "number": hdr.get("job_no") or st("number") or "",
                    "number_arch": st("number_arch") or "",
                    "number_owner": st("number_owner") or "",
                    "location": st("location") or ""},
        "logo": _logo_path(store, t),
        "long_date": long_date(d), "date": d,
    }


# ============================================================= records
def options(rep):
    o = dict(DEFAULT_OPTIONS)
    o.update((rep or {}).get("options") or {})
    return o


def week_ending_for(day=None, week_ends=1):
    """The last day of the report week on or before `day` (the week closes
    on weekday `week_ends`: 1 = Tuesday)."""
    d = _day(day) or date.today()
    return d - timedelta(days=(d.weekday() - int(week_ends)) % 7)


def week_range(rep):
    """(first, last) day of the report's week (seven days)."""
    we = _day(rep.get("week_ending") or rep.get("date")) or date.today()
    return we - timedelta(days=6), we


def reports(store):
    """This job's reports, oldest week first."""
    return sorted(store.list(COLL),
                  key=lambda r: (r.get("week_ending") or "",
                                 _num(r.get("report_no"))))


def next_report_no(store):
    n = 0
    for r in store.list(COLL):
        try:
            n = max(n, int(str(r.get("report_no") or "0").strip() or 0))
        except ValueError:
            continue
    return f"{n + 1:03d}"


def blank(store, week_ending, template=None):
    t = template or load_template()
    we = _day(week_ending)
    return {
        "report_no": next_report_no(store), "week_ending": we.isoformat(),
        "date": we.isoformat(), "status": "Draft",
        "header": {"job_no": store.setting("number") or "",
                   "job_name": store.name},
        "trades": [], "trades_src": {}, "trades_off": [],
        "progress": [],
        "logs": {k: {"as_of": we.isoformat(), "attached": True}
                 for k in ("rfi", "submittal", "co")},
        "weather": {"impacted": 0, "claimed": 0,
                    "threshold_in": float(t.get("threshold_in") or 0.5),
                    "gap_note": "", "as_of": we.isoformat(), "days": []},
        # Jon's team screenshots Wunderground's 10-day page; the table
        # (Open-Meteo) is the other choice in the template
        "forecast": {"mode": t.get("forecast_mode") or "attach",
                     "attach_ref": None, "rows": [], "as_of": ""},
        "photos": [], "before_candidates": [], "decisions": [],
        "options": dict(DEFAULT_OPTIONS, **(t.get("options") or {})),
        "work_areas": [], "key_plan": None, "safety": "",
        "logistics": "", "summary_text": "",
        "exported": [],
    }


def carry_over(prev, store, week_ending):
    """Next week's report from last week's: number + 1, trades and bullets
    kept (bullets marked "carried" so the PM updates them), open decisions
    only, options, work areas and key plan kept, weather history kept
    (re-pulled by autofill), no photos - last week's pinned or located
    photos become "before" candidates for before/after pairs."""
    t = load_template()
    rep = blank(store, week_ending, t)
    try:
        n = int(str(prev.get("report_no") or "0")) + 1
    except ValueError:
        n = 0
    rep["report_no"] = f"{max(n, int(rep['report_no'])):03d}"
    rep["prev_id"] = prev.get("_id")
    rep["header"] = dict(rep["header"], **{k: v for k, v in
                                          (prev.get("header") or {}).items()
                                          if v})
    rep["trades"] = list(prev.get("trades") or [])
    rep["trades_src"] = {k: "carried" for k in rep["trades"]}
    rep["trades_off"] = list(prev.get("trades_off") or [])
    rep["progress"] = [{"text": b.get("text", ""),
                        "include": b.get("include", True), "src": "carried"}
                       for b in prev.get("progress") or []
                       if (b.get("text") or "").strip()]
    rep["decisions"] = [copy.deepcopy(d) for d in prev.get("decisions") or []
                        if not d.get("done")]
    rep["options"] = options(prev)
    rep["work_areas"] = copy.deepcopy(prev.get("work_areas") or [])
    rep["logistics"] = prev.get("logistics") or ""      # carried (G26)
    rep["key_plan"] = copy.deepcopy(prev.get("key_plan"))
    for k in ("rfi", "submittal", "co"):
        rep["logs"][k]["attached"] = \
            ((prev.get("logs") or {}).get(k) or {}).get("attached", True)
    pw = prev.get("weather") or {}
    rep["weather"].update(threshold_in=pw.get("threshold_in",
                                              rep["weather"]["threshold_in"]),
                          days=copy.deepcopy(pw.get("days") or []),
                          impacted=pw.get("impacted", 0),
                          claimed=pw.get("claimed", 0))
    rep["forecast"]["mode"] = (prev.get("forecast") or {}).get("mode",
                                                               "table")
    rep["before_candidates"] = [
        copy.deepcopy(p) for p in prev.get("photos") or []
        if p.get("include", True) and (p.get("pin") or
                                       (p.get("location") or "").strip())]
    return rep


def save(store, rep):
    """Store the report (numbering and sync like every other record)."""
    rec = store.save_record(COLL, rep)
    rep.update(_id=rec["_id"])
    return rec


def new_report(store, week_ending=None, from_previous=True, online=True,
               save_it=True):
    """A new report for the week ending `week_ending` (default: the week
    that closed last), carried over from the latest earlier report when
    there is one, filled from the job, and saved (save_it=False: not
    saved - the window builds it off the GUI thread and saves it on the
    GUI thread, where the store's listeners may touch widgets)."""
    t = load_template()
    we_given = _day(week_ending)
    we = we_given or week_ending_for(date.today(), t.get("week_ends", 1))
    prev = None
    if from_previous:
        earlier = [r for r in reports(store)
                   if not we_given or (r.get("week_ending") or "") <
                   we.isoformat()]
        prev = earlier[-1] if earlier else None
        if prev and not we_given:
            pwe = _day(prev.get("week_ending"))
            if pwe and pwe >= we:             # this week's is already out
                we = pwe + timedelta(days=7)
    rep = carry_over(prev, store, we) if prev else blank(store, we, t)
    autofill(store, rep, online=online)
    if save_it:
        save(store, rep)
    return rep


# ------------------------------------------------- background job results
# The window runs Update Weather and AI Draft on a copy of the report, off
# the GUI thread. Each job owns only these fields; merge_job_result folds
# them back into the live report so edits made meanwhile stay.
JOB_FIELDS = {"weather": ("weather", "forecast"),
              "ai": ("progress", "trades", "trades_src", "ai"),
              "export": ("template", "template_hash", "exported")}


def merge_job_result(store, rep, kind, done, before=None):
    """Fold a finished job's report `done` into the live `rep` (changed in
    place, returned). kind "weather": `before` is rep["weather"] when the
    job started - unchanged since, the job's weather is taken whole;
    changed (days ticked or typed, threshold), the job's rain is merged
    under the PM's choices like a re-pull. The forecast's rows / as-of /
    error come from the job, its mode stays. kind "ai": the job's Daily
    Log bullets replace the drafted ones (typed and carried bullets, also
    ones added meanwhile, stay) and trades are ticked again, keeping
    unticks. kind "export": the export log and template snapshot."""
    if kind == "weather":
        _merge_weather_job(rep, done, before)
    elif kind == "ai":
        _merge_bullets(rep, [copy.deepcopy(b) for b in
                             done.get("progress") or []
                             if str(b.get("src") or "").startswith("DL-")])
        _tick_trades(store, rep)
        rep["ai"] = copy.deepcopy(done.get("ai"))
    elif kind == "export":
        if not rep.get("template") and done.get("template"):
            rep["template"] = copy.deepcopy(done["template"])
            rep["template_hash"] = done.get("template_hash")
        rep["exported"] = copy.deepcopy(done.get("exported") or [])
    else:
        raise ValueError(f"unknown job {kind!r}")
    return rep


def _merge_weather_job(rep, done, before):
    from . import owner_report_logs as logs
    dw = copy.deepcopy(done.get("weather") or {})
    cur = rep.setdefault("weather", {})
    if before is not None and cur == before:
        rep["weather"] = dw
    else:
        thr = float(cur.get("threshold_in") or dw.get("threshold_in")
                    or 0.5)
        jd = dw.get("days") or []
        rows = [{"date": d.get("date"),
                 "rain_in": d.get("download_in") if d.get("source") ==
                 "typed" else d.get("rain_in")} for d in jd]
        days = logs.merge_weather(cur.get("days") or [], rows, thr,
                                  old_threshold=cur.get("threshold_used",
                                                        thr))
        notes = {d.get("date"): d.get("note") for d in jd if d.get("note")}
        for d in days:
            if not d.get("note") and notes.get(d["date"]):
                d["note"] = notes[d["date"]]
        cur.update(days=days, threshold_used=thr)
        for k in ("as_of", "error"):
            if k in dw:
                cur[k] = dw[k]
            else:
                cur.pop(k, None)
        cur["impacted"], cur["claimed"] = logs.weather_counts(cur)
    df = done.get("forecast") or {}
    f = rep.setdefault("forecast", {})
    for k in ("rows", "as_of", "error"):
        if k in df:
            f[k] = copy.deepcopy(df[k])
        else:
            f.pop(k, None)


# ============================================================= the week's logs
def week_logs(store, rep):
    """The Daily Logs dated in the report's week (any status), by date."""
    a, b = week_range(rep)
    out = []
    for d in store.list("daily"):
        dd = _day(d.get("date"))
        if dd and a <= dd <= b:
            out.append(d)
    out.sort(key=lambda d: (d.get("date") or "", d.get("_n") or 0))
    return out


def _log_no(d):
    return d.get("_no") or f"DL-{d.get('_n', 0):04d}"


def week_facts(store, rep):
    """The week's logged work as de-duplicated sentences: [{text, src
    (DL no), date}], then one line naming the crews on site. One-word
    notes are dropped (PM review NW-05: 'Clear and grub' and 'Strip
    topsoil' were dropped as too short, and no crew was named)."""
    seen, out = set(), []
    crews, first = [], None
    for d in week_logs(store, rep):
        for m in d.get("manpower") or []:
            c = (m.get("company") or "").strip()
            if c and _num(m.get("workers")) > 0 and c not in crews:
                crews.append(c)
                first = first or d
        texts = sentences(d.get("work"))
        for m in d.get("manpower") or []:
            texts += sentences(m.get("notes"))
        for s in texts:
            if len(s.split()) < 2:
                continue
            k = _key(s)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append({"text": s, "src": _log_no(d), "date": d.get("date")})
    if crews:
        out.append({"text": "Crews on site: " + ", ".join(crews),
                    "src": _log_no(first), "date": first.get("date")})
    return out


def _trade_patterns(t, trade):
    kws = list((t.get("trade_keywords") or {}).get(trade) or [])
    kws += [re.escape(w.strip().lower()) for w in re.split(r"[/,&]", trade)
            if len(w.strip()) > 2]
    return [re.compile(r"(?<![\w])" + k, re.I) for k in kws]


def match_trades(text, template=None):
    """The template trades a piece of text is about."""
    t = template or load_template()
    hits = []
    for col in trade_list(t):
        for trade in col:
            if any(p.search(text or "") for p in _trade_patterns(t, trade)):
                hits.append(trade)
    return hits


def set_trade(rep, trade, on):
    """Tick or untick a trade by hand. An untick is remembered, so drafting
    from the logs never ticks it again (and carry-over keeps it)."""
    trades = rep.setdefault("trades", [])
    off = rep.setdefault("trades_off", [])
    if on:
        if trade not in trades:
            trades.append(trade)
        if trade in off:
            off.remove(trade)
        rep.setdefault("trades_src", {}).setdefault(trade, "typed")
    else:
        if trade in trades:
            trades.remove(trade)
        if trade not in off:
            off.append(trade)
        rep.setdefault("trades_src", {}).pop(trade, None)
    return rep


_CO_SUFFIX = re.compile(r"[\s,]+(?:\(fictional\)|inc\.?|llc|l\.l\.c\.|co\.?|"
                        r"corp\.?|company|ltd\.?)\s*$", re.I)


def company_names(store, rep=None):
    """Firm names on the job (team, Daily Log manpower, owner, contractor,
    architect) and their short forms without Inc / LLC / Co /
    "(fictional)" - longest first."""
    names = set()
    for m in store.list("member"):
        names.add(m.get("company") or "")
    logs = week_logs(store, rep) if rep else store.list("daily")
    for d in logs:
        for m in d.get("manpower") or []:
            names.add(m.get("company") or "")
    for k in ("owner", "contractor", "architect"):
        names.add(str(store.setting(k) or ""))
    out = set()
    for n in names:
        n = n.strip()
        while n:
            out.add(n)
            short = _CO_SUFFIX.sub("", n).strip()
            if short == n:
                break
            n = short
    return sorted((n for n in out if len(n) > 3), key=len, reverse=True)


def strip_names(text, names):
    """Text with the firm names taken out, so "Granite Line Concrete" in a
    sentence about schedule updates doesn't tick Footings/Concrete."""
    text = text or ""
    for n in names:
        text = re.sub(re.escape(n), " ", text, flags=re.I)
    return text


def _tick_trades(store, rep, template=None):
    t = template or load_template()
    names = company_names(store, rep)
    off = set(rep.get("trades_off") or [])
    trades = rep.setdefault("trades", [])
    src = rep.setdefault("trades_src", {})
    for d in week_logs(store, rep):
        texts = [m.get("trade") or "" for m in d.get("manpower") or []
                 if _num(m.get("workers")) > 0 or m.get("trade")]
        texts += [m.get("notes") or "" for m in d.get("manpower") or []]
        # by trade (G10): ticks come from the crews on site; the free work
        # text only when the log has no manpower
        if not (options(rep).get("progress_by_trade") and
                d.get("manpower")):
            texts.append(d.get("work") or "")
        for text in texts:
            for trade in match_trades(strip_names(text, names), t):
                if trade in off:
                    continue
                if trade not in trades:
                    trades.append(trade)
                if src.get(trade) in (None, "", "carried"):
                    src[trade] = _log_no(d)
    order = [x for col in trade_list(t) for x in col]
    rep["trades"] = sorted(trades, key=lambda x: order.index(x)
                           if x in order else 99)
    return rep


def _merge_bullets(rep, new):
    """Replace the bullets drafted from logs before; keep typed and carried
    ones; drop drafted ones that repeat them."""
    keep = [b for b in rep.get("progress") or []
            if not str(b.get("src") or "").startswith("DL-")]
    have = {_key(b.get("text")) for b in keep}
    out = list(keep)
    for b in new:
        k = _key(b["text"])
        if k and k not in have:
            have.add(k)
            out.append(b)
    rep["progress"] = out
    return rep


def draft_from_daily_logs(store, rep, template=None):
    """Option (l): progress bullets from the week's Daily Logs (work text
    and manpower notes, de-duplicated, each with its DL source) and trade
    boxes ticked from manpower trades and the work text. Typed and carried
    bullets stay; the PM's unticks stay unticked."""
    t = template or load_template()
    if options(rep).get("progress_by_trade"):
        # ticks drafted earlier from the work text (drafting is on by
        # default, NW-05) give way to the crews-only rule (G10); trades the
        # PM ticked or that were carried from last week stay
        src = rep.setdefault("trades_src", {})
        auto = {k for k, v in src.items() if v not in (None, "", "carried")}
        rep["trades"] = [x for x in rep.get("trades") or [] if x not in auto]
        for k in auto:
            src.pop(k, None)
        return draft_by_trade(store, rep, t)
    bullets = [{"text": _sentence_end(f["text"]), "include": True,
                "src": f["src"]} for f in week_facts(store, rep)]
    _merge_bullets(rep, bullets)
    _tick_trades(store, rep, t)
    return rep


def _sentence_end(s):
    s = s.strip()
    return s + "." if s and s[-1].isalnum() else s


GENERAL = "General / site conditions"
_STOP = {"the", "a", "an", "and", "of", "to", "in", "on", "at", "for",
         "with", "from", "by", "into", "site", "was", "were", "is", "are",
         "crew", "crews", "started", "start", "continued", "continue"}
_ROLE_ONLY = re.compile(r"^(?:(?:assistant|asst\.?|general)?\s*"
                        r"(?:superintendent|supervision|foreman|pm|"
                        r"project manager)s?\s*(?:and|,|/)?\s*)+$", re.I)
_MARKERS = re.compile(r"\((?:test data|sample data|test)\)", re.I)


def _stem(w):
    if w.startswith("truckload"):
        return "load"
    for suf in ("ing", "ed", "al", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[:-len(suf)]
            if len(w) > 4 and w[-1] == w[-2]:
                w = w[:-1]                     # stripping -> strip
            break
    return w


def _tokens(s):
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", str(s or "").lower())
            if w not in _STOP}


def similar(a, b):
    """Two log sentences that say the same thing (most of the shorter
    one's words are in the other)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.7 or \
        inter / len(ta | tb) >= 0.5


def draft_by_trade(store, rep, template=None):
    """Option progress_by_trade: CURRENT PROGRESS bullets grouped by the
    page-1 trade, one bullet a trade a day ("Site Work - Mon 11/16: ..."),
    with one crew line a trade first and the work that belongs to no trade
    (weather, meetings, visits) last. Sentences come from the logs' work
    text and manpower notes; one that repeats another (same words, see
    similar()) is dropped; role-only notes ("Superintendent and assistant
    superintendent") and test markers are left out. Firm names never pick
    the trade. Typed and carried bullets stay first."""
    t = template or load_template()
    names = company_names(store, rep)
    order = [x for col in trade_list(t) for x in col]

    def trade_of(text):
        hits = match_trades(strip_names(text, names), t)
        return hits[0] if hits else None
    firm_trade, crews = {}, {}
    logs = week_logs(store, rep)
    for d in logs:
        for m in d.get("manpower") or []:
            co = _CO_SUFFIX.sub("", (m.get("company") or "").strip())
            tr = trade_of(f"{m.get('trade') or ''} {m.get('notes') or ''}")
            if tr and co:
                firm_trade.setdefault(co, tr)
    items = {}                                     # trade -> [(day, text)]
    keys = set()
    for d in logs:
        dd = _day(d.get("date"))
        found = []
        for s in sentences(_MARKERS.sub("", d.get("work") or "")):
            found.append((trade_of(s) or GENERAL, s))
        for m in d.get("manpower") or []:
            if not _num(m.get("workers")):
                continue
            co = _CO_SUFFIX.sub("", (m.get("company") or "").strip())
            role = (m.get("trade") or "").strip()
            fallback = trade_of(role) or firm_trade.get(co)
            if fallback and co:
                crews.setdefault(fallback, {}).setdefault(co, [])
                if role and role not in crews[fallback][co]:
                    crews[fallback][co].append(role)
            for s in sentences(_MARKERS.sub("", m.get("notes") or "")):
                if _ROLE_ONLY.match(s.strip(" .")):
                    continue
                found.append((trade_of(s) or fallback or GENERAL, s))
        today = []
        for tr, s in found:
            s = _sentence_end(s.strip())
            # the same words the same day, or the very same sentence on
            # another day, is a repeat ("continued in the west third" on
            # two days is two days' work)
            if len(s.split()) < 3 or _key(s) in keys or \
                    any(similar(s, x) for x in today):
                continue
            today.append(s)
            keys.add(_key(s))
            items.setdefault(tr, []).append((dd, s))
    groups = sorted(items, key=lambda k: (k == GENERAL, order.index(k)
                                          if k in order else 99))
    bullets = []
    for tr in groups:
        if tr in crews:
            who = "; ".join(f"{co} ({', '.join(r for r in roles)})"
                            if roles else co
                            for co, roles in crews[tr].items())
            bullets.append({"text": f"{tr} - crews this week: {who}.",
                            "include": True, "src": "DL-trade",
                            "trade": tr})
        days = {}
        for dd, s in items[tr]:
            days.setdefault(dd, []).append(s)
        for dd in sorted(x for x in days if x):
            lead = f"{tr} - {dd:%a} {dd.month}/{dd.day}: "
            bullets.append({"text": lead + " ".join(days[dd]),
                            "include": True, "src": "DL-trade",
                            "trade": tr})
    keep = [b for b in rep.get("progress") or []
            if not str(b.get("src") or "").startswith("DL-")]
    rep["progress"] = keep + bullets
    _tick_trades(store, rep, t)
    return rep


# ------------------------------------------------------------- local AI
AI_PROMPT = """You help a general contractor write the weekly progress \
report to the building owner. Below are FACTS copied from this week's \
daily logs. Each fact has an id in brackets.

FACTS
{facts}

Rewrite the facts as short bullets the owner can read.
RULES - follow every one:
1. Use ONLY the facts above. Never add work, quantities, numbers, dates, \
names, places, causes, plans or opinions that are not in the facts.
2. Plain past tense, one idea per bullet, no crew chatter. Copy every \
number, date, area and gridline exactly as written.
3. You may merge facts about the same work into one bullet, and leave out \
trivial facts (housekeeping, breaks, meals).
4. Every bullet lists the ids of the facts it came from.

Answer with JSON only, like:
{{"bullets": [{{"text": "Placed slab-on-grade at Bldg A, east half.", \
"facts": [1, 4]}}]}}
"""
AI_MAX_FACTS = 120


def _numbers(text):
    return set(re.findall(r"\d+(?:[.,/:-]\d+)*", text or ""))


def _parse_ai(raw):
    data = raw if isinstance(raw, (dict, list)) else json.loads(
        re.sub(r"^```(?:json)?|```$", "", str(raw or "").strip()).strip())
    if isinstance(data, dict):
        data = data.get("bullets")
    if not isinstance(data, list):
        raise ValueError("no bullets in the answer")
    return data


def ai_draft_progress(store, rep, ask=None, template=None):
    """Progress bullets rewritten for the owner by the local model (Ollama,
    JSON mode) from the week's logged facts. Each bullet keeps its Daily
    Log source(s); a bullet citing no fact, or carrying a number that isn't
    in its facts, is replaced by its facts as logged; facts the model left
    out come back unticked. If the model can't be reached or answers
    badly, the plain draft_from_daily_logs() is used.
    `ask(prompt) -> text` (tests pass a scripted one)."""
    t = template or load_template()
    facts = week_facts(store, rep)[:AI_MAX_FACTS]
    if not facts:
        rep["ai"] = {"at": _now(), "fallback": "No daily-log text this week."}
        return draft_from_daily_logs(store, rep, t)
    if ask is None:
        from ..ai import review
        ask = lambda p: review._ollama(p, json_mode=True)  # noqa: E731
    lines = "\n".join(f"[{i}] ({f['src']}, {mdy(f['date'])}) "
                      f"{f['text']}" for i, f in enumerate(facts, 1))
    try:
        items = _parse_ai(ask(AI_PROMPT.format(facts=lines)))
        bullets, used = [], set()
        for it in items:
            if not isinstance(it, dict):
                continue
            text = " ".join(str(it.get("text") or "").split())
            ids = []
            for x in it.get("facts") or it.get("ids") or []:
                try:
                    i = int(x)
                except (TypeError, ValueError):
                    continue
                if 1 <= i <= len(facts) and i not in ids:
                    ids.append(i)
            if not text or not ids:
                continue
            src_text = " ".join(facts[i - 1]["text"] for i in ids)
            if not _numbers(text) <= _numbers(src_text):
                # a number that isn't logged: keep the facts as logged
                for i in ids:
                    if i not in used:
                        bullets.append(_fact_bullet(facts[i - 1]))
                        used.add(i)
                continue
            srcs = []
            for i in ids:
                if facts[i - 1]["src"] not in srcs:
                    srcs.append(facts[i - 1]["src"])
            used.update(ids)
            bullets.append({"text": _sentence_end(_clean(text)),
                            "include": True, "src": ",".join(srcs),
                            "ai": True})
        if not any(b.get("ai") for b in bullets):
            raise ValueError("the answer had no usable bullets")
    except Exception as e:                       # noqa: BLE001
        log.info("AI draft failed, plain draft used: %s", e)
        rep["ai"] = {"at": _now(), "fallback": str(e)[:200]}
        return draft_from_daily_logs(store, rep, t)
    for i, f in enumerate(facts, 1):              # left out: offered unticked
        if i not in used:
            b = _fact_bullet(f)
            b["include"] = False
            bullets.append(b)
    _merge_bullets(rep, bullets)
    _tick_trades(store, rep, t)
    rep["ai"] = {"at": _now(), "fallback": None}
    return rep


def _fact_bullet(f):
    return {"text": _sentence_end(f["text"]), "include": True,
            "src": f["src"]}


# ============================================================= photos
def _taken(path, fallback=None):
    """(iso time, "exif" | "file" | "log")."""
    try:
        from . import photofit
        when, how = photofit.exif_taken(path)
    except Exception:
        log.debug("no photo date", exc_info=True)
        when, how = None, "file"
    if how != "exif" and fallback:
        return str(fallback)[:16], "log"
    if when is None:
        return "", how
    return when.replace(microsecond=0).isoformat()[:16], how


def _photo_entry(ref, order, taken="", how="", src=""):
    return {"ref": ref, "order": order, "include": True, "rotate": 0,
            "crop": None, "fit": "auto", "caption": "", "location": "",
            "taken": taken, "taken_src": how, "src": src, "pin": None,
            "pair_with": None}


def add_photos(store, rep, paths, defer=False):
    """Attach photo files to the report (after the ones it has)."""
    photos = rep.setdefault("photos", [])
    have = {_photo_key(p.get("ref")) for p in photos}
    n = max([p.get("order") or 0 for p in photos] + [0])
    added = []
    for path in paths:
        ref = store.attach(path, defer=defer)
        if _photo_key(ref) in have:
            continue
        have.add(_photo_key(ref))
        n += 1
        taken, how = _taken(store.attachment_path(ref))
        e = _photo_entry(ref, n, taken, how, "upload")
        photos.append(e)
        added.append(e)
    return added


def photos_from_daily_logs(store, rep):
    """The week's Daily Log photos not in the report yet, in log order."""
    photos = rep.setdefault("photos", [])
    have = {_photo_key(p.get("ref")) for p in photos}
    n = max([p.get("order") or 0 for p in photos] + [0])
    added = []
    for d in week_logs(store, rep):
        for ref in d.get("photos") or []:
            if not isinstance(ref, dict) or not _is_image(ref) or \
                    _photo_key(ref) in have:
                continue
            have.add(_photo_key(ref))
            try:
                path = store.attachment_path(ref)
                taken, how = _taken(path, d.get("date"))
            except Exception:
                taken, how = str(d.get("date") or ""), "log"
            n += 1
            e = _photo_entry(ref, n, taken, how, _log_no(d))
            photos.append(e)
            added.append(e)
    return added


def sort_photos(rep):
    """Photos in the order they were taken (G09); untimed ones last."""
    ph = rep.get("photos") or []
    ph.sort(key=lambda p: (not p.get("taken"), str(p.get("taken") or ""),
                           p.get("order") or 0))
    for i, p in enumerate(ph, 1):
        p["order"] = i
    return rep


def printed_photos(rep):
    return sorted([p for p in rep.get("photos") or []
                   if p.get("include", True)],
                  key=lambda p: (p.get("order") or 0))


def _inside(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and \
                x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside


def _sheet_key(sheet):
    if isinstance(sheet, dict):
        return "ref:" + (sheet.get("sha256") or "")
    return "path:" + os.path.normcase(os.path.abspath(str(sheet or "")))


def photo_location(rep, photo):
    """Where a photo was taken: the work area its pin falls in, else the
    typed location."""
    pin = photo.get("pin")
    if pin:
        for a in rep.get("work_areas") or []:
            if _sheet_key(a.get("sheet")) == _sheet_key(pin.get("sheet")) \
                    and int(a.get("page") or 0) == int(pin.get("page") or 0) \
                    and len(a.get("pts") or []) >= 3 and \
                    _inside((pin["x"], pin["y"]), a["pts"]) and \
                    a.get("label"):
                return a["label"]
    return (photo.get("location") or "").strip()


def suggest_pairs(rep, max_dist=18.0):
    """Option (k): [(photo, before)] - for each photo with a pin, last
    week's photo with a pin on the same sheet and page within max_dist
    points; with no pin, last week's photo with the same location text."""
    out = []
    cands = rep.get("before_candidates") or []
    for p in printed_photos(rep):
        best, bd = None, None
        pin = p.get("pin")
        for c in cands:
            cp = c.get("pin")
            if pin and cp:
                if _sheet_key(pin.get("sheet")) != _sheet_key(cp.get("sheet")) \
                        or int(pin.get("page") or 0) != \
                        int(cp.get("page") or 0):
                    continue
                dist = math.hypot(pin["x"] - cp["x"], pin["y"] - cp["y"])
                if dist <= max_dist and (bd is None or dist < bd):
                    best, bd = c, dist
            elif not pin and not cp:
                loc = (p.get("location") or "").strip().lower()
                if loc and loc == (c.get("location") or "").strip().lower() \
                        and best is None:
                    best = c
        if best is not None:
            out.append((p, best))
    return out


def accept_pairs(rep, pairs=None):
    """Set pair_with on the suggested pairs (the PM accepted them)."""
    for p, before in (pairs if pairs is not None else suggest_pairs(rep)):
        p["pair_with"] = before.get("ref")
    return rep


# ============================================================= autofill
def _weather_rows_from_logs(store, start, end):
    rows = []
    for d in store.list("daily"):
        dd = _day(d.get("date"))
        w = d.get("weather")
        if not dd or not (start <= dd <= end) or not isinstance(w, dict):
            continue
        # '0.6', '0.6 in', '0.6"' all read (PM review NW-04: '0.6 in' was
        # skipped, so a logged rain day never counted)
        m = re.search(r"\d+(?:\.\d+)?", str(w.get("precip") or "0"))
        rain = float(m.group(0)) if m else 0.0
        rows.append({"date": dd.isoformat(), "rain_in": rain,
                     "high": w.get("high"), "low": w.get("low"),
                     "src": _log_no(d)})
    return rows


def project_start(store, rep=None):
    for k in ("project_start", "ntp", "contract_date"):
        d = _day(store.setting(k))
        if d:
            return d
    dates = [_day(d.get("date")) for d in store.list("daily")]
    dates = [d for d in dates if d]
    if dates:
        return min(dates)
    return week_range(rep)[0] if rep else date.today()


def fill_weather(store, rep, online=True, today=None):
    """Weather days from the project start to the report week's end: the
    weather history for the job site (Open-Meteo) over the Daily Logs'
    rain, merged into the stored days by owner_report_logs.merge_weather
    (days the PM toggled - "edited" - keep their tracked / claimed, notes
    stay). Daily Log rain fills only days not stored yet, so a stored
    (downloaded or typed) amount never falls back to a log's 0; a claimed
    day a re-pull would un-claim stays claimed with a note. A Daily Log
    weather delay notes its day."""
    from . import owner_report_logs as logs
    w = rep.setdefault("weather", {})
    thr = float(w.get("threshold_in") or 0.5)
    w["threshold_in"] = thr
    start = project_start(store, rep)
    # the report's week end, not the computer's clock (G02): Daily Logs
    # dated up to the report date count on any run date; a download only
    # asks for days up to today
    end = week_range(rep)[1]
    fetch_end = min(end, _day(today) or date.today())
    old = list(w.get("days") or [])
    # Daily Log rain (the morning fetch, often 0.00) only fills days not
    # stored yet: a stored day - downloaded history or a typed amount -
    # changes only by a fresh download or by the PM (review: a log 0
    # overwrote 1.2 in of recorded rain and the claimed day dropped out).
    stored = {str(d.get("date"))[:10] for d in old
              if _num(d.get("rain_in"), None) is not None}
    rows = {r["date"]: r for r in _weather_rows_from_logs(store, start, end)
            if r["date"] not in stored}
    place = store.setting("location") or ""
    w.pop("error", None)
    if online and place and start <= fetch_end:
        have = sorted(d.get("date") or "" for d in old)
        frm = start
        if have and have[-1]:                # re-pull the last week too
            frm = max(start, (_day(have[-1]) or start) - timedelta(days=7))
        try:
            from . import weather
            for r in weather.history(place, frm.isoformat(),
                                     fetch_end.isoformat()) or []:
                k = str(r.get("date"))[:10]
                rows[k] = dict(r, date=k)
        except Exception as e:                    # noqa: BLE001
            w["error"] = f"Weather history not available: {e}"
            log.info("weather history: %s", e)
    new = sorted(rows.values(), key=lambda r: r["date"])
    days = logs.merge_weather(old, new, thr,
                              old_threshold=w.get("threshold_used", thr))
    w["threshold_used"] = thr
    delays = {}
    for dl in store.list("daily"):
        for x in dl.get("delays") or []:
            if (x.get("cause") or "") == "Weather":
                delays[str(dl.get("date"))[:10]] = \
                    f"{_log_no(dl)}: {x.get('description') or 'weather delay'}"
    have = {d.get("date") for d in days}
    for k in delays:
        if k not in have and start.isoformat() <= k <= end.isoformat():
            days.append({"date": k, "rain_in": None, "tracked": False,
                         "claimed": False})
    for d in days:
        if d.get("date") in delays:
            if not d.get("note"):
                d["note"] = delays[d["date"]]
    days.sort(key=lambda d: d.get("date") or "")
    # NW-04 + gap G02: a day with 4+ hours lost to weather on a Daily Log is
    # an impacted day unless the PM set it; claimed from Delay Log notices
    apply_weather_rules(store, rep, days, end)
    w["days"] = days
    w["impacted"], w["claimed"] = logs.weather_counts(w)
    w["as_of"] = end.isoformat()
    return rep


ADVERSE_HOURS = 4.0          # hours lost to weather that make an adverse day


def weather_hours_lost(store, end=None):
    """{iso date: hours lost to weather} from the Daily Logs' delays."""
    out = {}
    for dl in store.list("daily"):
        k = str(dl.get("date") or "")[:10]
        if end and (_day(k) or end) > end:
            continue
        for x in dl.get("delays") or []:
            if (x.get("cause") or "") == "Weather":
                out[k] = out.get(k, 0.0) + _num(x.get("hours"))
    return out


def uses_delay_log(store):
    """True when the job keeps weather delays on the Delay Log - then a
    day is claimed only by a notice there and the contract finish moves
    by granted days (G02 / G03). A job with no weather delay records keeps
    the threshold / typed claimed days, as before."""
    return any((x.get("cause") or "") == "Weather"
               for x in store.list("delay"))


def weather_notices(store, as_of):
    """{iso date: delay no} - the workdays covered by Weather delay notices
    given on or before `as_of` (Delay Log; withdrawn / denied left out)."""
    out = {}
    for x in store.list("delay"):
        if (x.get("cause") or "") != "Weather" or \
                x.get("status") in ("Withdrawn", "Denied"):
            continue
        nd = _day(x.get("notice_date"))
        a = _day(x.get("event_start"))
        if not nd or not a or nd > as_of:
            continue
        b = _day(x.get("event_end")) or a
        d = a
        while d <= b:
            out[d.isoformat()] = x.get("_no") or ""
            d += DAY
    return out


def apply_weather_rules(store, rep, days, as_of):
    """Gap G02: a day is tracked (adverse) by rain over the threshold or
    ADVERSE_HOURS lost on a Daily Log (a PM's edit stays), and CLAIMED only
    when a Weather delay notice given by the report date covers it - the
    Delay Log, not the threshold. A PM's "claim_edited" day stays. A job
    with no weather delays on the Delay Log keeps the claimed flags it had
    (threshold / typed), as before."""
    lost = weather_hours_lost(store, as_of)
    notes = weather_notices(store, as_of)
    thr = _num(((rep or {}).get("weather") or {}).get("threshold_in"), 0.5)
    by_notice = uses_delay_log(store)
    for d in days:
        k = str(d.get("date") or "")[:10]
        if "tracked" not in d and not d.get("edited"):  # a typed day
            rain = _num(d.get("rain_in"), None)
            dd = _day(k)
            d["tracked"] = bool(rain is not None and dd and
                                dd.weekday() < 5 and
                                _c2(rain) >= _c2(thr))
        if lost.get(k, 0) >= ADVERSE_HOURS and not d.get("edited"):
            d["tracked"] = True
        if not by_notice:
            d.setdefault("claimed", bool(d.get("tracked")))
            continue
        if not d.get("claim_edited"):
            d["claimed"] = k in notes
            if k in notes:
                d["claim_ref"] = notes[k]
            else:
                d.pop("claim_ref", None)
    return days


def granted_days(store, as_of, cause=None):
    """Days granted on the Delay Log (status Granted, decided on or before
    `as_of`: granted_on, else the notice date)."""
    n = 0
    for x in store.list("delay"):
        if x.get("status") not in ("Granted", "Closed") or \
                not _num(x.get("days_granted")):
            continue
        if cause and (x.get("cause") or "") != cause:
            continue
        when = _day(x.get("granted_on")) or _day(x.get("notice_date"))
        if when and when <= as_of:
            n += int(_num(x.get("days_granted")))
    return n



def fill_forecast(store, rep, online=True, today=None):
    f = rep.setdefault("forecast", {"mode": "table", "attach_ref": None,
                                    "rows": [], "as_of": ""})
    place = store.setting("location") or ""
    if f.get("mode", "table") != "table" or not online or not place:
        return rep
    try:
        from . import weather
        f["rows"] = list(weather.forecast(place, days=10) or [])
        f["as_of"] = (_day(today) or date.today()).isoformat()
        f.pop("error", None)
    except Exception as e:                        # noqa: BLE001
        f["error"] = f"Forecast not available: {e}"
        log.info("forecast: %s", e)
    return rep


def autofill(store, rep, online=True, today=None):
    """Fill what the job already knows: header (project settings), logs'
    as-of date, weather days (history / Daily Logs), the 10-day forecast,
    the week's Daily Log photos, and - with option draft_from_logs - the
    trades and progress bullets."""
    hdr = rep.setdefault("header", {})
    if not hdr.get("job_no"):
        hdr["job_no"] = store.setting("number") or ""
    if not hdr.get("job_name"):
        hdr["job_name"] = store.name
    d = rep.get("date") or rep.get("week_ending")
    for k in ("rfi", "submittal", "co"):
        rep.setdefault("logs", {}).setdefault(k, {"attached": True})
        rep["logs"][k]["as_of"] = d
    try:
        fill_weather(store, rep, online=online, today=today)
    except ImportError:
        log.warning("owner_report_logs not available: weather not filled")
    fill_forecast(store, rep, online=online, today=today)
    photos_from_daily_logs(store, rep)
    if options(rep).get("draft_from_logs"):
        draft_from_daily_logs(store, rep)
    return rep


# ============================================================= manpower, safety
def manpower_week(store, rep):
    """Option (h): {"days": [dates], "rows": [{company, trade, by_day {iso:
    n}, total}], "totals": {iso: n}, "total": n} from the week's Daily Log
    manpower lines (workers summed per company and trade per day). Weekdays
    always show; a weekend day shows when anyone worked."""
    a, b = week_range(rep)
    by = {}
    days = set()
    d = a
    while d <= b:
        if d.weekday() < 5:
            days.add(d.isoformat())
        d += DAY
    for dl in week_logs(store, rep):
        day = str(dl.get("date"))[:10]
        for m in dl.get("manpower") or []:
            n = _num(m.get("workers"))
            if not n:
                continue
            k = ((m.get("company") or "").strip(),
                 (m.get("trade") or "").strip())
            row = by.setdefault(k, {"company": k[0], "trade": k[1],
                                    "by_day": {}, "total": 0})
            row["by_day"][day] = row["by_day"].get(day, 0) + n
            row["total"] += n
            days.add(day)
    days = sorted(days)
    rows = sorted(by.values(), key=lambda r: (r["company"].lower(),
                                              r["trade"].lower()))
    totals = {d: sum(r["by_day"].get(d, 0) for r in rows) for d in days}
    return {"days": [_day(x) for x in days], "rows": rows, "totals": totals,
            "total": sum(r["total"] for r in rows)}


def safety_line(store, rep):
    """The SAFETY line: typed, else the first sentence of each of the
    week's Daily Log safety notes."""
    if (rep.get("safety") or "").strip():
        return rep["safety"].strip()
    seen, out = set(), []
    for dl in week_logs(store, rep):
        ss = sentences(dl.get("safety"))
        if ss and _key(ss[0]) not in seen:
            seen.add(_key(ss[0]))
            out.append(ss[0].rstrip("."))
    return "; ".join(out) + ("." if out else "")


# ============================================================= schedule
def schedule_status(store, rep):
    """Option (c): {"has": False} without activities, else percent
    (duration-weighted), contract/weather/total days, used, remaining,
    ntp, contract_finish, data_date, milestones [{name, baseline, forecast,
    variance}], and recovery (None, or {behind, plan, status, steps,
    agreed, target, forecast})."""
    from . import schedule
    if not store.list("activity"):
        return {"has": False}
    cpm = schedule.cached(store)
    rows = [r for r in cpm["rows"] if not r.get("summary")]
    if not rows:
        return {"has": False}
    cal = cpm.get("cal")
    rd = _day(rep.get("date")) or date.today()
    wsum = sum(max(0, int(r.get("dur") or 0)) for r in rows)
    if wsum:
        pct = sum(max(0, int(r.get("dur") or 0)) *
                  (100.0 if r.get("status") == "Complete"
                   else min(100.0, _num(r.get("percent"))))
                  for r in rows) / wsum
    else:
        pct = 0.0
    ntp = _day(store.setting("project_start")) or cpm.get("start")
    weather_days = store.setting("weather_days_granted")
    weather_src = "granted"
    other = 0
    if weather_days in (None, "") and uses_delay_log(store):
        # G03: the contract finish moves only by GRANTED time - the Delay
        # Log's granted days as of the report date, never claimed days
        weather_days = granted_days(store, rd, "Weather")
        other = granted_days(store, rd) - weather_days
    elif weather_days in (None, ""):
        # no weather on the Delay Log: as before, the claimed days
        weather_days = weather_counts(rep)[1]
        weather_src = "claimed"
    weather_days = int(_num(weather_days))
    contract = store.setting("contract_days")
    contract = int(_num(contract)) if contract not in (None, "") else None
    if contract is None and ntp:
        cf = _day(store.setting("contract_finish"))
        if cf:
            contract = (cf - ntp).days + 1
    out = {"has": True, "percent": round(pct, 1), "ntp": ntp,
           "data_date": schedule.data_date(store),
           "contract_days": contract, "weather_days": weather_days,
           "weather_src": weather_src, "granted_other": other,
           "total_days": None, "used": None,
           "remaining": None, "contract_finish": None,
           "forecast_finish": cpm.get("finish")}
    if ntp:
        out["used"] = max(0, (rd - ntp).days + 1)
    if contract is not None and ntp:
        total = contract + weather_days + other
        out["total_days"] = total
        out["remaining"] = total - out["used"]
        out["contract_finish"] = ntp + timedelta(days=total - 1)
    ms = sorted([r for r in rows if r.get("milestone") and
                 r.get("status") != "Complete"], key=lambda r: r["ef"])[:3]
    out["milestones"] = [{"name": r.get("name") or "",
                          "baseline": _day(r.get("baseline_finish")),
                          "forecast": r["ef"],
                          "variance": schedule.variance(r, cal)}
                         for r in ms]
    out["recovery"] = _recovery(store, cpm)
    return out


def _recovery(store, cpm):
    try:
        from . import recovery
        plan = store.setting(recovery.SETTING)
        st = recovery.standing(store, cpm=cpm)
    except Exception:
        log.debug("no recovery standing", exc_info=True)
        return None
    if st.get("behind") is None and not plan:
        return None
    steps = list((plan or {}).get("steps") or [])
    return {"behind": st.get("behind"), "target": st.get("target"),
            "forecast": st.get("forecast"),
            "plan": bool(plan and (steps or plan.get("status") in
                                   ("Applied", "Approved"))),
            "status": (plan or {}).get("status") or "",
            "applied": (plan or {}).get("applied") or "",
            "steps": len(steps),
            "agreed": sum(1 for s in steps if s.get("agreed"))}


def recovery_text(rec):
    """'Forecast finish ... vs target ...: 5 workdays behind. Recovery plan
    in place (...)' - or '' with nothing to say."""
    if not rec:
        return ""
    parts = []
    b = rec.get("behind")
    if b is not None and rec.get("target"):
        how = (f"{b} workday{'s' if b != 1 else ''} behind" if b > 0 else
               f"{-b} workday{'s' if b != -1 else ''} ahead" if b < 0 else
               "on schedule")
        parts.append(f"Forecast finish {mdy(rec.get('forecast'))} vs target "
                     f"{mdy(rec.get('target'))}: {how}.")
    if rec.get("plan"):
        st = rec.get("status") or "Draft"
        if st == "Applied":
            t = "Recovery plan in place"
            if rec.get("applied"):
                t += f" since {mdy(rec['applied'])}"
        else:
            t = f"Recovery plan prepared ({st.lower()}, not yet applied)"
        t += f": {rec['steps']} step{'s' if rec['steps'] != 1 else ''}"
        if rec["steps"]:
            t += f", {rec['agreed']} agreed by the subs"
        parts.append(t + ".")
    return " ".join(parts)


def lookahead_rows(store, rep):
    """Option (d): (first day, last day, rows) - the activities working in
    the 14 days after the report date, plus the overdue ones, from the
    meeting look-ahead (activity_lookahead.rows)."""
    from . import activity_lookahead as la
    rd = _day(rep.get("date")) or date.today()
    weeks = 3 if int(options(rep).get("lookahead_weeks") or 2) == 3 else 2
    s, e = rd + DAY, rd + timedelta(days=7 * weeks)
    rows = [r for r in la.rows(store, max(3, weeks), s)
            if r["late"] or (r["start"] <= e and r["finish"] >= s)]
    return s, e, rows


def _holidays(store):
    """The project's holidays (setting "holidays") as dates."""
    from . import schedule
    out = set()
    for h in store.setting("holidays") or ():
        d = schedule._holiday(h)
        if d:
            out.add(d)
    return out


def submittals_due(store, rep):
    from . import lookahead
    rd = _day(rep.get("date")) or date.today()
    return lookahead.lookahead(store, 2, rd + DAY)


# ============================================================= drawing
class _Ctx:
    """One build: the document, template, header and running state."""

    def __init__(self, store, rep, t, doc):
        self.store, self.rep, self.t, self.doc = store, rep, t, doc
        self.opts = options(rep)
        self.head = head_for(store, t, rep)
        col = t.get("colors") or {}
        self.bar = _rgb(col.get("bar", "#D9D9D9"))
        self.headfill = _rgb(col.get("head", "#F1F1F1"), (0.945,) * 3)
        self.frame = _rgb(col.get("frame", "#548235"), (0.329, 0.51, 0.208))
        self.frame_w = float(t.get("frame_width") or 1.65)
        self.title = t.get("title") or "Project Progress Report"
        self.logo = self.head.get("logo")
        self.logo_xref = 0
        self.photo_bytes = 0
        self.raster_bytes = 0                 # copied pages put in as images
        self.sheet_modes = []                 # (mode, why) a plan sheet
        self.photo_page = {}                  # photo key -> report page no
        self.photo_no = {}                    # photo key -> photo number
        self.warnings = []

    # ---- text and shapes
    def text(self, page, x, y, s, size=FS, bold=False, color=BLACK,
             align="left", width=None):
        s = _clean(s)
        if width is not None:
            s, size = fit_size(s, size, width, bold)
        if not s:
            return
        if align != "left":
            w = _tlen(s, size, bold)
            x = x - w / 2 if align == "center" else x - w
        from . import owner_report_logs as orl
        orl.put_text(page, (x, y), s, size, "hebo" if bold else "helv",
                     color)

    def rect(self, page, r, color=BLACK, fill=None, width=0.5):
        import fitz
        page.draw_rect(fitz.Rect(*r), color=color, fill=fill, width=width)

    def line(self, page, a, b, color=BLACK, width=0.5):
        page.draw_line(a, b, color=color, width=width)

    def section_bar(self, page, y, title, center=False, x0=X0, x1=X1):
        self.rect(page, (x0, y, x1, y + BAR_H), fill=self.bar)
        if center:
            self.text(page, (x0 + x1) / 2, y + 8.6, title, bold=True,
                      align="center")
        else:
            self.text(page, x0 + 1.5, y + 8.6, title, bold=True,
                      width=x1 - x0 - 3)

    def put_logo(self, page, box):
        import fitz
        if not self.logo:
            name = self.head["company"].get("name")
            if name:
                bw = box[2] - box[0]
                if self.opts.get("owner_pack") and _tlen(name, 10, True) > bw:
                    # shrink to fit on one line (down to 8 pt), else two
                    # lines, before cutting the name
                    lines = _name_lines(name, bw)
                    size = lines[0]
                    y = (box[1] + box[3]) / 2 + 4 - \
                        (len(lines) - 2) * (size + 1.5) / 2
                    for ln in lines[1:]:
                        self.text(page, box[2], y, ln, size=size, bold=True,
                                  color=GREY_TEXT, align="right", width=bw)
                        y += size + 1.5
                    return
                self.text(page, box[2], (box[1] + box[3]) / 2 + 4, name,
                          size=10, bold=True, color=GREY_TEXT,
                          align="right", width=bw)
            return
        r = fitz.Rect(*box)
        try:
            if self.logo.lower().endswith(".pdf"):
                # vectors, or one image when its fonts aren't embedded
                from . import owner_report_logs as orl
                orl.place_logo(page, r, self.logo)
            elif self.logo_xref:
                page.insert_image(r, xref=self.logo_xref,
                                  keep_proportion=True)
            else:
                self.logo_xref = page.insert_image(r, filename=self.logo,
                                                   keep_proportion=True)
        except Exception as e:                    # noqa: BLE001
            self.warnings.append(f"Logo not printed: {e}")
            self.logo = None

    def std_page(self):
        """A landscape page with the photo-page header (title + logo)."""
        p = self.doc.new_page(width=W, height=H)
        self.text(p, W / 2, TITLE_Y2, self.title, size=15.4, bold=True,
                  align="center")
        self.put_logo(p, LOGO2)
        return p

    def header_table(self, page):
        rep = self.rep
        hdr = rep.get("header") or {}
        vals = [("REPORT #", rep.get("report_no") or ""),
                ("JOB NUMBER", hdr.get("job_no") or ""),
                ("JOB NAME", hdr.get("job_name") or ""),
                ("DATE", mdy(rep.get("date") or rep.get("week_ending")))]
        for i, (lab, val) in enumerate(vals):
            y = HEAD_Y + i * HEAD_ROW
            self.rect(page, (HEAD_X[0], y, HEAD_X[1], y + HEAD_ROW))
            self.rect(page, (HEAD_X[1], y, HEAD_X[2], y + HEAD_ROW))
            self.text(page, HEAD_X[0] + 1.5, y + 8.4, lab, bold=True,
                      width=HEAD_X[1] - HEAD_X[0] - 3)
            self.text(page, HEAD_X[1] + 1.5, y + 8.4, val,
                      width=HEAD_X[2] - HEAD_X[1] - 3)

    def page1_top(self):
        p = self.doc.new_page(width=W, height=H)
        self.text(p, 394.0, TITLE_Y1, self.title, size=12, bold=True,
                  align="center")
        self.put_logo(p, LOGO1)
        self.header_table(p)
        return p


def _name_lines(name, width):
    """[size, line, ...]: the company name on one line at 10 down to 8 pt,
    else split in two at the best word break, 10 down to 6 pt."""
    size = 10.0
    while size >= 8.0:
        if _tlen(name, size, True) <= width:
            return [size, name]
        size -= 0.25
    words = name.split()
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        w = max(_tlen(a, 1, True), _tlen(b, 1, True))
        if best is None or w < best[0]:
            best = (w, a, b)
    if not best:
        return [size, name]
    size = max(6.0, min(10.0, width / best[0]))
    return [size, best[1], best[2]]


def _check(page, x, y):
    """A tick drawn in a checkbox whose top left is (x, y)."""
    page.draw_polyline([(x + 1.8, y + 4.4), (x + 3.7, y + 6.7),
                        (x + 7.3, y + 1.9)], color=BLACK, width=1.1)


def _bullet_blocks(rep):
    return [bullet_lines(b.get("text") or "")
            for b in rep.get("progress") or []
            if b.get("include", True) and (b.get("text") or "").strip()]


def _page1(ctx, page_map):
    rep, t, opts = ctx.rep, ctx.t, ctx.opts
    sec = dict(DEFAULT_TEMPLATE["sections"], **(t.get("sections") or {}))
    p = ctx.page1_top()
    first = ctx.doc.page_count
    # WORK IN PROGRESS
    ctx.section_bar(p, WIP_Y, sec["wip"], center=True)
    ticked = set(rep.get("trades") or [])
    for c, col in enumerate(trade_list(t)):
        for r, trade in enumerate(col):
            bx, by = BOX_X[c], BOX_Y[r]
            ctx.rect(p, (bx, by, bx + BOX_W, by + BOX_H), width=1.0)
            if trade in ticked:
                _check(p, bx, by)
            nxt = LABEL_X[c + 1] - 26 if c < 3 else X1
            ctx.text(p, LABEL_X[c], by + 7.2, trade,
                     width=nxt - LABEL_X[c])
    # LOGS
    ctx.section_bar(p, LOGS_Y, sec["logs"])
    logs = rep.get("logs") or {}
    rows = [("RFI", "rfi"), ("Submittal", "submittal")]
    if opts.get("co_log"):
        rows.append(("Change Orders", "co"))
    counts = None
    if opts.get("counts"):
        from . import owner_report_logs as orl
        counts = orl.counts(ctx.store, _day(rep.get("date")), opts) or {}
    hy0, hy1 = LOGS_HEAD
    ctx.rect(p, (X0, hy0, X1, hy1), fill=ctx.headfill)
    ctx.text(p, 41.5, hy0 + 8.4, "Description", bold=True)
    ctx.text(p, 398.0, hy0 + 8.4, "As Of:", bold=True)
    if counts is not None:
        ctx.text(p, OPEN_CX, hy0 + 8.4, "Open", bold=True, align="center")
        ctx.text(p, OVERDUE_CX, hy0 + 8.4, "Overdue", bold=True,
                 align="center")
    y = hy1
    for label, k in rows:
        lg = logs.get(k) or {}
        ctx.rect(p, (X0, y, X1, y + LOG_ROW))
        ctx.text(p, 41.5, y + 8.6, label)
        if lg.get("attached", True):
            # centred in its column: Helvetica dates run wider than Calibri
            ctx.text(p, (LOG_COLS[0] + LOG_COLS[1]) / 2, y + 8.6,
                     mdy(lg.get("as_of") or rep.get("date")),
                     align="center", width=LOG_COLS[1] - LOG_COLS[0] - 3)
            ctx.text(p, LOG_COLS[1] + 3.5, y + 8.6, "Attached")
        if counts is not None:
            c = counts.get(k) or {}
            ctx.text(p, OPEN_CX, y + 8.6, str(c.get("open", 0)),
                     align="center")
            od = int(c.get("overdue", 0) or 0)
            ctx.text(p, OVERDUE_CX, y + 8.6, str(od),
                     align="center", bold=od > 0, color=RED if od else BLACK)
        y += LOG_ROW
    for x in LOG_COLS:
        ctx.line(p, (x, hy0), (x, y))
    if counts is not None:
        ctx.line(p, (COUNT_COLS[0], hy0), (COUNT_COLS[0], y))
        ctx.line(p, (COUNT_COLS[1], hy0), (COUNT_COLS[1], y))
    # INCLEMENT WEATHER DAYS - the per-day list's totals (the same pair
    # the weather log and the gap line count)
    imp, cl = weather_counts(rep)
    ctx.section_bar(p, WEATHER_Y, sec["weather"], x1=X1)
    ctx.text(p, IMPACT_X, WEATHER_Y + 8.6,
             f"IMPACTED WEATHER DAYS: {imp}", bold=True)
    ctx.text(p, CLAIM_X, WEATHER_Y + 8.6, "CLAIMED WEATHER DAYS:", bold=True)
    ctx.text(p, max(CLAIM_V, CLAIM_X + _tlen("CLAIMED WEATHER DAYS:", FS,
                                            True) + 5.0),
             WEATHER_Y + 8.6, str(cl))
    ctx.text(p, 41.5, WEATHER_RULE - 3.0,
             "See Attached Inclement Weather Log")
    if opts.get("weather_gap"):
        gap = gap_line(rep)
        if gap:
            size = FS
            while size > 6.0 and _tlen(gap, size) > X1 - IMPACT_X:
                size -= 0.2
            ctx.text(p, IMPACT_X, WEATHER_RULE - 3.0, gap, size=size,
                     width=X1 - IMPACT_X)
    ctx.line(p, (X0, WEATHER_RULE), (X1, WEATHER_RULE), width=0.75)
    # CURRENT PROGRESS
    ctx.section_bar(p, PROGRESS_Y, sec["progress"])
    blocks = _bullet_blocks(rep)
    rest = _flow_bullets(ctx, p, blocks, BULLET_Y, LAST_LINE_Y)
    # UPCOMING WEATHER FORECAST - 10 DAY
    fy0, fy1 = FORECAST_Y
    ctx.section_bar(p, fy0, sec["forecast"], x1=FORECAST_X[0])
    ctx.rect(p, (FORECAST_X[0], fy0, FORECAST_X[1], fy1), fill=ctx.bar)
    ctx.text(p, FORECAST_X[1] - 2.0, fy0 + 8.6, "AS OF:", bold=True,
             align="right")
    ctx.rect(p, (FORECAST_X[1], fy0, X1, fy1))
    fc = rep.get("forecast") or {}
    ctx.text(p, FORECAST_X[1] + 2.0, fy0 + 7.6,
             mdy(fc.get("as_of") or rep.get("date")), size=5.5)
    if not fc.get("rows") and not fc.get("attach_ref"):
        ctx.text(p, 41.5, FORECAST_RULE - 3.0,
                 "Not available offline - no forecast downloaded or "
                 "attached", bold=True)
    else:
        ctx.text(p, 41.5, FORECAST_RULE - 3.0, "See Attached", bold=True)
    ctx.line(p, (X0, FORECAST_RULE), (X1, FORECAST_RULE), width=0.75)
    page_map.append(("page1", first))
    # page 1b, 1c...: the bullets that didn't fit, same header
    n = 0
    while rest:
        n += 1
        q = ctx.page1_top()
        ctx.section_bar(q, WIP_Y, sec["progress"] + " (CONTINUED)")
        rest = _flow_bullets(ctx, q, rest, CONT_BULLET_Y, CONT_LAST_Y)
        page_map.append(("page1" + "bcdefghij"[min(n - 1, 8)],
                         ctx.doc.page_count))


def _flow_bullets(ctx, page, blocks, y0, ylast):
    """Write bullets from baseline y0; returns the blocks that didn't fit.
    A bullet isn't split unless it is longer than a whole page."""
    y = y0
    for i, lines in enumerate(blocks):
        room = max(0, math.floor((ylast - y) / PITCH + 1e-6) + 1)
        if len(lines) > room:
            if y == y0:                         # longer than a page
                for ln in lines[:room]:
                    ctx.text(page, BULLET_X, y, ln)
                    y += PITCH
                return [lines[room:]] + blocks[i + 1:]
            return blocks[i:]
        for ln in lines:
            ctx.text(page, BULLET_X, y, ln)
            y += PITCH
    return []


def weather_counts(rep):
    """(impacted, claimed) weather days as page 1 prints them: the totals
    of the per-day list when there is one, else the stored totals (see
    owner_report_logs.weather_counts)."""
    from . import owner_report_logs as orl
    return orl.weather_counts(rep.get("weather") or {})


def gap_line(rep):
    """Option (e): the logs module's line (a typed weather["gap_note"]
    replaces it); None when impacted == claimed."""
    from . import owner_report_logs as orl
    return orl.weather_gap_line(rep.get("weather") or {})


# ------------------------------------------------------------- photo pages
def photos_a_page(v):
    """Photos a page: 2, 3, 4 (as the form) or 6; anything else is 4."""
    try:
        n = int(v or 4)
    except (TypeError, ValueError):
        return 4
    return n if n in (2, 3, 4, 6) else 4


def photo_cells(per_page=4, captions=False):
    """The cells of a photo page (x0, y0, x1, y1), print order.
    2 a page: two large photos side by side; 3 a page: one large photo on
    the left and two on the right (G09)."""
    n = photos_a_page(per_page)
    x0, y0, x1, y1 = GRID
    if n == 2:
        gx = CELLS4[1][0] - CELLS4[0][2]
        w = (x1 - x0 - gx) / 2
        h = min(y1 - y0, w * 0.75 + (CAPTION_H if captions else 0))
        top = y0 + (y1 - y0 - h) / 2
        cells = [(x0, top, x0 + w, top + h), (x0 + w + gx, top, x1, top + h)]
    elif n == 3:
        gx, gy = CELLS4[1][0] - CELLS4[0][2], CELLS4[2][1] - CELLS4[0][3]
        wl = (x1 - x0 - gx) * 0.64
        h = (y1 - y0 - gy) / 2
        cells = [(x0, y0, x0 + wl, y1),
                 (x0 + wl + gx, y0, x1, y0 + h),
                 (x0 + wl + gx, y0 + h + gy, x1, y1)]
    elif n == 6:
        x0, y0, x1, y1 = GRID
        gx, gy = GAP6
        w = (x1 - x0 - 2 * gx) / 3
        h = (y1 - y0 - gy) / 2
        cells = [(x0 + c * (w + gx), y0 + r * (h + gy),
                  x0 + c * (w + gx) + w, y0 + r * (h + gy) + h)
                 for r in range(2) for c in range(3)]
    else:
        cells = list(CELLS4)
    if captions:
        cells = [(a, b, c, d - CAPTION_H) for a, b, c, d in cells]
    return cells


def _image_info(path, rotate=0):
    """(width, height) as printed: EXIF orientation and the PM's turn."""
    from . import photofit
    w, h = photofit.upright_size(path)
    if int(rotate or 0) % 180 == 90:
        w, h = h, w
    return w, h


def max_crop_for(captions):
    """Captions take 22 pt off the cell, so a 4:3 photo would need a 19 %
    crop: allow more, so phone photos still fill their cells."""
    return 0.22 if captions else 0.12


def _encode_original(img, box):
    """"original": every pixel of the photo, upright, as a high-quality
    JPEG without EXIF (no GPS in the PDF; the camera's orientation tag,
    which PDF viewers ignore, is already applied)."""
    import io
    w, h = img.size
    if tuple(box) != (0, 0, 1, 1):
        img = img.crop((round(box[0] * w), round(box[1] * h),
                        round(box[2] * w), round(box[3] * h)))
    img = img.convert("RGB")
    img.info = {}
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, subsampling=0, optimize=True,
             exif=b"")
    return buf.getvalue()


def _place_photo(ctx, page, photo, cell, preset, captions=False):
    """Fit, compress and place one photo with its frame. Returns the rect
    used."""
    import fitz
    from . import photofit
    path = ctx.store.attachment_path(photo["ref"])
    rot = int(photo.get("rotate") or 0) % 360
    img = None
    if rot:
        img = photofit.load(path).rotate(-rot, expand=True)  # clockwise
        iw, ih = img.size
    else:
        iw, ih = _image_info(path)
    rect, box = photofit.fit(cell, iw, ih, photo.get("fit") or "auto",
                             max_crop=max_crop_for(captions),
                             crop=photo.get("crop"))
    rect = tuple(rect)
    box = tuple(box) if box else (0, 0, 1, 1)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    enc = preset
    if preset == "original":
        data = _encode_original(img if img is not None
                                else photofit.load(path), box)
    elif img is None and photo["ref"].get("sha256"):
        data = photofit.cached_encode(ctx.store, photo["ref"], w, h, enc,
                                      src_box=box)
    else:
        img = img if img is not None else photofit.load(path)
        data = photofit.encode(img, w, h, enc, src_box=box)
    page.insert_image(fitz.Rect(*rect), stream=data, keep_proportion=False)
    ctx.rect(page, rect, color=ctx.frame, width=ctx.frame_w)
    ctx.photo_bytes += len(data)
    return rect


def _missing_photo(ctx, page, cell, why):
    ctx.rect(page, cell, color=ctx.frame, width=ctx.frame_w,
             fill=(0.95, 0.95, 0.95))
    ctx.text(page, (cell[0] + cell[2]) / 2, (cell[1] + cell[3]) / 2,
             "Photo not available", size=9, color=GREY_TEXT, align="center")
    ctx.warnings.append(why)


def _taken_text(photo):
    t = photo.get("taken") or ""
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return mdy(t)
    s = mdy(dt)
    if len(t) > 10:
        s += f" {dt.hour % 12 or 12}:{dt.minute:02d} " \
             f"{'AM' if dt.hour < 12 else 'PM'}"
    if photo.get("taken_src") == "file":
        s += " (file date)"
    elif photo.get("taken_src") == "log":
        s += " (log date)"
    return s


def _caption(ctx, page, cell, lead, location, desc):
    x0, x1 = cell[0], cell[2]
    y = cell[3] + 9.0
    first = lead + (f"  |  {location}" if location else "")
    ctx.text(page, x0, y, first, size=7.5, bold=True, width=x1 - x0)
    if desc:
        ctx.text(page, x0, y + 9.0, desc, size=7.2, width=x1 - x0)


def _photo_pages(ctx, page_map):
    photos = printed_photos(ctx.rep)
    if not photos:
        return
    per = photos_a_page(ctx.opts.get("photos_per_page"))
    caps = bool(ctx.opts.get("captions"))
    cells = photo_cells(per, caps)
    preset = ctx.opts.get("size_preset") or "email"
    first = ctx.doc.page_count + 1
    page = None
    for i, ph in enumerate(photos):
        if i % per == 0:
            page = ctx.std_page()
        cell = cells[i % per]
        k = _photo_key(ph.get("ref"))
        ctx.photo_page[k] = ctx.doc.page_count
        ctx.photo_no[k] = i + 1
        try:
            _place_photo(ctx, page, ph, cell, preset, caps)
        except Exception as e:                    # noqa: BLE001
            log.warning("photo not placed", exc_info=True)
            _missing_photo(ctx, page, cell, f"Photo {i + 1}: {e}")
        if caps:
            _caption(ctx, page, cell, f"#{i + 1:02d}  {_taken_text(ph)}",
                     photo_location(ctx.rep, ph), ph.get("caption") or "")
            if not (ph.get("caption") or "").strip():
                ctx.warnings.append(f"Photo #{i + 1:02d} has no caption")
    page_map.append(_span("photos", first, ctx.doc.page_count))


def _span(name, a, b):
    return (name, a) if a == b else (name, a, b)


# ------------------------------------------------------------- flow pages
class _Flow:
    """Stacked sections on standard pages (title + logo), new page as
    needed."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.page = None
        self.y = PAGE_TOP
        self.first = None

    def new(self):
        self.page = self.ctx.std_page()
        if self.first is None:
            self.first = self.ctx.doc.page_count
        self.y = PAGE_TOP

    def need(self, h):
        if self.page is None or self.y + h > PAGE_BOTTOM:
            self.new()

    def bar(self, title):
        self.need(BAR_H * 3)
        self.ctx.section_bar(self.page, self.y, title)
        self.y += BAR_H

    def text(self, s, size=FS, bold=False, color=BLACK, x=41.5,
             width=X1 - 43.0):
        for ln in wrap(s, width, size, bold) or [""]:
            self.need(size + 3.5)
            self.ctx.text(self.page, x, self.y + size + 1.5, ln, size=size,
                          bold=bold, color=color)
            self.y += size + 3.5

    def table(self, cols, rows, row_h=11.7, size=FS, title=None):
        """cols: [(header, width, align)], widths scaled to the bar width;
        a cell is text or {"text", "bold", "color", "fill"}."""
        ctx = self.ctx
        tot = sum(c[1] for c in cols)
        ws = [c[1] * (X1 - X0) / tot for c in cols]

        def head():
            self.need(row_h * 2)
            ctx.rect(self.page, (X0, self.y, X1, self.y + row_h),
                     fill=ctx.headfill)
            x = X0
            for (h, _w, al), w in zip(cols, ws):
                self._cell(x, w, h, al, size, True, BLACK)
                x += w
            self.y += row_h
        if title:
            self.bar(title)
        head()
        for row in rows:
            if self.y + row_h > PAGE_BOTTOM:
                self.new()
                if title:
                    self.bar(title + " (continued)")
                head()
            ctx.rect(self.page, (X0, self.y, X1, self.y + row_h))
            x = X0
            for c, (_h, _w, al), w in zip(row, cols, ws):
                if isinstance(c, dict):
                    if c.get("fill"):
                        ctx.rect(self.page, (x, self.y, x + w,
                                             self.y + row_h),
                                 color=None, fill=c["fill"])
                    self._cell(x, w, c.get("text", ""), al, size,
                               c.get("bold", False), c.get("color", BLACK))
                else:
                    self._cell(x, w, c, al, size, False, BLACK)
                x += w
            self.y += row_h
        self.y += 6

    def _cell(self, x, w, s, align, size, bold, color):
        s = _fit_text("" if s is None else s, size, w - 4, bold)
        if align == "right":
            self.ctx.text(self.page, x + w - 2, self.y + 8.6, s, size=size,
                          bold=bold, color=color, align="right")
        elif align == "center":
            self.ctx.text(self.page, x + w / 2, self.y + 8.6, s, size=size,
                          bold=bold, color=color, align="center")
        else:
            self.ctx.text(self.page, x + 2, self.y + 8.6, s, size=size,
                          bold=bold, color=color)


def open_decisions(rep):
    return [d for d in rep.get("decisions") or []
            if not d.get("done") and (d.get("text") or "").strip()]


def decision_urgent(rep, d):
    """Needed within 3 days of the report date (or already late)."""
    due, rd = _day(d.get("due")), _day(rep.get("date"))
    return bool(due and rd and due <= rd + timedelta(days=3))


def _summary_pages(ctx, page_map):
    """Owner summary (after page 1, so page 1 stays the form): decisions
    (b), schedule status (c), manpower and safety (h)."""
    o = ctx.opts
    if not (o.get("decisions") or o.get("schedule") or o.get("manpower")
            or o.get("safety")):
        return
    fl = _Flow(ctx)
    fl.new()
    if o.get("decisions"):
        rows = []
        for i, d in enumerate(open_decisions(ctx.rep), 1):
            urgent = decision_urgent(ctx.rep, d)
            rows.append([str(i), d.get("text", ""),
                         {"text": mdy(d.get("due")), "bold": urgent,
                          "color": RED if urgent else BLACK},
                         d.get("impact", ""), d.get("ref", "")])
        if not rows:
            rows = [["", "No owner decisions needed this week.", "", "", ""]]
        fl.table([("#", 18, "left"), ("Decision needed from the Owner", 330,
                                      "left"),
                  ("Needed by", 72, "left"), ("If late", 190, "left"),
                  ("Ref", 100, "left")], rows, title="OWNER DECISIONS NEEDED")
    if o.get("schedule"):
        _schedule_block(ctx, fl)
    if o.get("manpower"):
        mp = manpower_week(ctx.store, ctx.rep)
        cols = [("Company", 150, "left"), ("Trade", 110, "left")] + \
            [(f"{d:%a} {d.month}/{d.day}", 58, "center")
             for d in mp["days"]] + [("Worker-days", 70, "center")]

        def n(v):
            return f"{v:g}" if v else ""
        rows = [[r["company"], r["trade"]] +
                [n(r["by_day"].get(d.isoformat(), 0)) for d in mp["days"]] +
                [n(r["total"])] for r in mp["rows"]]
        rows.append([{"text": "Total on site", "bold": True}, ""] +
                    [{"text": n(mp["totals"].get(d.isoformat(), 0)) or "0",
                      "bold": True} for d in mp["days"]] +
                    [{"text": n(mp["total"]) or "0", "bold": True}])
        fl.table(cols, rows, title="MANPOWER THIS WEEK (from Daily Logs)")
    if o.get("manpower") or o.get("safety"):
        s = safety_line(ctx.store, ctx.rep) or "No safety notes this week."
        fl.need(24)
        ctx.text(fl.page, 41.5, fl.y + 9.5, "SAFETY:", bold=True)
        lines = wrap(s, X1 - 90, FS)
        for i, ln in enumerate(lines):
            fl.need(11)
            ctx.text(fl.page, 85.0, fl.y + 9.5, ln)
            fl.y += 11
        fl.y += 4
    page_map.append(_span("summary", fl.first, ctx.doc.page_count))


def _schedule_block(ctx, fl):
    st = schedule_status(ctx.store, ctx.rep)
    fl.need(BAR_H + 75)
    fl.bar("SCHEDULE STATUS")
    if not st.get("has"):
        fl.y += 3
        fl.text("No schedule in Project Center.", color=GREY_TEXT)
        fl.y += 4
        return
    p = fl.page

    def kv(x, y, k, v, vx):
        ctx.text(p, x, y, k, bold=True)
        ctx.text(p, vx, y, v)
    cd = st["contract_days"]
    contract = (f"{cd} + {st['weather_days']} weather = {st['total_days']}"
                if cd is not None else "not set (Project settings)")
    y = fl.y + 12
    pk = (ctx.rep.get("pack") or {}) if ctx.opts.get("owner_pack") else {}
    if pk.get("percent_complete") not in (None, ""):
        # the cost-loaded (earned) figure the pack's dashboard prints, so
        # the report shows one percent complete, not two
        st["percent"] = float(pk["percent_complete"])
        kv(41.5, y, "% complete:", f"{st['percent']:.1f}% (earned)", 120)
    else:
        kv(41.5, y, "% complete:", f"{st['percent']:.1f}%", 120)
    kv(250, y, "Contract days:", contract, 330)
    kv(560, y, "Days used:", str(st["used"] if st["used"] is not None
                                 else "-"), 630)
    y += 13
    kv(41.5, y, "Days remaining:", str(st["remaining"]
                                       if st["remaining"] is not None
                                       else "-"), 120)
    kv(250, y, "Contract finish:", mdy(st["contract_finish"]) or "-", 330)
    kv(560, y, "Data date:", mdy(st["data_date"]), 630)
    y += 8
    # progress bar: % complete, with a marker at the share of time used
    bx0, bx1 = 41.5, 520.0
    ctx.rect(p, (bx0, y, bx1, y + 7), color=(0.6, 0.6, 0.6), width=0.5)
    pct = max(0.0, min(100.0, st["percent"]))
    if pct:
        ctx.rect(p, (bx0, y, bx0 + (bx1 - bx0) * pct / 100, y + 7),
                 color=None, fill=(0.33, 0.51, 0.21))
    if st["total_days"] and st["used"] is not None:
        f = max(0.0, min(1.0, st["used"] / st["total_days"]))
        mx = bx0 + (bx1 - bx0) * f
        ctx.line(p, (mx, y - 2), (mx, y + 9), color=RED, width=1.2)
        ctx.text(p, mx, y + 15, f"time used {f * 100:.0f}%", size=6,
                 color=RED, align="center")
    fl.y = y + 20
    rec = recovery_text(st.get("recovery"))
    if rec:
        fl.text(rec, bold=True,
                color=RED if (st["recovery"] or {}).get("behind", 0)
                and st["recovery"]["behind"] > 0 else BLACK)
    rows = []
    for m in st["milestones"]:
        v = m["variance"]
        vt = "" if v is None else ("on time" if v == 0 else f"{v:+d}")
        rows.append([m["name"], mdy(m["baseline"]), mdy(m["forecast"]),
                     {"text": vt, "color": RED if v and v > 0 else BLACK}])
    if rows:
        fl.table([("Next milestones", 300, "left"), ("Baseline", 90, "left"),
                  ("Forecast", 90, "left"),
                  ("Variance (work days)", 120, "left")], rows)


def _lookahead_pages(ctx, page_map):
    if not ctx.opts.get("lookahead"):
        return
    from . import schedule
    s, e, rows = lookahead_rows(ctx.store, ctx.rep)
    fl = _Flow(ctx)
    fl.new()
    days = [s + timedelta(days=i) for i in range((e - s).days + 1)]
    try:
        cal = schedule.calendar(ctx.store)
        is_work = cal.is_work
    except Exception:
        is_work = lambda d: d.weekday() < 5  # noqa: E731
    xa, xs, xf, xd = X0, 270.0, 312.0, 354.0
    dw = (X1 - xd) / len(days)
    span = "THREE-WEEK" if len(days) > 14 else "TWO-WEEK"
    title = f"{span} LOOK-AHEAD  {mdy(s)} - {mdy(e)}"
    hols = [d for d in days if d in _holidays(ctx.store)]

    def head():
        fl.bar(title)
        p, y = fl.page, fl.y
        ctx.rect(p, (X0, y, X1, y + 20), fill=ctx.headfill)
        ctx.text(p, xa + 2, y + 14, "Activity", bold=True)
        ctx.text(p, xs + 2, y + 14, "Start", bold=True)
        ctx.text(p, xf + 2, y + 14, "Finish", bold=True)
        for i, d in enumerate(days):
            cx = xd + i * dw
            ctx.text(p, cx + dw / 2, y + 8, "MTWTFSS"[d.weekday()], size=6.5,
                     bold=True, align="center")
            ctx.text(p, cx + dw / 2, y + 17, f"{d.day:02d}", size=6.5,
                     align="center")
        fl.y += 20
    head()
    rh = 11.7
    for r in rows:
        if fl.y + rh > PAGE_BOTTOM - 14:
            fl.new()
            head()
        p, y = fl.page, fl.y
        for i, d in enumerate(days):
            if not is_work(d):
                ctx.rect(p, (xd + i * dw, y, xd + (i + 1) * dw, y + rh),
                         color=None, fill=WEEKEND)
        ctx.rect(p, (X0, y, X1, y + rh), width=0.4)
        name = r["name"] + (" *" if r["critical"] else "")
        color = CRIT_RED if r["late"] else BLACK
        ctx.text(p, xa + 2, y + 8.4, name + (f"  ({r['flag']})" if r["flag"]
                                              else ""),
                 size=7.5, bold=r["critical"], color=color,
                 width=xs - xa - 4)
        ctx.text(p, xs + 2, y + 8.4, f"{r['start']:%m/%d}", size=7.5)
        ctx.text(p, xf + 2, y + 8.4, f"{r['finish']:%m/%d}", size=7.5)
        fill = CRIT_RED if r["critical"] else BAR_BLUE
        for i, d in enumerate(days):
            if not (r["start"] <= d <= r["finish"]) or not is_work(d):
                continue
            cx = xd + i * dw
            if r["milestone"]:
                c = (cx + dw / 2, y + rh / 2)
                k = 3.6
                p.draw_polyline([(c[0], c[1] - k), (c[0] + k, c[1]),
                                 (c[0], c[1] + k), (c[0] - k, c[1]),
                                 (c[0], c[1] - k)], color=BLACK,
                                fill=BLACK, closePath=True, width=0.5)
            else:
                ctx.rect(p, (cx + 0.6, y + 2.5, cx + dw - 0.6, y + rh - 2.5),
                         color=None, fill=fill)
        fl.y += rh
    if not rows:
        fl.text(f"Nothing scheduled in these {span.split('-')[0].lower()} "
                "weeks, and nothing overdue.", color=GREY_TEXT)
    if hols:
        fl.need(12)
        ctx.text(fl.page, 41.5, fl.y + 8, "Holidays in this look-ahead: "
                 + ", ".join(f"{d:%a} {mdy(d)}" for d in hols)
                 + " (no work scheduled).", size=7.5, bold=True)
        fl.y += 12
    fl.need(12)
    ctx.text(fl.page, 41.5, fl.y + 8, "* critical path (zero float). Red "
             "bars = critical. Grey columns = non-work days. Red text = past "
             "its finish or behind its baseline.", size=6.5, color=GREY_TEXT)
    fl.y += 18
    subs = submittals_due(ctx.store, ctx.rep)
    srows = [[r["no"], r["title"], r["responsible"] or r["ball"], r["for"],
              mdy(r["due"]),
              {"text": str(r["days_left"]),
               "color": RED if r["days_left"] < 0 else BLACK,
               "bold": r["days_left"] < 0}] for r in subs]
    if not srows:
        srows = [["", "No submittals due in the next two weeks.", "", "", "",
                  ""]]
    fl.table([("No.", 70, "left"), ("Title", 220, "left"),
              ("Responsible", 150, "left"), ("Due for", 120, "left"),
              ("Due", 70, "left"), ("Days left", 60, "center")], srows,
             title="SUBMITTALS DUE IN THE NEXT TWO WEEKS")
    page_map.append(_span("lookahead", fl.first, ctx.doc.page_count))


# ------------------------------------------------------------- plan pages
def _sheet_path(store, sheet):
    return store.attachment_path(sheet) if isinstance(sheet, dict) \
        else str(sheet)


def _open_sheet(store, sheet):
    import fitz
    return fitz.open(_sheet_path(store, sheet))


def _label_text(a):
    """The text of a free-text annotation: its Contents, else what its
    appearance shows."""
    text = str((a.info or {}).get("content") or "").strip()
    if not text:
        try:
            text = str(a.get_text() or "").strip()
        except Exception:                         # noqa: BLE001
            text = ""
    return text


def _lift_labels(tmp, keep=()):
    """Take the free-text labels (the pin numbers) off the marked sheet:
    their appearance uses the base-14 Helvetica, not embedded, so the
    report draws them itself in its embedded font (_show_sheet). Returns
    [(rect, text, fontsize, color)]. A rotated sheet keeps them (its
    annotation coordinates aren't the shown ones; it goes in as an image
    when that leaves a non-embedded font). Annotations whose xref is in
    keep (the sheet's own markups) are left alone. Two passes (read, then
    delete by xref) so a deletion never upsets the walk."""
    import fitz
    page = tmp[0]
    if page.rotation:
        return []
    found = []
    for a in page.annots():
        if a.type[0] != fitz.PDF_ANNOT_FREE_TEXT or a.xref in keep:
            continue
        text = _label_text(a)
        if not text or "\n" in text or "\r" in text:
            continue
        fs, col = 8.0, BLACK
        try:
            da = tmp.xref_get_key(a.xref, "DA")[1] or ""
            m = re.search(r"([\d.]+)\s+Tf", da)
            if m and float(m.group(1)) > 0:
                fs = float(m.group(1))
            m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
            if m:
                col = tuple(float(v) for v in m.groups())
        except Exception:                         # noqa: BLE001
            pass
        found.append((a.xref, (fitz.Rect(a.rect), text, fs, col)))
    out = []
    for xref, label in found:
        try:
            page.delete_annot(page.load_annot(xref))
        except Exception:                         # noqa: BLE001
            log.debug("label %s not lifted", xref, exc_info=True)
            continue
        out.append(label)
    left = {a.xref for a in page.annots()}
    return [lb for (x, lb) in found if x not in left and lb in out]


def _marked_sheet(ctx, sheet, pno, ops):
    """A one-page copy of the sheet with the ops applied (through
    annotate.apply_op, as in the app) and flattened. Returns (doc,
    labels): the free-text labels lifted off it (_lift_labels)."""
    import fitz
    from .. import annotate
    src = _open_sheet(ctx.store, sheet)
    tmp = fitz.open()
    tmp.insert_pdf(src, from_page=pno, to_page=pno)
    src.close()
    own = {a.xref for a in tmp[0].annots()}       # the sheet's own markups
    for op in ops:
        annotate.apply_op(tmp, op, fresh=True)
    labels = _lift_labels(tmp, own)
    if hasattr(tmp, "bake"):
        tmp.bake(annots=True, widgets=True)
    return tmp, labels


def _contain(area, w, h):
    ax0, ay0, ax1, ay1 = area
    s = min((ax1 - ax0) / w, (ay1 - ay0) / h)
    cw, ch = w * s, h * s
    x0 = ax0 + ((ax1 - ax0) - cw) / 2
    y0 = ay0 + ((ay1 - ay0) - ch) / 2
    return (x0, y0, x0 + cw, y0 + ch)


def _sheet_mode(tmp):
    """("vector" | "image", why) for a marked, flattened sheet copy:
    vector when no annotation is left (an engine too old to flatten) and
    every font its content uses is embedded. Font resources that are not
    embedded but not used either (left behind by a lifted label) are
    dropped from the copy first, so they don't reach the report."""
    from . import owner_report_logs as orl
    sp = tmp[0]
    if sp.first_annot or sp.first_widget:
        return "image", "annotations left after flattening"
    if orl.fonts_embedded(tmp, 0):
        return "vector", "all fonts embedded"
    dropped = orl.drop_unused_fonts(tmp, 0)
    missing = orl.missing_fonts(tmp, 0)
    if not missing:
        return "vector", "unused non-embedded font resources dropped: " + \
            ", ".join(dropped)
    used = sorted({f[3] for f in orl.font_report(tmp, 0)
                   if not f[6] and f[7]})
    return "image", "fonts not embedded: " + ", ".join(missing) + \
        (" (used: " + ", ".join(used) + ")" if used else "") + \
        (" (dropped: " + ", ".join(dropped) + ")" if dropped else "")


def _show_sheet(ctx, page, tmp, area, clip, labels=()):
    """The marked sheet (its clip) fitted into area: vectors when every
    font it uses is embedded, else an image (orl.raster_page at
    RASTER_DPI of the placed size) - also when an engine too old to
    flatten left annotations on it. Then the lifted labels, in the
    report's embedded font, where the sheet had them."""
    import fitz
    from . import owner_report_logs as orl
    src_rect = orl.source_rect(tmp, 0, fitz.Rect(*clip) if clip else None)
    r = _contain(area, src_rect.width, src_rect.height)
    tr = fitz.Rect(*r)
    mode, why = _sheet_mode(tmp)
    ctx.sheet_modes.append((mode, why))
    if mode == "image":
        log.info("plan sheet printed as an image: %s", why)
        kw, n = orl.raster_page(tmp, 0, (tr.width, tr.height), src_rect,
                                orl.RASTER_DPI, annots=True)
        page.insert_image(tr, keep_proportion=False, **kw)
        ctx.raster_bytes += n
    else:
        page.show_pdf_page(tr, tmp, 0, clip=src_rect if clip else None)
    s = tr.width / src_rect.width
    for lr, text, fs, col in labels:
        cx = tr.x0 + ((lr.x0 + lr.x1) / 2 - src_rect.x0) * s
        cy = tr.y0 + ((lr.y0 + lr.y1) / 2 - src_rect.y0) * s
        if not (tr.x0 <= cx <= tr.x1 and tr.y0 <= cy <= tr.y1):
            continue                              # outside the clip
        size = max(1.0, fs * s)
        w = orl.text_width(text, size)
        orl.put_text(page, (cx - w / 2, cy + 0.35 * size), text, size,
                     "helv", col)
    ctx.rect(page, r, width=0.75)
    return r


def _clip_for(rep, sheet, pno):
    kp = rep.get("key_plan") or {}
    if kp.get("clip") and _sheet_key(kp.get("sheet")) == _sheet_key(sheet) \
            and int(kp.get("page") or 0) == int(pno or 0):
        return tuple(kp["clip"])
    return None


PLAN_AREA = (9.0, 65.3, 560.0, 596.6)
SIDE_X = (570.0, 783.0)


VIEW_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
VIEW_ARROW = 28.0                        # pt on the sheet


def _view(pin):
    """The pin's view direction as (compass word, degrees clockwise from up
    the sheet), else None. Typed as N/NE/.../NW or degrees (G24)."""
    v = str((pin or {}).get("view") or "").strip().upper()
    if not v:
        return None
    if v in VIEW_DIRS:
        return v, VIEW_DIRS.index(v) * 45.0
    try:
        deg = float(v) % 360
    except ValueError:
        return None
    return VIEW_DIRS[int((deg + 22.5) // 45) % 8], deg


def view_arrow_op(pin):
    """An arrow from the pin the way the camera looked (annotate add_line,
    arrow end), or None when the pin has no view direction."""
    import math
    from .. import annotate
    v = _view(pin)
    if v is None:
        return None
    x, y = float(pin["x"]), float(pin["y"])
    a = math.radians(v[1])
    x1 = x + VIEW_ARROW * math.sin(a)
    y1 = y - VIEW_ARROW * math.cos(a)
    return annotate.new_op("add_line", 0, pts=[[x, y], [round(x1, 3),
                                                        round(y1, 3)]],
                           arrow=True, color=list(PIN_COLOR), width=1.5)


def _key_plan_pages(ctx, page_map):
    """Option (i): each plan sheet with the photos' pins (numbered as the
    photos), flattened, and a table pin -> report page -> location."""
    if not ctx.opts.get("key_plan"):
        return
    from .. import annotate
    groups = {}
    for i, ph in enumerate(printed_photos(ctx.rep), 1):
        pin = ph.get("pin")
        if not pin:
            continue
        g = groups.setdefault((_sheet_key(pin.get("sheet")),
                               int(pin.get("page") or 0)),
                              {"sheet": pin.get("sheet"),
                               "page": int(pin.get("page") or 0),
                               "pins": []})
        g["pins"].append((ctx.photo_no.get(_photo_key(ph.get("ref")), i),
                          ph))
    if not groups:
        return
    first = ctx.doc.page_count + 1
    for g in groups.values():
        ops = [annotate.new_op("add_count", 0, pt=[float(ph["pin"]["x"]),
                                                   float(ph["pin"]["y"])],
                               n=str(no), color=list(PIN_COLOR),
                               look="takeoff")
               for no, ph in g["pins"]]
        ops += [o for o in (view_arrow_op(ph["pin"]) for no, ph in g["pins"])
                if o is not None]
        page = ctx.std_page()
        try:
            tmp, labels = _marked_sheet(ctx, g["sheet"], g["page"], ops)
            _show_sheet(ctx, page, tmp, PLAN_AREA,
                        _clip_for(ctx.rep, g["sheet"], g["page"]), labels)
            tmp.close()
        except Exception as e:                    # noqa: BLE001
            log.warning("key plan sheet", exc_info=True)
            ctx.warnings.append(f"Key plan sheet not printed: {e}")
            ctx.text(page, 40, 100, "Plan sheet not available.",
                     color=GREY_TEXT)
        sx0, sx1 = SIDE_X
        y = PLAN_AREA[1]
        cols = [(sx0, "Pin"), (sx0 + 26, "Page"), (sx0 + 58,
                                                   "Location / caption")]
        ctx.rect(page, (sx0, y, sx1, y + 11.7), fill=ctx.headfill)
        for x, h in cols:
            ctx.text(page, x + 2, y + 8.6, h, size=7.5, bold=True)
        y += 11.7
        for no, ph in g["pins"]:
            if y + 11.7 > PLAN_AREA[3]:
                break
            ctx.rect(page, (sx0, y, sx1, y + 11.7), width=0.4)
            loc = photo_location(ctx.rep, ph) or ph.get("caption") or ""
            v = _view(ph.get("pin"))
            if v:
                loc = f"{loc} (looking {v[0]})".strip()
            ctx.text(page, cols[0][0] + 2, y + 8.6, str(no), size=7.5)
            ctx.text(page, cols[1][0] + 2, y + 8.6,
                     str(ctx.photo_page.get(_photo_key(ph.get("ref")), "")),
                     size=7.5)
            ctx.text(page, cols[2][0] + 2, y + 8.6, loc, size=7.5,
                     width=sx1 - cols[2][0] - 4)
            y += 11.7
        other = getattr(ctx, "photo_report", "")
        note = ("Pin numbers are the photo numbers; Page is the page of "
                "this report the photo is on." if not other else
                f"Pin numbers are the photo numbers in the {other} report; "
                f"Page is the page of the {other} report the photo is on "
                f"(W5 = {other} report page 5).")
        ctx.text(page, PLAN_AREA[0] + 2, PLAN_AREA[3] + 10, note, size=6.5,
                 color=GREY_TEXT)
    page_map.append(_span("key_plan", first, ctx.doc.page_count))


def _work_area_pages(ctx, page_map):
    """Option (j): the plan with this week's work areas shaded (annotate
    add_polygon, takeoff look), flattened, and a legend."""
    if not ctx.opts.get("work_areas"):
        return
    from .. import annotate
    groups = {}
    for i, a in enumerate(ctx.rep.get("work_areas") or []):
        if len(a.get("pts") or []) < 3:
            continue
        g = groups.setdefault((_sheet_key(a.get("sheet")),
                               int(a.get("page") or 0)),
                              {"sheet": a.get("sheet"),
                               "page": int(a.get("page") or 0), "areas": []})
        g["areas"].append((i, a))
    if not groups:
        return
    first = ctx.doc.page_count + 1
    for g in groups.values():
        ops = []
        for i, a in g["areas"]:
            col = tuple(a.get("color") or AREA_COLORS[i % len(AREA_COLORS)])
            ops.append(annotate.new_op(
                "add_polygon", 0, pts=[[float(x), float(y)]
                                       for x, y in a["pts"]],
                color=list(col), fill=list(col), look="takeoff",
                measure={"type": "area", "value": "", "unit": "",
                         "group": "Work areas"}))
        page = ctx.std_page()
        try:
            tmp, labels = _marked_sheet(ctx, g["sheet"], g["page"], ops)
            _show_sheet(ctx, page, tmp, PLAN_AREA,
                        _clip_for(ctx.rep, g["sheet"], g["page"]), labels)
            tmp.close()
        except Exception as e:                    # noqa: BLE001
            log.warning("work-area sheet", exc_info=True)
            ctx.warnings.append(f"Work-area sheet not printed: {e}")
            ctx.text(page, 40, 100, "Plan sheet not available.",
                     color=GREY_TEXT)
        sx0, sx1 = SIDE_X
        y = PLAN_AREA[1] + 10
        ctx.text(page, sx0, y, "This week's work areas", size=9, bold=True)
        y += 10
        for i, a in g["areas"]:
            col = tuple(a.get("color") or AREA_COLORS[i % len(AREA_COLORS)])
            note = wrap(a.get("note") or "", sx1 - sx0 - 22, 7.2)
            if y + 12 + 9 * len(note) > PLAN_AREA[3]:
                break
            ctx.rect(page, (sx0, y, sx0 + 14, y + 10), color=(0.3, 0.3, 0.3),
                     fill=col, width=0.5)
            ctx.text(page, sx0 + 20, y + 8, a.get("label") or f"Area {i + 1}",
                     bold=True, width=sx1 - sx0 - 22)
            y += 12
            for ln in note:
                ctx.text(page, sx0 + 20, y + 6.5, ln, size=7.2)
                y += 9
            y += 6
    page_map.append(_span("work_areas", first, ctx.doc.page_count))


def _before_after_pages(ctx, page_map):
    """Option (k): accepted pairs, BEFORE | AFTER side by side, two pairs a
    page, with dates."""
    if not ctx.opts.get("before_after"):
        return
    cands = {_photo_key(c.get("ref")): c
             for c in ctx.rep.get("before_candidates") or []}
    pairs = [(ph, cands.get(_photo_key(ph.get("pair_with"))))
             for ph in printed_photos(ctx.rep) if ph.get("pair_with")]
    pairs = [(a, b) for a, b in pairs if b is not None]
    if not pairs:
        return
    cells = photo_cells(4, True)
    preset = ctx.opts.get("size_preset") or "email"
    first = ctx.doc.page_count + 1
    page = None
    for i, (after, before) in enumerate(pairs):
        if i % 2 == 0:
            page = ctx.std_page()
        row = (i % 2) * 2
        for cell, ph, what in ((cells[row], before, "BEFORE"),
                               (cells[row + 1], after, "AFTER")):
            try:
                _place_photo(ctx, page, ph, cell, preset, True)
            except Exception as e:                # noqa: BLE001
                _missing_photo(ctx, page, cell, f"{what} photo: {e}")
            no = ctx.photo_no.get(_photo_key(after.get("ref")), "")
            lead = f"{what}  -  photo {no}  -  {_taken_text(ph)}"
            _caption(ctx, page, cell, lead, photo_location(ctx.rep, ph),
                     ph.get("caption") or "")
    page_map.append(_span("before_after", first, ctx.doc.page_count))


# ------------------------------------------------------------- logs (B)
def _log_pages(ctx, page_map):
    from . import owner_report_logs as orl
    rep, opts, head = ctx.rep, ctx.opts, ctx.head
    logs = rep.get("logs") or {}

    def run(name, fn, *args):
        a = ctx.doc.page_count + 1
        fn(*args)
        if ctx.doc.page_count >= a:
            page_map.append(_span(name, a, ctx.doc.page_count))
    if (logs.get("rfi") or {}).get("attached", True):
        run("rfi_log", orl.add_rfi_log, ctx.doc, ctx.store, head, opts)
    if (logs.get("submittal") or {}).get("attached", True):
        run("submittal_log", orl.add_submittal_log, ctx.doc, ctx.store, head,
            opts)
    if opts.get("co_log") and (logs.get("co") or {}).get("attached", True):
        run("co_log", orl.add_co_log, ctx.doc, ctx.store, head, opts)
    run("weather_log", orl.add_weather_log, ctx.doc, head,
        rep.get("weather") or {}, opts)
    fc = dict(rep.get("forecast") or {})
    if fc.get("mode") == "attach" and fc.get("attach_ref"):
        try:
            fc["attach_path"] = ctx.store.attachment_path(fc["attach_ref"])
        except Exception as e:                    # noqa: BLE001
            ctx.warnings.append(f"Forecast attachment missing: {e}")
    run("forecast", orl.add_forecast_page, ctx.doc, head, fc, opts)


# ============================================================= build
def template_for(rep, template=None):
    """The template a build uses: the one passed, else the snapshot taken
    when the report was first exported (re-exports look the same), else
    the company template now."""
    if template is not None:
        return _merge(DEFAULT_TEMPLATE, template)
    snap = rep.get("template")
    if isinstance(snap, dict) and snap:
        t = _merge(DEFAULT_TEMPLATE, snap)
        if "trades" in snap:
            t["trades"] = copy.deepcopy(snap["trades"])
        return t
    return load_template()


def build_pdf(store, rep, path=None, template=None):
    """Build the report PDF. Order: page 1 (+1b overflow), owner summary
    (b/c/h), look-ahead (d), photo pages, key plan (i), work areas (j),
    before/after (k), RFI log, submittal log, CO log (m), weather log,
    forecast. Flattened (no fields, no annotations), garbage=4, deflate.
    Copied PDF pages (PDF logo, forecast PDF, plan sheets) stay vector
    only when their fonts are embedded, else go in as images.
    Writes `path` when given. Returns {"pages", "bytes" (file size),
    "photo_bytes", "raster_bytes" (plan sheets put in as images),
    "sheet_modes" [(vector | image, why)] a plan sheet,
    "unembedded_fonts" [(page, base font)] (empty unless the report's own
    font files are missing), "page_map" [(name, first[, last])...],
    "data" (the PDF bytes), "warnings"}."""
    t = template_for(rep, template)
    if options(rep).get("auto_pack"):
        # G04-G28: the pack drawn from the project data, as of the report
        # date (owner_report_auto); the record itself isn't changed
        from . import owner_report_auto as auto
        rep = auto.with_pack(store, rep)
        if auto.wants_contents(rep):
            first = _build_doc(store, rep, t)
            auto.set_contents(rep, first[1])
            first[0].close()
    doc, pm, ctx = _build_doc(store, rep, t)
    return _finish(doc, pm, ctx, path)


def _report_no(rep):
    no = str(rep.get("report_no") or "").strip()
    return no if no and options(rep).get("auto_pack") else ""


def _stamp_report_no(ctx):
    """G23: every page of an auto-pack report shows its report number -
    the pages without a footer (cover, photo and plan pages) get a small
    one under the form ("Report #007  |  Page i of n")."""
    no = _report_no(ctx.rep)
    if not no:
        return
    mark = f"Report #{no}"
    n = ctx.doc.page_count
    from . import owner_report_logs as orl
    for i, page in enumerate(ctx.doc):
        if mark in page.get_text():
            continue
        w, h = page.rect.width, page.rect.height
        orl._put(page, w - 36, h - 8, f"{mark}  |  Page {i + 1} of {n}",
                 6.5, align="right")


def _build_doc(store, rep, t):
    """(doc, page_map, ctx) - the pages, before fonts are subset."""
    from . import owner_report_logs as orl
    no = _report_no(rep)
    orl.FOOTER_SUFFIX = f"  |  Report #{no}" if no else ""
    try:
        out = _build_pages(store, rep, t)
        _stamp_report_no(out[2])
        return out
    finally:
        orl.FOOTER_SUFFIX = ""


def _build_pages(store, rep, t):
    import fitz
    doc = fitz.open()
    ctx = _Ctx(store, rep, t, doc)
    pm = []
    pack = None
    if ctx.opts.get("owner_pack") and rep.get("pack"):
        from . import owner_report_pack as pack
    preset = pack.preset(ctx) if pack else ""
    if preset == "weekly":                 # short weekly update
        pack.weekly_page1(ctx, pm)
        pack.add_sections(ctx, pm, "weekly")
        _photo_pages(ctx, pm)
        pack.add_footers(ctx, pm)
    elif preset == "monthly":              # optional monthly appendix
        pack.monthly_setup(ctx)
        pack.add_sections(ctx, pm, "front")
        pack.add_sections(ctx, pm, "detail")
        _key_plan_pages(ctx, pm)
        _work_area_pages(ctx, pm)
        _before_after_pages(ctx, pm)
        _log_pages(ctx, pm)
        pack.add_sections(ctx, pm, "end")
        pack.add_footers(ctx, pm)
    else:
        _page1(ctx, pm)
        if pack:
            pack.add_sections(ctx, pm, "front")
        _summary_pages(ctx, pm)
        _lookahead_pages(ctx, pm)
        if pack:
            pack.add_sections(ctx, pm, "detail")
        _photo_pages(ctx, pm)
        _key_plan_pages(ctx, pm)
        _work_area_pages(ctx, pm)
        _before_after_pages(ctx, pm)
        _log_pages(ctx, pm)
        if pack:
            pack.add_sections(ctx, pm, "end")
            pack.add_footers(ctx, pm)
    return doc, pm, ctx


def _finish(doc, pm, ctx, path):
    if hasattr(doc, "bake") and any(p.first_annot or p.first_widget
                                    for p in doc):
        doc.bake(annots=True, widgets=True)
    try:
        doc.subset_fonts()
    except Exception:                             # nothing to subset
        log.debug("font subsetting skipped", exc_info=True)
    from . import owner_report_logs as orl
    bad = orl.unembedded_fonts(doc)
    if bad:      # copied pages are already images; this is the report's own
        log.warning("report fonts not embedded: %s", bad)
        ctx.warnings.append("Fonts not embedded (the report may look "
                            "different on another computer): " + ", ".join(
                                sorted({b for _p, b in bad})))
    data = doc.tobytes(garbage=4, deflate=True)
    pages = doc.page_count
    doc.close()
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = str(path) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return {"pages": pages, "bytes": len(data),
            "photo_bytes": ctx.photo_bytes, "raster_bytes": ctx.raster_bytes,
            "unembedded_fonts": bad, "sheet_modes": ctx.sheet_modes,
            "page_map": pm, "data": data,
            "warnings": ctx.warnings}


def file_name(rep):
    """'2026.10.23 Project Name PPR Report 001.pdf' - the company rule
    (app/reportname.py): report date first, project name, PPR Report,
    3-digit report number."""
    from ..reportname import report_file_name
    hdr = rep.get("header") or {}
    return report_file_name("PPR Report", hdr.get("job_name") or "",
                            rep.get("report_no"),
                            rep.get("date") or rep.get("week_ending"))


def export(store, rep, folder=None, template=None, save_it=True):
    """Export the report into <project>/Reports/Owner (or `folder`): the
    first export snapshots the template (a later template edit won't
    change a re-export), the PDF is also kept as an attachment of the
    record, and the record is saved. Returns build_pdf()'s result plus
    "path"."""
    t = template_for(rep, template)
    folder = folder or os.path.join(store.folder, "Reports", "Owner")
    path = os.path.join(folder, file_name(rep))
    res = build_pdf(store, rep, path, t)
    if not rep.get("template"):
        snap = copy.deepcopy(t)
        logo = snap.get("logo")
        if logo and os.path.isfile(logo):
            snap["logo_ref"] = store.attach(logo)
        rep["template"] = snap
        rep["template_hash"] = template_hash(t)
    ref = store.attach(path)
    rep.setdefault("exported", []).append({
        "path": path, "at": _now(), "bytes": res["bytes"],
        "sha256": hashlib.sha256(res["data"]).hexdigest(), "ref": ref})
    if save_it:                    # False: the window saves on its thread
        save(store, rep)
    res["path"] = path
    return res


def mark_sent(store, rep, sent=True):
    rep["status"] = "Sent" if sent else "Draft"
    save(store, rep)
    return rep


# ============================================================= size estimate
PAGE_OVERHEAD = 9000                      # bytes a page of text and lines
FONT_BYTES = 30000                        # the two embedded font subsets
TRIAL_PHOTOS = 3                          # photos really encoded per call
CONTENT_EXP = 1.0                         # see _content()
_trials = {}                              # trial key -> encoded bytes


def _content(path, iw, ih):
    """How busy a camera JPEG is, from its own bytes per pixel (a plain
    sky ~0.2, gravel / rebar close-ups ~0.5+), relative to 0.4: a busier
    photo also costs more after re-encoding. 1.0 for non-JPEG files."""
    if os.path.splitext(path)[1].lower() not in (".jpg", ".jpeg"):
        return 1.0
    try:
        bpp = os.path.getsize(path) / float(max(1, iw * ih))
    except OSError:
        return 1.0
    return min(3.0, max(0.33, bpp / 0.40)) ** CONTENT_EXP


def _trial_bytes(store, ph, path, rect, box, preset):
    """len() of the photo exactly as build_pdf encodes it (same code path;
    the email/print/small result also lands in photofit's disk cache, so
    the export reuses it). Remembered per file, size, crop and preset."""
    from . import photofit
    rot = int(ph.get("rotate") or 0) % 360
    st = os.stat(path)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size, preset, rot,
           _c2(w), _c2(h), tuple(round(v, 4) for v in box))
    if key in _trials:
        return _trials[key]
    img = None
    if rot or preset == "original" or not ph["ref"].get("sha256"):
        img = photofit.load(path)
        if rot:
            img = img.rotate(-rot, expand=True)
    if preset == "original":
        n = len(_encode_original(img, box))
    elif img is None:
        n = len(photofit.cached_encode(store, ph["ref"], w, h, preset,
                                       src_box=box))
    else:
        n = len(photofit.encode(img, w, h, preset, src_box=box))
    if len(_trials) > 2000:
        _trials.clear()
    _trials[key] = n
    return n


def _raster_bytes(path, pno=0, fit=None, clip=None, logo=False):
    """Bytes a copied PDF page adds as an image - rendered through the same
    code the build uses (orl.raster_page / logo_raster) - or None when its
    fonts are embedded and it stays vector. fit: the box it is fitted
    into (plan area, forecast box). Remembered per file, page, clip."""
    import fitz
    from . import owner_report_logs as orl
    st = os.stat(path)
    key = ("raster", os.path.abspath(path), st.st_mtime_ns, st.st_size,
           int(pno), tuple(clip) if clip else None, fit, logo)
    if key in _trials:
        return _trials[key]
    with fitz.open(path) as src:
        if orl.fonts_embedded(src, pno):
            n = None
        elif logo:
            n = orl.logo_raster(src)[1]
        else:
            sr = orl.source_rect(src, pno, fitz.Rect(*clip) if clip
                                 else None)
            tr = orl.fit_rect(fitz.Rect(*fit), sr.width, sr.height)
            n = orl.raster_page(src, pno, (tr.width, tr.height), sr,
                                orl.RASTER_DPI)[1]
    if len(_trials) > 2000:
        _trials.clear()
    _trials[key] = n
    return n


def _plan_sheets(rep, o):
    """(sheet, page) of every plan page the build prints (key plan and
    work areas), as _key_plan_pages / _work_area_pages group them."""
    out = []
    if o.get("key_plan"):
        seen = set()
        for ph in printed_photos(rep):
            pin = ph.get("pin")
            if pin:
                k = (_sheet_key(pin.get("sheet")), int(pin.get("page") or 0))
                if k not in seen:
                    seen.add(k)
                    out.append((pin.get("sheet"), k[1]))
    if o.get("work_areas"):
        seen = set()
        for a in rep.get("work_areas") or []:
            if len(a.get("pts") or []) >= 3:
                k = (_sheet_key(a.get("sheet")), int(a.get("page") or 0))
                if k not in seen:
                    seen.add(k)
                    out.append((a.get("sheet"), k[1]))
    return out


def _copied_pdf_bytes(store, rep, o, logo):
    """The images copied PDF pages with non-embedded fonts become: the
    logo (one image, reused), a forecast PDF attachment, plan sheets.
    Returns (bytes, logo_is_image)."""
    from . import owner_report_logs as orl
    total, logo_img = 0, False
    if logo and logo.lower().endswith(".pdf"):
        try:
            n = _raster_bytes(logo, logo=True)
        except Exception:                         # noqa: BLE001
            n = None
        if n is not None:
            total += n
            logo_img = True
    fc = rep.get("forecast") or {}
    if fc.get("mode") == "attach" and fc.get("attach_ref"):
        try:
            path = store.attachment_path(fc["attach_ref"])
            if path.lower().endswith(".pdf"):
                total += _raster_bytes(path, int(fc.get("attach_page") or 0),
                                       orl.FC_BOX) or 0
        except Exception:                         # noqa: BLE001
            log.debug("forecast size estimate skipped", exc_info=True)
    for sheet, pno in _plan_sheets(rep, o):
        try:
            total += _raster_bytes(_sheet_path(store, sheet), pno,
                                   PLAN_AREA,
                                   _clip_for(rep, sheet, pno)) or 0
        except Exception:                         # noqa: BLE001
            log.debug("plan size estimate skipped", exc_info=True)
    return total, logo_img


def estimate_size(store, rep, preset=None):
    """The PDF's size in bytes without building it.

    Photos: a first guess for each - photofit.estimate() at its printed
    size scaled by how busy the photo is (_content), or for "original" the
    camera file's size - then TRIAL_PHOTOS of them (spread from the
    plainest to the busiest) are really encoded at the preset and the
    guesses for the rest scaled by real / guessed on those. The model alone
    was fitted to synthetic photos and ran ~2x high on real site photos;
    "original" re-encodes at q95 4:4:4, ~1.5x the camera file. Plus a
    per-page allowance, the embedded fonts and the logo, and the images
    copied PDF pages with non-embedded fonts become (_copied_pdf_bytes:
    a PDF logo, a forecast PDF, plan sheets - rendered as the build does;
    vector copies are not counted, as before)."""
    from . import photofit
    o = options(rep)
    preset = preset or o.get("size_preset") or "email"
    per = photos_a_page(o.get("photos_per_page"))
    cells = photo_cells(per, bool(o.get("captions")))
    photos = printed_photos(rep)
    caps = bool(o.get("captions"))
    jobs = [(ph, cells[i % per], caps) for i, ph in enumerate(photos)]
    if o.get("before_after"):
        cands = {_photo_key(c.get("ref")): c
                 for c in rep.get("before_candidates") or []}
        bcells = photo_cells(4, True)
        k = 0
        for ph in photos:
            b = cands.get(_photo_key(ph.get("pair_with")))
            if ph.get("pair_with") and b is not None:
                row = (k % 2) * 2
                jobs += [(b, bcells[row], True), (ph, bcells[row + 1], True)]
                k += 1
    items = []                  # [ph, path, rect, box, guess, busy]
    for ph, cell, cap in jobs:
        try:
            path = store.attachment_path(ph["ref"])
            iw, ih = _image_info(path, ph.get("rotate"))
        except Exception:
            continue
        rect, box = photofit.fit(cell, iw, ih, ph.get("fit") or "auto",
                                 max_crop=max_crop_for(cap),
                                 crop=ph.get("crop"))
        box = tuple(box) if box else (0, 0, 1, 1)
        busy = _content(path, iw, ih)
        if preset == "original":
            try:
                guess = float(os.path.getsize(path))
            except OSError:
                continue
        else:
            guess = photofit.estimate(iw, ih, rect[2] - rect[0],
                                      rect[3] - rect[1], preset,
                                      src_box=box) * busy
        items.append([ph, path, tuple(rect), box, guess, busy])
    # the trial: TRIAL_PHOTOS spread over the photos sorted by busyness
    order = sorted(range(len(items)), key=lambda i: items[i][5])
    n = min(TRIAL_PHOTOS, len(order))
    pick = sorted({order[int((j + 0.5) * len(order) / n)]
                   for j in range(n)}) if n else []
    real, guessed, done = 0.0, 0.0, {}
    for i in pick:
        ph, path, rect, box, guess, _b = items[i]
        try:
            done[i] = _trial_bytes(store, ph, path, rect, box, preset)
        except Exception:                         # noqa: BLE001
            log.debug("size trial failed", exc_info=True)
            continue
        real += done[i]
        guessed += guess
    scale = real / guessed if guessed > 0 and real > 0 else 1.0
    total = sum(done[i] if i in done else it[4] * scale
                for i, it in enumerate(items))
    pages = 1 + math.ceil(len(photos) / per) + 4
    pages += sum(1 for k in ("decisions", "schedule", "manpower", "lookahead",
                             "key_plan", "work_areas", "co_log") if o.get(k))
    total += PAGE_OVERHEAD * pages + FONT_BYTES
    logo = _logo_path(store, template_for(rep))
    copied, logo_img = _copied_pdf_bytes(store, rep, o, logo)
    total += copied
    if logo and not logo_img:
        try:
            total += os.path.getsize(logo)
        except OSError:
            pass
    return int(total)
