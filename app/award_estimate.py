"""Scope Sheets > Use Award in Estimate: each awarded trade becomes one
Subcontract line in the open drawing's estimate (estimate_lines.py).

    line: code = the sheet's CSI section, "<trade> - <bidder> (award)",
          1 ls, Sub = the award amount (to the cent), cost type
          Subcontract, source "Scope Sheet award: <sheet id>"

The source names the sheet, so running it again updates that line (new
bidder or amount) and never adds a second one. A budget allowance for the
trade - an Allowance line coded with the same CSI section, else the
division's allowance ("09 00 00", as the quick $/SF estimate makes them)
the first time the trade goes in - is replaced: its quantity goes to 0 so it no longer counts, its prices
stay, and its note says "Replaced by award to <bidder> on <date> ...; was
$X". Nothing is deleted. The new line flows to the proposal, the bid
build-up and the exports like any added line (estimate_lines.rollup_rows).

Pure apart from reading and writing the lines file: plan() works on a
list of lines and is what the tests check.
"""
import copy
from datetime import date
from decimal import Decimal

from . import csi, dmoney, estimate_lines as EL

MARK = "Scope Sheet award"
REPLACED = "Replaced by award to"


def _ss():
    from .pm import scope_sheet
    return scope_sheet


def sheet_key(sheet):
    """What ties a line to its sheet: the stored record id, else the CSI
    code and trade."""
    rid = str(sheet.get("_id") or "").strip()
    if rid:
        return rid
    return " ".join(f"{sheet.get('csi') or ''} {sheet.get('trade') or ''}"
                    .split()) or "scope sheet"


def source_of(sheet):
    return f"{MARK}: {sheet_key(sheet)}"[:EL.TEXT_MAX["source"]]


def awards(sheets):
    """[{sheet, key, code, trade, title, bidder, amount (cents)}] for the
    sheets with a recommended award and an amount."""
    ss = _ss()
    out = []
    for sh in sheets or []:
        aw = sh.get("award") or {}
        bid = aw.get("bidder") or ""
        b = ss.bidder(sh, bid) if bid else None
        if b is None:
            continue
        amt = ss.award_amount(sh)
        if amt is None:
            continue
        out.append({"sheet": sh, "key": sheet_key(sh),
                    "source": source_of(sh),
                    "code": csi.parse_code(sh.get("csi") or ""),
                    "trade": (sh.get("trade") or "").strip(),
                    "title": ss.title(sh),
                    "bidder": ss.bidder_name(sh, b), "amount": int(amt),
                    "adjusted": ss.accepted_adjustment(sh, b)})
    return out


def _is_award(ln):
    return str(ln.get("source") or "").startswith(MARK + ":")


def _is_replaced(ln):
    return str(ln.get("note") or "").startswith(REPLACED)


def allowances_for(lines, code, division=True):
    """The active allowance lines a trade's award replaces: those coded
    with its CSI section, else (division=True) the first one coded with
    its division ("09 00 00")."""
    code = csi.parse_code(code or "")
    if not code:
        return []
    live = [ln for ln in lines
            if ln.get("cost_type") == "Allowance" and not _is_award(ln)
            and not _is_replaced(ln)]
    exact = [ln for ln in live if csi.parse_code(ln.get("code") or "")
             .split(".")[0] == code.split(".")[0]]
    if exact or not division:
        return exact
    div = f"{code[:2]} 00 00"
    return [ln for ln in live
            if csi.parse_code(ln.get("code") or "") == div][:1]


def _money(cents):
    return dmoney.fmt(Decimal(int(cents)) / 100) if cents is not None \
        else ""


def _line_total(ln):
    try:
        return EL.price(ln)["total"]
    except Exception:                                     # noqa: BLE001
        return Decimal("0.00")


def plan(lines, sheets, today=None):
    """(new list of lines, report) for these sheets' awards. Report rows:
    {title, bidder, amount, action: added | updated | unchanged, line_id,
    replaced: [line ids]}. `lines` is not changed."""
    today = today or date.today().isoformat()
    lines = [copy.deepcopy(EL.clean(x)) for x in lines]
    report = []
    for a in awards(sheets):
        dollars = (Decimal(a["amount"]) / 100).quantize(Decimal("0.01"))
        desc = f"{a['trade'] or a['title']} - {a['bidder']} (award)"
        want = {"code": a["code"], "desc": desc, "unit": "ls", "qty": "1",
                "cost_type": "Subcontract", "mat": "0", "lab": "0",
                "eqp": "0", "sub": str(dollars), "link": None,
                "source": a["source"]}
        note = (f"Award to {a['bidder']} on {today} from scope sheet "
                f"{a['title']}")
        adj = a.get("adjusted") or 0
        if adj:
            note += (f"; accepted clarifications of {_money(adj)} are not "
                     "in this amount")
        have = next((ln for ln in lines if ln.get("source") == a["source"]),
                    None)
        if have is None:
            ln = EL.new_line(desc=desc, qty=1, unit="ls", code=a["code"],
                             cost_type="Subcontract", sub=dollars,
                             source=a["source"], note=note)
            lines.append(ln)
            action, lid = "added", ln["id"]
        else:
            before = EL.clean(have)
            same = all(_same(before.get(k), v) for k, v in want.items())
            if not same:
                have.update(want)
                have["note"] = note
                have.update(EL.clean(have))
            action, lid = ("unchanged" if same else "updated"), have["id"]
        replaced = []
        # the division's allowance only the first time: a later run must
        # not take a division allowance another trade still relies on
        for al in allowances_for(lines, a["code"], division=have is None):
            was = _line_total(al)
            al["note"] = (f"{REPLACED} {a['bidder']} on {today} (scope sheet "
                          f"{a['title']}); was {dmoney.fmt(was)}"
                          + (f". {al['note']}" if al.get("note") else ""))
            al["note"] = al["note"][:EL.TEXT_MAX["note"]]
            al["link"] = None
            al["qty"] = "0"
            replaced.append(al["id"])
        if replaced and action == "unchanged":
            action = "updated"
        report.append({"title": a["title"], "bidder": a["bidder"],
                       "amount": a["amount"], "action": action,
                       "line_id": lid, "replaced": replaced})
    return [EL.clean(x) for x in lines], report


def _same(a, b):
    if a == b:
        return True
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:                                     # noqa: BLE001
        return False


def apply(doc, sheets, today=None):
    """Write the awards into the drawing's estimate. Returns the report;
    the lines file is only rewritten when something changed."""
    lines = EL.read(doc)
    new, report = plan(lines, sheets, today)
    if any(r["action"] != "unchanged" for r in report):
        if len(new) > EL.MAX_LINES:
            raise EL.LineError(f"An estimate holds at most {EL.MAX_LINES} "
                               "added lines.")
        EL.write(doc, new)
    return report


def describe(report):
    """One line per trade for the message box."""
    out = []
    for r in report:
        verb = {"added": "added", "updated": "updated",
                "unchanged": "already in the estimate"}[r["action"]]
        s = f"{r['title']}: {r['bidder']} {_money(r['amount'])} - {verb}"
        if r["replaced"]:
            s += f" (replaced {len(r['replaced'])} allowance line" + \
                ("s" if len(r["replaced"]) > 1 else "") + ")"
        out.append(s)
    return "\n".join(out)
