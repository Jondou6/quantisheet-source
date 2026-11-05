"""Estimate vs Actual: what each estimate item really took.

Record the actual quantity and cost of any priced item of the estimate
(items.py: an added line, a takeoff group priced by a unit cost, an
assembly or a civil activity) as the job goes; compare() shows estimate
vs actual per item - quantity, cost, unit cost and the variance in
dollars and percent - and the job totals. Kept in the PDF
(quantisheet_estimate_actuals.json) with the item ids.

archive() adds the job's actual unit costs, by cost code and unit, to a
history file you keep (JSON, your path); load_history() reads it back in
the shape Estimate Error Check uses to point out unit costs far from your
own history. (For cost books there is also Job Cost Feedback,
pricehistory.py; this file is separate and only yours.)
"""
import datetime
import json
import logging
import os
from decimal import Decimal, InvalidOperation

from .. import dmoney, embfiles, estimate_lines as EL
from . import _io, safedb

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_actuals.json"
HISTORY_KIND = "estimate_history"


class ActualsError(ValueError):
    pass


def _num(v, what, places):
    if v is None or str(v).strip() == "":
        return None
    if dmoney.bad(v):
        raise ActualsError(f"{what}: can't read {v!r} as a number")
    try:
        d = dmoney.D(v)
    except (InvalidOperation, ValueError):
        raise ActualsError(f"{what}: can't read {v!r} as a number")
    if not d.is_finite() or abs(d) > Decimal("1e12"):
        raise ActualsError(f"{what}: {v!r} is out of range")
    return d.quantize(places)


def read(doc):
    try:
        if doc is not None and FILE in embfiles.names(doc):
            data = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
            if isinstance(data, dict):
                return {str(k): v for k, v in dict(data.get("lines") or
                                                   {}).items()
                        if isinstance(v, dict)}
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the actuals", exc_info=True)
    return {}


def record(doc, line_id, qty=None, cost=None, note="", job=None, lib=None,
           installed=None):
    """Actual quantity / cost of one estimate item (items.py id: a line
    id, "takeoff:...", "assembly:..." or - with the civil job -
    "civil:..."). `qty` is what was bought / used, `installed` (v2 step
    7, optional) what is in place: actual waste = qty / installed - 1."""
    from . import items
    if EL.get(doc, line_id) is None and items.find(
            items.collect(doc, job, lib), line_id) is None:
        raise ActualsError("That item is no longer in the estimate.")
    q = _num(qty, "Actual quantity", Decimal("0.0001"))
    c = _num(cost, "Actual cost", Decimal("0.01"))
    i = _num(installed, "Installed quantity", Decimal("0.0001"))
    data = read(doc)
    data[line_id] = _entry(q, c, i, note)
    _write(doc, data)
    return data[line_id]


def _entry(q, c, i, note):
    e = {"qty": "" if q is None else str(q),
         "cost": "" if c is None else str(c),
         "note": " ".join(str(note or "").split())[:300],
         "at": datetime.date.today().isoformat()}
    if i is not None:
        e["installed"] = str(i)
    return e


def _write(doc, data):
    """All the actuals in one write (never a part of an import)."""
    embfiles.put(doc, FILE, json.dumps({"version": 1, "lines": data},
                                       indent=1).encode("utf-8"),
                 "QuantiSheet estimate actuals")


@safedb.read_only
def compare(doc, job=None, lib=None):
    """Estimate vs actual for every priced item (items.collect): added
    lines, takeoff groups priced by a unit cost, assemblies and - with
    the civil job - civil activities."""
    from . import items
    acts = read(doc)
    rows = []
    t = {"est_cost": Decimal("0.00"), "act_cost": Decimal("0.00"),
         "est_cost_with_actuals": Decimal("0.00"), "lines_with_actuals": 0}
    for p in items.collect(doc, job, lib)["items"]:
        a = acts.get(p["id"]) or {}
        aq = Decimal(a["qty"]) if a.get("qty") else None
        ac = Decimal(a["cost"]) if a.get("cost") else None
        r = {"id": p["id"], "kind": p["kind"], "code": p["code"],
             "desc": p["desc"], "unit": p["unit"], "est_qty": p["qty"],
             "est_cost": p["total"], "est_unit": p["unit_cost"],
             "act_qty": aq, "act_cost": ac, "qty_var": None,
             "cost_var": None, "cost_var_pct": None, "act_unit": None,
             "note": a.get("note", ""),
             "net_qty": p.get("net_qty", p["qty"]),
             "waste_pct": p.get("waste_pct"),
             "waste_basis": p.get("waste_basis", ""),
             "act_installed": _dec(a.get("installed")),
             "act_waste_pct": None, "qty_var_cost": None, "price_var": None}
        if aq is not None:
            r["qty_var"] = aq - p["qty"]
            r["qty_var_cost"] = dmoney.cents(r["qty_var"] * p["unit_cost"])
            if r["act_installed"]:
                r["act_waste_pct"] = ((aq / r["act_installed"] - 1) * 100
                                      ).quantize(Decimal("0.1"))
            if ac is not None:
                r["price_var"] = dmoney.cents(ac - aq * p["unit_cost"])
        if ac is not None:
            r["cost_var"] = ac - p["total"]
            if p["total"]:
                r["cost_var_pct"] = (r["cost_var"] / p["total"] * 100
                                     ).quantize(Decimal("0.1"))
            q = aq if aq else p["qty"]
            if q:
                r["act_unit"] = dmoney.cents(ac / q)
            t["act_cost"] += ac
            t["est_cost_with_actuals"] += p["total"]
            t["lines_with_actuals"] += 1
        t["est_cost"] += p["total"]
        rows.append(r)
    return {"rows": rows, "totals": t}


def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _blank(v):
    return "" if v is None else v


def export(result, path):
    head = ["Kind", "Code", "Description", "Unit", "Estimate qty", "Actual qty",
            "Estimate cost", "Actual cost", "Variance $", "Variance %",
            "Estimate unit cost", "Actual unit cost", "Note",
            # v2 step 7: added after the old columns, which are unchanged
            "Measured qty", "Waste % planned", "Installed qty",
            "Waste % actual", "Quantity variance $", "Price variance $",
            "Item id"]
    rows = [[r.get("kind", ""), r["code"], r["desc"], r["unit"], r["est_qty"],
             "" if r["act_qty"] is None else r["act_qty"], r["est_cost"],
             "" if r["act_cost"] is None else r["act_cost"],
             "" if r["cost_var"] is None else r["cost_var"],
             "" if r["cost_var_pct"] is None else r["cost_var_pct"],
             r["est_unit"], "" if r["act_unit"] is None else r["act_unit"],
             r["note"], _blank(r.get("net_qty")),
             _blank(r.get("waste_pct")) if r.get("waste_pct") is not None
             else (r.get("waste_basis") or ""),
             _blank(r.get("act_installed")), _blank(r.get("act_waste_pct")),
             _blank(r.get("qty_var_cost")), _blank(r.get("price_var")),
             r["id"]] for r in result["rows"]]
    return _io.write_table(path, head, rows, "Estimate vs actual")


# ---- import actuals (v2 step 7) ----------------------------------------------

_HEAD_CODE = ("cost code", "code", "csi", "phase code")
_HEAD_ID = ("item id",)
_HEAD_COST = ("actual cost", "actual", "amount", "cost", "total")
_HEAD_QTY = ("actual qty", "actual quantity", "quantity", "qty",
             "units installed")
_HEAD_INST = ("installed qty", "installed")
_HEAD_DESC = ("description", "desc", "name")


def _pick(head, names, avoid=()):
    for n in names:
        for i, h in enumerate(head):
            if i not in avoid and (h == n or h.startswith(n)):
                return i
    return None


def _code_key(c):
    import re
    return re.sub(r"[^0-9A-Za-z]", "", str(c or "")).upper()


def _clean(v):
    return " ".join(str(v or "").split()).lstrip("=+-@\t")[:120]


@safedb.read_only
def import_preview(doc, path, job=None, lib=None):
    """What an actuals file would record - nothing is written. Rows match
    by the Item id column of an earlier export, else by cost code; items
    sharing a code split the amount by estimate cost (to the cent).
    {"file", "rows": [{id, desc, code, cost, qty, installed, how}],
    "unmatched": [{line, code, desc, cost}], "skipped": [{line, why}]}."""
    from . import items
    name = os.path.basename(str(path))
    head, body = _io.read_table(path)
    h = [_io.norm(x) for x in head]
    ci = _pick(h, _HEAD_ID)
    cc = _pick(h, _HEAD_CODE, avoid=() if ci is None else (ci,))
    used = {x for x in (ci, cc) if x is not None}
    ca = _pick(h, ("actual cost",)) if "actual cost" in h else \
        _pick(h, _HEAD_COST, avoid=used)
    if (ci is None and cc is None) or ca is None:
        raise ActualsError(f"{name}: no cost code (or item id) and amount "
                           "columns found - nothing was imported.")
    used.add(ca)
    cq = _pick(h, ("actual qty",)) if "actual qty" in h else \
        _pick(h, _HEAD_QTY, avoid=used)
    cn = _pick(h, _HEAD_INST, avoid=used | {cq})
    cd = _pick(h, _HEAD_DESC, avoid=used)
    est = items.collect(doc, job, lib)["items"]
    by_id = {i["id"]: i for i in est}
    by_code = {}
    for i in est:
        if i["code"]:
            by_code.setdefault(_code_key(i["code"]), []).append(i)
    out = {"file": name, "rows": [], "unmatched": [], "skipped": []}
    got = {}

    def cell(r, k):
        return r[k] if k is not None and k < len(r) else ""
    for n, r in enumerate(body, start=2):
        if not any(str(x).strip() for x in r):
            continue
        iid, code = cell(r, ci).strip(), cell(r, cc).strip()
        if not iid and not code:
            out["skipped"].append({"line": n, "why": "no cost code or item "
                                   "id"})
            continue
        try:
            cost = _num(str(cell(r, ca)).replace("$", "").replace(",", ""),
                        "Actual cost", Decimal("0.01"))
            qty = _num(str(cell(r, cq)).replace(",", ""), "Actual quantity",
                       Decimal("0.0001"))
            inst = _num(str(cell(r, cn)).replace(",", ""),
                        "Installed quantity", Decimal("0.0001"))
        except ActualsError as e:
            out["skipped"].append({"line": n, "why": str(e)})
            continue
        if cost is None and qty is None:
            out["skipped"].append({"line": n, "why": "no amount"})
            continue
        desc = _clean(cell(r, cd))
        if iid and iid in by_id:
            got.setdefault(iid, {"cost": None, "qty": None, "installed":
                                 None, "how": "item id", "desc": desc})
            g = got[iid]
            g["cost"] = cost if g["cost"] is None else g["cost"] + (cost or 0)
            g["qty"], g["installed"] = qty, inst
            continue
        targets = by_code.get(_code_key(code)) if code else None
        if not targets:
            out["unmatched"].append({"line": n, "code": code or iid,
                                     "desc": desc, "cost": cost})
            continue
        if len(targets) == 1:
            t = targets[0]
            g = got.setdefault(t["id"], {"cost": None, "qty": None,
                                         "installed": None, "how": "cost "
                                         "code", "desc": desc})
            g["cost"] = cost if g["cost"] is None else g["cost"] + (cost or 0)
            g["qty"], g["installed"] = qty, inst
            continue
        shares = _pro_rata(cost or Decimal("0.00"),
                           [t["total"] for t in targets])
        for t, part in zip(targets, shares):
            g = got.setdefault(t["id"], {"cost": None, "qty": None,
                                         "installed": None, "desc": desc,
                                         "how": f"cost code, shared by "
                                         f"{len(targets)} items by "
                                         "estimate cost"})
            g["cost"] = part if g["cost"] is None else g["cost"] + part
    for iid, g in got.items():
        it = by_id[iid]
        out["rows"].append({"id": iid, "desc": it["desc"], "code": it["code"],
                            "cost": g["cost"], "qty": g["qty"],
                            "installed": g["installed"], "how": g["how"],
                            "file_desc": g["desc"]})
    return out


def _pro_rata(amount, weights):
    """Split `amount` by `weights` to the cent; the cents left over go to
    the largest remainders so the parts add up exactly."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    w = [Decimal(x) for x in weights]
    tot = sum(w)
    if tot <= 0:
        w, tot = [Decimal(1)] * len(w), Decimal(len(w))
    cents = int(amount * 100)
    raw = [Decimal(cents) * x / tot for x in w]
    base = [int(r) for r in raw]
    left = cents - sum(base)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - base[i], -i),
                   reverse=True)
    for i in order[:left]:
        base[i] += 1
    return [Decimal(b) / 100 for b in base]


def apply_import(doc, preview):
    """Record every previewed row in one write; returns how many."""
    data = read(doc)
    for r in preview["rows"]:
        old = data.get(r["id"]) or {}
        note = f"imported from {preview.get('file', 'a file')}" + (
            f" ({r['how']})" if r.get("how") else "")
        data[r["id"]] = _entry(
            r["qty"] if r["qty"] is not None else _dec(old.get("qty")),
            r["cost"], r.get("installed") if r.get("installed") is not None
            else _dec(old.get("installed")), note)
    _write(doc, data)
    return len(preview["rows"])


# ---- your history file --------------------------------------------------------

def _load_rows(path):
    if not os.path.isfile(path):
        return []
    data = _io.read_json(path)
    if not isinstance(data, dict) or data.get("kind") != HISTORY_KIND:
        raise ActualsError(f"{os.path.basename(path)} isn't an estimate "
                           "history file.")
    return [r for r in data.get("rows") or [] if isinstance(r, dict)]


def archive(doc, path, job, civil=None, lib=None):
    """Add (or replace) this job's actual unit costs in the history file.
    Returns how many rows the job has there now."""
    job = " ".join(str(job or "").split())
    if not job:
        raise ActualsError("Name the job.")
    rows = [r for r in _load_rows(_io.check_user_path(path))
            if r.get("job") != job]
    n = 0
    for r in compare(doc, civil, lib)["rows"]:
        if r["act_unit"] is None or not r["code"]:
            continue
        rows.append({"job": job, "code": r["code"], "unit": _io.norm(
            r["unit"]), "desc": r["desc"], "unit_cost": str(r["act_unit"]),
            "date": datetime.date.today().isoformat()})
        n += 1
    _io.write_json(path, {"kind": HISTORY_KIND, "version": 1, "rows": rows})
    return n


def load_history(path):
    """{(code, unit): [unit costs]} from the history file."""
    out = {}
    for r in _load_rows(path):
        try:
            out.setdefault((r["code"], _io.norm(r["unit"])), []).append(
                Decimal(str(r["unit_cost"])))
        except (KeyError, InvalidOperation):
            continue
    return out
