"""Estimate templates and bid-item templates: your own reusable sets of
items, saved as plain JSON files you keep (default folder: the
"estimate_templates" folder in QuantiSheet's data folder, settings.DIR).

Estimate template ("kind": "estimate"): items with a description, code,
unit, cost type and Mat / Lab / Eqp / Sub unit prices. An item can name a
takeoff group placeholder ("Floor area") and a quantity formula of `qty`
and `count` (see costlink.py); applying the template to a job binds each
placeholder to one of that job's takeoff groups, and the lines follow the
markups from then on. An item without a placeholder keeps its typed
quantity. A placeholder left unbound gives a typed line with quantity 0,
which Estimate Error Check then points out.

Bid-item template ("kind": "bid_items"): a pay-item list (item no.,
description, unit, quantity, weight) for the civil estimate (heavy.py).
Applying it adds the items the job doesn't have yet.

An item may carry "match": a regular expression of trade words for its
placeholder ("door"), used only to suggest takeoff groups
(starters.suggest_bindings). A placeholder may be bound to several
groups: one line per group, "<item> - <group>".

Blank starter templates (every price 0) are in starters.py; they are
only written to the templates folder when you ask (Add Starter
Templates).
"""
import os
import re

from .. import estimate_lines as EL
from . import _io, costlink, safedb

VERSION = 1
KINDS = ("estimate", "bid_items")
ITEM_KEYS = ("desc", "code", "unit", "cost_type", "mat", "lab", "eqp", "sub",
             "hours", "crew", "note", "qty", "placeholder", "group_type",
             "group_unit", "formula", "match")
BID_KEYS = ("no", "desc", "unit", "owner_qty", "weight")


class TemplateError(ValueError):
    pass


def folder():
    from .. import settings
    return os.path.join(settings.DIR, "estimate_templates")


def _file_name(name):
    s = re.sub(r"[^A-Za-z0-9 ._-]+", "_", str(name)).strip(" ._") or \
        "template"
    return s[:80] + ".json"


def from_lines(doc, name, line_ids=None, note=""):
    """A template from the document's added estimate lines (all of them,
    or those in `line_ids`)."""
    items = []
    for ln in EL.read(doc):
        if line_ids is not None and ln["id"] not in line_ids:
            continue
        it = {k: ln[k] for k in ("desc", "code", "unit", "cost_type", "mat",
                                 "lab", "eqp", "sub", "hours", "crew",
                                 "note")}
        link = ln.get("link")
        if link:
            it.update(placeholder=link["name"], group_type=link["type"],
                      group_unit=link["unit"],
                      formula=link.get("formula", ""), qty="0")
        else:
            it["qty"] = ln["qty"]
        items.append(it)
    return validate({"kind": "estimate", "version": VERSION,
                     "name": str(name), "note": str(note), "items": items})


def from_pay_items(job, name, note=""):
    return validate({"kind": "bid_items", "version": VERSION,
                     "name": str(name), "note": str(note),
                     "items": [{k: str(p.get(k, "")) for k in BID_KEYS}
                               for p in job.get("pay_items") or []]})


def validate(tpl):
    """The template, checked (TemplateError says what's wrong)."""
    if not isinstance(tpl, dict) or tpl.get("kind") not in KINDS:
        raise TemplateError("Not a QuantiSheet estimate or bid-item "
                            "template.")
    if not str(tpl.get("name") or "").strip():
        raise TemplateError("The template has no name.")
    items = tpl.get("items")
    if not isinstance(items, list):
        raise TemplateError("The template has no item list.")
    keys = ITEM_KEYS if tpl["kind"] == "estimate" else BID_KEYS
    clean = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise TemplateError(f"Item {i} isn't an item.")
        c = {k: str(it.get(k, "") if it.get(k) is not None else "")
             for k in keys}
        if tpl["kind"] == "estimate":
            try:
                costlink.check_formula(c["formula"])
                EL.new_line(c["desc"], c["qty"] or 0, c["unit"] or "ls",
                            cost_type=c["cost_type"], mat=c["mat"],
                            lab=c["lab"], eqp=c["eqp"], sub=c["sub"],
                            hours=c["hours"])
            except EL.LineError as e:
                raise TemplateError(f"Item {i} ({c['desc']}): {e}") from e
        elif not c["no"]:
            raise TemplateError(f"Bid item {i} has no item number.")
        clean.append(c)
    return {"kind": tpl["kind"], "version": VERSION, "name": str(tpl["name"]),
            "note": str(tpl.get("note") or ""), "items": clean}


def default_file(name):
    """Where a template named `name` goes in the templates folder - only
    inside the data folder (_io.data_file)."""
    return _io.data_file("estimate_templates", _file_name(name))


def save(tpl, path=None):
    tpl = validate(tpl)
    path = path or default_file(tpl["name"])
    return _io.write_json(path, tpl)


def load(path):
    try:
        data = _io.read_json(path)
    except (OSError, ValueError) as e:
        raise TemplateError(f"Can't read {os.path.basename(path)}: {e}") \
            from e
    return validate(data)


def list_saved(where=None):
    """[{"name", "kind", "path", "items"}] of the templates in a folder."""
    where = where or folder()
    out = []
    if not os.path.isdir(where):
        return out
    for f in sorted(os.listdir(where)):
        if not f.lower().endswith(".json"):
            continue
        p = os.path.join(where, f)
        try:
            t = load(p)
        except TemplateError:
            continue
        out.append({"name": t["name"], "kind": t["kind"], "path": p,
                    "items": len(t["items"])})
    return out


def placeholders(tpl):
    """The takeoff group placeholders, in order, each once."""
    out = []
    for it in tpl.get("items") or []:
        p = it.get("placeholder")
        if p and p not in out:
            out.append(p)
    return out


def _many(g):
    """The groups when `g` is a list of groups, None for one group."""
    if isinstance(g, list) and (not g or not isinstance(g[0], str)):
        return list(g)
    return None


@safedb.read_only
def apply(doc, tpl, bindings, skip_unlinked=False):
    """Add the template's items to the document as estimate lines.
    `bindings` = {placeholder: takeoff group (dict or (name, type, unit)),
    or a list of groups - one line per group}. skip_unlinked: leave out
    the items whose placeholder has no group (instead of 0-quantity
    lines); items without a placeholder always go in.
    Returns the new line ids."""
    tpl = validate(tpl)
    if tpl["kind"] != "estimate":
        raise TemplateError("That is a bid-item template; use it in the "
                            "civil estimate.")
    src = f"Template: {tpl['name']}"
    lines = []
    for it in tpl["items"]:
        vals = dict(desc=it["desc"], code=it["code"], unit=it["unit"] or "ls",
                    cost_type=it["cost_type"], mat=it["mat"], lab=it["lab"],
                    eqp=it["eqp"], sub=it["sub"], hours=it["hours"],
                    crew=it["crew"], note=it["note"], source=src)
        g = bindings.get(it["placeholder"]) if it["placeholder"] else None
        many = _many(g)
        if g is not None and many is not None and not many:
            g = None
        if g is not None:
            for one in (many if many is not None else [g]):
                link = costlink._group_key(one)
                if it["formula"]:
                    link["formula"] = it["formula"]
                elif EL.link_problem(link, vals["unit"]):
                    raise TemplateError(f"{it['desc']}: " +
                                        EL.link_problem(link, vals["unit"]))
                v = dict(vals)
                if many is not None:
                    v["desc"] = f"{it['desc']} - {link['name']}"[:300]
                lines.append(EL.new_line(qty=0, link=link, **v))
        elif skip_unlinked and it["placeholder"]:
            continue
        else:
            lines.append(EL.new_line(qty=it["qty"] or 0, **vals))
    return EL.add(doc, lines) if lines else []


def apply_bid_items(job, tpl):
    """Add the template's pay items the job doesn't have yet (by item no.);
    returns the numbers added."""
    tpl = validate(tpl)
    if tpl["kind"] != "bid_items":
        raise TemplateError("That is an estimate template.")
    have = {p.get("no") for p in job.setdefault("pay_items", [])}
    added = []
    for it in tpl["items"]:
        if it["no"] in have:
            continue
        job["pay_items"].append({"no": it["no"], "desc": it["desc"],
                                 "unit": it["unit"],
                                 "owner_qty": it["owner_qty"] or "0",
                                 "weight": it["weight"] or "1"})
        have.add(it["no"])
        added.append(it["no"])
    return added
