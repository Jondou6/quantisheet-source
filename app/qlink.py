"""Quantity Link: keep an Excel workbook up to date with the takeoff.

Link a drawing to a workbook once; after that every change to the
measurements rewrites it. Point cells in your own estimate workbook at it
(for example  ='C:\\Jobs\\[quantities.xlsx]Summary'!C2 ) and Excel picks up
the new numbers when it recalculates or reopens. Excel locks a workbook
while it is open, so the linked workbook itself should stay closed; it is
updated as soon as it can be.
"""
import logging
import os

from . import acrobat, annotate, settings

log = logging.getLogger(__name__)


def _key(doc_path):
    return os.path.normcase(os.path.abspath(doc_path)) if doc_path else ""


def link_for(doc_path):
    if not doc_path:
        return None
    return (settings.get("quantity_links") or {}).get(_key(doc_path))


def set_link(doc_path, xlsx_path):
    links = dict(settings.get("quantity_links") or {})
    if xlsx_path:
        links[_key(doc_path)] = xlsx_path
    else:
        links.pop(_key(doc_path), None)
    settings.set("quantity_links", links)


def sheets(doc):
    """The workbook's sheets: Summary (one row per item and unit, with
    totals) and Measurements (every measurement)."""
    items = annotate.totals_items(doc)
    summary = {}
    for it in items:
        k = (it["group"] or it["type"].title(), it["type"], it["unit"])
        s = summary.setdefault(k, [0, 0.0])
        s[0] += 1
        s[1] += 1 if it["type"] == "count" else it["value"]
    srows = [["Item", "Type", "Quantity", "Unit", "Count"]]
    for (name, mtype, unit), (n, total) in sorted(summary.items()):
        srows.append([name, mtype.title(), round(total, 4),
                      "ea" if mtype == "count" else unit, n])
    mrows = [["Page", "Item", "Type", "Value", "Unit", "Label"]]
    for it in items:
        mrows.append([it["page"] + 1, it["group"], it["type"].title(),
                      round(it["value"], 4), it["unit"], it["label"]])
    out = [("Summary", srows), ("Measurements", mrows)]
    try:
        from . import assemblies
        rows, totals, _err = assemblies.rollup(doc)
        if rows:
            arows = [["Assembly", "Trade", "Takeoff Qty", "Unit", "Material",
                      "Labor Hours", "Labor Cost", "Total"]]
            for r in rows:
                arows.append([r["name"], r["trade"], round(r["quantity"], 4),
                              r["unit"], round(r["material"], 2),
                              round(r["labor_hours"], 2),
                              round(r["labor_cost"], 2), round(r["total"], 2)])
            arows.append(["Total", "", "", "", round(totals["material"], 2),
                          round(totals["labor_hours"], 2),
                          round(totals["labor_cost"], 2),
                          round(totals["total"], 2)])
            out.append(("Assemblies", arows))
    except Exception:
        log.warning("assembly rollup for quantity link", exc_info=True)
    return out


def update(doc, xlsx_path):
    """Rewrite the linked workbook. Returns None, or a message saying why
    it couldn't be written (usually: it's open in Excel)."""
    tmp = xlsx_path + ".tmp"
    try:
        acrobat.write_xlsx(tmp, sheets(doc))
        os.replace(tmp, xlsx_path)
    except PermissionError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return (f"{os.path.basename(xlsx_path)} is open in Excel; it will "
                "update when it's closed")
    except OSError as e:
        return f"Couldn't update {os.path.basename(xlsx_path)}: {e}"
    return None
