"""Migration import with opening balances (addendum P2-17). Full-books.

Sources, all files the user exports themselves:
- QuickBooks Desktop IIF files (the tab-separated Intuit Interchange
  Format): lists (accounts, customers, vendors, items, classes) and open
  invoices and bills;
- the CSV files QuickBooks Online's own 'Export data' produces;
- generic CSV with a column map.
No Intuit API and no QuickBooks company files (fileguard refuses them).
Preview first, with problems; nothing posts until Apply; a batch can be
undone as a whole. QuickBooks is a trademark of Intuit Inc. QuantiSheet is
not affiliated with or endorsed by Intuit.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from . import ap, cents, clock, fileguard, ledger, store

IIF_TYPES = {"BANK": ("asset", "bank"), "AR": ("asset", "ar"),
             "OCASSET": ("asset", ""), "FIXASSET": ("asset", ""),
             "OASSET": ("asset", ""), "AP": ("liability", "ap"),
             "CCARD": ("liability", "credit card"),
             "OCLIAB": ("liability", ""), "LTLIAB": ("liability", ""),
             "EQUITY": ("equity", ""), "INC": ("income", ""),
             "COGS": ("cogs", ""), "EXP": ("expense", ""),
             "EXINC": ("other income", ""), "EXEXP": ("other expense", "")}
QBO_TYPES = {"bank": ("asset", "bank"),
             "accounts receivable (a/r)": ("asset", "ar"),
             "accounts receivable": ("asset", "ar"),
             "other current assets": ("asset", ""),
             "other current asset": ("asset", ""),
             "fixed assets": ("asset", ""), "fixed asset": ("asset", ""),
             "other assets": ("asset", ""), "other asset": ("asset", ""),
             "accounts payable (a/p)": ("liability", "ap"),
             "accounts payable": ("liability", "ap"),
             "credit card": ("liability", "credit card"),
             "other current liabilities": ("liability", ""),
             "other current liability": ("liability", ""),
             "long term liabilities": ("liability", ""),
             "long term liability": ("liability", ""),
             "equity": ("equity", ""), "income": ("income", ""),
             "cost of goods sold": ("cogs", ""), "expenses": ("expense", ""),
             "expense": ("expense", ""), "other income": ("other income", ""),
             "other expense": ("other expense", "")}
CONTROL = ("ar", "ap", "retainage receivable", "retainage payable")


class MigrateError(ValueError):
    pass


def read_file(path) -> str:
    """Text of an import file. QuickBooks company files are refused."""
    fileguard.refuse_company_file(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _date(s):
    s = (s or "").strip()
    for f in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    raise MigrateError(f"date {s!r} can't be read")


# ---- IIF -----------------------------------------------------------------

def parse_iif(text: str) -> dict:
    """{'ACCNT': [rows], 'CUST': [...], 'VEND': [...], 'INVITEM': [...],
    'CLASS': [...], 'TRNS': [{'trns': row, 'spl': [rows]}]}"""
    heads, out = {}, {"TRNS": []}
    cur = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        f = raw.rstrip("\r\n").split("\t")
        tag = f[0].strip()
        if tag.startswith("!"):
            heads[tag[1:]] = [h.strip() for h in f[1:]]
            continue
        cols = heads.get(tag)
        if tag == "ENDTRNS":
            if cur:
                out["TRNS"].append(cur)
            cur = None
            continue
        if cols is None:
            continue
        row = {cols[i]: (f[i + 1].strip() if i + 1 < len(f) else "")
               for i in range(len(cols))}
        if tag == "TRNS":
            cur = {"trns": row, "spl": []}
        elif tag == "SPL":
            if cur is not None:
                cur["spl"].append(row)
        else:
            out.setdefault(tag, []).append(row)
    return out


def _existing(office):
    db = office.db
    return {"acct_names": {r["name"].lower() for r in db.rows(
                "SELECT name FROM accounts WHERE deleted = 0")} |
            {(r["qb_name"] or "").lower() for r in db.rows(
                "SELECT qb_name FROM accounts WHERE deleted = 0")},
            "acct_numbers": {r["number"] for r in db.rows(
                "SELECT number FROM accounts")},
            "customers": {r["name"].lower() for r in db.rows(
                "SELECT name FROM customers WHERE deleted = 0")},
            "vendors": {r["name"].lower() for r in db.rows(
                "SELECT name FROM vendors WHERE deleted = 0")},
            "ar": {r["number"] for r in db.rows(
                "SELECT number FROM ar_invoices WHERE deleted = 0")},
            "ap": {(r["vendor_id"], r["invoice_no"]) for r in db.rows(
                "SELECT vendor_id, invoice_no FROM ap_invoices WHERE "
                "deleted = 0")}}


def preview_iif(office, path) -> dict:
    d = parse_iif(read_file(path))
    ex = _existing(office)
    plan = {"accounts": [], "customers": [], "vendors": [], "items": [],
            "classes": [], "invoices": [], "bills": []}
    problems, skipped = [], {k: 0 for k in plan}
    for r in d.get("ACCNT", []):
        name = r.get("NAME", "")
        t = IIF_TYPES.get(r.get("ACCNTTYPE", "").upper())
        if t is None:
            problems.append(f"account '{name}': unknown account type "
                            f"'{r.get('ACCNTTYPE', '')}'")
            continue
        if name.lower() in ex["acct_names"] or \
                (r.get("ACCNUM") and r["ACCNUM"] in ex["acct_numbers"]):
            skipped["accounts"] += 1
            continue
        plan["accounts"].append({"name": name, "number": r.get("ACCNUM", ""),
                                 "type": t[0], "subtype": t[1],
                                 "description": r.get("DESC", "")})
    for key, tag, field in (("customers", "CUST", "NAME"),
                            ("vendors", "VEND", "NAME"),
                            ("items", "INVITEM", "NAME"),
                            ("classes", "CLASS", "NAME")):
        for r in d.get(tag, []):
            n = r.get(field, "")
            if key in ("customers", "vendors") and n.lower() in ex[key]:
                skipped[key] += 1
                continue
            plan[key].append(r)
    for t in d["TRNS"]:
        tr = t["trns"]
        kind = tr.get("TRNSTYPE", "").upper()
        try:
            amt = cents.parse_amount(tr.get("AMOUNT", ""))
            dt = _date(tr.get("DATE"))
            due = _date(tr["DUEDATE"]) if tr.get("DUEDATE") else ""
        except (cents.MoneyError, MigrateError) as e:
            problems.append(f"{kind} {tr.get('DOCNUM', '')}: {e}")
            continue
        total = sum(cents.parse_amount(s.get("AMOUNT") or "0")
                    for s in t["spl"]) + amt
        if total != 0:
            problems.append(f"{kind} {tr.get('DOCNUM', '')}: does not "
                            f"balance ({cents.fmt(total)})")
            continue
        rec = {"number": tr.get("DOCNUM", ""), "name": tr.get("NAME", ""),
               "date": dt, "due": due, "amount": abs(amt),
               "memo": tr.get("MEMO", "")}
        if kind == "INVOICE":
            if rec["number"] in ex["ar"]:
                skipped["invoices"] += 1
                continue
            plan["invoices"].append(rec)
        elif kind == "BILL":
            v = ap.vendor_by_name(office, rec["name"])
            if v and (v["id"], rec["number"]) in ex["ap"]:
                skipped["bills"] += 1
                continue
            plan["bills"].append(rec)
    return {"counts": {k: len(v) for k, v in plan.items()},
            "skipped": skipped, "problems": problems, "plan": plan,
            "source": "iif"}


def _new_batch(office, source, files):
    hashes = {}
    for f in files:
        try:
            hashes[f] = store.file_hash(f)
        except OSError:
            hashes[f] = ""
    return office.db.insert("import_batches", source=source,
                            files=json.dumps(hashes), counts="{}",
                            created="{}", applied_by=office.who,
                            ts=clock.iso_now(), status="Applied")


def _refuse_closed(office, dates) -> None:
    """Migration never posts into closed books (review fix)."""
    ct = ledger.closed_through(office)
    bad = sorted({str(d)[:10] for d in dates if d and ct and
                  str(d)[:10] <= ct})
    if bad:
        raise MigrateError(
            f"The books are closed through {ct}; nothing was imported. "
            f"{len(bad)} posting date(s) fall in the closed period "
            f"({bad[0]}{' to ' + bad[-1] if len(bad) > 1 else ''}). Pick a "
            f"conversion date after {ct}, or have an Admin reopen the books.")


def _apply_plan(office, plan, batch, as_of=None) -> dict:
    """Creates the planned records in batch `batch`; returns created ids
    per table. Open items post against Opening balance equity on the
    conversion date (or their own date) so aging works on day one."""
    _refuse_closed(office, [as_of or x["date"] for x in
                            plan["invoices"] + plan["bills"]])
    db = office.db
    made = {k: [] for k in ("accounts", "customers", "vendors", "items",
                            "classes", "ar_invoices", "ap_invoices",
                            "journal_entries")}
    used = {r["number"] for r in db.rows("SELECT number FROM accounts")}
    nxt = 10000
    for a in plan["accounts"]:
        num = a["number"]
        if not num or num in used:
            while str(nxt) in used:
                nxt += 1
            num = str(nxt)
        used.add(num)
        made["accounts"].append(db.insert(
            "accounts", number=num, name=a["name"], type=a["type"],
            subtype=a["subtype"], active=1, qb_name=a["name"],
            sage_gl="", description=a.get("description", ""), system=0))
    for c in plan["customers"]:
        made["customers"].append(db.insert(
            "customers", name=c.get("NAME", ""),
            address=" ".join(x for x in (c.get("BADDR1", ""),
                                         c.get("BADDR2", "")) if x),
            email=c.get("EMAIL", ""), phone=c.get("PHONE1", ""),
            import_batch=batch))
    for v in plan["vendors"]:
        made["vendors"].append(db.insert(
            "vendors", name=v.get("NAME", ""), terms=30,
            is_1099=1 if v.get("1099", "").upper() in ("Y", "YES") else 0,
            w9=None, email=v.get("EMAIL", ""), phone=v.get("PHONE1", "")))
    for it in plan["items"]:
        made["items"].append(db.insert("items", name=it.get("NAME", ""),
                                       kind=it.get("INVITEMTYPE", ""),
                                       account=it.get("ACCNT", ""),
                                       import_batch=batch))
    for c in plan["classes"]:
        made["classes"].append(db.insert("classes", name=c.get("NAME", ""),
                                         import_batch=batch))
    obe = ledger.default_account(office, "opening_equity")
    for inv in plan["invoices"]:
        due = inv["due"] or inv["date"]
        iid = db.insert("ar_invoices", number=inv["number"], job_id=None,
                        customer=inv["name"], type="Other",
                        invoice_date=inv["date"], due_date=due,
                        gl_date=as_of or inv["date"], amount=inv["amount"],
                        retainage=0, tax=0, total=inv["amount"],
                        status="Approved", note="opening item")
        eid = ledger.post(office, as_of or inv["date"], [
            {"account": ledger.default_account(office, "ar"),
             "debit": inv["amount"], "party": inv["name"]},
            {"account": obe, "credit": inv["amount"], "party": inv["name"]}],
            "ar_invoice", iid, f"Opening item {inv['number']}",
            batch_id=batch)
        db.update("ar_invoices", iid, entry_id=eid)
        made["ar_invoices"].append(iid)
        made["journal_entries"].append(eid)
    for b in plan["bills"]:
        v = ap.vendor_by_name(office, b["name"])
        vid = v["id"] if v else db.insert("vendors", name=b["name"], terms=30)
        if not v:
            made["vendors"].append(vid)
        iid = db.insert("ap_invoices",
                        number=db.next_number("AP", "AP-{n:04d}"),
                        vendor_id=vid, invoice_no=b["number"],
                        invoice_date=b["date"], due_date=b["due"] or b["date"],
                        gl_date=as_of or b["date"], total=b["amount"], tax=0,
                        retainage=0, status="Approved")
        eid = ledger.post(office, as_of or b["date"], [
            {"account": obe, "debit": b["amount"], "party": b["name"]},
            {"account": ledger.default_account(office, "ap"),
             "credit": b["amount"], "party": b["name"]}],
            "ap_invoice", iid, f"Opening bill {b['number']}", batch_id=batch)
        db.update("ap_invoices", iid, entry_id=eid)
        made["ap_invoices"].append(iid)
        made["journal_entries"].append(eid)
    return made


def apply_iif(office, path, as_of=None) -> int:
    office.require_full_books("Migration import")
    office.require("gl.manage", "import", "iif")
    pv = preview_iif(office, path)
    with office.db.tx():
        batch = _new_batch(office, "iif", [path])
        made = _apply_plan(office, pv["plan"], batch, as_of)
        office.db.update("import_batches", batch,
                         counts=json.dumps(pv["counts"]),
                         created=json.dumps(made))
        office.audit("import", "import_batch", batch, None,
                     {"source": "iif", "counts": pv["counts"],
                      "problems": pv["problems"]})
    return batch


# ---- QuickBooks Online 'Export data' CSV files -----------------------------

def _csv_rows(path):
    return list(csv.DictReader(io.StringIO(read_file(path))))


def _col(r, *names):
    low = {(k or "").strip().lower(): v for k, v in r.items()}
    for n in names:
        if n.lower() in low:
            return (low[n.lower()] or "").strip()
    return ""


def preview_qbo(office, files: dict) -> dict:
    """files: {'accounts': path, 'customers': path, 'vendors': path}
    (any subset), as QuickBooks Online's Export data writes them."""
    ex = _existing(office)
    plan = {"accounts": [], "customers": [], "vendors": [], "items": [],
            "classes": [], "invoices": [], "bills": []}
    problems = []
    if files.get("accounts"):
        for r in _csv_rows(files["accounts"]):
            name = _col(r, "Account", "Name", "Full name")
            typ = _col(r, "Type", "Account type")
            t = QBO_TYPES.get(typ.lower())
            if not name:
                continue
            if t is None:
                problems.append(f"account '{name}': unknown account type "
                                f"'{typ}'")
                continue
            if name.lower() in ex["acct_names"]:
                continue
            plan["accounts"].append({"name": name,
                                     "number": _col(r, "Account #",
                                                    "Number"),
                                     "type": t[0], "subtype": t[1],
                                     "description": _col(r, "Description")})
    for key, names in (("customers", ("Customer", "Name", "Display name")),
                       ("vendors", ("Vendor", "Name", "Display name"))):
        if files.get(key):
            for r in _csv_rows(files[key]):
                n = _col(r, *names)
                if n and n.lower() not in ex[key]:
                    plan[key].append({"NAME": n, "EMAIL": _col(r, "Email"),
                                      "PHONE1": _col(r, "Phone")})
    return {"counts": {k: len(v) for k, v in plan.items()},
            "problems": problems, "plan": plan, "source": "qbo"}


def apply_qbo(office, files: dict) -> int:
    office.require_full_books("Migration import")
    office.require("gl.manage", "import", "qbo")
    pv = preview_qbo(office, files)
    with office.db.tx():
        batch = _new_batch(office, "qbo", [p for p in files.values() if p])
        made = _apply_plan(office, pv["plan"], batch)
        office.db.update("import_batches", batch,
                         counts=json.dumps(pv["counts"]),
                         created=json.dumps(made))
        office.audit("import", "import_batch", batch, None,
                     {"source": "qbo", "counts": pv["counts"],
                      "problems": pv["problems"]})
    return batch


# ---- opening balances --------------------------------------------------------

def opening_balances(office, as_of, rows) -> int:
    """rows: [(account number or name, debit, credit)] as of the conversion
    date. Must balance to the cent; AR, AP and retainage come in item by
    item (open invoices and bills), not as a lump."""
    office.require_full_books("Opening balances")
    office.require("gl.manage", "import", "opening")
    lines = []
    for acct, dr, cr in rows:
        a = ledger.account(office, ledger._acct_id(office, acct))
        if a["subtype"] in CONTROL:
            raise MigrateError(f"{a['name']}: import its open items item by "
                               f"item instead of a balance")
        lines.append({"account": a["id"], "debit": cents.amount_in(dr or "0"),
                      "credit": cents.amount_in(cr or "0")})
    td = sum(x["debit"] for x in lines)
    tc = sum(x["credit"] for x in lines)
    if td != tc:
        raise MigrateError(f"The opening trial balance does not balance: "
                           f"debits {cents.fmt(td)}, credits {cents.fmt(tc)}, "
                           f"difference {cents.fmt(abs(td - tc))}.")
    _refuse_closed(office, [as_of])
    with office.db.tx():
        batch = _new_batch(office, "opening", [])
        eid = ledger.post(office, as_of, lines, "opening", batch,
                          f"Opening balances as of {as_of}", batch_id=batch)
        office.db.update("import_batches", batch,
                         counts=json.dumps({"lines": len(lines)}),
                         created=json.dumps({"journal_entries": [eid]}))
        office.audit("opening balances", "import_batch", batch, None,
                     {"as_of": str(as_of), "debits": td})
    return batch


# ---- undo --------------------------------------------------------------------

def batches(office) -> list[dict]:
    return office.db.rows("SELECT * FROM import_batches ORDER BY id DESC")


def undo(office, batch_id, reason="") -> dict:
    """Remove every record the batch created and nothing else: its
    postings are reversed (journal lines are never deleted), its documents
    and list records are removed."""
    office.require("gl.manage", "import_batch", batch_id)
    b = office.db.get("import_batches", batch_id)
    if b["status"] != "Applied":
        raise MigrateError("This batch is already undone.")
    made = json.loads(b["created"] or "{}")
    kept = []
    with office.db.tx():
        for eid in made.get("journal_entries", []):
            e = ledger.entry(office, eid)
            if not e["reversed_by_id"]:
                ledger.reverse(office, eid, e["date"],
                               f"Undo import batch {batch_id}")
        for table in ("ar_invoices", "ap_invoices", "customers", "vendors",
                      "items", "classes"):
            for rid in made.get(table, []):
                office.db.soft_delete(table, rid)
        for aid in made.get("accounts", []):
            if ledger.has_lines(office, aid):
                office.db.update("accounts", aid, active=0)
                kept.append(aid)
            else:
                office.db.soft_delete("accounts", aid)
        office.db.update("import_batches", batch_id, status="Undone",
                         undone_by=office.who)
        office.audit("undo", "import_batch", batch_id, None,
                     {"reason": reason, "kept_inactive": kept})
    return {"kept_inactive": kept}
