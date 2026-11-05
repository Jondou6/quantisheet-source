"""Accuracy harness: run AI Takeoff headless on a COPY of a plan set and
score it against a human takeoff workbook (sheet Mapping).

    python tools/aiken_eval.py [--pages 1-20,58] [--out DIR] [--score-only]
                               [--src DIR] [--drawings NAME] [--spec NAME]
                               [--xlsx FILE] [--map FILE]
                               [--start] [--show]

The plan-set folder and the drawing, spec and workbook file names are
not stored in this repository. Pass them with --src, --drawings, --spec
and --xlsx, or set the environment variables QS_<SET>_SRC,
QS_<SET>_DRAWINGS, QS_<SET>_SPEC and QS_<SET>_XLSX (SET is AIKEN or
COLLETON), or the settings keys <set>_src, <set>_drawings, <set>_spec
and <set>_xlsx. If a value the run needs is unset, the harness skips
and says which ones.

1. Copies the drawings and the spec book from that folder into
   %LOCALAPPDATA%\\QuantiSheetWork\\<set> - skipped when the copy is
   already there with the same size and time - and marks the copies
   read-only. Only the copies are opened; nothing is ever written to
   the source folder.
2. Runs AI Takeoff on the drawing copy the way the app's AI Takeoff dialog
   does (aitakeoff.plan_set, then aitakeoff.run), without a window.
   --pages (1-based, e.g. 1-20,58,76-77) limits what is taken off; the
   whole set is still read, so duplicate sheets are still found.
3. Writes every AI result line to ai_lines.csv: key, engine, description,
   CSI division, qty, unit, status (taken off / review / existing),
   source sheets. Engines: rooms, pipes, civil, devices, ducts, steel,
   footings, schedules, finishes (floor SF / base LF / ceiling SF / wall
   finish SF per finish code: 'finishes:Floor EPX', 'finishes:Base RB',
   'finishes:Ceiling ACT', 'finishes:Wall finish PT-1') and walls (LF per
   wall type and of the exterior wall's outer face loop: 'walls:Wall
   Type 2A', 'walls:Exterior Walls'; SF where a height is known:
   'walls:Wall Type 1A wall area').
4. Scores them against the Mapping sheet (read-only) with the explicit
   map in tools/aiken_map.json - no fuzzy matching: each human Group_ID is
   compared on base quantity (pre-waste), summed over its rows, with the
   reviewer's unit conversions.
5. Prints a compact scorecard (under ~150 lines) and writes the full
   per-item and per-group CSVs.

--score-only re-scores the ai_lines.csv already in --out (no takeoff run:
seconds, for map changes). --start runs it in the background (output in
OUT\\console.txt); --show prints the last scorecard.

Outputs in --out (default %LOCALAPPDATA%\\QuantiSheetWork\\aiken\\out):
  scorecard.txt   the printed scorecard
  ai_lines.csv    AI result lines (one per key)
  score_groups.csv  one row per human group: human qty, AI qty, diff, status
  score_items.csv   one row per human item (Mapping row) with its group status
  unmapped_ai.csv   AI lines no rule maps (what the AI adds)
  sheets.csv      how AI Takeoff read each sheet (number, kind, engines, note)
  summary.txt     the app's own summary text; problems.txt; review.csv;
                  existing.csv; unfinished.csv; submittals.csv
  run_log.txt     progress with times
  meta.json       times, counts, versions

Rules: the owner's drawings and takeoff are never modified or bundled.
Never reads anything under "04. Planswift Takeoff" (prices). No network.
"""
import argparse
import csv
import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FORBIDDEN = re.compile(r"planswift", re.I)
# other plan sets scored the same way: --set NAME (or QS_EVAL_SET=NAME for
# the diag tools). Each has its own work folder copy and map.
MAPS = {
    "aiken": os.path.join(ROOT, "tools", "aiken_map.json"),
    "colleton": os.path.join(ROOT, "tools", "colleton_map.json"),
}
SET = "aiken"
DEFAULT_SRC = ""
DRAWINGS = ""
SPEC = ""
XLSX_REL = ""
MAP = MAPS["aiken"]


def _from_settings(key):
    """A string setting, or '' when it is unset or settings can't be read."""
    try:
        from app import settings
        got = settings.get(key)
    except Exception:                                     # noqa: BLE001
        return ""
    return got.strip() if isinstance(got, str) else ""


def _configured(env_key, settings_key):
    """Environment variable, otherwise the same key in settings."""
    v = (os.environ.get(env_key) or "").strip()
    return v or _from_settings(settings_key)


def plan_config(name):
    """Folder, drawing, spec and workbook for plan set `name`.

    Each one is QS_<SET>_* or the settings key <set>_*. '' means unset.
    The map file is the quantity crosswalk shipped with the program.
    """
    key = name.lower()
    if key not in MAPS:
        raise KeyError(key)
    up = key.upper()
    return {
        "src": _configured(f"QS_{up}_SRC", f"{key}_src"),
        "drawings": _configured(f"QS_{up}_DRAWINGS", f"{key}_drawings"),
        "spec": _configured(f"QS_{up}_SPEC", f"{key}_spec"),
        "xlsx": _configured(f"QS_{up}_XLSX", f"{key}_xlsx"),
        "map": MAPS[key],
    }


def skip_message(name, missing):
    """What to print when the plan set's paths are not configured."""
    up = name.upper()
    return (f"skipping {name}: {', '.join(missing)} not set. "
            f"Set QS_{up}_SRC, QS_{up}_DRAWINGS, QS_{up}_SPEC and "
            f"QS_{up}_XLSX, or the settings {name}_src, {name}_drawings, "
            f"{name}_spec and {name}_xlsx.")


def use_set(name):
    """Point the module at plan set `name` (drawings, spec, comparison
    workbook, map, work folder)."""
    global SET, DEFAULT_SRC, DRAWINGS, SPEC, XLSX_REL, MAP
    c = plan_config(name)
    SET = name
    DEFAULT_SRC, DRAWINGS, SPEC = c["src"], c["drawings"], c["spec"]
    XLSX_REL, MAP = c["xlsx"], c["map"]


if os.environ.get("QS_EVAL_SET") in MAPS:
    use_set(os.environ["QS_EVAL_SET"])
else:
    use_set("aiken")
# the diag tools take "--set NAME" anywhere on their command line
if __name__ != "__main__" and "--set" in sys.argv[:-1]:
    _i = sys.argv.index("--set")
    if sys.argv[_i + 1] in MAPS:
        use_set(sys.argv[_i + 1])
        del sys.argv[_i:_i + 2]

DIV_NAMES = {
    "01": "General Requirements", "02": "Existing Conditions",
    "03": "Concrete", "04": "Masonry", "05": "Metals",
    "06": "Wood & Plastics", "07": "Thermal & Moisture", "08": "Openings",
    "09": "Finishes", "10": "Specialties", "11": "Equipment",
    "12": "Furnishings", "13": "Special Construction", "14": "Conveying",
    "21": "Fire Suppression", "22": "Plumbing", "23": "HVAC",
    "26": "Electrical", "27": "Communications", "28": "Electronic Safety",
    "31": "Earthwork", "32": "Exterior Improvements", "33": "Utilities"}
ENGINE_OF = {"AI takeoff: rooms": "rooms", "AI takeoff: pipe runs": "pipes",
             "AI takeoff: civil": "civil", "AI takeoff: devices": "devices",
             "AI takeoff: schedules": "schedules",
             "AI takeoff: ducts": "ducts", "AI takeoff: steel": "steel",
             "AI takeoff: walls": "walls",
             "AI takeoff: finishes": "finishes"}
UNIT_OF = {"ea": "EA", "ft": "LF", "lf": "LF", "sf": "SF", "cy": "CY",
           "lb": "LB", "sq ft": "SF", "sqft": "SF", "sq. ft.": "SF",
           "sq ft.": "SF"}
DISC_DIV = {"plumbing": "22", "mechanical": "23", "fire protection": "21",
            "electrical": "26", "fire alarm": "28", "telecom": "27",
            "civil": "33", "architectural": "09", "interiors": "09",
            "structural": "05", "landscape": "32"}


def work_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "QuantiSheetWork", SET)


def guard(path):
    if FORBIDDEN.search(os.path.abspath(path)):
        sys.exit(f"refusing to read {path}: Planswift folders hold prices")
    return path


# ------------------------------------------------------------- copies
def copy_in(src, dst_dir):
    """Copy `src` into dst_dir unless an identical copy (size, mtime) is
    already there. The copy is made read-only. Returns (path, copied)."""
    guard(src)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    s = os.stat(src)
    if os.path.exists(dst):
        d = os.stat(dst)
        if d.st_size == s.st_size and abs(d.st_mtime - s.st_mtime) < 2.0:
            return dst, False
        os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)
    tmp = dst + ".part"
    shutil.copy2(src, tmp)
    if os.path.getsize(tmp) != s.st_size:
        os.remove(tmp)
        sys.exit(f"copy of {src} came out the wrong size")
    os.replace(tmp, dst)
    os.chmod(dst, stat.S_IREAD)
    return dst, True


# ------------------------------------------------------------- pages
def parse_pages(spec):
    """'1-20,58' (1-based) -> set of 0-based page numbers, or None."""
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a) - 1, int(b)))
        else:
            out.add(int(part) - 1)
    return out


# ------------------------------------------------------------- run
class Log:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")
        self.t0 = time.time()
        self.last = self.t0

    def __call__(self, *a):
        now = time.time()
        self.f.write(f"{now - self.t0:8.1f}s (+{now - self.last:5.1f}) "
                     + " ".join(str(x) for x in a) + "\n")
        self.f.flush()
        self.last = now


def run_takeoff(pdf, pages, log):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import logging
    logging.basicConfig(filename=log.f.name + ".app.txt", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s "
                               "%(message)s")
    import app  # noqa: F401  (makes "fitz" the installed PyMuPDF)
    import fitz
    from app import aitakeoff as ait
    doc = fitz.open(pdf)
    log("opened", pdf, doc.page_count, "pages")
    t = time.time()

    def p1(i, n):
        if i % 10 == 0:
            log(f"reading sheet {i + 1}/{n}")
        return True
    rows = ait.plan_set(doc, p1)
    t_read = time.time() - t
    log(f"read the set in {t_read:.1f}s")
    if pages is not None:
        for r in rows:
            if r["page"] not in pages:
                r["engines"] = []
    t = time.time()

    def p2(k, n, text):
        log(f"step {k}/{n}: {text}")
        return True
    res = ait.run(doc, rows, p2)
    t_run = time.time() - t
    log(f"ran in {t_run:.1f}s: {len(res['marks'])} marks")
    return doc, rows, res, {"read_s": round(t_read, 1),
                            "run_s": round(t_run, 1)}


def ait_spec(res, sp):
    from app import aitakeoff as ait
    return ait.spec_quantities(res, sp)


def ai_lines(doc, rows, res):
    """The AI result as lines: one per (engine, group name, unit) with
    status 'taken off' (measurements placed), 'review' (found, not
    measured with confidence) or 'existing' (listed, not in totals)."""
    from app import aitakeoff as ait
    by_page = {r["page"]: r for r in rows}

    def sheet_no(p):
        r = by_page.get(p) or {}
        return r.get("number") or f"p{p + 1}"
    lines = {}

    def add(engine, name, qty, unit, status, page, div=None):
        key = f"{engine}:{name}"
        k = (key, status, unit)
        ln = lines.setdefault(k, {"key": key, "engine": engine,
                                  "description": name, "qty": 0.0,
                                  "unit": unit, "status": status,
                                  "sheets": [], "divs": {}})
        ln["qty"] += qty or 0.0
        if page is not None:
            s = sheet_no(page)
            if s not in ln["sheets"]:
                ln["sheets"].append(s)
            d = div or DISC_DIV.get((by_page.get(page) or {}).get(
                "discipline"), "")
            if d:
                ln["divs"][d] = ln["divs"].get(d, 0) + 1
    for p, kind, pl in res["marks"]:
        m = pl.get("measure") or {}
        eng = ENGINE_OF.get(m.get("method"), m.get("method") or "?")
        typ = m.get("type")
        if typ == "count":
            qty, unit = 1.0, "EA"
        elif typ == "area":
            qty, unit = float(m.get("value") or 0), "SF"
        else:
            qty, unit = float(m.get("value") or 0), "LF"
        div = (m.get("csi") or "")[:2] or \
            {"rooms": "09", "civil": "33", "walls": "09",
             "finishes": "09"}.get(eng)
        add(eng, m.get("group") or "?", qty, unit, "taken off", p, div)
    for x in res.get("review") or []:
        eng = x.get("engine") or (
            "devices" if "legend" in (x.get("why") or "") else "pipes")
        unit = UNIT_OF.get(str(x.get("unit") or "").lower()) or (
            "EA" if eng in ("devices", "schedules") else
            "SF" if eng in ("rooms", "finishes") else "LF")
        q = x.get("qty")
        add(eng, x["name"], q if isinstance(q, (int, float)) else 0.0,
            unit, "review", x.get("page"), (x.get("csi") or "")[:2] or None)
    # quantities that are not marks: steel LB, footing CY
    for x in res.get("quantities") or []:
        add(x["engine"], x["name"], x["qty"],
            UNIT_OF.get(str(x["unit"]).lower(), str(x["unit"]).upper()),
            x.get("status") or "taken off", x.get("page"),
            (x.get("csi") or "")[:2] or None)
    # the Division 01 lines the estimate workbook carries (1 LS each)
    from app import estimate_book
    for g in estimate_book.general_lines():
        add("general", g["description"], g["qty"], "LS", "taken off",
            None, "01")
    for x in res.get("existing") or []:
        eng = "civil" if x.get("source") == "civil" else "pipes"
        add(eng, x["name"], x["length"], "LF", "existing", x.get("page"),
            "33" if eng == "civil" else None)
    out = []
    for ln in lines.values():
        ln["csi"] = max(ln["divs"], key=ln["divs"].get) if ln["divs"] \
            else ""
        del ln["divs"]
        ln["qty"] = round(ln["qty"], 3)
        ln["sheets"] = "/".join(ln["sheets"])
        out.append(ln)
    out.sort(key=lambda l: (l["csi"], l["key"], l["status"]))
    totals = ait.totals(res)
    return out, totals


LINE_COLS = ["key", "engine", "description", "csi", "qty", "unit", "status",
             "sheets"]


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _safe(r.get(c)) for c in cols})


def _safe(v):
    """Cell text that a spreadsheet won't run as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and \
            not re.match(r"^-?\d", v):
        return "'" + v
    return v


def read_lines(path):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["qty"] = float(r["qty"] or 0)
            out.append(r)
    return out


# ------------------------------------------------------------- human
def read_mapping(xlsx):
    """Mapping sheet rows: [{row, div, desc, qty, unit, group}]."""
    guard(xlsx)
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["Mapping"]
    it = ws.iter_rows(values_only=True)
    head = [str(h or "") for h in next(it)]
    ix = {h: i for i, h in enumerate(head)}
    need = ["Human_Row", "CSI_Div", "Human_Description", "Human_Qty",
            "Human_Unit", "Group_ID"]
    miss = [n for n in need if n not in ix]
    if miss:
        sys.exit(f"Mapping sheet lacks columns {miss}")
    out = []
    for r in it:
        if r is None or r[ix["Human_Row"]] is None:
            continue
        g = str(r[ix["Group_ID"]] or "").strip()
        row = str(r[ix["Human_Row"]]).strip()
        if re.fullmatch(r"\d+(\.0)?", row):
            row = str(int(float(row)))
        q = r[ix["Human_Qty"]]
        try:
            q = float(q)
        except (TypeError, ValueError):
            q = None
        out.append({"row": row, "div": str(r[ix["CSI_Div"]] or "").zfill(2),
                    "desc": str(r[ix["Human_Description"]] or ""),
                    "qty": q, "unit": str(r[ix["Human_Unit"]] or "").upper(),
                    "group": g if g and g != "(unmapped)" else f"R{row}",
                    "mapped": bool(g and g != "(unmapped)")})
    wb.close()
    return out


# ------------------------------------------------------------- scoring
def load_map(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    exact = {}
    regex = []
    for r in m.get("rules", []):
        if "key" in r:
            exact.setdefault(r["key"], r["group"])
        else:
            regex.append((re.compile(r["regex"]), r["group"]))
    info = [(re.compile(r["regex"]), r.get("why", ""))
            for r in m.get("info", [])]
    return m, exact, regex, info


def map_line(key, exact, regex):
    if key in exact:
        return exact[key]
    for rx, g in regex:
        if rx.search(key):
            return g
    return None


def score(lines, human, mp):
    m, exact, regex, info = mp
    conv = m.get("groups", {})
    # human rows the AI can only take off together (ball valves of two
    # sizes from one legend symbol): one group, by the map's "regroup"
    rg = {str(row): g for g, rows in (m.get("regroup") or {}).items()
          for row in rows}
    for h in human:
        if not h.get("mapped") and h["row"] in rg:
            h["group"] = rg[h["row"]]
    groups = {}
    for h in human:
        g = groups.setdefault(h["group"], {
            "group": h["group"], "div": h["div"], "items": [],
            "unit": h["unit"], "human": 0.0, "units": set()})
        g["items"].append(h)
        g["units"].add(h["unit"])
        if h["qty"] is not None:
            g["human"] += h["qty"]
    for ln in lines:
        ln["group"] = map_line(ln["key"], exact, regex) or ""
        ln["info"] = ""
        if not ln["group"]:
            for rx, why in info:
                if rx.search(ln["key"]):
                    ln["info"] = why
                    break
        if ln["group"] and ln["group"] not in groups:
            ln["info"] = f"maps to unknown group {ln['group']}"
            ln["group"] = ""
    for g in groups.values():
        mine = [l for l in lines if l["group"] == g["group"]]
        took = [l for l in mine if l["status"] == "taken off"]
        rev = [l for l in mine if l["status"] == "review"]
        g["ai_keys"] = "; ".join(sorted({l["key"] for l in mine}))
        g["review_qty"] = sum(l["qty"] for l in rev)
        g["ai"] = None
        g["cmp_unit"] = g["unit"]
        g["cmp_human"] = g["human"]
        g["status"] = "MISSED"
        if len(g["units"]) > 1:
            g["note"] = "human rows in mixed units"
        else:
            g["note"] = ""
        if took:
            units = {l["unit"] for l in took}
            alt = (conv.get(g["group"]) or {}).get("alt", {})
            if g["unit"] in units:
                u = g["unit"]
            else:
                u = next((x for x in sorted(units) if x in alt), None)
            if u is None:
                g["status"] = "UNIT_MISMATCH"
                g["note"] = f"AI unit {'/'.join(sorted(units))} vs human " \
                            f"{g['unit']}"
            else:
                g["cmp_unit"] = u
                if u != g["unit"]:
                    g["cmp_human"] = g["human"] * alt[u]
                    g["note"] = (conv[g["group"]].get("note") or
                                 f"converted to {u}")
                g["ai"] = sum(l["qty"] for l in took if l["unit"] == u)
                g["status"] = "FOUND"
        elif rev:
            g["status"] = "FLAGGED"
        g["diff"] = None
        if g["ai"] is not None and g["cmp_human"]:
            g["diff"] = (g["ai"] - g["cmp_human"]) / g["cmp_human"] * 100
        g["w2"] = g["diff"] is not None and abs(g["diff"]) <= 2.0
        g["w5"] = g["diff"] is not None and abs(g["diff"]) <= 5.0
        g["exact"] = (g["status"] == "FOUND" and g["cmp_unit"] == "EA" and
                      round(g["ai"]) == round(g["cmp_human"]))
    added = [l for l in lines if not l["group"] and not l["info"] and
             l["status"] == "taken off"]
    return groups, added


# ------------------------------------------------------------- report
def scorecard(groups, added, lines, rows, res_meta, mp, args, totals=None,
              sub=None):
    m = mp[0]
    out = []
    P = out.append
    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    # the map the score was made with, so release notes can quote it (a
    # map changed in the same release changes the score; review 0.13.9 #3)
    try:
        import hashlib
        with open(args.map, "rb") as fh:
            msha = hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:                                     # noqa: BLE001
        msha = "?"
    P(f"{SET.upper()} AI TAKEOFF SCORECARD  {when}  "
      f"(pages: {args.pages or 'all'}; map v{m.get('version')}, "
      f"{len(m.get('rules') or [])} rules, sha256 {msha})")
    if res_meta:
        P(f"read {res_meta.get('read_s')} s, run {res_meta.get('run_s')} s, "
          f"{res_meta.get('marks')} marks, {res_meta.get('lines')} AI lines")
    P("Compared on base quantity (pre-waste). FOUND = AI took it off; "
      "FLAGGED = AI found it but sent it to review; ok2/ok5 = groups within "
      "2%/5%; EA= = counts exact")
    P("")
    hdr = (f"{'Div':<4}{'Name':<20}{'items':>6}{'found':>6}{'miss':>6}"
           f"{'flag':>5} |{'grp':>4}{'fnd':>4}{'ok2':>4}{'ok5':>4}"
           f"{'EA=':>6}{'unit?':>6}{'added':>6}")
    P(hdr)
    P("-" * len(hdr))
    divs = sorted({g["div"] for g in groups.values()} |
                  {l.get("csi") or "??" for l in added})
    tot = dict(items=0, found=0, miss=0, flag=0, grp=0, fnd=0, ok2=0,
               ok5=0, ea=0, eaf=0, um=0, add=0)
    for d in divs:
        gs = [g for g in groups.values() if g["div"] == d]
        items = sum(len(g["items"]) for g in gs)
        found = sum(len(g["items"]) for g in gs if g["status"] == "FOUND")
        flag = sum(len(g["items"]) for g in gs if g["status"] == "FLAGGED")
        miss = items - found - flag
        fnd = [g for g in gs if g["status"] == "FOUND"]
        ok2 = sum(g["w2"] for g in fnd)
        ok5 = sum(g["w5"] for g in fnd)
        eaf = [g for g in fnd if g["cmp_unit"] == "EA"]
        ea = sum(g["exact"] for g in eaf)
        um = sum(1 for g in gs if g["status"] == "UNIT_MISMATCH")
        add = sum(1 for l in added if (l.get("csi") or "??") == d)
        for k, v in (("items", items), ("found", found), ("miss", miss),
                     ("flag", flag), ("grp", len(gs)), ("fnd", len(fnd)),
                     ("ok2", ok2), ("ok5", ok5), ("ea", ea),
                     ("eaf", len(eaf)), ("um", um), ("add", add)):
            tot[k] += v
        P(f"{d:<4}{DIV_NAMES.get(d, '')[:19]:<20}{items:>6}{found:>6}"
          f"{miss:>6}{flag:>5} |{len(gs):>4}{len(fnd):>4}{ok2:>4}{ok5:>4}"
          f"{f'{ea}/{len(eaf)}':>6}{um:>6}{add:>6}")
    P("-" * len(hdr))
    ea_all = f"{tot['ea']}/{tot['eaf']}"
    P(f"{'ALL':<24}{tot['items']:>6}{tot['found']:>6}{tot['miss']:>6}"
      f"{tot['flag']:>5} |{tot['grp']:>4}{tot['fnd']:>4}{tot['ok2']:>4}"
      f"{tot['ok5']:>4}{ea_all:>6}{tot['um']:>6}{tot['add']:>6}")
    fnd = [g for g in groups.values() if g["status"] == "FOUND"]
    P("")
    P(f"FOUND GROUPS ({len(fnd)}), worst first:  group | human -> AI unit "
      "| diff | AI lines")
    for g in sorted(fnd, key=lambda g: -abs(g["diff"] or 0))[:25]:
        d = f"{g['diff']:+.1f}%" if g["diff"] is not None else "n/a"
        P(f"  {g['group']:<14}{g['cmp_human']:>10,.1f} ->{g['ai']:>10,.1f} "
          f"{g['cmp_unit']:<3}{d:>9}  {g['ai_keys'][:58]}")
    flg = [g for g in groups.values() if g["status"] in ("FLAGGED",
                                                         "UNIT_MISMATCH")]
    if flg:
        P(f"FLAGGED / UNIT MISMATCH ({len(flg)}):")
        for g in flg[:12]:
            P(f"  {g['group']:<14}{g['status']:<14} human {g['human']:,.1f} "
              f"{g['unit']}  {g['note'] or g['ai_keys'][:50]}")
    P("")
    P(f"AI LINES NOT IN THE HUMAN TAKEOFF ({len(added)}), biggest first:")
    for l in sorted(added, key=lambda l: -l["qty"])[:15]:
        P(f"  {l['csi'] or '??':<3}{l['key'][:52]:<53}{l['qty']:>10,.1f} "
          f"{l['unit']:<3}{l['sheets'][:22]}")
    rv = [l for l in lines if l["status"] == "review"]
    ex = [l for l in lines if l["status"] == "existing"]
    P(f"REVIEW LINES ({len(rv)}) / EXISTING LINES ({len(ex)}):")
    for l in rv[:10]:
        q = f"{l['qty']:,.0f} {l['unit']}" if l["qty"] else "-"
        P(f"  review   {l['key'][:58]:<59}{q:>12} {l['sheets'][:16]}")
    for l in ex[:6]:
        P(f"  existing {l['key'][:58]:<59}{l['qty']:>8,.0f} {l['unit']:<3} "
          f"{l['sheets'][:16]}")
    P("")
    P("SET CHECKS:")
    chk = m.get("checks", {})
    if totals is not None:
        P(f"  rooms: {totals.get('rooms')} rooms, "
          f"{totals.get('rooms_sf', 0):,.0f} SF (room tags on the floor " +
          (f"plan: {chk['rooms_sf_from_tags']:,} SF)" if chk.get('rooms_sf_from_tags') else "plan: not set)"))
    if rows:
        sup = [r for r in rows if r.get("kind") == "superseded"]
        P(f"  superseded sheets: {len(sup)} - " + ", ".join(
            f"{r['number']} p{r['page'] + 1}" for r in sup[:8]) +
          f" (expected duplicates: "
          f"{', '.join(chk.get('duplicate_sheet_numbers', []))})")
        took = [r for r in rows if r.get("engines")]
        P(f"  sheets taken off: {len(took)} of {len(rows)}; needs a scale: "
          f"{sum(1 for r in rows if r.get('wanted') and not r.get('engines') and r.get('kind') == 'plan')}")
    if res_meta and res_meta.get("unfinished") is not None:
        P(f"  not finished: {res_meta['unfinished']}  problems: "
          f"{res_meta.get('problems')}")
    if sub is not None:
        P(f"  submittals from spec book: {sub[0]} items in {sub[1]} sections "
          f"(spec has {chk.get('spec_sections', '?')} sections)")
    return out


def write_outputs(out_dir, groups, added, lines):
    gcols = ["group", "div", "status", "cmp_unit", "cmp_human", "ai",
             "diff", "w2", "w5", "exact", "review_qty", "unit", "human",
             "note", "ai_keys", "n_items", "first_desc"]
    grows = []
    for g in sorted(groups.values(), key=lambda g: (g["div"], g["group"])):
        grows.append(dict(g, n_items=len(g["items"]),
                          first_desc=g["items"][0]["desc"][:80],
                          diff=None if g["diff"] is None else
                          round(g["diff"], 2)))
    write_csv(os.path.join(out_dir, "score_groups.csv"), grows, gcols)
    irows = []
    for g in groups.values():
        for h in g["items"]:
            irows.append({"row": h["row"], "div": h["div"],
                          "description": h["desc"], "qty": h["qty"],
                          "unit": h["unit"], "group": g["group"],
                          "mapped_by_reviewer": h["mapped"],
                          "status": g["status"],
                          "group_human": round(g["cmp_human"], 3),
                          "group_ai": g["ai"], "cmp_unit": g["cmp_unit"],
                          "group_diff_pct": None if g["diff"] is None else
                          round(g["diff"], 2)})
    irows.sort(key=lambda r: (not r["row"].isdigit(),
                              int(r["row"]) if r["row"].isdigit() else 0,
                              r["row"]))
    write_csv(os.path.join(out_dir, "score_items.csv"), irows,
              list(irows[0]) if irows else ["row"])
    write_csv(os.path.join(out_dir, "unmapped_ai.csv"), added, LINE_COLS)
    write_csv(os.path.join(out_dir, "ai_lines.csv"), lines,
              LINE_COLS + ["group", "info"])


def spec_check(spec_pdf, out_dir):
    from app.pm import submittals
    t = time.time()
    props = submittals.from_spec_book(spec_pdf)
    write_csv(os.path.join(out_dir, "submittals.csv"), props,
              ["spec", "section", "type", "title", "page"])
    return len(props), len({p["spec"] for p in props}), \
        round(time.time() - t, 1)


# ------------------------------------------------------------- main
def _xlsx_path(src, xlsx_rel):
    if not xlsx_rel:
        return ""
    if os.path.isabs(xlsx_rel):
        return xlsx_rel
    if not src:
        return ""
    return os.path.join(src, xlsx_rel)


def main(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--set", choices=sorted(MAPS))
    known, _rest = pre.parse_known_args(argv)
    if known.set:
        use_set(known.set)
    else:
        use_set(SET)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", choices=sorted(MAPS),
                    help="plan set to score (default aiken)")
    ap.add_argument("--pages", help="1-based pages to take off: 1-20,58")
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--src", default=None,
                    help="folder with the plan-set files (read only); "
                         "default QS_<SET>_SRC or the <set>_src setting")
    ap.add_argument("--drawings", default=None,
                    help="drawing file name inside --src")
    ap.add_argument("--spec", default=None,
                    help="spec-book file name inside --src")
    ap.add_argument("--xlsx", help="the comparison workbook (read only)")
    ap.add_argument("--map", default=MAP)
    ap.add_argument("--score-only", action="store_true",
                    help="re-score ai_lines.csv in --out, no takeoff")
    ap.add_argument("--no-spec", action="store_true",
                    help="skip the submittals-from-spec check")
    ap.add_argument("--start", action="store_true",
                    help="run in the background (OUT/console.txt)")
    ap.add_argument("--show", action="store_true",
                    help="print the last scorecard")
    args = ap.parse_args(argv)
    work = work_dir()
    out_dir = args.out or os.path.join(work, "out")
    card = os.path.join(out_dir, "scorecard.txt")
    if args.show:
        os.makedirs(out_dir, exist_ok=True)
        if os.path.exists(card):
            print(open(card, encoding="utf-8").read())
        else:
            print("no scorecard yet in", out_dir)
        return 0
    if args.start:
        os.makedirs(out_dir, exist_ok=True)
        rest = [a for a in (argv if argv is not None else sys.argv[1:])
                if a != "--start"]
        with open(os.path.join(out_dir, "console.txt"), "w") as con:
            subprocess.Popen([sys.executable, os.path.abspath(__file__)] +
                             rest, cwd=ROOT, stdout=con,
                             stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
        print(f"started; then: python tools/aiken_eval.py --show "
              f"{'--out ' + args.out if args.out else ''}")
        return 0
    src = args.src or DEFAULT_SRC
    drawings = args.drawings or DRAWINGS
    spec_name = args.spec or SPEC
    xlsx_rel = args.xlsx or XLSX_REL
    xlsx = _xlsx_path(src, xlsx_rel)
    missing = []
    if args.score_only:
        if not xlsx:
            missing.append("xlsx")
    else:
        if not src:
            missing.append("src")
        if not drawings:
            missing.append("drawings")
        if not args.no_spec and not spec_name:
            missing.append("spec")
        if not xlsx:
            missing.append("xlsx")
    if missing:
        print(skip_message(SET, missing))
        return 0
    os.makedirs(out_dir, exist_ok=True)
    guard(xlsx)
    mp = load_map(args.map)
    human = read_mapping(xlsx)
    rows, res_meta, totals, sub = None, None, None, None
    lines_csv = os.path.join(out_dir, "ai_lines.csv")
    if args.score_only:
        lines = read_lines(lines_csv)
        if os.path.exists(os.path.join(out_dir, "meta.json")):
            meta = json.load(open(os.path.join(out_dir, "meta.json")))
            res_meta, totals = meta.get("run"), meta.get("totals")
            rows = meta.get("rows")
            sub = meta.get("submittals")
    else:
        pdf, c1 = copy_in(os.path.join(src, drawings), work)
        spec = None
        if not args.no_spec:
            spec, c2 = copy_in(os.path.join(src, spec_name), work)
        log = Log(os.path.join(out_dir, "run_log.txt"))
        log("drawings copy:", pdf, "(copied)" if c1 else "(already there)")
        doc, rows, res, tm = run_takeoff(pdf, parse_pages(args.pages), log)
        if spec:            # the project manual: materials, insulation
            try:
                import fitz as _fz
                from app import spec_materials
                n_sp = ait_spec(res, spec_materials.Spec.from_pdf(
                    _fz.open(spec)))
                log("spec lines added:", n_sp)
            except Exception as e:                        # noqa: BLE001
                log("spec not read:", e)
        lines, totals = ai_lines(doc, rows, res)
        from app import aitakeoff as ait
        unit = next((r["scale"][2] for r in rows if r["scale"]), "ft")
        with open(os.path.join(out_dir, "summary.txt"), "w",
                  encoding="utf-8") as f:
            f.write(ait.summary_text(rows, res, unit))
        with open(os.path.join(out_dir, "problems.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(res["problems"]))
        with open(os.path.join(out_dir, "checks.txt"), "w",
                  encoding="utf-8") as f:
            for c in res.get("checks") or ():
                f.write(f"{'ok   ' if c['ok'] else 'CHECK'} {c['name']}: "
                        f"{c['a']:,.1f} {c['unit']} ({c['a_from']}) vs "
                        f"{c['b']:,.1f} ({c['b_from']}) {c['off']:+.1%}\n")
        try:      # the estimate workbook the app saves (rates blank)
            from app import estimate_book
            gsf = next((q["qty"] for q in res.get("quantities") or ()
                        if q.get("name") == "Gross floor area"), None)
            estimate_book.write(
                os.path.join(out_dir, "estimate_workbook.xlsx"),
                estimate_book.collect(rows, res),
                project=f"{SET.title()} (AI Takeoff test)", gsf=gsf)
        except Exception as e:                            # noqa: BLE001
            log("estimate workbook not written:", e)
        write_csv(os.path.join(out_dir, "review.csv"), res["review"],
                  ["sheet", "page", "name", "qty", "unit", "why"])
        write_csv(os.path.join(out_dir, "existing.csv"), res["existing"],
                  ["sheet", "page", "name", "length", "unit", "source"])
        write_csv(os.path.join(out_dir, "unfinished.csv"),
                  res["unfinished"], ["sheet", "page", "engine", "why"])
        srows = [dict(r, scale=(r["scale"] or [""])[0],
                      engines="+".join(r["engines"]),
                      date=r.get("date") and "%04d-%02d-%02d" % r["date"])
                 for r in rows]
        write_csv(os.path.join(out_dir, "sheets.csv"), srows,
                  ["page", "number", "title", "discipline", "kind", "scale",
                   "scale_from", "engines", "date", "note", "dup_warning",
                   "raster"])
        doc.close()
        if spec:
            log("submittals from the spec copy")
            sub = spec_check(spec, out_dir)
            log(f"submittals: {sub[0]} in {sub[1]} sections, {sub[2]} s")
        res_meta = dict(tm, marks=len(res["marks"]), lines=len(lines),
                        unfinished=len(res["unfinished"]),
                        problems=len(res["problems"]))
        slim_rows = [{k: r.get(k) for k in ("page", "number", "kind",
                                            "engines", "wanted")}
                     for r in rows]
        with open(os.path.join(out_dir, "meta.json"), "w") as f:
            json.dump({"run": res_meta, "totals": {
                "rooms": totals["rooms"], "rooms_sf": totals["rooms_sf"]},
                "rows": slim_rows, "submittals": sub,
                "timing": res.get("timing"), "pages": args.pages,
                "python": sys.version.split()[0]}, f, indent=1)
    groups, added = score(lines, human, mp)
    write_outputs(out_dir, groups, added, lines)
    text = scorecard(groups, added, lines, rows, res_meta, mp, args,
                     totals, sub)
    text.append("")
    text.append(f"full results: {out_dir}")
    with open(card, "w", encoding="utf-8") as f:
        f.write("\n".join(text) + "\n")
    print("\n".join(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
