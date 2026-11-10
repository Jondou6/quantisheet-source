"""Where closed work orders' invoices go (QuantiSheet 1.2, Nov 5; Jon):

- "backoffice" (default): QuantiSheet Back Office, through the one-way
  interface v1 snapshot (its additive service_invoices section). Back
  Office posts each invoice once; a reversal goes in as its own entry.
- "sage": the Sage AR invoice CSV (sage_ar.py), plus its reverse file.
- "hh2": an upload folder for hh2 - each invoice as its own PDF (hh2's
  published intake is uploading invoice documents: AP > Document Flow >
  Document Acceptance) and a manifest CSV whose columns the client sets
  once (service_hh2_invoice_columns), plus a reverse manifest. hh2
  publishes no data import format for invoices; nothing here guesses one.

Every route uses the same checks: an invoice whose lines don't add up to
its total (or with no customer or lines) is held back and listed; each
invoice goes out once per route (sending again needs again=True); and a
way back out is always written. Offline: no sign-in, no network.
"""
import csv
import datetime as dt
import os

from .. import dmoney
from . import files, sage_ar

ROUTES = {"backoffice": "QuantiSheet Back Office",
          "sage": "Sage (AR invoice CSV)",
          "hh2": "hh2 (upload folder)"}
SENT = {"backoffice": "bo_sent", "sage": "sage_sent", "hh2": "hh2_sent"}
# Amount is what the customer owes; the discount, sales tax and card fee
# are columns of their own, never mixed into the work (Nov 7)
HH2_COLUMNS = ["Invoice", "Date", "Customer", "Job", "Work Order",
               "Subtotal", "Member Discount", "Sales Tax", "Card Fee",
               "Amount", "File"]
HH2_FIELDS = {"Invoice": "number", "Date": "date", "Customer": "customer",
              "Job": "site", "Work Order": "work_order_number",
              "Subtotal": "subtotal", "Member Discount": "discount",
              "Sales Tax": "tax", "Card Fee": "card_fee",
              "Amount": "total", "File": "file"}
HH2_MONEY = ("Subtotal", "Member Discount", "Sales Tax", "Card Fee",
             "Amount")


class RouteError(ValueError):
    pass


def route():
    from .. import settings
    r = settings.get("service_invoice_route") or "backoffice"
    return r if r in ROUTES else "backoffice"


def set_route(r):
    from .. import settings
    if r not in ROUTES:
        raise RouteError("Pick Back Office, Sage or hh2.")
    settings.set("service_invoice_route", r)


def pending(store, r, again=False):
    return [i for i in store.get("invoices", [])
            if again or not i.get(SENT[r])]


def check(store, invoices):
    """(good invoices, held [(number, why)]) - the same holds for every
    route (sage_ar.rows)."""
    rws, held = sage_ar.rows(store, invoices)
    ok = {r["_id"] for r in rws}
    return [i for i in invoices if i["id"] in ok], held


def preview(store, r, again=False):
    good, held = check(store, pending(store, r, again))
    total = sum((dmoney.D(i["total"]) for i in good), dmoney.D(0))
    return {"route": r, "invoices": len(good),
            "total": dmoney.text(dmoney.cents(total)), "held": held,
            "numbers": [i["number"] for i in good]}


def _stamp(now=None):
    return (now or dt.datetime.now()).isoformat(timespec="seconds")


def _mark(invs, r, extra=None, now=None):
    for i in invs:
        i[SENT[r]] = dict({"at": _stamp(now)}, **(extra or {}))


# ---- Back Office ------------------------------------------------------------

def _bo_item(inv):
    return {"id": inv["id"], "number": inv["number"], "date": inv["date"],
            "customer": inv.get("customer", ""), "site": inv.get("site", ""),
            "work_order": inv.get("work_order_number", ""),
            "lines": [{"description": ln.get("desc", ""),
                       "qty": str(ln.get("qty", "")),
                       "unit": ln.get("unit", ""),
                       "price": str(ln.get("price", "")),
                       "amount": dmoney.text(dmoney.cents(
                           dmoney.D(ln.get("amount") or 0))),
                       "taxable": bool(ln.get("taxable")),
                       "kind": ln.get("kind") or "work"}
                      for ln in inv.get("lines", [])],
            "total": dmoney.text(dmoney.cents(dmoney.D(inv["total"])))}


def backoffice_snapshot(store, invoices=(), reversals=()):
    """Interface v1, the Service Department job, only service_invoices
    (no time cards - Back Office keeps what came in before)."""
    from . import timecards
    snap = timecards.snapshot({"orders": []})
    snap["source"]["file"] = "service invoices"
    snap["service_invoices"] = [_bo_item(i) for i in invoices] + [
        {"id": i["id"], "number": i["number"],
         "date": dt.date.today().isoformat(), "reverse": True,
         "reason": why} for i, why in reversals]
    return snap


def send_backoffice(store, invoices=None, again=False, start=None, now=None):
    """Hand the invoices to Back Office (start: backoffice_hook.
    launch_snapshot, or a stand-in in tests). Marks them sent."""
    invoices = pending(store, "backoffice", again) if invoices is None \
        else invoices
    if not again and any(i.get("bo_sent") for i in invoices):
        raise RouteError("Already sent to Back Office: " + ", ".join(
            i["number"] for i in invoices if i.get("bo_sent")))
    good, held = check(store, invoices)
    if not good:
        raise RouteError("Nothing to send: " + ("; ".join(
            f"{n}: {w}" for n, w in held) or "every invoice has gone to "
            "Back Office."))
    snap = backoffice_snapshot(store, good)
    if start is None:
        from .. import backoffice_hook
        start = backoffice_hook.launch_snapshot
    start(snap)
    _mark(good, "backoffice", now=now)
    return {"snapshot": snap, "sent": [i["number"] for i in good],
            "held": held}


def reverse_backoffice(store, invoice_id, why, start=None):
    """Back one invoice out of Back Office: it voids the posted invoice
    there (the ledger keeps both entries)."""
    inv = next((i for i in store.get("invoices", [])
                if i["id"] == invoice_id), None)
    if inv is None:
        raise RouteError("That invoice isn't on file.")
    if not inv.get("bo_sent"):
        raise RouteError(f"{inv['number']} was never sent to Back Office.")
    if inv.get("bo_reversed"):
        raise RouteError(f"{inv['number']} was already reversed.")
    if not files.txt(why):
        raise RouteError("Say why it is being reversed.")
    snap = backoffice_snapshot(store, (), [(inv, files.txt(why, 200))])
    if start is None:
        from .. import backoffice_hook
        start = backoffice_hook.launch_snapshot
    start(snap)
    inv["bo_reversed"] = {"at": _stamp(), "why": files.txt(why, 200)}
    return snap


# ---- hh2 upload folder -----------------------------------------------------

def hh2_columns():
    from .. import settings
    cols = settings.get("service_hh2_invoice_columns") or HH2_COLUMNS
    cols = [c for c in cols if c in HH2_FIELDS]
    return cols or list(HH2_COLUMNS)


def export_hh2(store, folder, invoices=None, again=False, comp=None,
               now=None):
    """Write each invoice's PDF and a manifest (and its reverse) into
    `folder` for uploading to hh2. Marks them sent."""
    from . import workorder
    invoices = pending(store, "hh2", again) if invoices is None else invoices
    if not again and any(i.get("hh2_sent") for i in invoices):
        raise RouteError("Already in an hh2 folder: " + ", ".join(
            i["number"] for i in invoices if i.get("hh2_sent")))
    good, held = check(store, invoices)
    if not good:
        raise RouteError("Nothing to send: " + ("; ".join(
            f"{n}: {w}" for n, w in held) or "every invoice has gone to "
            "hh2."))
    os.makedirs(folder, exist_ok=True)
    rows = []
    for i in good:
        name = f"{i['number']}.pdf"
        workorder.invoice_pdf(store, i["id"], os.path.join(folder, name),
                              comp=comp)
        rows.append(dict(i, file=name))
    cols = hh2_columns()
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d %H%M")
    man = os.path.join(folder, f"hh2 invoices {stamp}.csv")
    rev = os.path.join(folder, f"hh2 invoices {stamp} (reverse).csv")
    for path, sign in ((man, 1), (rev, -1)):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(cols)
            for r in rows:
                out = []
                for c in cols:
                    v = r.get(HH2_FIELDS[c], "")
                    if c == "Subtotal" and v in (None, ""):
                        v = r.get("total", "")       # made before Nov 7
                    if c in HH2_MONEY:
                        v = dmoney.text(dmoney.cents(dmoney.D(v or 0)) * sign)
                        if c == "Member Discount" and v.startswith("-"):
                            v = v[1:]
                        elif c == "Member Discount" and v != "0.00":
                            v = "-" + v
                    out.append(sage_ar._clean(v))
                w.writerow(out)
    _mark(good, "hh2", {"folder": folder}, now=now)
    return {"folder": folder, "manifest": man, "reverse": rev,
            "sent": [i["number"] for i in good], "held": held}


def send(store, r=None, target=None, again=False, start=None, comp=None):
    """One call for the window: the route in settings unless given.
    target is the CSV path (Sage) or folder (hh2); Back Office needs none."""
    r = r or route()
    if r == "backoffice":
        return send_backoffice(store, again=again, start=start)
    if not target:
        raise RouteError("Pick where to save the file.")
    if r == "sage":
        out = sage_ar.export(store, target, again=again)
        return {"file": out["file"], "reverse": out["reverse"],
                "sent": [], "held": out["preview"]["held"]}
    return export_hh2(store, target, again=again, comp=comp)
