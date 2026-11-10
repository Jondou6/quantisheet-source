"""Assemblies to and from a spreadsheet (CSV), one row per part:

Assembly_ID, Assembly_Name, CSI_Division, CSI_Division_Title, Process_Area,
Assembly_Unit, Assembly_Formula, Variables, Item_Seq, Item_Description,
Cost_Type, Item_Unit, Calc_Method, Calculation, Waste_Pct, Notes

* Assembly_Formula names the driving quantity: L = length (LF), A = area
  (SF, or SY), N = count, V = volume (CY or GAL), 1 = lump sum. Drivers
  that can't be measured on a drawing (W weight, K kW, T tons, B MBH) are
  counted, with the value per item entered as a property.
* Variables: "L = length (LF); W = 24 in; D = 12 in" - a number becomes a
  property with that default; a description with no number becomes a
  property you must fill in (the estimate says so until you do).
* Calc_Method Factor: quantity = driver x Calculation. Formula: Calculation
  is an expression in the variables (e.g. L*(W/12)*(D/12)/27).
* Waste_Pct is added to the quantity. Labor rows in HR become labor hours.
* Each part gets a cost code (Assembly_ID.Item_Seq) so a cost book made
  from the cost-book template prices it.

The catalog shipped with QuantiSheet (data/assembly_catalog.csv) is loaded
into the Assembly Library alongside the built-in assemblies.
"""
import csv
import io
import logging
import os
import re

log = logging.getLogger(__name__)

COLUMNS = ["Assembly_ID", "Assembly_Name", "CSI_Division",
           "CSI_Division_Title", "Process_Area", "Assembly_Unit",
           "Assembly_Formula", "Variables", "Item_Seq", "Item_Description",
           "Cost_Type", "Item_Unit", "Calc_Method", "Calculation",
           "Waste_Pct", "Notes"]
CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                       "assembly_catalog.csv")

# driver letter (+ assembly unit) -> (measure, expression in QuantiSheet's
# measurement names)
_GAL_PER_CF = 7.48052


def _driver(var, unit):
    v, u = str(var or "").strip().upper(), str(unit or "").strip().upper()
    if v == "L":
        return "length", "Length"
    if v == "A":
        return "area", "(Area/9)" if u == "SY" else "Area"
    if v == "V":
        if u in ("CF", "CU FT"):
            return "volume", "Volume"
        if u == "GAL":
            return "volume", f"(Volume*{_GAL_PER_CF})"
        return "volume", "(Volume/27)"
    if v in ("N", "P", "1", ""):
        return "count", "Count"
    # weight, kW, tons, MBH...: count the items, enter the amount per item
    return "count", f"(Count*{v})"


def _variables(text):
    """'L = length (LF); W = 24 in' -> ({'W': 24.0}, {'L': 'length (LF)'})"""
    props, needs = {}, {}
    for chunk in str(text or "").split(";"):
        if "=" not in chunk:
            continue
        k, desc = (x.strip() for x in chunk.split("=", 1))
        if not re.fullmatch(r"[A-Za-z_]\w*", k):
            continue
        m = re.match(r"^(-?\d+(?:\.\d+)?)\b", desc)
        if m:
            props[k] = float(m.group(1))
        else:
            needs[k] = desc
    return props, needs


def _sub(expr, var, repl):
    if not var or var == "1":
        return expr
    return re.sub(rf"(?<![\w.]){re.escape(var)}(?![\w(])", repl, expr)


_SQUARED = re.compile(r"\(\s*Count\s*\*\s*\(\s*Count\s*\*\s*"
                      r"([A-Za-z_]\w*)\s*\)\s*\)", re.I)


# parts written by this parse (or by the assembly editor) carry "fv": 2;
# a catalog part without it was saved by the version that put the driver
# in twice, and only those are repaired (Chief's re-test, Nov 7: a custom
# (Count*(Count*T)) written on purpose was being rewritten)
FORMULA_VERSION = 2


def qty_for(assembly, part):
    """The quantity formula to evaluate for `part` - as stored. Old saved
    formulas are put right once, by migrate(), when they're read."""
    return part.get("qty")


_BAD = {}


def _bad_map():
    """{(assembly, part): (what the bad parse saved, the right formula)}
    for every catalog part the bad parse got wrong."""
    if "map" not in _BAD:
        out = {}
        try:
            good, _p = parse(CATALOG)
            bad, _p = parse(CATALOG, _buggy=True)
            gq = {(a["name"], p["name"]): p["qty"] for a in good
                  for p in a["parts"]}
            for a in bad:
                for p in a["parts"]:
                    k = (a["name"], p["name"])
                    if k in gq and gq[k] != p["qty"]:
                        out[k] = (p["qty"], gq[k])
        except Exception:                                 # noqa: BLE001
            pass
        _BAD["map"] = out
    return _BAD["map"]


def migrate(assembly):
    """Once, when a saved assembly is read: a catalog part with no formula
    version whose formula is exactly what the bad parse saved for that
    part gets the right formula; every unversioned part is then marked
    version 2 so it is never touched again - a formula written that way on
    purpose, which the bad parse never produced, stays as written
    (Chief's re-tests, Nov 7). Returns how many formulas were put right."""
    if not isinstance(assembly, dict) or assembly.get("source") != "catalog":
        return 0
    fixed = 0
    bad = None
    for p in assembly.get("parts") or []:
        if "fv" in p:
            continue
        if bad is None:
            bad = _bad_map()
        hit = bad.get((assembly.get("name"), p.get("name")))
        if hit and p.get("qty") == hit[0]:
            p["qty"] = hit[1]
            fixed += 1
        p["fv"] = FORMULA_VERSION
    return fixed


def repair_qty(expr):
    """A formula saved before the Nov 7 fix with the driver substituted
    twice - (Count*(Count*T)) - back to (Count*T). Anything else is
    returned unchanged. Use qty_for(), which applies it only to the
    catalog parts saved by that version."""
    if not isinstance(expr, str) or "count" not in expr.lower():
        return expr
    return _SQUARED.sub(lambda m: f"(Count*{m.group(1)})", expr)


def _num(v, default=0.0):
    try:
        return float(str(v).replace("%", "").strip() or default)
    except ValueError:
        return default


def parse(path_or_rows, _buggy=False):
    """Assemblies from a CSV file (or a list of row dicts). Returns
    (assemblies, problems). `_buggy` reproduces the parse that put a
    counted driver in twice - only to recognise what it saved."""
    from . import assemblies as asm_mod, csi, safecell
    if isinstance(path_or_rows, str):
        from .textio import open_csv
        with open_csv(path_or_rows) as f:   # Excel's Windows-1252 too
            rows = list(csv.DictReader(f))
    else:
        rows = list(path_or_rows)
    groups = {}
    for r in rows:
        # unquote: a file written by write() / safecell comes back as it was
        r = {str(k).strip(): safecell.unquote((v or "").strip())
             for k, v in r.items() if k}
        aid = r.get("Assembly_ID") or r.get("Assembly_Name")
        if aid:
            groups.setdefault(aid, []).append(r)
    # a name used by more than one assembly gets its process area (or
    # its ID) added, so every assembly has its own name
    count = {}
    for items in groups.values():
        n = items[0].get("Assembly_Name") or ""
        count[n] = count.get(n, 0) + 1
    final, used = {}, set()
    for aid, items in groups.items():
        n = items[0].get("Assembly_Name") or aid
        if count.get(n, 0) > 1:
            area = items[0].get("Process_Area")
            n = f"{n} ({area})" if area else f"{n} ({aid})"
        if n in used:
            n = f"{items[0].get('Assembly_Name') or aid} ({aid})"
        used.add(n)
        final[aid] = n
    out, problems = [], []
    for aid, items in groups.items():
        head = items[0]
        name = final[aid]
        unit = head.get("Assembly_Unit", "")
        var = head.get("Assembly_Formula", "").strip()
        measure, drv = _driver(var, unit)
        props, needs = _variables(head.get("Variables"))
        # the driver is a measurement unless it's a per-item amount
        if measure != "count" or var.upper() in ("N", "P", "1", ""):
            needs.pop(var, None)
            props.pop(var, None)
        elif var and var not in props:
            props[var] = 0.0
        for k in needs:
            props.setdefault(k, 0.0)
        div = head.get("CSI_Division", "").zfill(2) if \
            head.get("CSI_Division", "").isdigit() else \
            head.get("CSI_Division", "")
        a = {"name": name, "id": aid, "measure": measure,
             "trade": head.get("CSI_Division_Title") or "Other",
             "csi": csi.parse_code(div) if div else "",
             "unit": unit, "props": props, "parts": [],
             "source": "catalog"}
        if needs:
            a["inputs"] = needs
        if head.get("Process_Area"):
            a["area"] = head["Process_Area"]
        notes = []
        for r in sorted(items, key=lambda r: _num(r.get("Item_Seq"), 0)):
            desc = r.get("Item_Description") or "Item"
            calc = r.get("Calculation") or "0"
            if (r.get("Calc_Method") or "Factor").lower().startswith("form"):
                # once: a counted driver (T, K, W...) is also a property,
                # and a second pass put Count in twice - Count*(Count*T)
                # (Chief's estimator test, Nov 7)
                expr = _sub(calc, var, drv)
                if _buggy and var in props:
                    expr = _sub(expr, var, drv)
            else:
                f = _num(calc, 0.0)
                expr = drv if f == 1 else f"{drv}*{f:g}"
            waste = _num(r.get("Waste_Pct"), 0.0)
            if waste:
                expr = f"({expr})*{1 + waste / 100:g}"
            ctype = (r.get("Cost_Type") or "Material").strip()
            iunit = (r.get("Item_Unit") or "ea").strip()
            part = {"name": desc, "unit": iunit.lower(), "qty": expr,
                    "fv": FORMULA_VERSION, "cost": 0.0,
                    "labor": 1.0 if ctype.lower() == "labor" and
                    iunit.upper() in ("HR", "HRS", "MH") else 0.0,
                    "code": f"{aid}.{r.get('Item_Seq') or len(a['parts']) + 1}",
                    "type": ctype}
            try:
                names_ = {k: 1.0 for k in ("length", "area", "count",
                                           "volume", "perimeter",
                                           "segments")}
                for k in props:
                    names_[asm_mod.var_name(k)] = 1.0
                asm_mod.evaluate(expr, names_)
            except asm_mod.FormulaError as e:
                problems.append(f"{aid} item {r.get('Item_Seq')} "
                                f"({desc}): {e}")
            if r.get("Notes"):
                notes.append(f"{desc}: {r['Notes']}")
            if (ctype.lower() == "labor" and part["labor"] == 0):
                notes.append(f"{desc}: labor in {iunit} - give it hours "
                             "per unit (or price it in a cost book)")
            a["parts"].append(part)
        if notes:
            a["notes"] = "; ".join(notes)
        out.append(a)
    return out, problems


def write(assemblies, path):
    """The assemblies as a CSV in the same layout (formulas are written as
    QuantiSheet expressions with L, A, N, V for the measurement)."""
    back = {"Length": "L", "Area": "A", "Count": "N", "Volume": "V"}
    from . import safecell
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = safecell.writer(f)
        w.writerow(COLUMNS)
        for a in assemblies:
            letter = {"length": "L", "area": "A", "count": "N",
                      "volume": "V"}.get(a.get("measure"), "N")
            # quantities are written in QuantiSheet's base units, so the
            # driver unit is LF / SF / CF (any SY or CY conversion is
            # already in the formulas); counted units keep their name
            base = {"length": "LF", "area": "SF", "volume": "CF"}
            unit = base.get(a.get("measure")) or a.get("unit") or "EA"
            var_text = "; ".join(
                [f"{letter} = {a.get('measure', 'count')}"] +
                [f"{k} = {v:g}" if isinstance(v, (int, float)) else
                 f"{k} = {v}" for k, v in (a.get("props") or {}).items()])
            code = a.get("csi") or ""
            for i, p in enumerate(a.get("parts") or [], 1):
                expr = str(p.get("qty", "0"))
                for word, l in back.items():
                    expr = re.sub(rf"\b{word}\b", l, expr)
                w.writerow([a.get("id") or a["name"], a["name"], code[:2],
                            a.get("trade", ""), a.get("area", ""), unit,
                            letter, var_text, i, p.get("name", ""),
                            p.get("type") or ("Labor" if p.get("labor")
                                              else "Material"),
                            (p.get("unit") or "").upper(), "Formula", expr,
                            0, ""])
    return path


def cost_book_template(assemblies, path):
    """A CSV to fill in with prices and import as a cost book (Takeoff >
    Cost Books > Import CSV): one row per part, keyed by its cost code."""
    from . import safecell
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = safecell.writer(f)
        w.writerow(["Code", "Description", "Unit", "Material", "Labor",
                    "Crew", "Sub", "Assembly", "Cost_Type"])
        for a in assemblies:
            for p in a.get("parts") or []:
                if not p.get("code"):
                    continue
                labor = p.get("labor") or ""
                w.writerow([p["code"], p.get("name", ""),
                            p.get("unit", ""), "", labor, "", "",
                            a["name"], p.get("type", "")])
    return path


_CACHE = {}


def user_dir():
    """Your own catalogs (e.g. imported RSMeans assemblies): every CSV in
    ~/.quantisheet/catalogs is loaded with the shipped catalog."""
    from . import settings
    path = os.path.join(settings.DIR, "catalogs")
    os.makedirs(path, exist_ok=True)
    return path


def catalog_files():
    files = [CATALOG] if os.path.exists(CATALOG) else []
    try:
        d = user_dir()
        files += [os.path.join(d, n) for n in sorted(os.listdir(d))
                  if n.lower().endswith(".csv")]
    except OSError:
        pass
    return files


def _db_stamps():
    """{name: modified} of the catalogs in the price database (checked at
    most every 20 s)."""
    import time
    now = time.time()
    hit = _CACHE.get("db")
    from . import pricedb
    if hit and hit[0] == pricedb.path() and now - hit[1] < 20:
        return hit[2]
    try:
        stamps = pricedb.catalog_stamps()
    except Exception:
        log.warning("price database catalogs unavailable", exc_info=True)
        stamps = {}
    _CACHE["db"] = (pricedb.path(), now, stamps)
    return stamps


def catalog():
    """The assemblies shipped with QuantiSheet, the catalogs in the price
    database (e.g. imported RSMeans) and CSVs in ~/.quantisheet/catalogs,
    {name: assembly}."""
    files = catalog_files()
    dbs = _db_stamps()
    key = (tuple((f, os.path.getmtime(f)) for f in files),
           tuple(sorted(dbs.items())))
    if _CACHE.get("key") != key:
        items = {}
        sources = [(f, f, None) for f in files]
        from . import pricedb
        for name in sorted(dbs):
            sources.insert(1, (f"db:{name}", None, name))
        for label, f, dbname in sources:
            try:
                if dbname is not None:
                    text = pricedb.catalog_text(dbname) or ""
                    got, problems = parse(list(csv.DictReader(
                        io.StringIO(text))))
                else:
                    got, problems = parse(f)
                if problems:
                    log.warning("assembly catalog %s: %d formula problem(s)",
                                label, len(problems))
                for a in got:
                    if f != CATALOG:
                        a["source"] = dbname or os.path.splitext(
                            os.path.basename(f))[0]
                    items.setdefault(a["name"], a)
            except Exception:
                log.exception("could not read the assembly catalog %s", label)
        _CACHE.update(key=key, items=items)
    import copy
    return copy.deepcopy(_CACHE["items"])


def forget_cache():
    _CACHE.clear()


def import_to_library(path):
    """Add every assembly in a CSV to your library. Returns (count,
    problems)."""
    from . import assemblies as asm_mod
    items, problems = parse(path)
    asm_mod.save_many_to_library(items)
    return len(items), problems
