"""Revision-aware takeoff: what each drawing revision did to the bid.

* record(): when a revision comes in (Slip Sheet, or by hand), the bid as
  it stood is saved with the revision: total, every assembly's quantity
  and price, and the takeoffs that sit on changed areas with the money
  they carry ("value at risk").
* log(): every revision with the bid before it and after it (the next
  revision's "before", or the bid now for the latest), the change, and
  how many flagged takeoffs are still waiting to be re-measured.
* changes(): assembly by assembly, what moved between two snapshots.
* carry_ops(): takeoff from an older set copied onto a newer set (the
  newer file stays the master), lined up sheet by sheet with the overlay
  alignment, scales and viewports adjusted for any change in plot size;
  takeoffs on changed areas come across flagged for re-measure.

Saved inside the PDF (quantisheet_revisions.json), so it travels with the
job.
"""
import datetime
import json
import logging

import fitz

from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_revisions.json"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def read(doc):
    try:
        if FILE in doc.embfile_names():
            data = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(data, dict):
                data.setdefault("revisions", [])
                return data
    except Exception:
        log.warning("could not read revision log", exc_info=True)
    return {"revisions": []}


def write(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet revision log")


# ---- snapshots of the bid ------------------------------------------------------

def snapshot(doc):
    """The bid as it stands: {total, direct, items: {assembly: {trade,
    qty, unit, price}}, quantities: {group|unit: qty}, measurements}."""
    from . import annotate, proposal
    items, total, direct = {}, 0.0, 0.0
    try:
        data = dict(proposal.read(doc), detail="assembly")
        p = proposal.price(doc, data)
        total = float(p["total"])
        direct = float(p.get("direct") or p.get("cost") or 0)
        for ln in p["lines"]:
            items[ln["name"]] = {"trade": ln.get("trade") or "",
                                 "qty": float(ln.get("qty") or 0),
                                 "unit": ln.get("unit") or "",
                                 "price": float(ln["price"])}
    except Exception:
        log.warning("could not price the estimate", exc_info=True)
    qty = {}
    n = 0
    for it in annotate.takeoff_items(doc):
        k = f"{it['group'] or it['type'].title()}|{it['unit']}"
        qty[k] = round(qty.get(k, 0.0) + float(it["value"]), 4)
        n += 1
    return {"when": _now(), "total": round(total, 2),
            "direct": round(direct, 2), "items": items, "quantities": qty,
            "measurements": n}


def flagged_refs(doc):
    """Refs of takeoffs still marked "Check - drawing revised"."""
    from . import annotate
    out, seen = [], set()
    for page in doc:
        for a in annotate.iter_annots(page) or []:
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue
            if annotate.status_of(doc, a) != annotate.REVISED:
                continue
            r = annotate.ref(a)
            k = _key(r)
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def value_of(doc, refs):
    """Bid price carried by these takeoffs (0 when none are priced)."""
    if not refs:
        return 0.0
    try:
        from . import money, proposal
        data = proposal.read(doc)
        oh = float(data.get("overhead") or 0)
        pr = float(data.get("profit") or 0)
        markup = ((1 + oh / 100) * (1 + pr / 100) - 1) * 100
        _cost, price, _problems = money.price_markups(doc, list(refs), markup)
        return round(float(price), 2)
    except Exception:
        log.warning("could not price flagged takeoffs", exc_info=True)
        return 0.0


def record(doc, label, sheets=(), flagged=None, before=None, note=""):
    """Add a revision to the log. `before` = snapshot taken before the
    drawings changed (taken now when not given); `flagged` = refs of the
    takeoffs the revision flagged. Returns the entry."""
    data = read(doc)
    refs = list(flagged) if flagged is not None else flagged_refs(doc)
    entry = {"no": len(data["revisions"]) + 1, "label": str(label)[:80],
             "date": _now(), "author": _author(), "note": note,
             "sheets": list(sheets), "flagged": len(refs),
             "flagged_refs": refs[:2000],
             "at_risk": value_of(doc, refs),
             "before": before or snapshot(doc)}
    data["revisions"].append(entry)
    write(doc, data)
    return entry


def _author():
    try:
        from . import settings
        return settings.author()
    except Exception:
        return ""


def log_rows(doc, now=None):
    """[{no, label, date, sheets, flagged, open, at_risk, before, after,
    change, change_pct}] - `after` is the next revision's before, or the
    bid now for the latest."""
    revs = read(doc)["revisions"]
    if not revs:
        return []
    now = now or snapshot(doc)
    still = set(map(_key, flagged_refs(doc)))
    out = []
    for i, r in enumerate(revs):
        after = revs[i + 1]["before"] if i + 1 < len(revs) else now
        b, a = r["before"]["total"], after["total"]
        kept = r.get("flagged_refs") or []
        mine = {_key(x) for x in kept}
        n_open = len(mine & still)
        if r.get("flagged", 0) > len(kept):
            # only the first 2000 refs are stored: don't report fewer open
            # than are still flagged (3b M9)
            n_open = max(n_open, min(r.get("flagged", 0), len(still)))
        out.append({"no": r["no"], "label": r["label"], "date": r["date"],
                    "sheets": r.get("sheets") or [],
                    "flagged": r.get("flagged", 0),
                    "open": n_open,
                    "at_risk": r.get("at_risk", 0.0), "before": b,
                    "after": a, "change": round(a - b, 2),
                    "change_pct": (a - b) / b * 100 if b else 0.0,
                    "latest": i + 1 == len(revs)})
    return out


def _key(ref):
    return tuple(sorted(ref.items())) if isinstance(ref, dict) else ref


def changes(before, after):
    """Assembly by assembly: [{name, trade, unit, qty_before, qty_after,
    before, after, change}] for those that moved, biggest change first,
    plus the quantity groups that moved."""
    rows = []
    names = set(before["items"]) | set(after["items"])
    for n in names:
        b = before["items"].get(n) or {}
        a = after["items"].get(n) or {}
        pb, pa = b.get("price", 0.0), a.get("price", 0.0)
        qb, qa = b.get("qty", 0.0), a.get("qty", 0.0)
        if abs(pa - pb) < 0.005 and abs(qa - qb) < 1e-6:
            continue
        rows.append({"name": n, "trade": a.get("trade") or b.get("trade"),
                     "unit": a.get("unit") or b.get("unit"),
                     "qty_before": qb, "qty_after": qa, "before": pb,
                     "after": pa, "change": round(pa - pb, 2)})
    rows.sort(key=lambda r: -abs(r["change"]))
    qty = []
    for k in set(before["quantities"]) | set(after["quantities"]):
        qb = before["quantities"].get(k, 0.0)
        qa = after["quantities"].get(k, 0.0)
        if abs(qa - qb) > 1e-6:
            g, u = k.rsplit("|", 1) if "|" in k else (k, "")  # 3b M8
            qty.append({"group": g, "unit": u, "before": qb, "after": qa,
                        "change": round(qa - qb, 4)})
    qty.sort(key=lambda r: r["group"])
    return {"items": rows, "quantities": qty}


def revision_changes(doc, no, now=None, revs=None):
    """`now` (the bid as it stands) and `revs` can be passed in when
    working through many revisions, so the bid is priced once (3b M10)."""
    revs = revs if revs is not None else read(doc)["revisions"]
    i = next(k for k, r in enumerate(revs) if r["no"] == no)
    after = revs[i + 1]["before"] if i + 1 < len(revs) else \
        (now or snapshot(doc))
    return changes(revs[i]["before"], after)


def export_xlsx(doc, path):
    from . import acrobat
    now = snapshot(doc)                  # priced once for every sheet
    revs = read(doc)["revisions"]
    rows = log_rows(doc, now)
    summary = [["No", "Revision", "Date", "Sheets changed", "Takeoffs flagged",
                "Still to check", "Value at risk ($)", "Bid before ($)",
                "Bid after ($)", "Change ($)", "Change (%)"]]
    for r in rows:
        summary.append([r["no"], r["label"], r["date"][:10], len(r["sheets"]),
                        r["flagged"], r["open"], round(r["at_risk"], 2),
                        round(r["before"], 2), round(r["after"], 2),
                        round(r["change"], 2), round(r["change_pct"], 2)])
    sheets = [("Revisions", summary)]
    for r in rows:
        ch = revision_changes(doc, r["no"], now, revs)
        det = [["Assembly", "Trade", "Unit", "Qty before", "Qty after",
                "Before ($)", "After ($)", "Change ($)"]]
        for it in ch["items"]:
            det.append([it["name"], it["trade"] or "", it["unit"] or "",
                        round(it["qty_before"], 3), round(it["qty_after"], 3),
                        round(it["before"], 2), round(it["after"], 2),
                        round(it["change"], 2)])
        sheets.append((f"Rev {r['no']} detail", det))
    acrobat.write_xlsx(path, sheets)
    return path


# ---- carrying takeoff onto a newer set ------------------------------------------

def _map_geom(d, m):
    from . import overlay
    out = dict(d)
    out["rect"] = list(overlay.map_rect(d["rect"], m))
    v = d.get("vertices")
    if v:
        if v and isinstance(v[0][0], (list, tuple)):        # ink strokes
            out["vertices"] = [[list(overlay.map_point(p, m)) for p in s]
                               for s in v]
        else:
            out["vertices"] = [list(overlay.map_point(p, m)) for p in v]
    if out.get("fontsize"):
        out["fontsize"] = d["fontsize"] * overlay.affine(m)[0] if \
            abs(overlay.affine(m)[0] - 1) > 0.02 else d["fontsize"]
    return out


def copy_job_data(old, new):
    """The older set's job data (assemblies, cost book, prices, proposal,
    revision log, logs) onto the newer set, where it has none of its own.
    Page-indexed data (scales) is carried by carry_ops instead."""
    from . import jobdata
    from . import prebid
    # the new set's sheets must be reviewed (and the bid locked) again
    data = {n: raw for n, raw in jobdata.snapshot(old).items()
            if n not in (jobdata.SCALE_FILE, prebid.FILE)}
    jobdata.restore(new, data, overwrite=False)
    if FILE in data:                       # the log always comes across
        jobdata.restore(new, {FILE: data[FILE]}, overwrite=True)
    return sorted(data)


def carry_ops(old, new, results, flag=True, layer=None):
    """Marks for `new` that copy every markup and takeoff of `old` across,
    sheet by sheet (results from overlay.compare(old, new)), plus the
    sheet scales and viewports. Takeoffs on changed areas get the status
    "Check - drawing revised". Returns (marks, summary)."""
    from . import annotate, overlay
    marks = []
    scales = annotate.read_scales(old)
    vports = annotate.read_viewports(old)
    carried = flagged = 0
    for r in results:
        i, j, m = r["old"], r["new"], r["align"]
        if i is None or j is None:
            continue
        s = overlay.affine(m)
        s = (s[0] ** 2 + s[1] ** 2) ** 0.5 or 1.0
        sc = scales.get(i)
        if sc:
            marks.append((j, "set_scale", {"ppu": sc["ppu"] * s,
                                          "unit": sc.get("unit", "ft"),
                                          "name": sc.get("name", "")}))
        for vp in vports.get(i, []):
            marks.append((j, "set_scale", {"viewport": {
                "name": vp.get("name"), "unit": vp.get("unit", "ft"),
                "ppu": vp["ppu"] * s, "label": vp.get("label", ""),
                "rect": list(overlay.map_rect(vp["rect"], m))}}))
        zones = [fitz.Rect(c) for c in r.get("changes") or []]
        groups = {}
        for a in annotate.iter_annots(old[i]) or []:
            if a.type[0] in (fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET,
                             fitz.PDF_ANNOT_POPUP):
                continue
            subj = (a.info or {}).get("subject", "")
            if subj == overlay.CHANGE_SUBJECT:
                continue                  # old revision clouds stay behind
            key = annotate.tag_of(a) or f"x{a.xref}"
            d = _map_geom(annotate.serialize_annot(old, a), m)
            is_takeoff = subj.startswith(annotate.TAKEOFF + ":")
            if is_takeoff:
                au = annotate.audit_of(old, a)
                au["from"] = au.get("method") or "manual"
                au["method"] = "carried"
                au["carried"] = datetime.datetime.now().isoformat(
                    timespec="seconds")
                d.setdefault("keys", {})["PSAudit"] = ["string",
                                                       json.dumps(au)]
            hit = flag and any(fitz.Rect(d["rect"]).intersects(z)
                               for z in zones)
            sc_raw = (d.get("keys") or {}).get("PSScope")
            if hit and sc_raw:
                # its area changed: the pricing decision has to be made
                # again (the cost line it was linked to is kept)
                try:
                    sc = json.loads(sc_raw[1])
                except (ValueError, TypeError, IndexError):
                    sc = {}
                if sc.get("status") not in (None, "", "open"):
                    sc.update(status="open", reason="", was=sc.get("status"),
                              revised=datetime.datetime.now().isoformat(
                                  timespec="minutes"))
                    sc.pop("checked", None)
                    d["keys"]["PSScope"] = ["string", json.dumps(sc)]
                d["keys"]["PSStatus"] = ["string", annotate.REVISED]
            if is_takeoff and hit:
                d.setdefault("keys", {})["PSStatus"] = [
                    "string", annotate.REVISED]
                groups.setdefault(key, {"flag": True})
                groups[key]["flag"] = True
            g = groups.setdefault(key, {"flag": False})
            g.setdefault("annots", []).append(d)
            g["takeoff"] = g.get("takeoff") or is_takeoff
        for g in groups.values():
            payload = {"annots": g["annots"]}
            if layer:
                payload["layer"] = layer
            marks.append((j, "import_annots", payload))
            if g.get("takeoff"):
                carried += 1
                flagged += 1 if g["flag"] else 0
    return marks, {"carried": carried, "flagged": flagged,
                   "sheets": sum(1 for r in results
                                 if r["old"] is not None
                                 and r["new"] is not None)}
