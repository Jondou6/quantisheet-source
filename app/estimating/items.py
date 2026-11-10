"""One estimate: every priced item of the drawing in one list.

Kinds (each item has a stable id, so actuals, supplier choices and quote
options stay with it):

  line      an added estimate line (estimate_lines.py) - id: its line id
  takeoff   a takeoff group priced by a plain unit cost in the Estimate
            panel (estimate.lines) - id: "takeoff:<name|type|unit>"
  assembly  an assembly row (assemblies.rollup) - id: "assembly:<name>"
  civil     a civil crew activity (heavy.py), when a job is given -
            id: "civil:<activity id>"

Every item: {id, kind, code, desc, unit, qty, unit_cost, total,
parts: {mat, lab, eqp, sub}, hours, materials: [{desc, unit, code, qty,
cost, assumed}], source, problem, net_qty, waste_pct, waste_basis}.
Money is Decimal (cents). v2 step 7: `qty` stays the quantity priced
(with waste for a takeoff group); `net_qty` is the measured quantity,
`waste_pct` the planned waste and `waste_basis` where it comes from
("takeoff", "assembly", "in formula" or "").

The pricing is each module's own; this only puts the results side by
side. A takeoff group's unit cost goes in the part its cost type names.
With no cost type (v2 step 4) it is in the total only - no part, no
material row - and the item says so ("no_cost_type": True; the error
check and the material list name it).
"""
import logging
from decimal import Decimal

from .. import dmoney
from . import safedb
from ..dmoney import c2 as _c2

log = logging.getLogger(__name__)

Z = Decimal("0.00")
KINDS = ("line", "takeoff", "assembly", "civil")


def takeoff_id(name, mtype, unit):
    from .. import estimate
    return "takeoff:" + estimate.key_of(name, mtype, unit)


def _c(v):
    return dmoney.cents(dmoney.D(v))


def _parts(**kw):
    p = {k: Z for k in ("mat", "lab", "eqp", "sub")}
    p.update({k: _c(v) for k, v in kw.items()})
    return p


def _item(id_, kind, code, desc, unit, qty, total, parts, **kw):
    qty = dmoney.D(qty)
    out = {"id": id_, "kind": kind, "code": code or "", "desc": desc,
           "unit": unit or "", "qty": qty, "total": _c(total),
           "unit_cost": _c(dmoney.D(total) / qty) if qty else Z,
           "parts": parts, "hours": Decimal("0.00"), "materials": [],
           "source": "", "problem": "", "no_cost_type": False,
           "net_qty": qty, "waste_pct": None, "waste_basis": ""}
    out.update(kw)
    return out


def _lines(doc):
    from .. import estimate_lines as EL
    out = []
    for p in EL.priced(doc):
        e = p["ext"]
        it = _item(p["id"], "line", p["code"], p["desc"], p["unit_label"],
                   p["quantity"], p["total"],
                   _parts(mat=e["mat"], lab=e["lab"], eqp=e["eqp"],
                          sub=e["sub"]),
                   source=p.get("source", "") or "", problem=p.get(
                       "problem", "") or "", link=p.get("link"),
                   waste_basis=_formula_basis(p.get("link")))
        it["unit_cost"] = p["unit_cost"]
        if e["mat"]:
            it["materials"] = [{"desc": p["desc"], "unit": p["unit_label"],
                                "code": p["code"], "qty": p["quantity"],
                                "cost": e["mat"], "assumed": False}]
        out.append(it)
    return out


def _pct(v):
    """A percentage as a plain Decimal (10, 12.5 - never 1E+1)."""
    d = Decimal(str(v or 0))
    return Decimal(format(d.normalize(), "f")) if d else Decimal(0)


def _formula_basis(link):
    f = str((link or {}).get("formula") or "").replace(" ", "").lower()
    return "in formula" if f and f != "qty" else ""


def _takeoff(doc):
    from .. import estimate, estimate_lines as EL
    out = []
    for g in estimate.lines(doc):
        if not g.get("unit_cost") or not g.get("total"):
            continue
        ct = g.get("cost_type") or ""
        try:
            kind = EL.cost_type(ct)
        except EL.LineError:
            kind = ""
        part = EL.TYPE_PART.get(kind)
        qty = dmoney.D(round(g["adjusted"], 4))
        it = _item(takeoff_id(g["name"], g["type"], g["unit"]), "takeoff",
                   g.get("code", ""), g["name"], g["unit"], qty, g["total"],
                   _parts(**({part: g["total"]} if part else {})),
                   source=f"takeoff group, page(s) {g.get('pages', '')}",
                   group=(g["name"], g["type"], g["unit"]),
                   no_cost_type=not part,
                   net_qty=dmoney.D(round(g["quantity"] * g["multiplier"],
                                          4)),
                   waste_pct=_pct(g["waste"]), waste_basis="takeoff")
        it["unit_cost"] = _c(g["unit_cost"])
        if part == "mat":
            it["materials"] = [{"desc": g["name"], "unit": g["unit"],
                                "code": g.get("code", ""), "qty": qty,
                                "cost": it["total"], "assumed": False}]
        out.append(it)
    return out


def _assemblies(doc):
    from .. import assemblies
    try:
        rows, _t, errors = assemblies.rollup(doc, added=False)
    except Exception:                                     # noqa: BLE001
        log.warning("assemblies unavailable", exc_info=True)
        return []
    out = []
    for r in rows:
        mats = [{"desc": q["name"], "unit": q.get("unit", ""),
                 "code": q.get("code", ""),
                 "qty": dmoney.D(round(q["qty"], 4)),
                 "cost": _c(q["material"]), "assumed": False}
                for q in r.get("parts") or [] if q.get("material")]
        mat = sum((m["cost"] for m in mats), Z)
        lab = _c(r.get("labor_cost") or 0)
        wp, wb = _assembly_waste(doc, r["name"])
        it = _item(f"assembly:{r['name']}", "assembly", r.get("csi", ""),
                   r["name"], r.get("unit", ""),
                   dmoney.D(round(r.get("quantity") or 0, 4)), mat + lab,
                   _parts(mat=mat, lab=lab), materials=mats,
                   hours=dmoney.D(_c2(r.get("labor_hours") or 0)),
                   source="assembly", waste_pct=wp, waste_basis=wb)
        out.append(it)
    return out


def _assembly_waste(doc, name):
    """(waste %, basis) of an assembly: its Waste property when a part
    formula uses it; 'assembly, per part' when parts have their own
    Waste_<part> properties (assembly rules, v2 step 7)."""
    from .. import assemblies
    try:
        a = assemblies.find(doc, name) or {}
    except Exception:                                     # noqa: BLE001
        return None, ""
    props = {str(k).lower(): v for k, v in (a.get("props") or {}).items()}
    forms = " ".join(str(p.get("qty") or "") for p in a.get("parts") or []
                     ).lower()
    if any(k.startswith("waste_") for k in props) and "waste_" in forms:
        return None, "assembly, per part"
    if "waste" in props and "waste" in forms:
        try:
            return _pct(props["waste"]), "assembly"
        except Exception:                                 # noqa: BLE001
            return None, "assembly"
    return None, ""


def _civil(job, lib):
    from .. import heavy
    out = []
    for a in job.get("activities") or []:
        try:
            c = heavy.activity_cost(a, lib, job)
        except Exception as e:                            # noqa: BLE001
            c = {"hours": Decimal(0), "labor": Z, "equipment": Z,
                 "material": Z, "sub": Z, "total": Z, "problem": str(e)}
        if not c["total"] and not heavy.D(a.get("qty")):
            continue
        qty = heavy.D(a.get("qty"))
        mats = []
        quote = next((q for q in a.get("quotes") or [] if q.get("use")
                      and q.get("kind") != "sub"), None)
        if quote is not None:
            mats.append({"desc": f"{a.get('name', '')} (quote "
                                 f"{quote.get('vendor', '')})".strip(),
                         "unit": a.get("unit", ""), "code": a.get("code", ""),
                         "qty": qty, "cost": c["material"],
                         "assumed": False, "supplier": quote.get("vendor", "")})
        else:
            for m in a.get("materials") or []:
                mq = qty * heavy.D(m.get("qty_per", 1))
                mats.append({"desc": m.get("desc") or a.get("name", ""),
                             "unit": m.get("unit") or a.get("unit", ""),
                             "code": m.get("code", "") or a.get("code", ""),
                             "qty": mq,
                             "cost": _c(mq * heavy.D(m.get("cost"))),
                             "assumed": False})
        out.append(_item(
            f"civil:{a.get('id') or a.get('name')}", "civil",
            a.get("code", ""), a.get("name", ""), a.get("unit", ""), qty,
            c["total"], _parts(mat=c["material"], lab=c["labor"],
                               eqp=c["equipment"], sub=c["sub"]),
            hours=dmoney.D(c["hours"]).quantize(Decimal("0.01")),
            materials=mats, crew=a.get("crew", ""),
            pay_item=a.get("pay_item", ""), problem=c.get("problem", ""),
            source="civil estimate"))
    return out


@safedb.read_only
def collect(doc, job=None, lib=None):
    """{"items": [...], "total": Decimal, "by_kind": {kind: total}}.
    Read only; the drawing's takeoff is scanned once (scan_cache)."""
    from .. import annotate
    with annotate.scan_cache():
        return _collect(doc, job, lib)


def _collect(doc, job, lib):
    found = []
    if doc is not None:
        for f in (_lines, _takeoff, _assemblies):
            try:
                found += f(doc)
            except Exception:                             # noqa: BLE001
                log.warning("estimate items: %s left out", f.__name__,
                            exc_info=True)
    if job is not None:
        found += _civil(job, lib or {"crews": {}, "labor": {},
                                     "equipment": {}, "settings": {}})
    by = {k: sum((i["total"] for i in found if i["kind"] == k), Z)
          for k in KINDS}
    return {"items": found, "total": sum(by.values(), Z), "by_kind": by}


def find(est, item_id):
    return next((i for i in est["items"] if i["id"] == item_id), None)
