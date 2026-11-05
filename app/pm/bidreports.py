"""Bidding reports for a project (Bid Packages > Bidding Reports): package
status, bidder coverage, buyout against the budget and bidder history -
one Excel workbook."""
import re

from .bidforms import num


def _div(text):
    m = re.search(r"\b(\d{2})(?:\s?\d{2}\s?\d{2})?\b", str(text or ""))
    return m.group(1) if m else ""


def _bidders(rec):
    return [b for b in rec.get("bidders") or [] if isinstance(b, dict)]


def _amounts(rec):
    return sorted(v for v in (num(b.get("amount")) for b in _bidders(rec))
                  if v is not None)


def package_rows(store):
    rows = [["Package", "Title", "Trade", "Due", "Status", "Sealed",
             "Invited", "Viewed", "Will bid", "Won't bid", "Bids in",
             "Low bid", "High bid", "Spread %", "Awarded to", "Award"]]
    for r in sorted(store.list("bidpkg"), key=lambda r: r.get("_no", "")):
        bs = _bidders(r)
        st = [b.get("status") or "" for b in bs]
        am = _amounts(r)
        spread = round((am[-1] - am[0]) / am[0] * 100) if len(am) > 1 and \
            am[0] else ""
        rows.append([r.get("_no", ""), r.get("title", ""),
                     r.get("trades", ""), r.get("due", ""),
                     r.get("status", ""),
                     ("opened " + r["unsealed"][:10]) if r.get("unsealed")
                     else ("yes" if r.get("sealed") else ""),
                     sum(1 for b in bs if b.get("invited") or b.get("token")),
                     sum(1 for b in bs if b.get("viewed") or
                         b.get("status") in ("Viewed", "Will Bid",
                                             "Might Bid", "Bid Received",
                                             "Awarded")),
                     st.count("Will Bid") + st.count("Might Bid"),
                     st.count("Won't Bid"),
                     sum(1 for b in bs if b.get("status") in (
                         "Bid Received", "Awarded") or
                         num(b.get("amount")) is not None),
                     am[0] if am else "", am[-1] if am else "", spread,
                     r.get("awarded_to", ""),
                     num(r.get("award_amount")) or ""])
    return rows


def coverage_rows(store):
    rows = [["Package", "Title", "Company", "Contact", "Email", "Status",
             "Invited", "Viewed", "Responded", "Addenda ack'd", "Late",
             "Amount", "Missing lines", "Note"]]
    for r in sorted(store.list("bidpkg"), key=lambda r: r.get("_no", "")):
        adds = [str(a.get("number")) for a in r.get("addenda") or []
                if isinstance(a, dict)]
        for b in _bidders(r):
            acks = b.get("ack_list") or []
            ack = (f"{len(set(acks) & set(adds))} of {len(adds)}"
                   if adds else "")
            rows.append([r.get("_no", ""), r.get("title", ""),
                         b.get("company", ""), b.get("contact", ""),
                         b.get("email", ""), b.get("status", ""),
                         b.get("invited", ""), (b.get("viewed") or "")[:10],
                         (b.get("responded") or "")[:10], ack,
                         "late" if b.get("late") else "",
                         num(b.get("amount")) if num(b.get("amount"))
                         is not None else "",
                         ", ".join(b.get("form_missing") or []),
                         b.get("note", "")])
    return rows


def buyout_rows(store):
    """Budget (lines in the package's CSI division) against the award."""
    budget = {}
    for ln in store.list("budget"):
        d = _div(ln.get("cost_code"))
        if d:
            budget[d] = budget.get(d, 0.0) + (num(ln.get("original")) or 0)
    rows = [["Package", "Title", "Division", "Budget", "Low bid",
             "Awarded to", "Award", "Over (under) budget", "% of budget"]]
    tb = ta = 0.0
    for r in sorted(store.list("bidpkg"), key=lambda r: r.get("_no", "")):
        d = _div(r.get("trades"))
        bud = budget.get(d)
        am = _amounts(r)
        award = num(r.get("award_amount"))
        if award is None and r.get("awarded_to"):
            award = next((num(b.get("amount")) for b in _bidders(r)
                          if b.get("company") == r["awarded_to"]), None)
        var = (award - bud) if award is not None and bud else ""
        pct = round(award / bud * 100, 1) if award is not None and bud \
            else ""
        if award is not None and bud:
            tb += bud
            ta += award
        rows.append([r.get("_no", ""), r.get("title", ""), d,
                     bud if bud is not None else "", am[0] if am else "",
                     r.get("awarded_to", ""),
                     award if award is not None else "", var, pct])
    if tb:
        rows += [[], ["", "Bought out", "", tb, "", "", ta, ta - tb,
                      round(ta / tb * 100, 1)]]
    return rows


def history_rows(store):
    """Each company that bid on this project: bids and wins everywhere
    (from your Company Directory's history)."""
    from .. import subdir
    names = sorted({b.get("company") for r in store.list("bidpkg")
                    for b in _bidders(r) if b.get("company")})
    rows = [["Company", "Bids (all projects)", "Won", "Win rate",
             "Last bid", "Prequalification", "Insurance expires"]]
    contacts = subdir.load()
    for n in names:
        st = subdir.stats(n)
        c = next((x for x in contacts
                  if subdir._company_key(x.get("company")) ==
                  subdir._company_key(n)), {})
        rows.append([n, st["bids"], st["wins"],
                     f"{st['win_rate']:.0%}" if st["win_rate"] is not None
                     else "", st["last"],
                     subdir.prequal_status(c) if c else "",
                     c.get("insurance_exp", "") if c else ""])
    return rows


def export_xlsx(store, path):
    from .. import acrobat
    acrobat.write_xlsx(path, [("Packages", package_rows(store)),
                              ("Bidder Coverage", coverage_rows(store)),
                              ("Buyout", buyout_rows(store)),
                              ("Bidder History", history_rows(store))])
    return path
