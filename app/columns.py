"""Custom Markups List columns (Bluebeam-style), saved inside the PDF.

A column is text, a number, a choice from a list, or a formula. Formulas
use the markup's measurement (Value, Length, Area, Count, Volume...) and
other number columns by name, e.g.  Area * Unit_Price  or  Count * 2.5
"""
import json
import logging

from . import annotate
from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_columns.json"
TYPES = ("text", "number", "choice", "formula")


def read(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(d, dict):
                d.setdefault("columns", [])
                d.setdefault("values", {})
                return d
    except Exception:
        log.warning("could not read custom columns", exc_info=True)
    return {"columns": [], "values": {}}


def write(doc, data):
    raw = json.dumps(data).encode()
    embfiles.put(doc, FILE, raw, "QuantiSheet Markups List columns")


def key_of(item):
    """How a markup is identified in the values table."""
    ref = item.get("ref") or {}
    if ref.get("target"):
        return ref["target"]
    return f"p{item['page']}x{ref.get('xref')}"


def set_columns(doc, columns):
    clean, seen = [], set()
    for c in columns:
        name = str(c.get("name", "")).strip()[:40]
        typ = c.get("type", "text")
        if not name or name.lower() in seen or typ not in TYPES:
            continue
        seen.add(name.lower())
        col = {"name": name, "type": typ}
        if typ == "choice":
            col["choices"] = [str(x).strip() for x in c.get("choices") or []
                              if str(x).strip()][:50]
        if typ == "formula":
            col["formula"] = str(c.get("formula", ""))[:300]
        clean.append(col)
    d = read(doc)
    d["columns"] = clean
    write(doc, d)
    return clean


def choice_parts(choice):
    """'Carpet = 4.50' -> ('Carpet', 4.5); 'Carpet' -> ('Carpet', None).
    The number is a choice's hidden value: formulas use it ($/SF and the
    like) while the list shows the name."""
    text = str(choice).strip()
    if "=" in text:
        name, _, num = text.rpartition("=")
        try:
            return name.strip(), float(num.strip().replace("$", "")
                                       .replace(",", ""))
        except ValueError:
            pass
    return text, None


def choice_labels(col):
    return [choice_parts(c)[0] for c in col.get("choices") or []]


def choice_value(col, label):
    """The hidden number behind choice `label` in column `col`, or None."""
    for c in col.get("choices") or []:
        name, num = choice_parts(c)
        if name == str(label).strip():
            return num
    return None


def set_value(doc, key, column, value):
    d = read(doc)
    row = d["values"].setdefault(key, {})
    if value in (None, ""):
        row.pop(column, None)
    else:
        row[column] = value
    if not row:
        d["values"].pop(key, None)
    write(doc, d)


def _measure_vars(item):
    """Formula names from a Markups List row. A wall area also gives
    Wall_Area, Height and Openings; a run with a rise/drop gives Rise."""
    names = {"value": 0.0, "length": 0.0, "area": 0.0, "count": 0.0,
             "volume": 0.0, "angle": 0.0, "radius": 0.0, "diameter": 0.0,
             "wall_area": 0.0, "height": 0.0, "openings": 0.0, "rise": 0.0,
             "page": float(item.get("page", 0) + 1)}
    ex = item.get("extra") or {}
    for k in ("height", "openings", "rise"):
        if isinstance(ex.get(k), (int, float)):
            names[k] = abs(float(ex[k]))
    m = item.get("mvalue")
    if isinstance(m, (int, float)):
        names["value"] = float(m)
        t = item.get("mtype", "")
        if t in names:
            names[t] = float(m)
        if t == "count":
            names["count"] = 1.0
        if t == "area" and names["height"]:
            names["wall_area"] = float(m)
    return names


def values_for(doc, items, data=None):
    """{key: {column: shown value}} with formulas worked out."""
    from .assemblies import FormulaError, evaluate, var_name
    data = data or read(doc)
    cols = data["columns"]
    out = {}
    for it in items:
        k = key_of(it)
        stored = dict(it.get("fields") or {})     # from the tool it was made
        stored.update(data["values"].get(k, {}))  # with; edits win
        names = _measure_vars(it)
        for c in cols:
            if c["type"] == "number":
                try:
                    names[var_name(c["name"])] = float(stored.get(c["name"])
                                                       or 0)
                except (TypeError, ValueError):
                    names[var_name(c["name"])] = 0.0
            elif c["type"] == "choice":
                names[var_name(c["name"])] = choice_value(
                    c, stored.get(c["name"], "")) or 0.0
        row = {}
        for c in cols:
            if c["type"] == "formula":
                try:
                    v = evaluate(c.get("formula", ""), names)
                    row[c["name"]] = f"{v:,.2f}"
                    names[var_name(c["name"])] = v
                except FormulaError as e:
                    row[c["name"]] = f"#ERR {e}"[:60]
            else:
                v = stored.get(c["name"], "")
                row[c["name"]] = "" if v is None else str(v)
        out[k] = row
    return out


# ---- grouping and export (Nov 2) ----------------------------------------------------

BUILT_IN = {"Subject": "subject", "Status": "status", "Page": "page",
            "Type": "type", "Origin": "origin", "Author": "author"}


def group_key(item, column, values=None):
    """What row `item` is grouped under for `column` (a built-in column
    name or a custom column)."""
    if column in BUILT_IN:
        v = item.get(BUILT_IN[column], "")
        if column == "Page":
            return str(int(v) + 1)
        return str(v or "(none)")
    vals = (values or {}).get(key_of(item), {})
    return str(vals.get(column, "") or "(none)")


def group_summary(items, column, values=None):
    """[(group, markups, {unit: total})] for `items` grouped by `column`,
    largest group first. Totals add each measurement's value per unit."""
    groups = {}
    for it in items:
        g = groups.setdefault(group_key(it, column, values),
                              [0, {}])
        g[0] += 1
        v = it.get("mvalue")
        if isinstance(v, (int, float)):
            unit = "ea" if it.get("mtype") == "count" else \
                (it.get("measure", "").split(" ", 1) + [""])[1].replace(
                    " net", "").strip() or it.get("mtype", "")
            g[1][unit] = g[1].get(unit, 0.0) + (1.0 if it.get("mtype") ==
                                                "count" else float(v))
    out = [(k, n, tot) for k, (n, tot) in groups.items()]
    out.sort(key=lambda r: (-r[1], r[0]))
    return out


def rows_for_export(items, cols, custom, values):
    """[[cell]] rows of the Markups List for an export (header first)."""
    head = list(cols) + ["Color"] + [c["name"] for c in custom]
    rows = [head]
    for it in items:
        vals = values.get(key_of(it), {})
        rows.append([it["page"] + 1, it["type"], it["subject"],
                     it["comment"], it["measure"], it["author"], it["date"],
                     it["status"], it.get("origin", ""), it["color"]] +
                    [vals.get(c["name"], "") for c in custom])
    return rows


def write_xlsx(path, rows, sheet="Markups"):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from . import safecell
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    for r in rows:
        safecell.append_row(ws, r)
    for c in ws[1]:
        c.font = Font(bold=True)
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(60, width + 2)
    wb.save(path)
    return path


def write_xml(path, rows):
    """A plain XML list: <Markups><Markup><Page>..</Page>..</Markup>.."""
    import re
    from xml.sax.saxutils import escape
    head = rows[0]
    tags = []
    for h in head:
        t = re.sub(r"[^A-Za-z0-9_]", "_", str(h)).strip("_") or "Field"
        if t[0].isdigit():
            t = "F_" + t
        tags.append(t)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<Markups>"]
    for r in rows[1:]:
        out.append("  <Markup>")
        for t, x in zip(tags, r):
            out.append(f"    <{t}>{escape(str(x))}</{t}>")
        out.append("  </Markup>")
    out.append("</Markups>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return path
