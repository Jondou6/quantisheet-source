"""Service invoices out to Sage (Accounts Receivable), Nov 5.

One CSV row per invoice line, for Sage's Accounts Receivable invoice
import: Customer, Invoice, Date, Due Date, Job, Description, Quantity,
Unit, Unit Price, Amount, Account. The column names and order are a
setting (service_sage_ar_columns) so they can be matched to the import
layout set up in Sage - check one export against your import settings
before the first real run.

Rules:
- only closed tickets' invoices; each invoice goes out once (marked
  "sent to Sage" with the file and time); sending again needs again=True
- an invoice whose lines don't add up to its total is held back and
  listed, never exported
- a preview says what would be written; every export also writes a
  "reverse" file (amounts negated) that backs it out if it went wrong
- no formulas: text a spreadsheet would run (=, +, -, @) is cleaned
"""
import csv
import datetime as dt
import os

from .. import dmoney

DEFAULT_COLUMNS = ["Customer", "Invoice", "Date", "Due Date", "Job",
                   "Description", "Quantity", "Unit", "Unit Price",
                   "Amount", "Account"]
FIELDS = {"Customer": "customer", "Invoice": "invoice", "Date": "date",
          "Due Date": "due", "Job": "job", "Description": "desc",
          "Quantity": "qty", "Unit": "unit", "Unit Price": "price",
          "Amount": "amount", "Account": "account"}


class SageARError(ValueError):
    pass


def columns():
    from .. import settings
    cols = settings.get("service_sage_ar_columns") or DEFAULT_COLUMNS
    cols = [c for c in cols if c in FIELDS]
    return cols or list(DEFAULT_COLUMNS)


def _clean(text):
    from .. import safecell
    t = "" if text is None else str(text)
    while t and safecell.risky(t):
        t = t.lstrip("".join(safecell.FORMULA_START)).lstrip()
    return t


def _due(date_text, days):
    try:
        d = dt.date.fromisoformat(str(date_text)[:10])
    except ValueError:
        return ""
    return (d + dt.timedelta(days=int(days))).isoformat()


def pending(store, again=False):
    """Invoices not yet sent to Sage (all of them with again=True)."""
    return [i for i in store.get("invoices", [])
            if again or not i.get("sage_sent")]


def rows(store, invoices=None, terms_days=30, account="", job=""):
    """(rows, held). rows are dicts keyed by FIELDS values; held lists
    (invoice number, reason) for invoices that can't go out as they are."""
    out, held = [], []
    for inv in (pending(store) if invoices is None else invoices):
        lines = inv.get("lines") or []
        if not lines:
            held.append((inv.get("number"), "no lines"))
            continue
        try:
            total = sum((dmoney.cents(dmoney.D(ln.get("amount") or 0))
                         for ln in lines), dmoney.D(0))
            stated = dmoney.cents(dmoney.D(inv.get("total") or 0))
        except Exception:                                 # noqa: BLE001
            held.append((inv.get("number"), "an amount isn't a number"))
            continue
        if total != stated:
            held.append((inv.get("number"),
                         f"lines add to {dmoney.text(total)}, invoice says "
                         f"{dmoney.text(stated)}"))
            continue
        if not str(inv.get("customer") or "").strip():
            held.append((inv.get("number"), "no customer"))
            continue
        for ln in lines:
            out.append({
                "customer": inv.get("customer", ""),
                "invoice": inv.get("number", ""),
                "date": inv.get("date", ""),
                "due": _due(inv.get("date", ""), terms_days),
                "job": job or inv.get("site", ""),
                "desc": ln.get("desc", ""),
                "qty": ln.get("qty", ""),
                "unit": ln.get("unit", ""),
                "price": ln.get("price", ""),
                "amount": ln.get("amount", ""),
                "account": account,
                "_id": inv.get("id")})
    return out, held


def preview(rws, held):
    total = sum((dmoney.D(r["amount"] or 0) for r in rws), dmoney.D(0))
    invs = sorted({r["invoice"] for r in rws})
    return {"invoices": len(invs), "lines": len(rws),
            "total": dmoney.text(dmoney.cents(total)), "held": list(held)}


def _write(path, rws, cols, sign=1):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(cols)
        for r in rws:
            row = []
            for c in cols:
                k = FIELDS[c]
                v = r.get(k, "")
                if sign < 0 and k in ("amount", "qty") and v not in ("", None):
                    v = dmoney.text(-dmoney.D(v)) if k == "amount" else \
                        str(-dmoney.D(v))
                row.append(_clean(v))
            w.writerow(row)
    return path


def export(store, path, invoices=None, again=False, terms_days=30,
           account="", now=None):
    """Write the Sage file and its reverse file; mark the invoices sent.
    Returns {"file", "reverse", "preview"}. The caller saves the store."""
    if invoices is None:
        invoices = pending(store, again=again)
    elif not again:
        sent = [i.get("number") for i in invoices if i.get("sage_sent")]
        if sent:
            raise SageARError("Already sent to Sage: " + ", ".join(sent) +
                              ". Choose Send Again to send them anyway.")
    rws, held = rows(store, invoices, terms_days=terms_days, account=account)
    if not rws:
        raise SageARError("Nothing to send: " + (
            "; ".join(f"{n}: {why}" for n, why in held) if held
            else "every invoice has already gone to Sage."))
    cols = columns()
    _write(path, rws, cols)
    base, ext = os.path.splitext(path)
    rev = _write(f"{base} (reverse){ext or '.csv'}", rws, cols, sign=-1)
    when = (now or dt.datetime.now()).isoformat(timespec="seconds")
    ids = {r["_id"] for r in rws}
    for inv in store.get("invoices", []):
        if inv.get("id") in ids:
            inv["sage_sent"] = {"at": when, "file": os.path.basename(path)}
    return {"file": path, "reverse": rev, "preview": preview(rws, held)}
