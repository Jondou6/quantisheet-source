"""QuantiSheet -> Back Office snapshot, interface version 1 (read-only).

One JSON file per job, written by app/backoffice_hook.py. Back Office
checks it, lists what was rejected and why, and copies it into its own
job record. It never reads or writes the PDF or Project Center files.

{"interface_version": 1,
 "source": {"app": "QuantiSheet 0.13.1", "file": "...", "taken_at": "..."},
 "project": {"name", "number", "address", "owner", "contractor",
             "architect", "contract_no", "contract_date", "state"},
 "cost_codes":   [{"code", "description", "category": L/M/E/S/O}],
 "budget":       [{"code", "description", "category", "original", "revised"}],
 "estimate":     [{"code", "description", "category", "quantity", "unit",
                   "amount"}],
 "activities":   [{"id", "name", "cost_code", "start", "finish", "percent"}],
 "contract":     {"retainage_work", "retainage_stored",
                  "sov": [{"item", "cost_code", "description", "scheduled"}]},
 "changes":      [{"id", "pco", "cor", "co", "title", "stage", "amount",
                   "approved_amount", "days", "executed"}],
 "payapps":      [{"number", "period_to", "status",
                   "lines": [{"item", "previous", "this_period", "stored"}],
                   "summary": {"1".."9", "5a", "5b"}, "received",
                   "received_on"}],
 "commitments":  [{"number", "vendor", "type", "lines": [{"cost_code",
                   "description", "amount"}], "retainage",
                   "insurance_expires", "license_expires", "w9"}],
 "direct_costs": [{"id", "date", "vendor", "cost_code", "category",
                   "amount", "invoice", "status", "paid_on", "commitment"}],
 "timecards":    [{"id", "date", "foreman", "crew": [{"name", "class",
                   "hours"}], "equipment": [{"code", "hours"}],
                   "production": [{"cost_code", "qty", "unit", "hours"}]}],
 "directory":    [{"name", "company", "email", "phone", "role"}],
 "daily_logs":   [{"id", "date", "status", "manpower": [{"company",
                   "trade", "workers", "hours"}]}],      (optional, P2-10)
 "service_invoices": [{"id", "number", "date", "customer", "site",
                   "work_order", "lines": [{"description", "qty", "unit",
                   "price", "amount", "taxable"}], "total",
                   "reverse", "reason"}]}   (optional, 1.2 - service desk)

service_invoices is additive (Nov 5, interface version stays 1): a
closed work order's invoice, posted once in Back Office; "reverse": true
with a reason backs one out as its own entry. An invoice whose lines
don't add up to its total is rejected, never posted.

All money and quantities are decimal STRINGS: no floats cross the line.
A bad item is listed as rejected with the reason, never set to 0; an
interface_version other than 1 refuses the whole file.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from decimal import Decimal

from . import cents, fileguard

INTERFACE_VERSION = 1
MAX_ITEMS = 50_000
CATEGORIES = ("L", "M", "E", "S", "O")
STAGES = ("pco", "cor", "co", "rejected", "void")
PAYAPP_STATUSES = ("draft", "submitted", "certified", "paid")
SUMMARY_KEYS = ("1", "2", "3", "4", "5a", "5b", "5", "6", "7", "8", "9")
COUNTED = ("certified", "paid")


class SnapshotError(ValueError):
    """The whole file is refused."""


class _Bad(ValueError):
    pass


def _s(item, k, required=False, maxlen=500):
    v = item.get(k, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise _Bad(f"{k} must be text, not {type(v).__name__} {v!r}")
    if required and not v.strip():
        raise _Bad(f"{k} is missing")
    if len(v) > maxlen:
        raise _Bad(f"{k} is longer than {maxlen} characters")
    return v.strip()


def _dec(item, k, required=True, nonneg=False, what=None):
    v = item.get(k)
    if v is None or v == "":
        if required:
            raise _Bad(f"{k} is missing")
        return None
    if isinstance(v, float):
        raise _Bad(f"{k} is the number {v!r}, not a decimal string like "
                   f"\"{v:.2f}\"")
    if not isinstance(v, str):
        raise _Bad(f"{k} must be a decimal string, not {v!r}")
    try:
        d = cents.D(v)
    except cents.MoneyError:
        raise _Bad(f"{k} {v!r} can't be read as a number") from None
    if nonneg and d < 0:
        raise _Bad(f"{what or k} {v} is negative")
    return d


def _money(item, k, required=True, nonneg=False):
    d = _dec(item, k, required, nonneg)
    return None if d is None else cents.text(cents.to_cents(d))


def _date(item, k, required=False):
    v = _s(item, k, required)
    if v:
        from datetime import date
        try:
            date.fromisoformat(v[:10])
        except ValueError:
            raise _Bad(f"{k} {v!r} is not a date (YYYY-MM-DD)") from None
        return v[:10]
    return ""


def _cat(item, k="category"):
    v = _s(item, k).upper()[:1]
    if v and v not in CATEGORIES:
        raise _Bad(f"category {item.get(k)!r} is not one of L/M/E/S/O")
    return v


def _lines(item, k):
    v = item.get(k) or []
    if not isinstance(v, list):
        raise _Bad(f"{k} must be a list")
    for x in v:
        if not isinstance(x, dict):
            raise _Bad(f"{k} entries must be objects")
    return v


# ---- one checker per section: item -> (key, clean item) ------------------

def _cost_code(it):
    c = {"code": _s(it, "code", True), "description": _s(it, "description"),
         "category": _cat(it)}
    return c["code"], c


def _budget(it):
    c = {"code": _s(it, "code", True), "description": _s(it, "description"),
         "category": _cat(it), "original": _money(it, "original"),
         "revised": _money(it, "revised", required=False)}
    if c["revised"] is None:
        c["revised"] = c["original"]
    return c["code"], c


def _estimate(it):
    c = {"code": _s(it, "code"), "description": _s(it, "description", True),
         "category": _cat(it),
         "quantity": str(_dec(it, "quantity", nonneg=True, what="quantity")),
         "unit": _s(it, "unit"), "amount": _money(it, "amount")}
    return f"{c['code']}|{c['description']}|{c['unit']}", c


def _activity(it):
    p = _dec(it, "percent", required=False, nonneg=True)
    if p is not None and p > 100:
        raise _Bad(f"percent {p} is over 100")
    c = {"id": _s(it, "id", True), "name": _s(it, "name"),
         "cost_code": _s(it, "cost_code"), "start": _date(it, "start"),
         "finish": _date(it, "finish"), "percent": str(p or Decimal(0))}
    return c["id"], c


def _sov(it):
    c = {"item": _s(it, "item", True), "cost_code": _s(it, "cost_code"),
         "description": _s(it, "description"),
         "scheduled": _money(it, "scheduled")}
    return c["item"], c


def _change(it):
    st = _s(it, "stage", True).lower()
    if st not in STAGES:
        raise _Bad(f"stage {st!r} is not one of {', '.join(STAGES)}")
    days = _dec(it, "days", required=False)
    c = {"id": _s(it, "id", True), "pco": _s(it, "pco"), "cor": _s(it, "cor"),
         "co": _s(it, "co"), "title": _s(it, "title"), "stage": st,
         "amount": _money(it, "amount"),
         "approved_amount": _money(it, "approved_amount", required=False),
         "days": str(days) if days is not None else "0",
         "executed": _date(it, "executed")}
    if st == "co" and c["approved_amount"] is None:
        c["approved_amount"] = c["amount"]
    return c["id"], c


def _payapp(it):
    n = _s(it, "number", True)
    if not n.isdigit():
        raise _Bad(f"number {n!r} is not a whole number")
    st = _s(it, "status", True).lower()
    if st not in PAYAPP_STATUSES:
        raise _Bad(f"status {st!r} is not one of {', '.join(PAYAPP_STATUSES)}")
    lines = []
    for ln in _lines(it, "lines"):
        lines.append({"item": _s(ln, "item", True),
                      "previous": _money(ln, "previous", required=False) or "0.00",
                      "this_period": _money(ln, "this_period", required=False) or "0.00",
                      "stored": _money(ln, "stored", required=False) or "0.00"})
    summ = it.get("summary") or {}
    if not isinstance(summ, dict):
        raise _Bad("summary must be an object")
    summary = {}
    for k in SUMMARY_KEYS:
        if k in summ:
            summary[k] = _money(summ, k)
    if st in COUNTED:
        missing = [k for k in ("1", "2", "3", "4", "5", "6", "7", "8", "9")
                   if k not in summary]
        if missing:
            raise _Bad(f"certified summary line(s) {', '.join(missing)} missing")
    c = {"number": int(n), "period_to": _date(it, "period_to", True),
         "status": st, "lines": lines, "summary": summary,
         "received": _money(it, "received", required=False),
         "received_on": _date(it, "received_on")}
    return str(c["number"]), c


def _commitment(it):
    lines = [{"cost_code": _s(ln, "cost_code"),
              "description": _s(ln, "description"),
              "amount": _money(ln, "amount")} for ln in _lines(it, "lines")]
    w9 = _s(it, "w9")
    c = {"number": _s(it, "number", True), "vendor": _s(it, "vendor", True),
         "type": _s(it, "type"), "lines": lines,
         "retainage": str(_dec(it, "retainage", required=False, nonneg=True)
                          or Decimal(0)),
         "insurance_expires": _date(it, "insurance_expires"),
         "license_expires": _date(it, "license_expires"),
         "w9": w9}
    return c["number"], c


def _direct_cost(it):
    c = {"id": _s(it, "id"), "date": _date(it, "date", True),
         "vendor": _s(it, "vendor"), "cost_code": _s(it, "cost_code"),
         "category": _cat(it), "amount": _money(it, "amount"),
         "invoice": _s(it, "invoice"), "status": _s(it, "status"),
         "paid_on": _date(it, "paid_on"), "commitment": _s(it, "commitment"),
         "description": _s(it, "description")}
    key = c["id"] or f"{c['date']}|{c['vendor']}|{c['invoice']}|{c['amount']}"
    return key, c


def _timecard(it):
    crew = [{"name": _s(ln, "name", True), "class": _s(ln, "class"),
             "hours": str(_dec(ln, "hours", nonneg=True, what="hours"))}
            for ln in _lines(it, "crew")]
    eq = [{"code": _s(ln, "code", True),
           "hours": str(_dec(ln, "hours", nonneg=True, what="hours"))}
          for ln in _lines(it, "equipment")]
    prod = [{"cost_code": _s(ln, "cost_code"),
             "qty": str(_dec(ln, "qty", required=False, nonneg=True,
                             what="quantity") or Decimal(0)),
             "unit": _s(ln, "unit"),
             "hours": str(_dec(ln, "hours", required=False, nonneg=True,
                               what="hours") or Decimal(0))}
            for ln in _lines(it, "production")]
    c = {"id": _s(it, "id"), "date": _date(it, "date", True),
         "foreman": _s(it, "foreman"), "crew": crew, "equipment": eq,
         "production": prod}
    return c["id"] or f"{c['date']}|{c['foreman']}", c


def _daily_log(it):
    """Daily Log manpower only (head count and hours each); no free text,
    weather, visitors or photos cross the line."""
    def whole(ln):
        v = _dec(ln, "workers", nonneg=True, what="workers")
        if v != v.to_integral_value():
            raise _Bad("workers must be a whole number")
        return str(int(v))
    man = [{"company": _s(ln, "company"), "trade": _s(ln, "trade"),
            "workers": whole(ln),
            "hours": str(_dec(ln, "hours", nonneg=True, what="hours"))}
           for ln in _lines(it, "manpower")]
    c = {"id": _s(it, "id"), "date": _date(it, "date", True),
         "status": _s(it, "status"), "manpower": man}
    return c["id"] or c["date"], c


def _service_invoice(it):
    lines = []
    for ln in _lines(it, "lines"):
        lines.append({"description": _s(ln, "description"),
                      "qty": _s(ln, "qty"), "unit": _s(ln, "unit"),
                      "price": _s(ln, "price"),
                      "amount": _money(ln, "amount"),
                      "taxable": bool(ln.get("taxable"))})
    rev = bool(it.get("reverse"))
    c = {"id": _s(it, "id", True), "number": _s(it, "number", True),
         "date": _date(it, "date", True), "customer": _s(it, "customer"),
         "site": _s(it, "site"), "work_order": _s(it, "work_order"),
         "lines": lines, "total": _money(it, "total", required=not rev) or "",
         "reverse": rev,
         "reason": _s(it, "reason")}
    if rev:
        if not c["reason"]:
            raise _Bad("a reversal needs a reason")
    else:
        if not lines:
            raise _Bad("no lines")
        if not c["customer"]:
            raise _Bad("no customer")
        tot = sum((Decimal(ln["amount"]) for ln in lines), Decimal(0))
        if tot != Decimal(c["total"]):
            raise _Bad(f"lines add to {tot}, invoice says {c['total']}")
    return c["id"] + (":reverse" if rev else ""), c


def _member(it):
    c = {k: _s(it, k) for k in ("name", "company", "email", "phone", "role")}
    if not c["name"] and not c["company"]:
        raise _Bad("name is missing")
    return f"{c['name']}|{c['company']}", c


SECTIONS = {"cost_codes": _cost_code, "budget": _budget,
            "estimate": _estimate, "activities": _activity,
            "changes": _change, "payapps": _payapp,
            "commitments": _commitment, "direct_costs": _direct_cost,
            "timecards": _timecard, "directory": _member,
            "daily_logs": _daily_log, "service_invoices": _service_invoice}


@dataclass
class Snapshot:
    source: dict
    project: dict
    contract: dict
    sections: dict = field(default_factory=dict)   # name -> {key: item}
    rejected: list = field(default_factory=list)   # (section, label, reason)
    file_hash: str = ""

    def counts(self) -> dict:
        out = {k: len(v) for k, v in self.sections.items()}
        out["sov"] = len(self.sections.get("sov", {}))
        return out


def load_snapshot(src) -> Snapshot:
    """Path or dict -> Snapshot. Raises SnapshotError for a refused file."""
    raw = b""
    if isinstance(src, (str, os.PathLike)):
        fileguard.refuse_company_file(src)
        with open(src, "rb") as fh:
            raw = fh.read()
        try:
            data = json.loads(raw.decode("utf-8"), parse_float=_FloatMark)
        except (ValueError, UnicodeDecodeError) as e:
            raise SnapshotError(f"not a readable JSON file: {e}") from None
    else:
        data = src
        raw = json.dumps(src, sort_keys=True, default=str).encode("utf-8")
    if not isinstance(data, dict):
        raise SnapshotError("the snapshot must be a JSON object")
    v = data.get("interface_version")
    if v != INTERFACE_VERSION or isinstance(v, bool):
        raise SnapshotError(f"interface_version {v!r} is not supported "
                            f"(this Back Office reads version "
                            f"{INTERFACE_VERSION}); update Back Office")
    data = _unmark(data)
    proj = data.get("project") or {}
    if not isinstance(proj, dict):
        raise SnapshotError("project must be an object")
    try:
        project = {k: _s(proj, k) for k in (
            "name", "number", "address", "owner", "contractor", "architect",
            "contract_no", "contract_date", "state")}
    except _Bad as e:
        raise SnapshotError(f"project: {e}") from None
    if not project["number"]:
        raise SnapshotError("project number is missing")
    src_info = data.get("source") or {}
    snap = Snapshot(source={k: str(src_info.get(k, "")) for k in
                            ("app", "file", "folder", "taken_at")},
                    project=project, contract={},
                    file_hash=hashlib.sha256(raw).hexdigest())
    con = data.get("contract") or {}
    try:
        snap.contract = {
            "retainage_work": str(_dec(con, "retainage_work", False, True)
                                  or Decimal(0)),
            "retainage_stored": str(_dec(con, "retainage_stored", False, True)
                                    or Decimal(0))}
    except _Bad as e:
        raise SnapshotError(f"contract: {e}") from None
    snap.sections["sov"] = {}
    _read_list(snap, "sov", con.get("sov") or [], _sov)
    for name, fn in SECTIONS.items():
        snap.sections[name] = {}
        _read_list(snap, name, data.get(name) or [], fn)
    return snap


def _read_list(snap, name, items, fn):
    if not isinstance(items, list):
        snap.rejected.append((name, "(section)", "must be a list"))
        return
    for i, it in enumerate(items[:MAX_ITEMS]):
        label = f"#{i + 1}"
        if not isinstance(it, dict):
            snap.rejected.append((name, label, "not an object"))
            continue
        for k in ("code", "id", "item", "number", "name", "description"):
            if isinstance(it.get(k), str) and it.get(k):
                label = f"#{i + 1} {it[k]}"
                break
        try:
            key, clean = fn(it)
        except (_Bad, cents.MoneyError) as e:
            snap.rejected.append((name, label, str(e)))
            continue
        if key in snap.sections[name]:
            snap.rejected.append((name, label, f"duplicate {key}"))
            continue
        snap.sections[name][key] = clean


class _FloatMark(float):
    """parse_float hook: keeps the literal so a float is reported, not used."""

    def __new__(cls, s):
        o = float.__new__(cls, s)
        o.literal = s
        return o


def _unmark(v):
    if isinstance(v, _FloatMark):
        return float(v.literal)          # reaches the checker as a float
    if isinstance(v, dict):
        return {k: _unmark(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unmark(x) for x in v]
    return v


# ---- read-only math helpers (no recomputing certified numbers) -----------

def original_contract(sov_items) -> int:
    return sum(cents.to_cents(s["scheduled"]) for s in sov_items)


def executed_changes(changes) -> int:
    return sum(cents.to_cents(c["approved_amount"] or c["amount"])
               for c in changes if c["stage"] == "co")


def pending_changes(changes) -> int:
    return sum(cents.to_cents(c["amount"]) for c in changes
               if c["stage"] in ("pco", "cor"))
