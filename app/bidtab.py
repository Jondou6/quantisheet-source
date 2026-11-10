"""Bid tab library: public bid results kept in the price database.

Import bid tabs (CSV/TSV/TXT, Excel .xlsx, or a PDF with tables) - one
file per bidder or one file with a bidder column - with the project's
name, owner, state and bid date. Each line is classified into a trade
(bidtab_core). The library groups the same item (description + unit)
across projects and bidders and shows low / median / mean / high and the
spread, each bid escalated from its own bid date to the date you pick at
the trade's yearly rate.

Bid prices are installed unit prices including the contractors' overhead
and profit, so compare them with an estimate's total after markup.
"""
import logging
import csv
import datetime as _dt
import difflib
import io
import os
import re
import statistics
import zipfile
from xml.etree import ElementTree as ET

from . import bidtab_core as core
from . import pricedb
from .dmoney import c2 as _c2

RATES_KEY = "bidtab_rates"


# ---- reading files --------------------------------------------------------------

def _xlsx_rows(path):
    """Rows of the first worksheet of an .xlsx (values only). Members are
    size-checked and parsed without DTDs (threat model T-007)."""
    from . import safexml
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = safexml.fromstring(safexml.zip_read(
                z, "xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(
                    "{%s}t" % ns["m"])))
        sheets = sorted(n for n in z.namelist()
                        if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        if not sheets:
            return []
        root = safexml.fromstring(safexml.zip_read(z, sheets[0]))
    rows = []
    for r in root.iter("{%s}row" % ns["m"]):
        cells = {}
        for c in r.findall("m:c", ns):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0) if ref else "A":
                col = col * 26 + ord(ch) - 64
            v = c.find("m:v", ns)
            t = c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None else ""
            cells[col - 1] = val or ""
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _pdf_rows(path):
    import fitz
    rows = []
    with fitz.open(path) as d:
        for page in d:
            try:
                tabs = page.find_tables()
            except Exception:
                continue
            for t in tabs.tables:
                for r in t.extract():
                    rows.append([(c or "").replace("\n", " ").strip()
                                 for c in r])
    return rows


def read_lines(path):
    """The file as delimited text lines (what bidtab_core parses)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        rows = _xlsx_rows(path)
    elif ext == ".pdf":
        rows = _pdf_rows(path)
        if not rows:
            raise ValueError(f"{os.path.basename(path)}: no tables found in "
                             "the PDF. Export the bid tab to Excel or CSV.")
    else:
        return core.read_lines(core.Path(path))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        if any(str(c).strip() for c in r):
            w.writerow(r)
    return [ln for ln in buf.getvalue().split("\n") if ln.strip()]


def preview(path, overrides=None):
    """(column map, first rows parsed) for the import window."""
    lines = read_lines(path)
    cmap = core.detect_columns(lines)
    cmap.index.update(overrides or {})
    rows = core.parse_lines(lines, os.path.splitext(os.path.basename(
        path))[0], overrides or {}, os.path.basename(path))
    return cmap, rows


# ---- the library ----------------------------------------------------------------

def import_files(paths, name, owner="", location="", state="", bid_date="",
                 bidder=None, overrides=None, source="", notes=""):
    """Add a project and its bid lines. Returns (project id, rows added,
    bidders)."""
    rows = []
    for p in paths:
        lines = read_lines(p)
        default = bidder if (bidder and len(paths) == 1) else \
            os.path.splitext(os.path.basename(p))[0]
        rows += core.parse_lines(lines, default, overrides or {},
                                 os.path.basename(p))
    if not rows:
        raise ValueError("No priced lines found. Check that the file has "
                         "description, unit and unit price (or quantity and "
                         "total) columns.")
    return add_rows(rows, name, owner, location, state, bid_date,
                    source or ", ".join(os.path.basename(p) for p in paths),
                    notes)


def _month(d):
    d = str(d or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})", d)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})/(?:\d{1,2}/)?(\d{4})", d)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    raise ValueError(f"Bid date {d!r}: use YYYY-MM (e.g. 2025-06).")


def import_and_route(paths, name, owner="", location="", state="",
                     bid_date="", bidder=None, overrides=None, source="",
                     notes="", auto=0.92, review=0.75, create_new_min=0):
    """Import like import_files, then route every line through the
    vocabulary (your import_cost tool): auto -> alias, review -> queue,
    new -> candidates (made into items when seen create_new_min+ times).
    Returns {project, rows, bidders, auto, review, new, created}."""
    from . import vocab
    rows = []
    for p in paths:
        lines = read_lines(p)
        default = bidder if (bidder and len(paths) == 1) else \
            os.path.splitext(os.path.basename(p))[0]
        rows += core.parse_lines(lines, default, overrides or {},
                                 os.path.basename(p))
    if not rows:
        raise ValueError("No priced lines found. Check that the file has "
                         "description, unit and unit price (or quantity and "
                         "total) columns.")
    pid, n, nb = add_rows(rows, name, owner, location, state, bid_date,
                          source or ", ".join(os.path.basename(p)
                                              for p in paths), notes)
    priced = [r for r in rows if getattr(r, "note", "") != "included"]
    counts = vocab.apply_routing(vocab.route(priced, auto, review), pid,
                                 f"bid tab: {name}", create_new_min,
                                 core.classify_trade)
    return dict(counts, project=pid, rows=n, bidders=nb)


def add_rows(rows, name, owner="", location="", state="", bid_date="",
             source="", notes=""):
    month = _month(bid_date or _dt.date.today().strftime("%Y-%m"))
    with pricedb.connect(write=True) as con:
        cur = con.execute(
            "INSERT INTO bid_projects (name, owner, location, state, "
            "bid_date, source, notes, added, added_by) VALUES "
            "(?,?,?,?,?,?,?,?,?)", (name or "Bid tab", owner, location,
                                    state, month, source, notes,
                                    pricedb.now(), pricedb.user()))
        pid = cur.lastrowid
        con.executemany(
            "INSERT INTO bid_rows (project, bidder, item_no, desc, unit, qty,"
            " price, trade, note) VALUES (?,?,?,?,?,?,?,?,?)",
            [(pid, r.bidder, r.item_no, r.desc, r.unit, r.qty, r.price,
              r.trade, getattr(r, "note", "") or "") for r in rows])
    return pid, len(rows), len({r.bidder for r in rows})


def projects():
    with pricedb.connect() as con:
        out = []
        for p in con.execute("SELECT * FROM bid_projects ORDER BY bid_date "
                             "DESC, id DESC"):
            n = con.execute("SELECT COUNT(*), COUNT(DISTINCT bidder), "
                            "COUNT(DISTINCT lower(desc) || unit) FROM "
                            "bid_rows WHERE project=?", (p["id"],)).fetchone()
            out.append(dict(p, rows=n[0], bidders=n[1], items=n[2]))
    return out


def remove_project(pid):
    with pricedb.connect(write=True) as con:
        con.execute("DELETE FROM bid_rows WHERE project=?", (pid,))
        con.execute("DELETE FROM bid_projects WHERE id=?", (pid,))


def rates():
    """Yearly escalation % by trade (yours, then bidtab_core's)."""
    out = dict(core.DEFAULT_RATES)
    try:
        mine = pricedb.meta(RATES_KEY) or {}
        if isinstance(mine, dict):
            out.update({k: float(v) for k, v in mine.items()})
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return out


def set_rates(table):
    pricedb.set_meta(RATES_KEY, {k: float(v) for k, v in table.items()})


def _months(a, b):
    return core.months_between(a, b)


def analyze(to=None, state=None, trade=None, search="", projects_in=None,
            min_bids=1, spread_flag=35.0, use_vocab=True):
    """Items across the library: [{desc, unit, trade, bids, projects,
    bidders, low, median, mean, high, spread, flag, escalated (low, median,
    high), states, first, last}] with each bid escalated from its project's
    bid date to `to` (YYYY-MM, default this month)."""
    to = _month(to) if to else _dt.date.today().strftime("%Y-%m")
    table = rates()
    q = ("SELECT r.*, p.bid_date, p.state, p.name AS pname FROM bid_rows r "
         "JOIN bid_projects p ON p.id = r.project")
    where, args = [], []
    if state:
        where.append("p.state=?")
        args.append(state)
    if trade:
        where.append("r.trade=?")
        args.append(trade)
    if projects_in:
        where.append("r.project IN (%s)" % ",".join("?" * len(projects_in)))
        args += list(projects_in)
    # INCL lines (priced elsewhere in the bid) aren't unit prices
    where.append("COALESCE(r.note, '') = ''")
    if where:
        q += " WHERE " + " AND ".join(where)
    words = str(search or "").lower().split()
    groups = {}
    names = {}
    vmap = {}
    if use_vocab:
        try:
            from . import vocab
            vmap = vocab.canonical_map()
        except Exception:
            vmap = {}
    with pricedb.connect() as con:
        for r in con.execute(q, args):
            hit = vmap.get((_vnorm(r["desc"]), r["unit"])) if vmap else None
            label = hit[1] if hit else r["desc"]
            if words and not all(w in (r["desc"] + " " + label).lower()
                                 for w in words):
                continue
            if hit:
                key = (f"vocab:{hit[0]}", r["unit"])
                names[key] = hit[1]
            else:
                key = (core.normalize_desc(r["desc"]).lower(), r["unit"])
            months = _months(r["bid_date"], to) if r["bid_date"] else 0
            f = core.escalation_factor(r["trade"], months, table, 4.0)
            groups.setdefault(key, []).append((r, r["price"], r["price"] * f))
    out = []
    for (gkey, unit), members in groups.items():
        raw = [m[1] for m in members]
        esc = sorted(m[2] for m in members)
        st = core.stats_of(raw)
        if st.n < min_bids:
            continue
        r0 = members[0][0]
        out.append({
            "desc": names.get((gkey, unit)) or core.normalize_desc(r0["desc"]),
            "unit": unit,
            "wordings": len({core.normalize_desc(m[0]["desc"]).lower()
                             for m in members}),
            "trade": r0["trade"], "bids": st.n,
            "projects": len({m[0]["project"] for m in members}),
            "bidders": len({m[0]["bidder"] for m in members}),
            "low": st.low, "median": st.median, "mean": st.mean,
            "high": st.high, "spread": st.spread_pct,
            "flag": st.n > 1 and st.spread_pct > spread_flag,
            "esc_low": esc[0], "esc_median": statistics.median(esc),
            "esc_high": esc[-1],
            "states": sorted({m[0]["state"] for m in members
                              if m[0]["state"]}),
            "first": min(m[0]["bid_date"] or "" for m in members),
            "last": max(m[0]["bid_date"] or "" for m in members),
            "qty": statistics.median([m[0]["qty"] or 1 for m in members])})
    out.sort(key=lambda i: (i["trade"], i["desc"].lower(), i["unit"]))
    return out


def _vnorm(desc):
    from . import vocab
    return vocab.normalize(desc)


def trades():
    with pricedb.connect() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT trade FROM bid_rows ORDER BY trade")]


def states():
    with pricedb.connect() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT state FROM bid_projects WHERE state<>'' "
            "ORDER BY state")]


def export(items, path, fmt="lib", to=None):
    """Write the analysis as CSV: lib (unit cost library), full (every
    statistic) or roll (trade rollup at the median quantities)."""
    from . import safecell
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = safecell.writer(f)       # item text can't become a formula
        if fmt == "roll":
            w.writerow(["Trade", "Items", "Extended_Base_Median",
                        "Extended_Low", "Extended_Escalated",
                        "Avg_Spread_Pct", "Max_Spread_Pct"])
            by = {}
            for i in items:
                by.setdefault(i["trade"], []).append(i)
            tot = [0, 0.0, 0.0, 0.0]
            for t in sorted(by):
                m = by[t]
                base = sum(i["median"] * i["qty"] for i in m)
                low = sum(i["low"] * i["qty"] for i in m)
                esc = sum(i["esc_median"] * i["qty"] for i in m)
                w.writerow([t, len(m), f"{_c2(base):.2f}", f"{_c2(low):.2f}",
                            f"{_c2(esc):.2f}",
                            f"{statistics.fmean(i['spread'] for i in m):.0f}",
                            f"{max(i['spread'] for i in m):.0f}"])
                tot = [tot[0] + len(m), tot[1] + base, tot[2] + low,
                       tot[3] + esc]
            w.writerow(["TOTAL", tot[0], f"{_c2(tot[1]):.2f}", f"{_c2(tot[2]):.2f}",
                        f"{_c2(tot[3]):.2f}", "", ""])
        elif fmt == "lib":
            w.writerow(["Trade", "Item_Description", "Unit", "Unit_Cost",
                        "Bids", "Low", "High", "Escalated_Unit_Cost",
                        "Escalated_To"])
            for i in items:
                w.writerow([i["trade"], i["desc"], i["unit"],
                            f"{_c2(i['median']):.2f}", i["bids"],
                            f"{_c2(i['low']):.2f}", f"{_c2(i['high']):.2f}",
                            f"{_c2(i['esc_median']):.2f}", to or ""])
        else:
            w.writerow(["Trade", "Item_Description", "Unit", "Bids",
                        "Projects", "Bidders", "Low", "Median", "Mean",
                        "High", "Spread_Pct", "Escalated_Low",
                        "Escalated_Median", "Escalated_High", "States",
                        "First_Bid", "Last_Bid", "Flag"])
            for i in items:
                w.writerow([i["trade"], i["desc"], i["unit"], i["bids"],
                            i["projects"], i["bidders"], f"{_c2(i['low']):.2f}",
                            f"{_c2(i['median']):.2f}", f"{_c2(i['mean']):.2f}",
                            f"{_c2(i['high']):.2f}", f"{i['spread']:.0f}",
                            f"{_c2(i['esc_low']):.2f}", f"{_c2(i['esc_median']):.2f}",
                            f"{_c2(i['esc_high']):.2f}", " ".join(i["states"]),
                            i["first"], i["last"],
                            "REVIEW" if i["flag"] else ""])
    return path


# ---- using it --------------------------------------------------------------------

_MEASURE = {"LF": ("length", "Length"), "SF": ("area", "Area"),
            "SY": ("area", "(Area/9)"), "CY": ("volume", "(Volume/27)"),
            "CF": ("volume", "Volume"),
            "GAL": ("volume", "(Volume*7.48052)")}


def to_assembly(item, which="esc_median", to=None):
    """A unit-price assembly from a bid tab item (one part, the installed
    price incl. contractor O&P)."""
    from . import csi
    measure, expr = _MEASURE.get(item["unit"], ("count", "Count"))
    code = item["trade"].split()[0]
    div = code.split("-")[0] if code[:2].isdigit() else ""
    price = _c2(float(item[which]))
    return {
        "name": f"{item['desc']} (bid tabs)", "measure": measure,
        "unit": item["unit"], "trade": item["trade"],
        "csi": csi.parse_code(div) if div else "", "props": {},
        "source": "bid tabs",
        "notes": (f"Median of {item['bids']} bid(s) from {item['projects']} "
                  f"project(s), {item['first']} to {item['last']}"
                  + (f" ({', '.join(item['states'])})" if item["states"]
                     else "") + f"; low ${_c2(item['esc_low']):,.2f}, high "
                  f"${_c2(item['esc_high']):,.2f} escalated to {to or 'today'}. "
                  "Installed price including the bidders' overhead and "
                  "profit."),
        "parts": [{"name": "Installed (bid tab median)",
                   "unit": item["unit"].lower(), "qty": expr, "cost": price,
                   "labor": 0.0, "type": "Other"}]}


def add_to_library(items, to=None):
    from . import assemblies
    made = [to_assembly(i, to=to) for i in items]
    assemblies.save_many_to_library(made)
    return [a["name"] for a in made]


def compare(doc, to=None, cutoff=0.55, items=None):
    """This job's estimate (cost per unit by assembly) next to the closest
    bid tab item with the same unit: [{assembly, unit, quantity, ours,
    bid item, bid median, bids, ratio}]."""
    from . import assemblies
    rows, _totals, _ = assemblies.rollup(doc)
    items = items if items is not None else analyze(to=to)
    by_unit = {}
    for i in items:
        by_unit.setdefault(i["unit"], []).append(i)
    unit_map = {"ft": "LF", "lf": "LF", "sq ft": "SF", "sf": "SF",
                "sy": "SY", "sq yd": "SY", "cu yd": "CY", "cy": "CY",
                "ea": "EA", "": "EA"}
    out = []
    for r in rows:
        u = unit_map.get(str(r.get("unit") or "").lower(),
                         str(r.get("unit") or "").upper())
        if r["measure"] == "count":
            u = "EA"
        cands = by_unit.get(u) or []
        if not cands or not r["quantity"]:
            continue
        names = [c["desc"].lower() for c in cands]
        clean = re.sub(r"\s*\((rsmeans|bid tabs)[^)]*\)", "",
                       r["name"]).lower()
        hit = difflib.get_close_matches(clean, names, 1, cutoff)
        if not hit:
            continue
        c = cands[names.index(hit[0])]
        ours = r["total"] / r["quantity"]
        out.append({"assembly": r["name"], "unit": u,
                    "quantity": r["quantity"], "ours": ours,
                    "bid_item": c["desc"], "bid_median": c["esc_median"],
                    "bid_low": c["esc_low"], "bid_high": c["esc_high"],
                    "bids": c["bids"],
                    "ratio": ours / c["esc_median"] if c["esc_median"]
                    else 0})
    return out
