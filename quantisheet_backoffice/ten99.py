"""1099 vendor totals and the missing W-9 list (addendum P2-16; also in
export mode). Back Office does not print or file IRS forms.

Payments to vendors flagged 1099 are totalled by payment date for the
calendar year. Card and third-party network payments are reported by the
card processor, so they are left out (listed with the note 'paid by card')
unless the user includes them. The threshold is a setting per year:
$2,000.00 for payments made in 2026 and later (IRS Pub. 1099), $600.00
before; the screen tells the user to check the current IRS instructions.
"""
from __future__ import annotations

import csv

from . import ap, cents, fileguard
from .crypto import mask

NOTE = ("Check the current IRS instructions for Forms 1099-NEC and "
        "1099-MISC; Back Office does not file or print IRS forms.")
CARD_METHODS = ("card", "credit card", "debit card", "paypal", "network")


def threshold(office, year) -> int:
    from . import settings
    over = settings.get(f"threshold_1099_{year}")
    if over:
        return cents.amount_in(str(over))
    return 200_000 if int(year) >= 2026 else 60_000


def totals(office, year, include_card=False, threshold_c=None) -> dict:
    th = threshold(office, year) if threshold_c is None else \
        cents.amount_in(threshold_c)
    rows, excluded = {}, []
    for p in office.db.rows(
            "SELECT p.*, v.name, v.is_1099, v.box_1099, v.w9 FROM "
            "bill_payments p JOIN vendors v ON v.id = p.vendor_id WHERE "
            "p.void = 0 AND p.deleted = 0 AND v.is_1099 = 1 AND "
            "substr(p.date, 1, 4) = ?", (str(year),)):
        card = (p["method"] or "").lower() in CARD_METHODS
        if card and not include_card:
            excluded.append({"vendor_id": p["vendor_id"], "vendor": p["name"],
                             "amount": p["amount"], "date": p["date"],
                             "note": "paid by card"})
            continue
        r = rows.setdefault(p["vendor_id"], {
            "vendor_id": p["vendor_id"], "vendor": p["name"],
            "box": p["box_1099"] or "NEC", "total": 0,
            "w9": "on file" if p["w9"] else "missing",
            "tin": ap.vendor_tax_id(office, p["vendor_id"])})
        r["total"] += p["amount"]
    listed = sorted((r for r in rows.values() if r["total"] >= th),
                    key=lambda r: r["vendor"])
    return {"year": int(year), "threshold": th, "listed": listed,
            "below": sorted((r for r in rows.values() if r["total"] < th),
                            key=lambda r: r["vendor"]),
            "excluded": excluded, "note": NOTE}


def missing_w9(office, year) -> list[dict]:
    return [r for r in totals(office, year)["listed"] if r["w9"] != "on file"]


def export_csv(office, year, path, full_tins=False) -> str:
    """CSV for the user's own filing service. Full TINs only for a
    Controller or Admin, and every export is audit-logged."""
    if full_tins:
        office.require("1099.full_tin", "1099", year)
    fileguard.write_target(path)
    t = totals(office, year)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(fileguard.safe_row(["Vendor", "TIN", "Box", "Total paid", "W-9"]))
        for r in t["listed"]:
            tin = ap.vendor_tax_id(office, r["vendor_id"], reveal=True) \
                if full_tins else r["tin"]
            w.writerow(fileguard.safe_row([r["vendor"], tin, r["box"], cents.text(r["total"]),
                        r["w9"]]))
    office.audit("export 1099", "1099", year, None,
                 {"rows": len(t["listed"]), "full_tins": bool(full_tins),
                  "path": path})
    return path


__all__ = ["totals", "missing_w9", "export_csv", "threshold", "mask"]
