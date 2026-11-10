"""Trench volumes by depth band, structure counts, cut/fill and a HeavyBid
import file (v22).

What's already there: civiltakeoff reads pipe LF by size and material,
structures (MH, CB, CO...) with rim, invert and depth, and depth bands.
Its catalog trench assemblies price excavation, bedding, backfill and spoil
with vertical walls (trench box). tradetakeoff.cut_fill gives cut and fill
CY. heavy.py is a HeavyBid-*style* estimator, but nothing exported to
HeavyBid.

This adds:
* section(D, H, soil): per-foot trench quantities (SF of section) for a
  trench box (same formulas as the catalog assembly A-33-GRAVSEWER) or
  OSHA sloped walls - soil A 0.75H:1V, B 1H:1V, C 1.5H:1V - when the trench
  is deeper than 5 ft.
* trench_volumes(result): CY of excavation, bedding, initial and final
  backfill and haul-off, per pipe and depth band (existing pipe left out;
  runs with no depth use DEFAULT_DEPTH and are marked "assumed").
* structure_counts(result): new structures by kind and depth band.
* heavybid_csv(path, result, cut_fill=...): biditems (pipe by band,
  structures by band, earthwork cut/fill) with activities and quantities,
  one row per activity.

HeavyBid's import layout is UNVERIFIED (no HCSS spec available here). The
columns are the generic biditem/activity fields HeavyBid's Excel import
maps by name. Check them against a HeavyBid import template before use.
"""
import os

from . import safecell
from .civiltakeoff import band_of, band_name
from .dmoney import half_up as _hu

DEFAULT_DEPTH = 8.0
SLOPES = {"box": 0.0, "A": 0.75, "B": 1.0, "C": 1.5}
BOTTOM_EXTRA_FT = 2.0          # B in the catalog: bottom width = D/12 + B
SWELL = 1.25


def section(d_in, h_ft, soil="box", extra=BOTTOM_EXTRA_FT):
    """Cross-section areas (SF) per foot of trench."""
    d = float(d_in) / 12.0
    h = float(h_ft)
    w = d + extra
    depth = h + 0.5                                  # 6 in below invert
    slope = SLOPES.get(str(soil).upper() if soil != "box" else "box", 0.0) \
        if h > 5 else 0.0
    side = slope * depth ** 2                        # two triangles
    exc = w * depth + side
    bedding = w * (0.5 + d / 2)
    initial = w * (d / 2 + 1) - 0.3927 * d ** 2
    final = w * max(0.0, h - d - 1) + side
    spoil = w * (d + 1.5) * SWELL
    return {"width": w, "slope": slope, "excavation": exc,
            "bedding": bedding, "initial": initial, "final": final,
            "spoil": spoil}


def trench_volumes(result, soil="box", extra=BOTTOM_EXTRA_FT):
    rows = []
    for p in result.get("pipes") or []:
        if p.get("existing"):
            continue
        groups = {}
        for r in p.get("runs") or []:
            groups.setdefault(band_of(r.get("depth")), []).append(r)
        order = sorted(groups, key=lambda b: (b is None, b or (0, 0)))
        for b in order:
            runs = groups[b]
            length = sum(float(r["length"]) for r in runs)
            known = [r for r in runs if r.get("depth") is not None]
            depth = (sum(r["length"] * r["depth"] for r in known) /
                     max(1e-9, sum(r["length"] for r in known))) \
                if known else DEFAULT_DEPTH
            s = section(p.get("size") or 8, depth, soil, extra)
            row = {"pipe": p["name"], "system": p.get("system", ""),
                   "size": p.get("size"), "band": band_name(b),
                   "length": _hu(length, 2), "depth": _hu(depth, 2),
                   "assumed": not known, "soil": soil}
            for k in ("excavation", "bedding", "initial", "final", "spoil"):
                row[f"{k}_cy"] = _hu(length * s[k] / 27.0, 2)
            rows.append(row)
    return rows


def totals(rows):
    out = {"length": _hu(sum(r["length"] for r in rows), 2)}
    for k in ("excavation", "bedding", "initial", "final", "spoil"):
        out[f"{k}_cy"] = _hu(sum(r[f"{k}_cy"] for r in rows), 2)
    return out


def structure_counts(result):
    from .civiltakeoff import structure_summary
    rows = []
    for (kind, b), rec in structure_summary(result.get("structures") or []
                                            ).items():
        rows.append({"kind": kind, "band": band_name(b),
                     "count": rec["count"], "avg_depth": rec["avg_depth"],
                     "ids": rec["ids"]})
    rows.sort(key=lambda r: (r["kind"], r["band"]))
    return rows


def report(doc, soil="box", **kw):
    from . import civiltakeoff
    res = civiltakeoff.takeoff(doc, **kw)
    tr = trench_volumes(res, soil)
    return {"trench": tr, "totals": totals(tr),
            "structures": structure_counts(res), "result": res}


HEAD = ["Biditem", "Biditem Description", "Biditem Quantity",
        "Biditem Units", "Activity", "Activity Description",
        "Activity Quantity", "Activity Units", "Notes"]
_ACTS = [("excavation_cy", "Trench excavation"), ("bedding_cy", "Bedding"),
         ("initial_cy", "Initial backfill"), ("final_cy", "Final backfill"),
         ("spoil_cy", "Haul off spoil")]


def heavybid_csv(path, result, soil="box", cut_fill=None, job="", step=10):
    rows, n = [], 0

    def item(desc, qty, unit, acts, note=""):
        nonlocal n
        n += step
        for k, (adesc, aqty, aunit) in enumerate(acts, 1):
            rows.append([str(n), desc, f"{qty}", unit, f"{n}.{k:02d}",
                         adesc, f"{aqty}", aunit, note])

    for r in trench_volumes(result, soil):
        acts = [("Pipe, lay and join", r["length"], "LF")]
        acts += [(lab, r[k], "CY") for k, lab in _ACTS]
        item(f"{r['pipe']}, {r['band']}", r["length"], "LF", acts,
             f"avg depth {r['depth']} ft" + (" (assumed)" if r["assumed"]
                                             else "") + f"; soil {soil}")
    for s in structure_counts(result):
        item(f"{s['kind'].title()}, {s['band']}", s["count"], "EA",
             [(f"Set {s['kind']}", s["count"], "EA")],
             ", ".join(s["ids"]))
    if cut_fill:
        for k in ("cut", "fill"):
            if cut_fill.get(k):
                v = _hu(float(cut_fill[k]), 1)
                item(f"Earthwork - {k}", v, "CY",
                     [(f"Earthwork {k}", v, "CY")])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f)
        w.writerow(HEAD)
        w.writerows(rows)
    return path


def _num(v):
    """Clean number for Excel: no $, commas or spaces; int when whole."""
    if isinstance(v, str):
        v = v.replace("$", "").replace(",", "").strip() or 0
    v = _hu(float(v), 2)
    return int(v) if v == int(v) else v


def _clean(s):
    return " ".join(str(s or "").split())


BID_HEAD = ["Biditem Code", "Description", "Unit", "Quantity", "Bid Quantity",
            "Type", "Client Number", "Sort Code", "Summary Sort 1",
            "Parent Biditem", "Taxable", "WBS Code", "Bid Notes"]


def _yn(v):
    if isinstance(v, str):
        return "Y" if v.strip().upper() in ("Y", "YES", "TRUE", "1") else "N"
    return "Y" if v else "N"


def biditem_record(r):
    """One HeavyBid biditem row (list, BID_HEAD order). r keys: code, desc,
    unit, qty, bid_qty (= qty), type (D), client, sort (= code), summary1,
    parent, taxable, wbs, notes. Codes stay text (leading zeros kept)."""
    code = _clean(r.get("code"))
    qty = _num(r.get("qty") or 0)
    bq = r.get("bid_qty")
    return [code, _clean(r.get("desc")), _clean(r.get("unit")), qty,
            qty if bq in (None, "") else _num(bq),
            _clean(r.get("type")) or "D", _clean(r.get("client")),
            _clean(r.get("sort")) or code, _clean(r.get("summary1")),
            _clean(r.get("parent")), _yn(r.get("taxable")),
            _clean(r.get("wbs")), _clean(r.get("notes"))]


def _plain(v):
    if isinstance(v, float):
        return repr(v)
    return str(v)


def write_biditems_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f, lineterminator="\r\n")
        w.writerow(BID_HEAD)
        for r in rows:
            w.writerow([_plain(v) for v in biditem_record(r)])
    return path


def write_biditems_xlsx(path, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Biditems"
    ws.append(BID_HEAD)
    for r in rows:
        safecell.append_row(ws, [v if v != "" else None
                                 for v in biditem_record(r)])
    text_cols = [i for i, h in enumerate(BID_HEAD, 1)
                 if h not in ("Quantity", "Bid Quantity")]
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if c.column in text_cols:
                c.number_format = "@"
    for i, w in enumerate((12, 40, 7, 11, 11, 5, 13, 10, 13, 13, 7, 10, 30)):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
    wb.save(path)
    return path


def takeoff_biditems(result, soil="box", cut_fill=None, step=10, taxable=None):
    """Takeoff -> biditem dicts (codes 00010, 00020...). taxable: set of
    biditem kinds ("pipe", "structure", "earthwork") marked Y."""
    tax = set(taxable or ())
    out = []
    for b, _ in heavybid_rows(result, soil, cut_fill, step):
        kind = ("earthwork" if b["desc"].startswith("Earthwork") else
                "structure" if b["unit"] == "EA" else "pipe")
        out.append({"code": b["no"].zfill(5), "desc": b["desc"],
                    "unit": b["unit"], "qty": b["qty"],
                    "taxable": kind in tax, "notes": b["note"]})
    return out


def heavybid_csv2(path, result, soil="box", cut_fill=None, **kw):
    return write_biditems_csv(path, takeoff_biditems(result, soil, cut_fill, **kw))
# Field names follow the HeavyBid API DTOs (developer.hcssapps.com,
# ActivityIntegrationDto / ResourceIntegrationDto: biditemCode, activityCode,
# resourceCode, description, quantity, units, crew, productionRate, unitPrice,
# typeCost, notes). The Excel-import dialog labels are UNVERIFIED.
ACT_HEAD = ["Biditem Code", "Activity Code", "Description", "Quantity",
            "Units", "Crew", "Production Rate", "Notes"]
RES_HEAD = ["Biditem Code", "Activity Code", "Resource Code", "Description",
            "Quantity", "Units", "Unit Price", "Type Cost"]


def heavybid_rows(result, soil="box", cut_fill=None, step=10):
    """[(biditem dict, [activity dicts])] shared by the CSV/XLSX exports."""
    out, n = [], 0

    def item(desc, qty, unit, acts, note=""):
        nonlocal n
        n += step
        out.append(({"no": str(n), "desc": desc, "qty": qty, "unit": unit,
                     "note": note},
                    [{"no": f"{n}.{k:02d}", "desc": a, "qty": q, "unit": u}
                     for k, (a, q, u) in enumerate(acts, 1)]))

    for r in trench_volumes(result, soil):
        acts = [("Pipe, lay and join", r["length"], "LF")]
        acts += [(lab, r[k], "CY") for k, lab in _ACTS]
        item(f"{r['pipe']}, {r['band']}", r["length"], "LF", acts,
             f"avg depth {r['depth']} ft" + (" (assumed)" if r["assumed"]
                                             else "") + f"; soil {soil}")
    for s in structure_counts(result):
        item(f"{s['kind'].title()}, {s['band']}", s["count"], "EA",
             [(f"Set {s['kind']}", s["count"], "EA")], ", ".join(s["ids"]))
    for k in ("cut", "fill"):
        if cut_fill and cut_fill.get(k):
            v = _num(cut_fill[k])
            item(f"Earthwork - {k}", v, "CY", [(f"Earthwork {k}", v, "CY")])
    return out


def _write(path, head, rows, num_cols, fmt):
    rows = [[_num(v) if i in num_cols and v not in (None, "") else
             ("" if v is None else _clean(v)) for i, v in enumerate(r)]
            for r in rows]
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = safecell.writer(f, lineterminator="\r\n")
            w.writerow(head)
            for r in rows:
                w.writerow([_plain(v) for v in r])
        return path
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = os.path.splitext(os.path.basename(path))[0][:31]
    ws.append(head)
    for r in rows:
        safecell.append_row(ws, [None if v == "" else v for v in r])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if c.column - 1 not in num_cols:
                c.number_format = "@"
    wb.save(path)
    return path


def takeoff_activities(result, soil="box", cut_fill=None, step=10):
    """(activities, resources) dicts sharing codes with takeoff_biditems:
    activity code = "<biditem code>.<nn>", e.g. 00010.01."""
    acts, res = [], []
    for b, al in heavybid_rows(result, soil, cut_fill, step):
        bc = b["no"].zfill(5)
        for k, a in enumerate(al, 1):
            ac = f"{bc}.{k:02d}"
            acts.append({"biditem": bc, "code": ac, "desc": a["desc"],
                         "qty": a["qty"], "unit": a["unit"]})
            if a["desc"].startswith("Pipe, lay"):
                res.append({"biditem": bc, "activity": ac,
                            "code": "PIPE", "desc": b["desc"].split(",")[0],
                            "qty": a["qty"], "unit": "LF"})
            elif a["desc"].startswith("Set "):
                res.append({"biditem": bc, "activity": ac,
                            "code": "STRUCT", "desc": b["desc"],
                            "qty": a["qty"], "unit": "EA"})
    return acts, res


def check_codes(biditems, activities, resources):
    """Pre-export orphan check (import order: biditems -> activities ->
    resources)."""
    bc = {_clean(b.get("code")) for b in biditems}
    ac = {(_clean(a.get("biditem")), _clean(a.get("code")))
          for a in activities}
    used = {b for b, _ in ac}
    out = {"activities_without_biditem": sorted(
               c for b, c in ac if b not in bc),
           "resources_without_activity": [
               f"{_clean(r.get('code'))} ({_clean(r.get('activity'))})"
               for r in resources
               if (_clean(r.get("biditem")), _clean(r.get("activity")))
               not in ac],
           "biditems_without_activities": sorted(bc - used)}
    out["ok"] = not any(out.values())
    return out


def heavybid_export(folder, result, soil="box", cut_fill=None, fmt="xlsx",
                    include=("biditems", "activities", "resources"),
                    extra_activities=(), extra_resources=(), force=False,
                    taxable=None, step=10):
    """Write biditems / activities / resources (one single-sheet file each,
    .xlsx or .csv) after the orphan check. Raises ValueError on orphans
    unless force=True. Returns {kind: path, "check": {...}}."""
    bids = takeoff_biditems(result, soil, cut_fill, step, taxable)
    acts, res = takeoff_activities(result, soil, cut_fill, step)
    acts += list(extra_activities)
    res += list(extra_resources)
    chk = check_codes(bids, acts if "activities" in include else
                      [{"biditem": b["code"], "code": ""} for b in bids],
                      res if "resources" in include else [])
    if not chk["ok"] and not force:
        raise ValueError(f"HeavyBid export: orphan codes {chk}")
    os.makedirs(folder, exist_ok=True)
    ext = "csv" if fmt == "csv" else "xlsx"
    out = {"check": chk}
    if "biditems" in include:
        p = os.path.join(folder, f"biditems.{ext}")
        out["biditems"] = (write_biditems_csv if ext == "csv" else
                           write_biditems_xlsx)(p, bids)
    if "activities" in include:
        out["activities"] = _write(
            os.path.join(folder, f"activities.{ext}"), ACT_HEAD,
            [[a.get("biditem"), a.get("code"), a.get("desc"), a.get("qty", 0),
              a.get("unit"), a.get("crew"), a.get("rate"), a.get("notes")]
             for a in acts], {3, 6}, ext)
    if "resources" in include:
        out["resources"] = _write(
            os.path.join(folder, f"resources.{ext}"), RES_HEAD,
            [[r.get("biditem"), r.get("activity"), r.get("code"),
              r.get("desc"), r.get("qty", 0), r.get("unit"),
              r.get("price"), r.get("type")] for r in res], {4, 6}, ext)
    return out


def heavybid_xlsx(path, result, soil="box", cut_fill=None, level="biditems",
                  step=10, taxable=None):
    """Single-sheet .xlsx for HeavyBid Exchange > Excel import, first row =
    column titles. level="biditems" (Jon's header) or "activities"."""
    if level == "biditems":
        return write_biditems_xlsx(path, takeoff_biditems(
            result, soil, cut_fill, step, taxable))
    acts, _ = takeoff_activities(result, soil, cut_fill, step)
    return _write(path, ACT_HEAD,
                  [[a["biditem"], a["code"], a["desc"], a["qty"], a["unit"],
                    "", "", ""] for a in acts], {3, 6}, "xlsx")
