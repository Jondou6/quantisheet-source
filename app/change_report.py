"""Revision change report (v30): what the takeoff did between two revisions
and what it costs.

Works on the real takeoff of both PDFs (annotate.takeoff_items), with pages
paired by sheet number (overlay.pair_pages, the same pairing the overlay
compare and revdelta's revision snapshots rely on). Each item is:

    UNCHANGED  same group / type / unit / quantity at the same place
    MOVED      same group / type / unit / quantity on the same sheet, but
               somewhere else (beyond `tol` points) - listed on its own and
               NOT counted as a removal plus an addition
    ADDED / REMOVED   everything left over

Orphans are listed separately and never priced as changes: takeoff on a
sheet that is gone from the new revision, and takeoff groups with no
assembly bound (assembly_codes.bind), which can't be priced.

Net direct change = priced(added) - priced(removed), using each revision's
own bindings. Net change with markups = cost_rollup.summary(new) total -
summary(old) total with the same cascade and tax.
"""
from decimal import Decimal

from . import annotate, assembly_codes as ac, cost_rollup
from .dmoney import c2 as _c2

TOL = 6.0          # points
Z = Decimal("0.00")


def _center(r):
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def _qty(it):
    v = (it.get("multiplier") or 1) if it["type"] == "count" else \
        (it.get("value") or 0)
    return ac.dec(v, Decimal(0))


def _key(it):
    return (it.get("group") or it["type"].title(), it["type"],
            it.get("unit") or "")


def _row(it, page_new=None, sheet=""):
    g, t, u = _key(it)
    return {"group": g, "type": t, "unit": u, "qty": _qty(it),
            "page": it["page"], "page_new": page_new, "sheet": sheet,
            "rect": list(it.get("rect") or [0, 0, 0, 0])}


def _pairs(old, new):
    from . import overlay
    return overlay.pair_pages(old, new)


def compare(old, new, library, cascade=None, tax_pct=0, tol=TOL, pair=None,
            qty_tol=Decimal("0.005")):
    pairs = (pair or _pairs)(old, new)
    o2n = {o: (n, s) for o, n, s in pairs if o is not None}
    oi, ni = annotate.takeoff_items(old), annotate.takeoff_items(new)
    ob, nb = ac.read_job(old)["bindings"], ac.read_job(new)["bindings"]
    res = {"unchanged": [], "moved": [], "added": [], "removed": [],
           "orphans": []}
    # groups with no assembly bound: one line each (not one per item), and
    # their changes are still listed below - just not priced
    groups = {}
    for docname, items, binds in (("old", oi, ob), ("new", ni, nb)):
        for it in items:
            k = _key(it)
            if ac.key_of(*k) in binds:
                continue
            g = groups.setdefault(k, dict(_row(it), qty=Decimal(0),
                                          why="no assembly bound"))
            if docname == "new":
                g["qty"] += _qty(it)
    res["orphans"].extend(groups.values())
    left_new = list(ni)
    cands = []
    for it in oi:
        n, sheet = o2n.get(it["page"], (None, ""))
        if n is None:
            res["orphans"].append(dict(_row(it, None, sheet),
                                       why="sheet removed in new revision"))
            continue
        cands.append((it, n, sheet))

    def same(a, b):
        qa, qb = _qty(a), _qty(b)
        return _key(a) == _key(b) and abs(qa - qb) <= max(qa, qb) * qty_tol

    def near(a, b):
        (ax, ay), (bx, by) = _center(a["rect"]), _center(b["rect"])
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 <= tol

    pending = []
    for it, n, sheet in cands:          # pass 1: same place
        m = next((b for b in left_new if b["page"] == n and same(it, b)
                  and near(it, b)), None)
        if m is not None:
            left_new.remove(m)
            res["unchanged"].append(_row(it, n, sheet))
        else:
            pending.append((it, n, sheet))
    for it, n, sheet in pending:        # pass 2: same sheet, new place
        m = next((b for b in left_new if b["page"] == n and same(it, b)),
                 None)
        if m is not None:
            left_new.remove(m)
            res["moved"].append(dict(_row(it, n, sheet),
                                     new_rect=list(m["rect"])))
        else:
            res["removed"].append(_row(it, n, sheet))
    res["added"] = [_row(b, b["page"]) for b in left_new]

    def price(rows, binds):
        tot = Z
        for r in rows:
            b = binds.get(ac.key_of(r["group"], r["type"], r["unit"]))
            a = library.get(b["code"]) if b else None
            if a is None:
                r["cost"] = None
                continue
            r["cost"] = ac.extend(a, r["qty"], b.get("waste") or 0)["total"]
            tot += r["cost"]
        return tot
    add = price(res["added"], nb)
    rem = price(res["removed"], ob)
    res["net_direct"] = add - rem
    lo, _ = ac.priced_lines(old, library)
    ln, _ = ac.priced_lines(new, library)
    so = cost_rollup.summary(lo, cascade, tax_pct)
    sn = cost_rollup.summary(ln, cascade, tax_pct)
    res["old_total"], res["new_total"] = so["total"], sn["total"]
    res["net_with_markups"] = sn["total"] - so["total"]
    return res


def _line(r):
    if "cost" in r and r["cost"] is None:
        c = "  (not priced - no assembly bound)"
    else:
        c = "" if r.get("cost") is None else f"  {_c2(r['cost']):.2f}"
    s = f" {r['sheet']}" if r.get("sheet") else f" p{r['page'] + 1}"
    return f"  {r['group']} ({r['type']}) {r['qty']} {r['unit']}{s}{c}"


def text(res):
    out = []
    for k in ("added", "removed", "moved"):
        out.append(f"{k.upper()} ({len(res[k])})")
        out += [_line(r) for r in res[k]]
    out.append(f"ORPHANED ({len(res['orphans'])})")
    out += [_line(r) + f"  - {r['why']}" for r in res["orphans"]]
    out.append(f"Net direct change: {_c2(res['net_direct']):.2f}")
    out.append(f"Net change with markups: {_c2(res['net_with_markups']):.2f}")
    return "\n".join(out)
