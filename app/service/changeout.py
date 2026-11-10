"""Equipment changeout proposal (QuantiSheet 1.2, #11).

A replacement proposal is a good / better / best quote (gbb.py) with the
changeout facts on it: the unit being replaced, the outside designer's
load report when one is attached (loadcalc.py - QuantiSheet doesn't
calculate loads), the new equipment for each choice (brand, model, tons,
efficiency, warranty), the permit fee, duct changes and the warranty
registration. Equipment prices come from the pricebook tasks picked for
each choice, member prices when an agreement covers the customer - the
same as any quote; the permit fee and duct changes are added to every
choice at their own price.

Signed: the chosen option opens a flat-rate work order with the permit
already on it (HVAC changeouts need one, by the permit settings).
Installed: the new unit goes on the service records, the old one is noted
as replaced, and the warranty registration countdown starts.

No sizing math: the designer's report and the contractor decide the
size; the proposal shows what the report says, or that there isn't one.
"""
from .. import dmoney
from . import files, gbb



class ChangeoutError(ValueError):
    pass


EQUIP_KEYS = ("brand", "model", "tons", "efficiency", "warranty", "line")


EQUIP_KEYS = ("brand", "model", "tons", "efficiency", "warranty", "line")


def oversize_pct():
    from .. import settings
    try:
        v = settings.get("service_changeout_oversize_pct")
        return OVERSIZE_PCT if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return OVERSIZE_PCT


def _equip(raw, name):
    raw = raw or {}
    out = {k: files.txt(raw.get(k), 120) for k in EQUIP_KEYS}
    if not out["brand"] or not out["model"]:
        raise ChangeoutError(f"{name}: enter the brand and model.")
    if out["tons"]:
        try:
            t = float(out["tons"])
        except ValueError:
            raise ChangeoutError(f"{name}: tons must be a number.") from None
        if not 0.5 <= t <= 50:
            raise ChangeoutError(f"{name}: tons is out of range.")
        out["tons"] = f"{t:g}"
    return out


def create(quotes, book, customer, site, choices, equipment, records=None,
           equipment_id="", existing="", load_job=None, agreements=None,
           property_id="", title="", notes="", when=None, member=None,
           permit_fee="", permit_required=True, duct_changes="",
           duct_price=""):
    """`choices` {"Good": [task ids], ...} as for gbb.create; `equipment`
    {"Good": {brand, model, tons, efficiency, warranty, line}, ...} for
    every choice offered. `load_job` is an outside load report job
    (loadcalc.py) or None. A permit fee (permit required is ON for a
    changeout, Jon's habit) and duct changes (what, and the price) go on
    every choice. Returns the quote id."""
    offered = [n for n in gbb.CHOICES if (choices or {}).get(n)]
    eq = {}
    for n in offered:
        eq[n] = _equip((equipment or {}).get(n), n)
    old = {}
    if equipment_id:
        from ..estimating import service as records_api
        found = records_api.find(records, equipment_id) if records else None
        if not found or "kind" not in found:
            raise ChangeoutError("That unit isn't on the service records.")
        old = {"equipment_id": equipment_id,
               "text": " ".join(p for p in (found.get("kind"),
                                            found.get("make"),
                                            found.get("model"),
                                            found.get("serial")) if p),
               "installed": found.get("installed") or ""}
        property_id = property_id or found.get("property") or ""
    elif existing:
        old = {"equipment_id": "", "text": files.txt(existing, 200),
               "installed": ""}
    else:
        raise ChangeoutError("Describe the unit being replaced.")
    fee = _money(permit_fee, "Permit fee") if permit_required else ""
    duct_what = files.txt(duct_changes, 300)
    duct = _money(duct_price, "Duct changes price")
    if duct and not duct_what:
        raise ChangeoutError("Say what the duct changes are.")
    try:
        qid = gbb.create(quotes, book, customer, site, choices,
                         member=member, agreements=agreements,
                         property_id=property_id,
                         equipment_id=equipment_id,
                         title=title or "Equipment replacement options",
                         notes=notes, when=when)
    except gbb.QuoteRecordError as e:
        raise ChangeoutError(str(e)) from e
    q = gbb.get(quotes, qid)
    extra = []
    if fee:
        extra.append({"task_id": "", "code": "", "name":
                      "Permit and inspection fees", "price": fee,
                      "cost": fee, "hours": "0.00", "labor_cost": "0.00",
                      "parts": []})
    if duct_what:
        extra.append({"task_id": "", "code": "", "name":
                      "Duct changes: " + duct_what, "price": duct or "0.00",
                      "cost": "0.00", "hours": "0.00", "labor_cost": "0.00",
                      "parts": []})
    for c in q["choices"]:
        c["lines"] += [dict(x) for x in extra]
        c["total"] = gbb._total(c["lines"])
        c["cost"] = gbb._total(c["lines"], "cost")
    report = None
    if load_job:
        from . import loadcalc
        r = load_job.get("report") or {}
        report = {"id": load_job["id"], "number": load_job["number"],
                  "attached": bool(r), "status": loadcalc.status(load_job),
                  "designer": r.get("designer", ""), "date": r.get("date", ""),
                  "cooling_btuh": r.get("cooling_btuh"),
                  "heating_btuh": r.get("heating_btuh"),
                  "recommended": r.get("recommended", "")}
    q["kind"] = "changeout"
    q["changeout"] = {
        "existing": old, "load_report": report, "equipment": eq,
        "permit_needed": bool(permit_required), "permit_fee": fee,
        "duct_changes": duct_what, "duct_price": duct,
        "installed": None}
    return qid


def load_warning(q):
    """'' or the warning the office sees: no outside load report."""
    r = (q.get("changeout") or {}).get("load_report")
    if r and r.get("attached"):
        return ""
    return ("No load report attached - get the outside designer's report "
            "before the equipment size is final.")


def _money(v, what):
    if v in (None, ""):
        return ""
    try:
        return files.money(v, what)
    except files.FileError as e:
        raise ChangeoutError(str(e)) from e


def accept(quotes, qid, name, orders, records=None, signed_by="",
           when=None, tech="", scheduled=""):
    """Signed: a flat-rate work order with the equipment and the permit
    (job type HVAC changeout) on it. Returns the work order id."""
    q = gbb.get(quotes, qid)
    if q.get("kind") != "changeout":
        raise ChangeoutError("That quote isn't a changeout proposal.")
    try:
        wo_id = gbb.accept(quotes, qid, name, orders, records,
                           signed_by=signed_by, when=when, tech=tech,
                           scheduled=scheduled)
    except gbb.QuoteRecordError as e:
        raise ChangeoutError(str(e)) from e
    from . import permits, workorder
    wo = workorder.get(orders, wo_id)
    co = q["changeout"]
    e = co["equipment"][name]
    wo["changeout"] = {"quote": q["number"], "choice": name,
                       "equipment": dict(e), "replaces": co["existing"]}
    wo["complaint"] = (f"{q['number']} {name}: replace "
                       f"{co['existing']['text'] or 'existing unit'} with "
                       f"{e['brand']} {e['model']}")[:1000]
    p = {"job_type": "hvac_changeout",
         "needed": bool(co.get("permit_needed", True)),
         "jurisdiction": permits.remembered(orders, wo), "number": "",
         "other_office": "", "inspections": []}
    wo["permit"] = p
    return wo_id


def install(quotes, qid, records, warranty_store, installed, serial="",
            commercial=False):
    """The new unit is in: add it to the service records, note the old
    unit as replaced, start the warranty registration countdown. Returns
    the new equipment id."""
    from ..estimating import service as records_api
    from . import warranty
    q = gbb.get(quotes, qid)
    co = q.get("changeout") or {}
    if q.get("status") != "accepted":
        raise ChangeoutError("Mark the proposal signed first.")
    if co.get("installed"):
        raise ChangeoutError(f"{q['number']} is already installed.")
    if not q.get("property_id"):
        raise ChangeoutError("The proposal has no service-record site; add "
                             "the site to the service records first.")
    try:
        inst = files.iso_date(installed, "Install date", blank_ok=False)
    except files.FileError as e:
        raise ChangeoutError(str(e)) from e
    e = co["equipment"][q["chosen"]]
    try:
        eid = records_api.add_equipment(
            records, q["property_id"], "HVAC " + (f"{e['tons']}-ton "
                                                  if e["tons"] else "") +
            "system", make=e["brand"], model=e["model"],
            serial=files.txt(serial, 80), installed=inst,
            notes=f"Installed under {q['number']} ({q['work_order']})")
    except records_api.ServiceError as err:
        raise ChangeoutError(str(err)) from err
    old_id = (co.get("existing") or {}).get("equipment_id")
    if old_id:
        old = records_api.find(records, old_id)
        if old and "kind" in old:
            old["notes"] = ((old.get("notes") or "") +
                            f"\nReplaced {inst} under {q['number']}").strip()
            old["replaced"] = inst
    brand = warranty.brand_of(e["brand"])
    text = " ".join(p for p in (e["brand"], e["model"], serial) if p)
    warranty.set_unit(warranty_store, eid, brand, installed=inst,
                      line=e.get("line") or "", commercial=commercial,
                      unit_text=text)
    co["installed"] = {"date": inst, "equipment_id": eid,
                       "serial": files.txt(serial, 80)}
    return eid


def proposal_pdf(q, path, comp=None):
    """The customer's copy: what is being replaced, the size basis, the
    options side by side with price, what's included, permit and warranty,
    and a signature line."""
    from .pdfdoc import Sheet, fit
    co = q.get("changeout")
    if not co:
        raise ChangeoutError("That quote isn't a changeout proposal.")
    sheet = Sheet("Equipment Replacement Proposal", comp,
                  subtitle=q["number"])
    sheet.section("01", "For")
    y = sheet.y + 12
    sheet.text(36, y, q["customer"], 11, True)
    sheet.text(36, y + 14, q["site"], 9)
    sheet.text(400, y, f"Date: {q['date']}", 9)
    if q.get("member"):
        sheet.text(400, y + 14, "Member prices"
                   + (f" ({q['agreement']})" if q.get("agreement") else ""),
                   9)
    sheet.y = y + 30
    sheet.section("02", "What we're replacing")
    sheet.y += 14
    ex = co["existing"]
    sheet.text(36, sheet.y, fit(ex["text"] + (f" (installed "
                                              f"{ex['installed']})" if
                                              ex.get("installed") else ""),
                                540, 9.5), 9.5)
    lr = co.get("load_report")
    sheet.y += 14
    if lr and lr.get("attached"):
        bits = [f"Load report by {lr['designer']} ({lr['date']})"]
        if lr.get("cooling_btuh"):
            bits.append(f"cooling {lr['cooling_btuh']:,} BTU/h")
        if lr.get("heating_btuh"):
            bits.append(f"heating {lr['heating_btuh']:,} BTU/h")
        if lr.get("recommended"):
            bits.append(f"recommended {lr['recommended']}")
        sheet.text(36, sheet.y, fit("; ".join(bits) + ".", 540, 8.5), 8.5)
    sheet.y += 8
    sheet.section("03", "Your options")
    cols = [c for c in q["choices"]]
    w = 540 / max(1, len(cols))
    y = sheet.y + 14
    sheet.need(170)
    bottom = y
    for i, c in enumerate(cols):
        x = 36 + i * w
        e = co["equipment"][c["name"]]
        sheet.text(x, y, c["name"], 11, True)
        sheet.text(x, y + 16, fit(f"{e['brand']} {e['model']}", w - 8, 9),
                   9, True)
        yy = y + 30
        for t in (f"{e['tons']} tons" if e["tons"] else "",
                  e["efficiency"], (f"Warranty: {e['warranty']}"
                                    if e["warranty"] else "")):
            if t:
                sheet.text(x, yy, fit(t, w - 8, 8.5), 8.5)
                yy += 12
        for line in c["lines"]:
            sheet.text(x, yy, fit("- " + line["name"], w - 8, 8), 8)
            yy += 11
        sheet.text(x, yy + 6, dmoney.fmt(c["total"]), 12, True)
        yy += 22
        bottom = max(bottom, yy)
    sheet.y = bottom + 8
    sheet.section("04", "Included with every option")
    for line in (("Permit and inspections: pulled by us; the fees are a "
                  "line in each option." if co.get("permit_fee") else
                  "Permit and inspections: pulled by us and included."
                  if co.get("permit_needed") else
                  "Permit: not required for this job."),
                 "Manufacturer warranty registration: done by us after "
                 "install, inside the maker's registration window.",
                 "Removal and disposal of the old equipment."):
        sheet.need(14)
        sheet.y += 12
        sheet.text(36, sheet.y, fit(line, 540, 8.5), 8.5)
    if q.get("notes"):
        sheet.y += 12
        sheet.text(36, sheet.y, fit(q["notes"], 540, 8.5), 8.5)
    sheet.need(60)
    sheet.y += 18
    sheet.section("", "Accepted")
    y = sheet.y + 8
    for name, label, x0, x1 in (("co_choice", "Option chosen", 36, 170),
                                ("co_signature", "Signature", 190, 430),
                                ("co_date", "Date", 450, 576)):
        sheet.label(x0, y, label)
        sheet.text_field(name, (x0, y + 2, x1, y + 16), "")
    sheet.y = y + 26
    return sheet.save(path)


def summary(q):
    co = q.get("changeout") or {}
    base = gbb.summary(q)
    if co.get("installed"):
        base += f"; installed {co['installed']['date']}"
    return base
