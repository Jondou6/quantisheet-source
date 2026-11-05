"""Scope Sheets: compare subcontractor bids for one CSI trade at a time.

A project has many scope sheets, one per trade. Each mirrors the GC's
paper/Excel "Scope Sheet": a header (control #, project #, bid date, time,
estimator), the trade, a budget block (your own number: Qty x Unit $ =
Total per scope line), one block per bidder (company, phone, contact, the
stated BID PRICE, a YES/NO checklist and, per scope line, an "included"
flag and the $ amount), TOTAL PRICE and Math Check rows, and a footer
(budget, recommended award, amount, owner approval).

Pure Python (no Qt): the window is scope_sheet_ui, the Excel/PDF files
are written here. Money is integer cents; quantities and unit prices are
exact decimal text, so totals never drift.

Stored in the project database (store.py) as "scopesheet" records - one
record per trade - so they sync with the hub like everything else.

    sh = new_sheet("09 29 00", "Drywall & framing")
    b = sh["bidders"][0]; b["company"] = "Example Drywall LLC"
    ln = add_line(sh, "Metal stud framing")
    set_bid(sh, ln["id"], b["id"], flag="Y", amount=parse_money("1,250"))
    bidder_total(sh, b)  -> 125000   (cents)

Conventions (confirm with the estimator who owns the template):
  * the narrow bidder column is the "included" flag: Y = included (also
    when it has no $ of its own: "in the lump sum"), N = excluded, blank
    = not stated, or a short note ("ALLOW", "BY GC") kept as typed;
  * a blank amount is "not priced", $0.00 is priced at nothing - they are
    different, and only a blank can be plugged when leveling;
  * TOTAL PRICE is the sum of the bidder's scope amounts, or the stated
    BID PRICE when the bidder gave no breakdown; Math Check is the BID
    PRICE minus the summed lines (blank when either is missing);
  * the budget block is D-G of the template: Qty, Unit, Unit $, Total
    (= Qty x Unit $, or a typed lump sum when there is no Qty / Unit $);
  * clarifications (schema 2): per bidder, qualification / exclusion /
    clarification rows with an optional $ adjustment and a status. Only
    accepted amounts count, in the leveled total (leveled(), low_bidder());
    rejected rows are kept as the award record. "As bid" (summary's
    low_bid) never includes them. The Excel export writes them under the
    footer of the trade's first tab (and reads them back), the PDF on a
    Clarifications page after the trade's pages.
"""
import copy
import os
import re
import secrets
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SCHEMA_VERSION = 2               # 2: per-bidder clarifications ("clar")
COLL = "scopesheet"
DEFAULT_BIDDERS = 6
PER_PAGE = 6                     # bidder blocks on one Excel tab / PDF page
MIN_LINES = 45                   # scope rows 16-60 of the template
LEVEL_MODES = ("none", "budget", "median")
LEVEL_LABEL = {"none": "Off (as bid)",
               "budget": "Plug excluded lines with the budget",
               "median": "Plug excluded lines with the median of the others"}
CHECKLIST = (("plans", "PLANS & SPECIFICATIONS"),
             ("addenda", "ADDENDA"),
             ("bonded", "BONDED"),
             ("material", "MATERIAL"),
             ("install", "INSTALLATION"),
             ("tax", "SALES TAX"))
CHECK_KEYS = tuple(k for k, _l in CHECKLIST)
HEADER_FIELDS = ("project", "project_no", "control_no", "bid_date",
                 "bid_time", "estimator", "addenda_from", "addenda_to",
                 "notes")
YES_WORDS = {"Y", "YES", "X", "INCL", "INCLUDED", "✓", "✔"}
NO_WORDS = {"N", "NO", "EXCL", "EXCLUDED", "NIC"}
CENT = Decimal("0.01")
# per bidder: qualifications / exclusions / clarifications, each with an
# optional $ adjustment the estimator accepts (counted in the bidder's
# leveled total: + adds, (credit) deducts), rejects (kept as the award
# record, not counted) or leaves pending (not counted yet)
CLAR_KINDS = ("Qualification", "Exclusion", "Clarification")
CLAR_STATUS = ("pending", "accepted", "rejected")
CLAR_STATUS_LABEL = {"pending": "Pending", "accepted": "Accept",
                     "rejected": "Reject"}
CLAR_TEXT_MAX = 500
ACCOUNTING = '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'
UNIT_PRICE = '_($* #,##0.00##_);_($* (#,##0.00##);_($* "-"??_);_(@_)'
CURRENCY = '"$"#,##0.00_);("$"#,##0.00)'
YELLOW = "FFFFFFC0"


class ScopeError(ValueError):
    pass


def _id():
    return secrets.token_hex(6)


# ============================================================ numbers
def parse_decimal(text, what="amount"):
    """A Decimal from what someone typed or pasted: "1,250", "$1,250.00",
    "(500)", "-500", "500-", " $ (500.00) " (Excel accounting), "$ -"
    (accounting zero). None for blank. Raises ScopeError when it can't be
    read."""
    if text is None:
        return None
    if isinstance(text, bool):
        raise ScopeError(f"Can't read {text!r} as an {what}.")
    if isinstance(text, Decimal):
        if not text.is_finite():
            raise ScopeError(f"Can't read {text!r} as an {what}.")
        return text
    if isinstance(text, int):
        return Decimal(text)
    if isinstance(text, float):
        if text != text or text in (float("inf"), float("-inf")):
            raise ScopeError(f"Can't read {text!r} as an {what}.")
        return Decimal(repr(text))
    s = str(text).strip()
    if not s:
        return None
    raw = s
    s = (s.replace("−", "-").replace(" ", "").replace(" ", "")
         .replace("$", "").replace(",", ""))
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
        if not s or s[0] in "+-":
            raise ScopeError(f"Can't read {raw!r} as an {what}.")
    elif "(" in s or ")" in s:
        raise ScopeError(f"Can't read {raw!r} as an {what}.")
    if s in ("-", "--"):
        return Decimal(0)                 # accounting format's zero dash
    if s.endswith("-") and len(s) > 1:
        neg, s = not neg, s[:-1]
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not re.fullmatch(r"\d+(\.\d*)?|\.\d+", s):
        raise ScopeError(f"Can't read {raw!r} as an {what}.")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ScopeError(f"Can't read {raw!r} as an {what}.")
    return -d if neg else d


def to_cents(d):
    """Decimal dollars -> integer cents (half up, away from zero)."""
    if d is None:
        return None
    return int((Decimal(d) * 100).quantize(Decimal(1),
                                           rounding=ROUND_HALF_UP))


def parse_money(text):
    """Typed/pasted money -> integer cents, None for blank."""
    return to_cents(parse_decimal(text, "amount"))


def dollars(cents):
    """Integer cents -> Decimal dollars ("12.50")."""
    if cents is None:
        return None
    return (Decimal(int(cents)) / 100).quantize(CENT)


def fmt_money(cents, dollar=True):
    """Accounting display: $1,250.00, ($500.00) for a credit, '' for
    blank (not priced) and $0.00 for zero."""
    if cents is None:
        return ""
    c = int(cents)
    body = f"{abs(c) // 100:,}.{abs(c) % 100:02d}"
    if dollar:
        body = "$" + body
    return f"({body})" if c < 0 else body


def plain_money(cents):
    """For copying to Excel: -500.00 / 1250.00 ('' for blank)."""
    if cents is None:
        return ""
    return str(dollars(cents))


def _dec_text(d, min_places=0, max_places=4):
    """Exact Decimal as storage text, at most `max_places` decimals."""
    if d is None:
        return None
    q = Decimal(1).scaleb(-max_places)
    d = d.quantize(q, rounding=ROUND_HALF_UP).normalize()
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    exp = -d.as_tuple().exponent
    if exp < min_places:
        d = d.quantize(Decimal(1).scaleb(-min_places))
    return format(d, "f")


def parse_qty(text):
    """'1,250.5' -> '1250.5' (exact text), None for blank."""
    return _dec_text(parse_decimal(text, "quantity"))


def parse_unit_price(text):
    """'$2.875' -> '2.875'; at least 2 decimals kept ('2.50')."""
    return _dec_text(parse_decimal(text, "unit price"), 2, 4)


def fmt_qty(q):
    if q in (None, ""):
        return ""
    d = Decimal(q)
    exp = max(0, -d.as_tuple().exponent)
    return f"{d:,.{exp}f}"


def fmt_unit_price(p):
    if p in (None, ""):
        return ""
    d = Decimal(p)
    exp = min(4, max(2, -d.as_tuple().exponent))
    s = f"${abs(d):,.{exp}f}"
    return f"({s})" if d < 0 else s


def parse_flag(text):
    """The narrow bidder column: Y / N / '' or a short note as typed."""
    t = str(text or "").strip()
    u = t.upper()
    if not t:
        return ""
    if u in YES_WORDS:
        return "Y"
    if u in NO_WORDS:
        return "N"
    return t[:24]


def parse_answer(text):
    """Checklist YES / NO / ''."""
    u = str(text or "").strip().upper()
    if u in YES_WORDS or u in ("TRUE", "1"):
        return "YES"
    if u in NO_WORDS or u in ("FALSE", "0"):
        return "NO"
    return str(text or "").strip()[:24]


def median_cents(values):
    vals = sorted(int(v) for v in values)
    if not vals:
        return None
    n = len(vals)
    if n % 2:
        return vals[n // 2]
    return to_cents((Decimal(vals[n // 2 - 1]) + vals[n // 2]) / 200)


# ============================================================ building
def _checklist():
    return {k: {"ans": "", "note": ""} for k in CHECK_KEYS}


def new_bidder(company="", phone="", contact="", price=None):
    return {"id": _id(), "company": company, "phone": phone,
            "contact": contact, "price": price, "checklist": _checklist(),
            "directory_id": "", "clar": []}


def new_line(desc=""):
    return {"id": _id(), "desc": desc, "qty": None, "unit": "",
            "unit_price": None, "lump": None, "bids": {}}


def new_sheet(csi="", trade="", bidders=DEFAULT_BIDDERS, header=None):
    h = {k: "" for k in HEADER_FIELDS}
    h.update({k: v for k, v in (header or {}).items() if k in h})
    return {"schema": SCHEMA_VERSION, "csi": csi or "", "trade": trade or "",
            "header": h,
            "budget": {"label": "", "price": None, "checklist": _checklist()},
            "bidders": [new_bidder() for _ in range(max(0, int(bidders)))],
            "lines": [],
            "award": {"bidder": "", "amount": None, "approved_by": "",
                      "approved_on": ""},
            "level": "none"}


def title(sheet):
    return f"{sheet.get('csi') or ''} {sheet.get('trade') or ''}".strip() \
        or "Scope Sheet"


def bidder(sheet, bid):
    return next((b for b in sheet["bidders"] if b["id"] == bid), None)


def line(sheet, lid):
    return next((ln for ln in sheet["lines"] if ln["id"] == lid), None)


def bidder_name(sheet, b, i=None):
    if isinstance(b, str):
        b = bidder(sheet, b)
    if b is None:
        return ""
    if i is None:
        i = next((n for n, x in enumerate(sheet["bidders"])
                  if x["id"] == b["id"]), 0)
    return (b.get("company") or "").strip() or f"Bidder {i + 1}"


def add_bidder(sheet, company="", index=None, **kw):
    b = new_bidder(company, **kw)
    if index is None:
        sheet["bidders"].append(b)
    else:
        sheet["bidders"].insert(index, b)
    return b


def remove_bidder(sheet, bid):
    sheet["bidders"] = [b for b in sheet["bidders"] if b["id"] != bid]
    for ln in sheet["lines"]:
        ln["bids"].pop(bid, None)
    if sheet["award"].get("bidder") == bid:
        sheet["award"]["bidder"] = ""
        sheet["award"]["amount"] = None


def add_line(sheet, desc="", index=None):
    ln = new_line(desc)
    if index is None or index >= len(sheet["lines"]):
        sheet["lines"].append(ln)
    else:
        sheet["lines"].insert(max(0, index), ln)
    return ln


def remove_line(sheet, lid):
    sheet["lines"] = [ln for ln in sheet["lines"] if ln["id"] != lid]


def move_line(sheet, lid, delta):
    """Move a line up (-1) or down (+1). Returns its new index."""
    ls = sheet["lines"]
    i = next((n for n, ln in enumerate(ls) if ln["id"] == lid), None)
    if i is None:
        return None
    j = max(0, min(len(ls) - 1, i + delta))
    ls.insert(j, ls.pop(i))
    return j


_KEEP = object()


def bid_cell(ln, bid):
    c = ln.get("bids", {}).get(bid) or {}
    return {"flag": c.get("flag") or "", "amount": c.get("amount")}


def set_bid(sheet, lid, bid, flag=_KEEP, amount=_KEEP):
    ln = line(sheet, lid)
    if ln is None:
        raise ScopeError("No such scope line.")
    c = bid_cell(ln, bid)
    if flag is not _KEEP:
        c["flag"] = parse_flag(flag)
    if amount is not _KEEP:
        c["amount"] = None if amount is None else int(amount)
    if not c["flag"] and c["amount"] is None:
        ln["bids"].pop(bid, None)
    else:
        ln["bids"][bid] = c
    return c


# ============================================================ clarifications
def parse_kind(text):
    """'excl' / 'Exclusion' / 'Q' -> one of CLAR_KINDS (default
    Clarification)."""
    t = str(text or "").strip().lower()
    for k in CLAR_KINDS:
        if t and k.lower().startswith(t[:4]):
            return k
    if t in ("q", "qual"):
        return "Qualification"
    if t in ("x", "e", "excl", "nic"):
        return "Exclusion"
    return "Clarification"


def parse_status(text):
    """'Accept' / 'accepted' / 'A' / 'Y' -> 'accepted'; 'Reject' / 'R' /
    'N' -> 'rejected'; anything else 'pending'."""
    t = str(text or "").strip().lower()
    if t in ("a", "y", "yes", "accept", "accepted", "ok"):
        return "accepted"
    if t in ("r", "n", "no", "reject", "rejected"):
        return "rejected"
    return "pending"


def new_clarification(text="", kind="Clarification", amount=None,
                      status="pending"):
    return {"id": _id(), "kind": parse_kind(kind),
            "text": " ".join(str(text or "").split())[:CLAR_TEXT_MAX],
            "amount": None if amount is None else int(amount),
            "status": parse_status(status)}


def clarifications(sheet, b):
    b = _b(sheet, b)
    return b.setdefault("clar", []) if b is not None else []


def add_clarification(sheet, b, text="", kind="Clarification", amount=None,
                      status="pending"):
    """Add a row to a bidder's list; returns it."""
    b = _b(sheet, b)
    if b is None:
        raise ScopeError("No such bidder.")
    c = new_clarification(text, kind, amount, status)
    b.setdefault("clar", []).append(c)
    return c


def clarification(sheet, b, cid):
    return next((c for c in clarifications(sheet, b) if c["id"] == cid),
                None)


def set_clarification(sheet, b, cid, text=None, kind=None, amount=None,
                      status=None, clear_amount=False):
    """Change a row. amount is cents (None = keep, unless clear_amount)."""
    c = clarification(sheet, b, cid)
    if c is None:
        raise ScopeError("No such clarification.")
    if text is not None:
        c["text"] = " ".join(str(text).split())[:CLAR_TEXT_MAX]
    if kind is not None:
        c["kind"] = parse_kind(kind)
    if clear_amount:
        c["amount"] = None
    elif amount is not None:
        c["amount"] = int(amount)
    if status is not None:
        c["status"] = parse_status(status)
    return c


def remove_clarification(sheet, b, cid):
    b = _b(sheet, b)
    if b is None:
        return False
    n = len(b.get("clar") or [])
    b["clar"] = [c for c in b.get("clar") or [] if c["id"] != cid]
    return len(b["clar"]) != n


def accepted_adjustment(sheet, b):
    """Sum (cents) of a bidder's accepted $ adjustments; 0 when none.
    Rejected and pending rows never count."""
    return sum(int(c["amount"]) for c in clarifications(sheet, b)
               if c.get("status") == "accepted" and
               c.get("amount") is not None)


def has_adjustments(sheet):
    """Does any bidder have an accepted row with a $ amount?"""
    return any(c.get("status") == "accepted" and c.get("amount") is not None
               for b in sheet["bidders"] for c in b.get("clar") or [])


def clarification_counts(sheet, b):
    out = {k: 0 for k in CLAR_STATUS}
    for c in clarifications(sheet, b):
        out[c.get("status") or "pending"] = \
            out.get(c.get("status") or "pending", 0) + 1
    return out


def rows_from_proposal(p, have=()):
    """Clarification rows prefilled from a parsed sub proposal
    (proposal_level.parse): each exclusion as an Exclusion, each
    qualification / clarification it lists as such - all Pending, no $
    (the estimator prices them). Texts already in `have` are skipped."""
    seen = {" ".join(str(t).lower().split()) for t in have}
    out = []
    for key, kind in (("exclusions", "Exclusion"),
                      ("qualifications", "Qualification"),
                      ("clarifications", "Clarification")):
        for t in (p or {}).get(key) or []:
            k = " ".join(str(t).lower().split())
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(new_clarification(t, kind))
    return out


# ============================================================ math
def budget_line_total(ln):
    """Qty x Unit $ (to the cent), else the typed lump sum, else None."""
    q, p = ln.get("qty"), ln.get("unit_price")
    if q not in (None, "") and p not in (None, ""):
        return to_cents(Decimal(q) * Decimal(p))
    return ln.get("lump")


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def budget_line_sum(sheet):
    return _sum(budget_line_total(ln) for ln in sheet["lines"])


def budget_total(sheet):
    """The budget: the scope lines when any are priced, else the stated
    budget price."""
    s = budget_line_sum(sheet)
    return s if s is not None else sheet["budget"].get("price")


def budget_math_check(sheet):
    p, s = sheet["budget"].get("price"), budget_line_sum(sheet)
    return None if p is None or s is None else p - s


def _b(sheet, b):
    return bidder(sheet, b) if isinstance(b, str) else b


def line_sum(sheet, b):
    """Sum of a bidder's scope amounts (None when none is priced)."""
    b = _b(sheet, b)
    return _sum(bid_cell(ln, b["id"])["amount"] for ln in sheet["lines"])


def bidder_total(sheet, b):
    """TOTAL PRICE: the summed lines, or the stated bid price when the
    bidder gave no breakdown."""
    b = _b(sheet, b)
    s = line_sum(sheet, b)
    return s if s is not None else b.get("price")


def math_check(sheet, b):
    """Stated BID PRICE minus the summed lines; None when either is
    missing. Non-zero means the sub's own numbers don't add up (or a line
    was typed wrong)."""
    b = _b(sheet, b)
    p, s = b.get("price"), line_sum(sheet, b)
    return None if p is None or s is None else p - s


def math_ok(sheet, b):
    m = math_check(sheet, b)
    return m is None or m == 0


def has_breakdown(sheet, b):
    return line_sum(sheet, b) is not None


def active(sheet, b):
    """A bidder that bid: a stated price or any priced line."""
    b = _b(sheet, b)
    return b.get("price") is not None or has_breakdown(sheet, b)


def excluded(sheet, ln, b):
    """Should this line be plugged for this bidder when leveling? Yes
    when it is flagged N with no amount, or - for a bidder who broke the
    bid down - left blank without a Y ("included") flag."""
    b = _b(sheet, b)
    c = bid_cell(ln, b["id"])
    if c["amount"] is not None:
        return False
    if c["flag"] == "N":
        return True
    if c["flag"]:                      # Y, or a note such as "ALLOW"
        return False
    return has_breakdown(sheet, b)


def plug_value(sheet, ln, b, mode):
    """(cents, source) to plug an excluded line, or (None, '')."""
    b = _b(sheet, b)
    if mode == "budget":
        v = budget_line_total(ln)
        return (v, "budget") if v is not None else (None, "")
    if mode == "median":
        others = [bid_cell(ln, o["id"])["amount"] for o in sheet["bidders"]
                  if o["id"] != b["id"]]
        others = [v for v in others if v is not None]
        if others:
            return median_cents(others), "median"
        v = budget_line_total(ln)
        return (v, "budget") if v is not None else (None, "")
    return None, ""


def leveled(sheet, mode=None, adjust=True):
    """{bidder id: {"total", "base", "plugged", "adjusted", "plugs": {line
    id: (cents, source)}}} - totals made apples to apples by plugging what
    each bidder excluded and (adjust=True) adding the bidder's accepted
    clarification adjustments (a credit deducts). Bidders who didn't bid
    get total None."""
    mode = mode or sheet.get("level") or "none"
    out = {}
    for b in sheet["bidders"]:
        base = bidder_total(sheet, b)
        plugs = {}
        if mode in ("budget", "median") and active(sheet, b):
            for ln in sheet["lines"]:
                if excluded(sheet, ln, b):
                    v, src = plug_value(sheet, ln, b, mode)
                    if v is not None:
                        plugs[ln["id"]] = (v, src)
        added = sum(v for v, _s in plugs.values())
        adj = accepted_adjustment(sheet, b) if adjust else 0
        out[b["id"]] = {"total": None if base is None else
                        base + added + adj,
                        "base": base, "plugged": added, "adjusted": adj,
                        "plugs": plugs}
    return out


def low_bidder(sheet, mode=None, adjust=True):
    """Id of the low bidder ('' when nobody bid). mode: None = the sheet's
    leveling setting, "none" = no plugs; adjust=False leaves accepted
    clarification adjustments out ("none" + adjust=False = as bid)."""
    mode = mode or sheet.get("level") or "none"
    lv = leveled(sheet, mode, adjust)
    best = None
    for b in sheet["bidders"]:
        t = lv[b["id"]]["total"]
        if t is None or not active(sheet, b):
            continue
        if best is None or t < best[0]:
            best = (t, b["id"])
    return best[1] if best else ""


def spread(sheet, amount):
    """amount vs budget: (cents over (+) / under (-), percent Decimal to
    0.1) - percent None when there is no budget."""
    bud = budget_total(sheet)
    if amount is None or bud is None:
        return None, None
    d = amount - bud
    pct = None if bud == 0 else (Decimal(d) * 100 / Decimal(bud)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)
    return d, pct


def award_amount(sheet):
    """The award amount: typed, else the recommended bidder's total."""
    a = sheet.get("award") or {}
    if a.get("amount") is not None:
        return a["amount"]
    b = bidder(sheet, a.get("bidder") or "")
    return bidder_total(sheet, b) if b else None


def summary(sheet):
    """One row of the Scope Sheets list."""
    low = low_bidder(sheet, "none", adjust=False)
    low_amt = bidder_total(sheet, low) if low else None
    lv_mode = sheet.get("level") or "none"
    if lv_mode != "none" or has_adjustments(sheet):
        lv_low = low_bidder(sheet, lv_mode)
        lv_amt = leveled(sheet, lv_mode)[lv_low]["total"] if lv_low \
            else None
    else:
        lv_low, lv_amt = low, low_amt
    aw = (sheet.get("award") or {}).get("bidder") or ""
    aw_amt = award_amount(sheet)
    basis = aw_amt if aw else low_amt
    var, pct = spread(sheet, basis)
    return {"csi": sheet.get("csi") or "", "trade": sheet.get("trade") or "",
            "budget": budget_total(sheet),
            "low_bidder": bidder_name(sheet, low) if low else "",
            "low_bid": low_amt,
            "leveled_low_bidder": bidder_name(sheet, lv_low) if lv_low
            else "",
            "leveled_low": lv_amt,
            "award_bidder": bidder_name(sheet, aw) if aw else "",
            "award_amount": aw_amt if aw else None,
            "variance": var, "variance_pct": pct,
            "bids": sum(1 for b in sheet["bidders"] if active(sheet, b)),
            "math_errors": sum(1 for b in sheet["bidders"]
                               if not math_ok(sheet, b))}


# ============================================================ dict / store
def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return parse_money(v)
        except ScopeError:
            return None


def _dec_or_none(v, places=(0, 4)):
    if v is None or v == "":
        return None
    try:
        return _dec_text(parse_decimal(v), *places)
    except ScopeError:
        return None


def _s(v):
    return "" if v is None else str(v)


def _chk(d):
    out = _checklist()
    for k in CHECK_KEYS:
        v = (d or {}).get(k) or {}
        if isinstance(v, str):
            v = {"ans": v}
        out[k] = {"ans": parse_answer(v.get("ans")), "note": _s(v.get("note"))}
    return out


def migrate(d):
    """Bring an older record up to SCHEMA_VERSION. 0/1 -> 2: every bidder
    gets an empty clarifications list (nothing else changed)."""
    try:
        v = int(d.get("schema") or 0)
    except (TypeError, ValueError):
        v = 0
    if v > SCHEMA_VERSION:
        raise ScopeError("This scope sheet was saved by a newer version of "
                         "QuantiSheet; update to open it.")
    if v < 2:
        for b in d.get("bidders") or []:
            if isinstance(b, dict) and not isinstance(b.get("clar"), list):
                b["clar"] = []
        d["schema"] = 2
    return d


def _clar_list(rows):
    out, seen = [], set()
    for c in rows if isinstance(rows, list) else []:
        if not isinstance(c, dict):
            continue
        nc = new_clarification(_s(c.get("text")), c.get("kind"),
                               _int_or_none(c.get("amount")),
                               c.get("status"))
        cid = _s(c.get("id")) or nc["id"]
        if cid in seen:
            cid = _id()
        seen.add(cid)
        nc["id"] = cid
        if nc["text"] or nc["amount"] is not None:
            out.append(nc)
    return out


def from_dict(d):
    """A clean sheet from a stored record (unknown fields dropped, types
    fixed, ids made where missing). Record bookkeeping (_id, _no ...) is
    kept so saving updates the same record."""
    d = migrate(copy.deepcopy(d or {}))
    sh = new_sheet(bidders=0)
    sh["csi"] = _s(d.get("csi"))
    sh["trade"] = _s(d.get("trade"))
    sh["header"].update({k: _s(v) for k, v in (d.get("header") or {}).items()
                         if k in HEADER_FIELDS})
    bud = d.get("budget") or {}
    sh["budget"] = {"label": _s(bud.get("label")),
                    "price": _int_or_none(bud.get("price")),
                    "checklist": _chk(bud.get("checklist"))}
    seen = set()
    for b in d.get("bidders") or []:
        nb = new_bidder()
        bid = _s(b.get("id")) or nb["id"]
        if bid in seen:
            bid = _id()
        seen.add(bid)
        nb.update(id=bid, company=_s(b.get("company")),
                  phone=_s(b.get("phone")), contact=_s(b.get("contact")),
                  price=_int_or_none(b.get("price")),
                  checklist=_chk(b.get("checklist")),
                  directory_id=_s(b.get("directory_id")),
                  clar=_clar_list(b.get("clar")))
        sh["bidders"].append(nb)
    for ln in d.get("lines") or []:
        nl = new_line(_s(ln.get("desc")))
        nl["id"] = _s(ln.get("id")) or nl["id"]
        nl["qty"] = _dec_or_none(ln.get("qty"))
        nl["unit"] = _s(ln.get("unit"))
        nl["unit_price"] = _dec_or_none(ln.get("unit_price"), (2, 4))
        nl["lump"] = _int_or_none(ln.get("lump"))
        if nl["qty"] is not None and nl["unit_price"] is not None:
            nl["lump"] = None                 # Qty x Unit $ is the total
        for bid, c in (ln.get("bids") or {}).items():
            if bid not in seen or not isinstance(c, dict):
                continue
            flag = parse_flag(c.get("flag"))
            amt = _int_or_none(c.get("amount"))
            if flag or amt is not None:
                nl["bids"][bid] = {"flag": flag, "amount": amt}
        sh["lines"].append(nl)
    a = d.get("award") or {}
    sh["award"] = {"bidder": _s(a.get("bidder")) if a.get("bidder") in seen
                   else "",
                   "amount": _int_or_none(a.get("amount")),
                   "approved_by": _s(a.get("approved_by")),
                   "approved_on": _s(a.get("approved_on"))}
    sh["level"] = d.get("level") if d.get("level") in LEVEL_MODES else "none"
    for k, v in d.items():
        if k.startswith("_"):
            sh[k] = v
    return sh


def to_dict(sheet):
    """JSON-safe copy for the store (schema version stamped)."""
    d = copy.deepcopy(from_dict(sheet))
    d["schema"] = SCHEMA_VERSION
    return d


def content(sheet):
    """The sheet's content with ids replaced by position, for comparing
    two sheets (an import with the export it came from)."""
    d = to_dict(sheet)
    pos = {b["id"]: i for i, b in enumerate(d["bidders"])}
    for k in [k for k in d if k.startswith("_")]:
        del d[k]
    for b in d["bidders"]:
        b.pop("id")
        b.pop("directory_id", None)
        for c in b.get("clar") or []:
            c.pop("id", None)
    for ln in d["lines"]:
        ln.pop("id")
        ln["bids"] = {pos[k]: v for k, v in sorted(
            ln["bids"].items(), key=lambda kv: pos[kv[0]])}
    a = d["award"]
    a["bidder"] = pos.get(a["bidder"], "")
    return d


def list_sheets(store):
    out = [from_dict(r) for r in store.list(COLL)]
    out.sort(key=lambda s: (s.get("csi") or "~", (s.get("trade") or "")
                            .lower()))
    return out


def save_sheet(store, sheet):
    """Add or update; returns the stored sheet (with its _id)."""
    rec = store.save_record(COLL, to_dict(sheet))
    sheet.update({k: v for k, v in rec.items() if k.startswith("_")})
    return sheet


def delete_sheet(store, sheet_or_id):
    rid = sheet_or_id if isinstance(sheet_or_id, str) else \
        sheet_or_id.get("_id")
    if rid:
        store.delete(COLL, rid)


def duplicate(sheet, trade=None):
    """A copy for another trade: same lines, bidders and budget; new ids,
    no award."""
    d = to_dict(sheet)
    for k in [k for k in d if k.startswith("_")]:
        del d[k]
    ids = {}
    for b in d["bidders"]:
        ids[b["id"]] = b["id"] = _id()
        b["clar"] = []                  # a sub's clarifications are per trade
    for ln in d["lines"]:
        ln["id"] = _id()
        ln["bids"] = {ids[k]: v for k, v in ln["bids"].items()}
    d["award"] = {"bidder": "", "amount": None, "approved_by": "",
                  "approved_on": ""}
    d["trade"] = trade if trade is not None else (
        (d.get("trade") or "Trade") + " (copy)")
    return from_dict(d)


# ============================================================ prefill
def company_info(store=None):
    """Your company's name and logo, from your own settings (the proposal
    company, else the project's contractor, else the company name)."""
    from .. import settings
    comp = settings.get("company") or {}
    if not isinstance(comp, dict):
        comp = {}
    name = str(comp.get("name") or "").strip()
    if not name and store is not None:
        name = str(store.setting("contractor") or
                   store.setting("company_name") or "").strip()
    if not name:
        name = str(settings.get("company_name") or "").strip()
    logo = str(comp.get("logo") or "")
    return {"name": name, "logo": logo if logo and os.path.isfile(logo)
            else ""}


def budget_label(sheet=None, company=None):
    lab = ((sheet or {}).get("budget") or {}).get("label") or ""
    if lab:
        return lab
    name = (company or {}).get("name") if isinstance(company, dict) \
        else (company or "")
    return f"{name} Budget" if name else "Budget"


def _division(code):
    m = re.match(r"\s*(\d{2})", str(code or ""))
    return m.group(1) if m else ""


def packages_for(store, csi="", trade=""):
    """The project's bid packages for this trade (same spec section, else
    same division, else the trade name)."""
    from .store import spec_number
    sec, div = spec_number(csi), _division(csi)
    t = (trade or "").strip().lower()
    exact, near = [], []
    for r in store.list("bidpkg"):
        txt = f"{r.get('trades') or ''} {r.get('specs') or ''}"
        if sec and sec in (spec_number(txt), spec_number(r.get("specs"))):
            exact.append(r)
        elif div and _division(txt) == div:
            near.append(r)
        elif t and t == (r.get("title") or "").strip().lower():
            near.append(r)
    return exact + near


def prefill_header(store, csi="", trade=""):
    """Project name / number / estimator / bid date and time from the
    project (and its bid package for the trade, when there is one)."""
    from .. import settings
    h = {k: "" for k in HEADER_FIELDS}
    if store is None:
        h["estimator"] = settings.author() or ""
        return h
    h["project"] = store.name or ""
    h["project_no"] = str(store.setting("number") or "")
    h["estimator"] = str(store.setting("estimator") or "") or \
        (settings.author() or "")
    h["bid_date"] = str(store.setting("bid_date") or "")
    h["bid_time"] = str(store.setting("bid_time") or "")
    pk = packages_for(store, csi, trade)
    if pk:
        h["bid_date"] = pk[0].get("due") or h["bid_date"]
        h["bid_time"] = pk[0].get("due_time") or h["bid_time"]
    return h


def bidders_from_package(store, sheet):
    """Add the bid package's bidders (company, contact, amount) to the
    sheet, filling blank bidder blocks first. Returns how many were
    added."""
    pk = packages_for(store, sheet.get("csi"), sheet.get("trade"))
    if not pk:
        return 0
    have = {(b.get("company") or "").strip().lower()
            for b in sheet["bidders"]}
    n = 0
    for row in pk[0].get("bidders") or []:
        name = (row.get("company") or "").strip()
        if not name or name.lower() in have:
            continue
        price = None
        if row.get("amount") not in (None, ""):
            try:
                price = parse_money(row.get("amount"))
            except ScopeError:
                price = None
        blank = next((b for b in sheet["bidders"] if not b["company"] and
                      not active(sheet, b)), None)
        b = blank or add_bidder(sheet)
        b.update(company=name, contact=row.get("contact") or "",
                 price=price)
        have.add(name.lower())
        n += 1
    return n


def directory_matches(contacts, csi="", trade=""):
    """Company Directory entries for this trade: same CSI division, or a
    trade word in common; the rest after them. Favorites first."""
    div = _division(csi)
    words = set(re.findall(r"[a-z]{4,}", (trade or "").lower()))
    words -= {"work", "trade", "general", "other"}
    first, rest = [], []
    for c in contacts:
        if not (c.get("company") or "").strip():
            continue
        ctr = set(re.findall(r"[a-z]{4,}", f"{c.get('trade') or ''} "
                                           f"{c.get('type') or ''}".lower()))
        if (div and c.get("division") == div) or (words & ctr):
            first.append(c)
        else:
            rest.append(c)
    key = lambda c: (not c.get("favorite"), (c.get("company") or "").lower())
    return sorted(first, key=key), sorted(rest, key=key)


def trade_choices():
    """(code, title) for the CSI picker: the MasterFormat divisions."""
    from ..csi import DIVISIONS
    return [(f"{d} 00 00", t.capitalize()) for d, t in sorted(
        DIVISIONS.items())]


# ============================================================ Excel export
COLS_W = {"A": 2.5, "B": 46.5, "C": 45.3, "D": 18.7, "E": 8.0, "F": 16.2,
          "G": 16.2}
NARROW_W, WIDE_W = 6.8, 19.3
FIRST_LINE = 16


def layout(n_lines):
    """Rows of a tab with `n_lines` scope lines (at least 45: rows 16-60,
    then TOTAL 61, Math Check 62, footer 63-64 - the template)."""
    n = max(MIN_LINES, n_lines)
    last = FIRST_LINE + n - 1
    return {"first": FIRST_LINE, "last": last, "total": last + 1,
            "check": last + 2, "foot1": last + 3, "foot2": last + 4}


def block_cols(k):
    """Column numbers (narrow, wide) of bidder block k (0-5): H/I ... R/S."""
    return 8 + 2 * k, 9 + 2 * k


def tab_names(sheets):
    """One Excel tab name per sheet page: "09 29 00 Drywall", then
    "... (2)" for bidders 7-12. Unique, <= 31 chars, no []:*?/\\."""
    used = {"summary"}
    out = []
    for sh in sheets:
        pages = max(1, -(-len(sh["bidders"]) // PER_PAGE))
        base = re.sub(r"[\[\]:*?/\\']", " ", title(sh))
        base = re.sub(r"\s+", " ", base).strip() or "Scope Sheet"
        names = []
        for p in range(pages):
            suf = f" ({p + 1})" if p else ""
            n, k = (base[:31 - len(suf)].rstrip() + suf), 2
            while n.lower() in used:
                extra = f" {k}{suf}"
                n = base[:31 - len(extra)].rstrip() + extra
                k += 1
            used.add(n.lower())
            names.append(n)
        out.append(names)
    return out


def _q(name):
    return "'" + name.replace("'", "''") + "'"


def export_xlsx(sheets, path, company=None, project=None):
    """Write the scope sheets to an Excel workbook laid out like the
    template, with live formulas: Total = Qty x Unit $, TOTAL = SUM, Math
    Check = BID PRICE - TOTAL, a Summary tab referencing the trade tabs.
    Returns the path."""
    from openpyxl import Workbook
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as L
    from .. import safecell
    Fx = safecell.Formula          # the sheet's own formulas stay live

    company = company if isinstance(company, dict) else \
        {"name": company or "", "logo": ""}
    sheets = [from_dict(s) for s in sheets]
    wb = Workbook()
    summ = wb.active
    summ.title = "Summary"
    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    yellow = PatternFill("solid", fgColor=YELLOW)
    red = PatternFill("solid", fgColor="FFFFC7CE")
    grey = PatternFill("solid", fgColor="FFF2F2F2")
    arial = lambda sz=10, b=False, i=False: Font(name="Arial", size=sz,
                                                 bold=b, italic=i)
    top_left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    names = tab_names(sheets)
    refs = []                                  # per sheet: dict of refs

    def put(ws, ref, value, font=None, fill=None, align=None, fmt=None,
            border=True):
        c = ws[ref]
        # user text (descriptions, bidder names, notes) is stored as text
        # even when it starts with = + - @; only Formula(...) stays live
        safecell.set_text(c, value)
        c.font = font or arial()
        if fill is not None:
            c.fill = fill
        if align is not None:
            c.alignment = align
        if fmt:
            c.number_format = fmt
        if border:
            c.border = box
        return c

    def merge(ws, rng, value=None, **kw):
        first = rng.split(":")[0]
        put(ws, first, value, **kw)
        if ":" in rng:
            from openpyxl.utils.cell import range_boundaries
            c1, r1, c2, r2 = range_boundaries(rng)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    cell = ws.cell(r, c)
                    if kw.get("border", True):
                        cell.border = box
                    if kw.get("fill") is not None:
                        cell.fill = kw["fill"]
            ws.merge_cells(rng)

    for si, sh in enumerate(sheets):
        lay = layout(len(sh["lines"]))
        F, last, T, M = lay["first"], lay["last"], lay["total"], lay["check"]
        h = sh["header"]
        pages = names[si]
        sref = {"tabs": [], "budget": None, "award": None}
        for p, tab in enumerate(pages):
            ws = wb.create_sheet(tab)
            sref["tabs"].append(tab)
            for col, w in COLS_W.items():
                ws.column_dimensions[col].width = w
            for k in range(PER_PAGE):
                n, w = block_cols(k)
                ws.column_dimensions[L(n)].width = NARROW_W
                ws.column_dimensions[L(w)].width = WIDE_W
            ws.row_dimensions[1].height = 22.5
            ws.row_dimensions[lay["foot1"]].height = 39
            ws.row_dimensions[lay["foot2"]].height = 19.75
            # ---- header
            merge(ws, "B1:S1", h.get("project") or project or "",
                  font=arial(16, True), align=top_left)
            merge(ws, "B2:C2", f"CONTROL #  {h.get('control_no') or ''}"
                  .rstrip(), align=top_left)
            merge(ws, "D2:F2", f"PROJECT #  {h.get('project_no') or ''}"
                  .rstrip(), font=arial(10, True), align=top_left)
            merge(ws, "G2:J2", f"BID DATE:  {h.get('bid_date') or ''}"
                  .rstrip(), font=arial(10, True), align=top_left)
            merge(ws, "K2:M2", f"TIME:  {h.get('bid_time') or ''}".rstrip(),
                  font=arial(10, True), align=top_left)
            merge(ws, "N2:S2", f"ESTIMATOR:  {h.get('estimator') or ''}"
                  .rstrip(), font=arial(10, True), align=top_left)
            comp_line = company.get("name") or ""
            if len(pages) > 1:
                comp_line = (comp_line + "   " if comp_line else "") + \
                    f"Bidders page {p + 1} of {len(pages)}"
            merge(ws, "B3:S3", comp_line, font=arial(9, True, True),
                  align=top_left)
            merge(ws, "B4:C6", f"TRADE:  {title(sh)}", font=arial(10, True),
                  align=top_left)
            for r, lab in ((4, "COMPANY"), (5, "TELEPHONE"), (6, "CONTACT")):
                put(ws, f"D{r}", lab, font=arial(10, True), align=top_left)
            merge(ws, "E4:G4", budget_label(sh, company), align=top_left,
                  font=arial(10, True))
            merge(ws, "E5:G5", "")
            merge(ws, "E6:G6", "")
            put(ws, "B7", None)
            put(ws, "C7", "BID PRICE", align=top_left)
            put(ws, "B8", "CHECKLIST", align=top_left)
            put(ws, "C8", None)
            merge(ws, "D7:G8", dollars(sh["budget"]["price"]), fmt=ACCOUNTING,
                  align=right)
            for i, (key, lab) in enumerate(CHECKLIST):
                r = 9 + i
                if key == "addenda":
                    lab = (f"ADDENDA   {h.get('addenda_from') or ''}   TO   "
                           f"{h.get('addenda_to') or ''}").rstrip()
                merge(ws, f"B{r}:C{r}", lab, align=top_left)
                c = sh["budget"]["checklist"][key]
                merge(ws, f"D{r}:E{r}", c["ans"] or None, align=center)
                merge(ws, f"F{r}:G{r}", c["note"] or None, align=top_left)
            merge(ws, "B15:C15", "SCOPE", font=arial(9, True), align=top_left)
            for col, lab in (("D", "QTY"), ("E", "UNIT"), ("F", "UNIT $"),
                             ("G", "TOTAL")):
                put(ws, f"{col}15", lab, font=arial(9, True), align=center,
                    fill=grey)
            # ---- budget block lines
            for i in range(last - F + 1):
                r = F + i
                ln = sh["lines"][i] if i < len(sh["lines"]) else None
                merge(ws, f"B{r}:C{r}", ln["desc"] if ln else None,
                      font=Font(name="Times New Roman", size=10),
                      align=Alignment(horizontal="left", vertical="center",
                                      wrap_text=True))
                q = Decimal(ln["qty"]) if ln and ln["qty"] is not None \
                    else None
                put(ws, f"D{r}", q, align=right,
                    fmt="#,##0" if q is None or q == q.to_integral_value()
                    else "#,##0.00##")
                put(ws, f"E{r}", (ln["unit"] or None) if ln else None,
                    align=center)
                put(ws, f"F{r}", Decimal(ln["unit_price"]) if ln and
                    ln["unit_price"] is not None else None, fmt=UNIT_PRICE)
                lump = ln is not None and (ln["qty"] is None or
                                           ln["unit_price"] is None) and \
                    ln["lump"] is not None
                put(ws, f"G{r}", dollars(ln["lump"]) if lump else
                    Fx(f'=IF(OR(D{r}="",F{r}=""),"",ROUND(D{r}*F{r},2))'),
                    fmt=ACCOUNTING)
            # ---- bidder blocks
            page_bidders = sh["bidders"][p * PER_PAGE:(p + 1) * PER_PAGE]
            for k in range(PER_PAGE):
                b = page_bidders[k] if k < len(page_bidders) else None
                n, w = block_cols(k)
                N, W = L(n), L(w)
                merge(ws, f"{N}4:{W}4", b["company"] or None if b else None,
                      fill=yellow, font=Font(name="Times New Roman", size=10,
                                             bold=True), align=top_left)
                merge(ws, f"{N}5:{W}5", (b["phone"] or None) if b else None,
                      fill=yellow, font=Font(name="Times New Roman",
                                             size=10), align=top_left)
                merge(ws, f"{N}6:{W}6", (b["contact"] or None) if b else None,
                      fill=yellow, font=Font(name="Times New Roman",
                                             size=10), align=top_left)
                merge(ws, f"{N}7:{W}8", dollars(b["price"]) if b else None,
                      fill=yellow, fmt=ACCOUNTING, align=right,
                      font=arial(10, True))
                for i, key in enumerate(CHECK_KEYS):
                    c = b["checklist"][key] if b else {"ans": "", "note": ""}
                    put(ws, f"{N}{9 + i}", c["ans"] or None, fill=yellow,
                        align=center)
                    put(ws, f"{W}{9 + i}", c["note"] or None, fill=yellow,
                        align=top_left)
                put(ws, f"{N}15", "INCL", font=arial(8, True), align=center,
                    fill=grey)
                put(ws, f"{W}15", "AMOUNT", font=arial(9, True),
                    align=center, fill=grey)
                for i in range(last - F + 1):
                    r = F + i
                    ln = sh["lines"][i] if i < len(sh["lines"]) else None
                    cell = bid_cell(ln, b["id"]) if (b and ln) else \
                        {"flag": "", "amount": None}
                    put(ws, f"{N}{r}", cell["flag"] or None, fill=yellow,
                        align=center,
                        font=Font(name="Times New Roman", size=10))
                    put(ws, f"{W}{r}", dollars(cell["amount"]), fill=yellow,
                        fmt=ACCOUNTING,
                        font=Font(name="Times New Roman", size=10))
                rng = f"{W}{F}:{W}{last}"
                merge(ws, f"{N}{T}:{W}{T}",
                      Fx(f'=IF(COUNT({rng})=0,IF({N}7="","",{N}7),'
                         f'SUM({rng}))'),
                      fmt=ACCOUNTING, font=arial(10, True))
                merge(ws, f"{N}{M}:{W}{M}",
                      Fx(f'=IF(OR({N}7="",COUNT({rng})=0),"",'
                         f'{N}7-SUM({rng}))'),
                      fmt=ACCOUNTING, font=arial(9))
                ws.conditional_formatting.add(
                    f"{N}{M}:{W}{M}",
                    FormulaRule(formula=[f"AND(ISNUMBER({N}{M}),"
                                         f"ROUND({N}{M},2)<>0)"],
                                fill=red, font=Font(color="FF9C0006",
                                                    bold=True)))
            # ---- totals
            brng = f"G{F}:G{last}"
            put(ws, f"B{T}", "TOTAL PRICE", font=arial(9, True),
                align=top_left)
            merge(ws, f"C{T}:E{T}", budget_label(sh, company),
                  font=arial(9, True), align=Alignment(horizontal="right",
                                                       vertical="top",
                                                       indent=1))
            merge(ws, f"F{T}:G{T}",
                  Fx(f'=IF(COUNT({brng})=0,IF(D7="","",D7),SUM({brng}))'),
                  fmt=ACCOUNTING, font=arial(10, True))
            put(ws, f"B{M}", "Math Check (Bid Price - Total)",
                font=arial(9), align=top_left)
            merge(ws, f"C{M}:E{M}", None)
            merge(ws, f"F{M}:G{M}",
                  Fx(f'=IF(OR(D7="",COUNT({brng})=0),"",D7-SUM({brng}))'),
                  fmt=ACCOUNTING, font=arial(9))
            ws.conditional_formatting.add(
                f"F{M}:G{M}",
                FormulaRule(formula=[f"AND(ISNUMBER(F{M}),ROUND(F{M},2)<>0)"],
                            fill=red, font=Font(color="FF9C0006", bold=True)))
            # ---- footer
            f1, f2 = lay["foot1"], lay["foot2"]
            merge(ws, f"B{f1}:F{f1}", budget_label(sh, company),
                  align=Alignment(horizontal="left", vertical="center"),
                  border=False)
            merge(ws, f"B{f2}:F{f2}", Fx(f"=F{T}"), fmt=CURRENCY,
                  font=arial(10, True), border=False,
                  align=Alignment(horizontal="left", vertical="top"))
            aw = bidder(sh, sh["award"]["bidder"]) if sh["award"]["bidder"] \
                else None
            merge(ws, f"H{f1}:N{f1}",
                  "RECOMMENDED AWARD TO:  " + (bidder_name(sh, aw) if aw
                                               else ""),
                  align=Alignment(horizontal="left", vertical="center",
                                  wrap_text=True), border=False)
            amt = None
            if aw is not None:
                ai = sh["bidders"].index(aw)
                ap = ai // PER_PAGE
                an, _aw = block_cols(ai % PER_PAGE)
                if sh["award"]["amount"] is not None:
                    amt = dollars(sh["award"]["amount"])
                else:
                    pre = "" if ap == p else _q(pages[ap]) + "!"
                    amt = Fx(f"={pre}{L(an)}{T}")
            merge(ws, f"O{f1}:S{f1}", amt if amt is not None else "AMOUNT:",
                  fmt='"AMOUNT:  "$#,##0.00_);"AMOUNT:  "($#,##0.00);'
                      '"AMOUNT:  "$0.00;@',
                  align=Alignment(horizontal="left", vertical="center"),
                  border=False)
            for col in range(2, 20):
                ws.cell(f1, col).border = Border(top=thin)
            merge(ws, f"I{f2}:N{f2}", ("OWNER APPROVAL:  " +
                                       (sh["award"]["approved_by"] or ""))
                  .rstrip(), align=top_left, border=False)
            merge(ws, f"O{f2}:S{f2}", ("DATE:  " +
                                       (sh["award"]["approved_on"] or ""))
                  .rstrip(), align=top_left, border=False)
            if p == 0:
                sref["budget"] = f"{_q(tab)}!F{T}"
                if aw is not None:
                    sref["award"] = f"{_q(tab)}!O{f1}"
            # ---- clarifications (first tab of the trade, every bidder)
            end = f2
            if p == 0 and any(b.get("clar") for b in sh["bidders"]):
                end = _clar_block(sh, ws, f2 + 2, put, merge, arial, grey,
                                  top_left, center, right)
            # ---- print setup: landscape, 1 page wide
            ws.page_setup.orientation = "landscape"
            ws.page_setup.paperSize = ws.PAPERSIZE_TABLOID
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.print_area = f"A1:S{end}"
            ws.page_margins.left = ws.page_margins.right = 0.4
            ws.page_margins.top = ws.page_margins.bottom = 0.5
            ws.freeze_panes = f"D{F}"
            ws.sheet_view.zoomScale = 85
            if company.get("logo") and p == 0:
                _logo(ws, company["logo"])
        sref["totals"] = [f"{_q(t)}!$H${T}:$S${T}" for t in sref["tabs"]]
        sref["names"] = [f"{_q(t)}!$H$4:$S$4" for t in sref["tabs"]]
        sref["award_name"] = bidder_name(sh, sh["award"]["bidder"]) \
            if sh["award"]["bidder"] else ""
        refs.append(sref)
    _summary_tab(summ, sheets, refs, company, project, put, merge, arial,
                 box, grey, right, top_left)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)
    return path


CLAR_HEAD = "CLARIFICATIONS"
CLAR_TOTAL = "ACCEPTED TOTAL"


def _clar_block(sh, ws, r, put, merge, arial, grey, top_left, center, right):
    """The trade's Clarifications section from row r: per bidder, each
    qualification / exclusion / clarification (type, text, $ adjustment,
    status), then the accepted total and the leveled total. Returns the
    last row written."""
    from openpyxl.styles import Alignment
    merge(ws, f"B{r}:G{r}", f"{CLAR_HEAD}  -  {title(sh)}",
          font=arial(10, True), align=top_left, fill=grey)
    r += 1
    put(ws, f"B{r}", "BIDDER", font=arial(9, True), align=center, fill=grey)
    put(ws, f"C{r}", "QUALIFICATION / EXCLUSION / CLARIFICATION",
        font=arial(9, True), align=center, fill=grey)
    merge(ws, f"D{r}:E{r}", "TYPE", font=arial(9, True), align=center,
          fill=grey)
    put(ws, f"F{r}", "ADJUSTMENT", font=arial(9, True), align=center,
        fill=grey)
    put(ws, f"G{r}", "STATUS", font=arial(9, True), align=center, fill=grey)
    lv = leveled(sh)
    wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)
    for i, b in enumerate(sh["bidders"]):
        rows = b.get("clar") or []
        if not rows:
            continue
        name = bidder_name(sh, b, i)
        for c in rows:
            r += 1
            put(ws, f"B{r}", name, align=top_left)
            put(ws, f"C{r}", c["text"] or None, align=wrap)
            merge(ws, f"D{r}:E{r}", c["kind"], align=center)
            put(ws, f"F{r}", dollars(c["amount"]), fmt=ACCOUNTING)
            put(ws, f"G{r}", {"accepted": "ACCEPTED",
                              "rejected": "REJECTED"}.get(c["status"],
                                                          "PENDING"),
                align=center)
        r += 1
        t = lv[b["id"]]["total"]
        put(ws, f"B{r}", name, font=arial(9, True), align=top_left)
        put(ws, f"C{r}", "Accepted adjustments (in the leveled total"
            + (f": {fmt_money(t)}" if t is not None else "") + ")",
            font=arial(9, True), align=top_left)
        merge(ws, f"D{r}:E{r}", CLAR_TOTAL, font=arial(8, True),
              align=center)
        put(ws, f"F{r}", dollars(accepted_adjustment(sh, b)), fmt=ACCOUNTING,
            font=arial(9, True))
        put(ws, f"G{r}", None)
    return r


def _read_clar(gf, val, start):
    """[(bidder name, row dict)] of a tab's Clarifications section."""
    out = []
    r0 = None
    for r in range(start, start + 60):
        if str(val(r, 2) or "").strip().upper().startswith(CLAR_HEAD):
            r0 = r
            break
    if r0 is None:
        return out
    r = r0 + 2
    blank = 0
    while blank < 3 and r < r0 + 2000:
        name = _txt(val(r, 2))
        text = _txt(val(r, 3))
        kind = _txt(val(r, 4))
        if not name and not text:
            blank += 1
            r += 1
            continue
        blank = 0
        if kind.upper() != CLAR_TOTAL:
            amt = val(r, 6)
            try:
                cents = parse_money(amt) if amt not in (None, "") else None
            except ScopeError:
                cents = None
            out.append((name, new_clarification(text, kind, cents,
                                                _txt(val(r, 7)))))
        r += 1
    return out


def _attach_clar(sh, rows):
    for name, c in rows:
        key = name.strip().lower()
        b = next((x for i, x in enumerate(sh["bidders"])
                  if bidder_name(sh, x, i).strip().lower() == key), None)
        if b is not None:
            b.setdefault("clar", []).append(c)


def _logo(ws, logo):
    try:
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(logo)
        ratio = 28 / float(img.height or 28)
        img.height = 28
        img.width = max(1, int(img.width * ratio))
        ws.add_image(img, "Q1")
    except Exception:
        import logging
        logging.getLogger(__name__).debug("logo not added", exc_info=True)


def _summary_tab(ws, sheets, refs, company, project, put, merge, arial, box,
                 grey, right, top_left):
    from openpyxl.styles import Alignment
    from .. import safecell
    Fx = safecell.Formula
    proj = project or next((s["header"].get("project") for s in sheets
                            if s["header"].get("project")), "")
    safecell.set_text(ws["B1"], proj or "Scope Sheets")
    ws["B1"].font = arial(16, True)
    safecell.set_text(ws["B2"], (company.get("name") + "  -  " if
                                 company.get("name") else "")
                      + "Scope Sheet Summary")
    ws["B2"].font = arial(10, True, True)
    heads = ["CSI", "TRADE", "BUDGET", "LOW BID", "LOW BIDDER",
             "LOW vs BUDGET", "%", "RECOMMENDED AWARD", "AWARD AMOUNT",
             "AWARD vs BUDGET"]
    widths = [12, 34, 16, 16, 30, 16, 9, 30, 16, 16]
    from openpyxl.utils import get_column_letter as L
    ws.column_dimensions["A"].width = 2.5
    for i, (hd, w) in enumerate(zip(heads, widths)):
        col = L(2 + i)
        ws.column_dimensions[col].width = w
        put(ws, f"{col}4", hd, font=arial(9, True), fill=grey,
            align=Alignment(horizontal="center", vertical="center",
                            wrap_text=True))
    r = 5
    for sh, ref in zip(sheets, refs):
        tots = ",".join(ref["totals"])
        put(ws, f"B{r}", sh.get("csi") or None)
        put(ws, f"C{r}", sh.get("trade") or None)
        put(ws, f"D{r}", Fx(f"={ref['budget']}"), fmt=ACCOUNTING)
        put(ws, f"E{r}", Fx(f'=IF(COUNT({tots})=0,"",MIN({tots}))'),
            fmt=ACCOUNTING)
        name = '""'
        for t, nm in reversed(list(zip(ref["totals"], ref["names"]))):
            name = f"IFERROR(INDEX({nm},MATCH(E{r},{t},0)),{name})"
        put(ws, f"F{r}", Fx(f'=IF(E{r}="","",{name})'))
        put(ws, f"G{r}", Fx(f'=IF(OR(D{r}="",E{r}=""),"",E{r}-D{r})'),
            fmt=ACCOUNTING)
        put(ws, f"H{r}", Fx(f'=IF(OR(D{r}="",E{r}="",N(D{r})=0),"",'
                            f'(E{r}-D{r})/D{r})'), fmt="0.0%")
        put(ws, f"I{r}", ref["award_name"] or None)
        put(ws, f"J{r}", Fx(f"={ref['award']}") if ref["award"] else None,
            fmt=ACCOUNTING)
        put(ws, f"K{r}", Fx(f'=IF(OR(D{r}="",J{r}=""),"",J{r}-D{r})'),
            fmt=ACCOUNTING)
        r += 1
    last = r - 1
    put(ws, f"B{r}", "TOTAL", font=arial(10, True))
    put(ws, f"C{r}", None)
    for col in "DEJ":
        put(ws, f"{col}{r}", Fx(f"=SUM({col}5:{col}{max(5, last)})")
            if sheets else 0, fmt=ACCOUNTING, font=arial(10, True))
    put(ws, f"G{r}", Fx(f"=E{r}-D{r}"), fmt=ACCOUNTING, font=arial(10, True))
    for col in "FHIK":
        put(ws, f"{col}{r}", None)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.freeze_panes = "B5"


# ============================================================ Excel import
SKIP_TAB = re.compile(r"^\s*sub[\s_-]*list", re.I)
_LABEL = re.compile(r"^\s*(CONTROL\s*#|PROJECT\s*#|BID\s*DATE\s*:?|TIME\s*:?|"
                    r"ESTIMATOR\s*:?|TRADE\s*:?\.?|RECOMMENDED\s+AWARD\s+TO"
                    r"\s*:?|OWNER\s+APPROVAL\s*:?|DATE\s*:?|AMOUNT\s*:?)\s*",
                    re.I)


def _strip_label(v):
    return _LABEL.sub("", str(v or ""), count=1).strip()


def _txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    if isinstance(v, (date,)):
        return v.isoformat()[:10]
    return str(v).strip()


def import_xlsx(path):
    """Read every tab laid out like the Scope Sheet template (its B4
    starts with TRADE) into scope sheets. A tab named like "SUB LIST" is
    never read (it holds contact data). A tab "<name> (2)" with the same
    trade continues the bidders of the tab before it. Returns
    (sheets, skipped tab count)."""
    from openpyxl import load_workbook
    wf = load_workbook(path, read_only=True, data_only=False)
    wv = load_workbook(path, read_only=True, data_only=True)
    out, skipped, prev = [], 0, None
    clar = []           # the current sheet's Clarifications rows (by name)

    def finish(sheet):
        # attach once every bidder page is in, then drop blank blocks
        if sheet is not None:
            _attach_clar(sheet, clar)
            _drop_trailing_blank(sheet)
        del clar[:]
    try:
        for name in wf.sheetnames:
            if SKIP_TAB.match(name):
                skipped += 1
                continue                      # never parsed at all
            grid_f = _grid(wf[name])
            if not str(grid_f.get((4, 2)) or "").strip().upper() \
                    .startswith("TRADE"):
                skipped += 1
                continue
            grid_v = _grid(wv[name])
            sh = _read_tab(grid_f, grid_v)
            rows = sh.pop("clar_rows", [])
            m = re.match(r"^(.*) \((\d+)\)$", name)
            if m and prev is not None and title(prev) == title(sh) and \
                    [ln["desc"] for ln in prev["lines"]] == \
                    [ln["desc"] for ln in sh["lines"]]:
                _append_page(prev, sh)
                clar.extend(rows)
                continue
            finish(prev)
            clar.extend(rows)
            out.append(sh)
            prev = sh
        finish(prev)
    finally:
        wf.close()
        wv.close()
    return out, skipped


def _grid(ws, max_col=60):
    g = {}
    for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
        for c, v in enumerate(row[:max_col], start=1):
            if v is not None and v != "":
                g[(r, c)] = v
    return g


def _drop_trailing_blank(sh):
    if sh is None or len(sh["bidders"]) <= PER_PAGE:
        return
    while len(sh["bidders"]) > PER_PAGE:
        b = sh["bidders"][-1]
        if b["company"] or b["phone"] or b["contact"] or active(sh, b) or \
                any(bid_cell(ln, b["id"])["flag"] for ln in sh["lines"]) or \
                any(v["ans"] or v["note"] for v in b["checklist"].values()) \
                or b.get("clar"):
            break
        remove_bidder(sh, b["id"])


def _append_page(prev, sh):
    for i, b in enumerate(sh["bidders"]):
        prev["bidders"].append(b)
        for ln_p, ln_s in zip(prev["lines"], sh["lines"]):
            if b["id"] in ln_s["bids"]:
                ln_p["bids"][b["id"]] = ln_s["bids"][b["id"]]
    if sh["award"]["bidder"] and not prev["award"]["bidder"]:
        prev["award"] = sh["award"]


def _read_tab(gf, gv):
    def val(r, c):
        """The cell: its cached value when it's a formula."""
        v = gf.get((r, c))
        if isinstance(v, str) and v.startswith("="):
            return gv.get((r, c))
        return v

    def money(r, c):
        v = val(r, c)
        if v in (None, ""):
            return None
        try:
            return parse_money(v)
        except ScopeError:
            return None

    def dec(r, c):
        v = val(r, c)
        try:
            return parse_decimal(v) if v not in (None, "") else None
        except ScopeError:
            return None

    sh = new_sheet(bidders=0)
    h = sh["header"]
    h["project"] = _txt(val(1, 2))
    h["control_no"] = _strip_label(_txt(val(2, 2)))
    h["project_no"] = _strip_label(_txt(val(2, 4)))
    h["bid_date"] = _strip_label(_txt(val(2, 7)))
    h["bid_time"] = _strip_label(_txt(val(2, 11)))
    h["estimator"] = _strip_label(_txt(val(2, 14)))
    tr = _strip_label(_txt(val(4, 2))).lstrip(".: ").strip()
    from ..csi import parse_code
    m = re.match(r"^(\d{2}[\s.]?\d{2}[\s.]?\d{2}(?:\.\d{1,2})?|\d{2})"
                 r"(?=\s|$)\s*[-:]?\s*(.*)$", tr)
    if m and parse_code(m.group(1)):
        sh["csi"], sh["trade"] = parse_code(m.group(1)), m.group(2).strip()
    else:
        sh["trade"] = tr
    lab = _txt(val(4, 5))
    if lab and lab.lower() != "budget" and not lab.lower().endswith(
            " budget"):
        sh["budget"]["label"] = lab
    add = re.search(r"ADDENDA\s*(\S*)\s*TO\s*(\S*)", _txt(val(10, 2)), re.I)
    if add:
        h["addenda_from"], h["addenda_to"] = add.group(1), add.group(2)
    # where the scope lines end: the TOTAL PRICE row (the template has
    # the label on the 2nd of its two total rows, beside "Math Check")
    last = 60
    for r in range(FIRST_LINE, 400):
        b = _txt(val(r, 2)).upper()
        if b.startswith("TOTAL PRICE"):
            if _txt(val(r, 3)).upper().startswith("MATH") or \
                    not _txt(val(r + 1, 2)).upper().startswith("MATH"):
                last = r - 2            # the template's two-row totals
            else:
                last = r - 1
            break
    tot_row = last + 1
    max_c = max([c for (_r, c) in gf] + [19])
    nblocks = max(PER_PAGE, (max_c - 8 + 2) // 2)
    # budget block
    sh["budget"]["price"] = money(7, 4)
    for i, key in enumerate(CHECK_KEYS):
        sh["budget"]["checklist"][key] = {
            "ans": parse_answer(_txt(val(9 + i, 4))),
            "note": _txt(val(9 + i, 6))}
    for k in range(nblocks):
        n, w = block_cols(k)
        b = new_bidder(_txt(val(4, n)), _txt(val(5, n)), _txt(val(6, n)),
                       money(7, n))
        for i, key in enumerate(CHECK_KEYS):
            b["checklist"][key] = {"ans": parse_answer(_txt(val(9 + i, n))),
                                   "note": _txt(val(9 + i, w))}
        sh["bidders"].append(b)
    for r in range(FIRST_LINE, last + 1):
        desc = _txt(val(r, 2)) or _txt(val(r, 3))
        q, p = dec(r, 4), dec(r, 6)
        tot_raw = gf.get((r, 7))
        cells = []
        for k, b in enumerate(sh["bidders"]):
            n, w = block_cols(k)
            cells.append((b["id"], parse_flag(_txt(val(r, n))), money(r, w)))
        if not desc and q is None and p is None and \
                not any(f or a is not None for _b, f, a in cells) and \
                val(r, 7) in (None, "") and not (
                    isinstance(tot_raw, (int, float, Decimal)) and
                    not isinstance(tot_raw, bool)):
            continue
        ln = add_line(sh, desc)
        ln["unit"] = _txt(val(r, 5))
        ln["qty"] = _dec_text(q) if q is not None else None
        ln["unit_price"] = _dec_text(p, 2, 4) if p is not None else None
        if q is None or p is None:
            ln["lump"] = money(r, 7)
        for bid, f, a in cells:
            if f or a is not None:
                ln["bids"][bid] = {"flag": f, "amount": a}
    # footer
    for r in range(tot_row, tot_row + 8):
        aw = _txt(val(r, 8))
        if aw.upper().startswith("RECOMMENDED AWARD"):
            name = _strip_label(aw)
            hit = next((b for b in sh["bidders"] if name and
                        b["company"].strip().lower() == name.lower()), None)
            if hit is not None:
                sh["award"]["bidder"] = hit["id"]
                amt = val(r, 15)
                if isinstance(amt, (int, float, Decimal)) and \
                        not isinstance(amt, bool):
                    c = parse_money(amt)
                    if c != bidder_total(sh, hit):
                        sh["award"]["amount"] = c
                elif isinstance(amt, str) and not amt.startswith("="):
                    try:
                        c = parse_money(_strip_label(amt))
                    except ScopeError:
                        c = None
                    if c is not None and c != bidder_total(sh, hit):
                        sh["award"]["amount"] = c
        for c in (8, 9):
            ap = _txt(val(r, c))
            if ap.upper().startswith("OWNER APPROVAL"):
                sh["award"]["approved_by"] = _strip_label(ap)
                sh["award"]["approved_on"] = _strip_label(_txt(val(r, 15)))
    sh["clar_rows"] = _read_clar(gf, val, tot_row + 2)
    return sh


# ============================================================ PDF export
def export_pdf(sheets, path, company=None, store=None):
    """One landscape 11x17 page per sheet (per 6 bidders): the header,
    the scope lines with every block, totals, math check (red when off),
    the leveled totals when leveling is on, and the footer. Returns the
    path."""
    import fitz
    company = company if isinstance(company, dict) else \
        {"name": company or "", "logo": ""}
    out = fitz.open()
    for sh in sheets:
        sh = from_dict(sh)
        pages = max(1, -(-len(sh["bidders"]) // PER_PAGE))
        for p in range(pages):
            _pdf_page(out, fitz, sh, p, pages, company)
        if any(b.get("clar") for b in sh["bidders"]):
            _pdf_clar_page(out, fitz, sh, company)
    if not len(out):
        out.new_page(width=1224, height=792)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out.save(path)
    out.close()
    return path


def _fit(fitz, s, width, size, font):
    s = str(s or "")
    while s and fitz.get_text_length(s, fontname=font, fontsize=size) > width:
        s = s[:-2] + "…" if len(s) > 2 else ""
    return s


def _pdf_page(out, fitz, sh, p, pages, company):
    W, H = 1224, 792                          # 17 x 11 in, landscape
    pg = out.new_page(width=W, height=H)
    m = 30
    black, grey = (0, 0, 0), (0.45, 0.45, 0.45)
    ylw, red, green = (1, 1, 0.75), (1, 0.8, 0.8), (0.82, 0.94, 0.82)

    def text(x, y, s, size=8, bold=False, right=None, color=black,
             width=None):
        font = "hebo" if bold else "helv"
        if width:
            s = _fit(fitz, s, width, size, font)
        s = str(s or "")
        if right is not None:
            x = right - fitz.get_text_length(s, fontname=font, fontsize=size)
        pg.insert_text((x, y), s, fontsize=size, fontname=font, color=color)

    def rect(x0, y0, x1, y1, fill=None, width=0.4):
        pg.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0.5, 0.5, 0.5),
                     fill=fill, width=width)

    h = sh["header"]
    logo = company.get("logo")
    lx = W - m
    if logo:
        try:
            r = fitz.Rect(W - m - 120, m - 6, W - m, m + 30)
            pg.insert_image(r, filename=logo, keep_proportion=True)
            lx = W - m - 128
        except Exception:
            pass
    text(m, m + 12, h.get("project") or "", 16, True, width=700)
    text(m, m + 28, company.get("name") or "", 9, True, color=grey)
    text(m + 300, m + 28, "SCOPE SHEET" + (f"  (bidders page {p + 1} of "
                                           f"{pages})" if pages > 1 else ""),
         9, True, color=grey)
    hdr = [("CONTROL #", h.get("control_no")),
           ("PROJECT #", h.get("project_no")),
           ("BID DATE", h.get("bid_date")), ("TIME", h.get("bid_time")),
           ("ESTIMATOR", h.get("estimator"))]
    x = m
    for lab, v in hdr:
        text(x, m + 44, f"{lab}: {v or ''}", 8, True, width=200)
        x += 210
    text(m, m + 60, f"TRADE: {title(sh)}", 11, True, width=lx - m)
    # columns: desc | qty unit unit$ total | 6 x (flag, amount)
    desc_w, bud = 250, [52, 32, 62, 74]
    blk_n, blk_w = 26, 104
    xs = [m, m + desc_w]
    for w in bud:
        xs.append(xs[-1] + w)
    bx = []
    for k in range(PER_PAGE):
        x0 = xs[-1] + k * (blk_n + blk_w)
        bx.append((x0, x0 + blk_n, x0 + blk_n + blk_w))
    page_b = sh["bidders"][p * PER_PAGE:(p + 1) * PER_PAGE]
    lv_mode = sh.get("level") or "none"
    lv = leveled(sh, lv_mode)
    y = m + 72
    rh = 12
    # bidder header rows
    rows = [("COMPANY", "company"), ("TELEPHONE", "phone"),
            ("CONTACT", "contact"), ("BID PRICE", "price")]
    for lab, key in rows:
        rect(xs[0], y, xs[-1], y + rh)
        text(xs[0] + 3, y + 9, lab, 7, True)
        if key == "company":
            text(xs[1] + 3, y + 9, budget_label(sh, company), 7, True,
                 width=xs[-1] - xs[1] - 6)
        if key == "price":
            text(0, y + 9, fmt_money(sh["budget"]["price"]), 7,
                 right=xs[-1] - 3)
        for k, (a, b_, c) in enumerate(bx):
            rect(a, y, c, y + rh, fill=ylw)
            if k < len(page_b):
                bd = page_b[k]
                if key == "price":
                    text(0, y + 9, fmt_money(bd["price"]), 7, True,
                         right=c - 3)
                else:
                    text(a + 3, y + 9, bd.get(key) or "", 7,
                         key == "company", width=c - a - 6)
        y += rh
    for key, lab in CHECKLIST:
        if key == "addenda":
            lab = f"ADDENDA {h.get('addenda_from') or ''} TO " \
                  f"{h.get('addenda_to') or ''}"
        rect(xs[0], y, xs[-1], y + rh)
        text(xs[0] + 3, y + 9, lab, 7)
        c0 = sh["budget"]["checklist"][key]
        text(xs[1] + 3, y + 9, f"{c0['ans']} {c0['note']}".strip(), 7,
             width=xs[-1] - xs[1] - 6)
        for k, (a, b_, c) in enumerate(bx):
            rect(a, y, c, y + rh, fill=ylw)
            if k < len(page_b):
                ck = page_b[k]["checklist"][key]
                text(a + 2, y + 9, ck["ans"], 6, True, width=blk_n - 3)
                text(b_ + 2, y + 9, ck["note"], 6, width=blk_w - 4)
        y += rh
    # column heads
    rect(xs[0], y, bx[-1][2], y + rh, fill=(0.93, 0.93, 0.93))
    text(xs[0] + 3, y + 9, "SCOPE", 7, True)
    for i, lab in enumerate(("QTY", "UNIT", "UNIT $", "TOTAL")):
        text(0, y + 9, lab, 7, True, right=xs[i + 2] - 3)
    for k, (a, b_, c) in enumerate(bx):
        text(a + 2, y + 9, "INCL", 6, True)
        text(0, y + 9, f"BIDDER {p * PER_PAGE + k + 1}", 6, True,
             right=c - 3)
    y += rh
    lines = sh["lines"]
    avail = H - m - 70 - y
    rows_fit = max(1, int(avail // rh))
    shown = lines[:rows_fit]
    for ln in shown:
        rect(xs[0], y, bx[-1][2], y + rh)
        text(xs[0] + 3, y + 9, ln["desc"], 7, width=desc_w - 6)
        text(0, y + 9, fmt_qty(ln["qty"]), 7, right=xs[2] - 3)
        text(xs[2] + 3, y + 9, ln["unit"], 7, width=bud[1] - 4)
        text(0, y + 9, fmt_unit_price(ln["unit_price"]), 7,
             right=xs[4] - 3)
        text(0, y + 9, fmt_money(budget_line_total(ln)), 7,
             right=xs[5] - 3)
        for k, (a, b_, c) in enumerate(bx):
            if k >= len(page_b):
                continue
            bd = page_b[k]
            cell = bid_cell(ln, bd["id"])
            plug = lv[bd["id"]]["plugs"].get(ln["id"])
            if plug:
                pg.draw_rect(fitz.Rect(b_, y, c, y + rh), color=None,
                             fill=green)
                text(0, y + 9, fmt_money(plug[0]) + "*", 7, color=grey,
                     right=c - 3)
            else:
                text(0, y + 9, fmt_money(cell["amount"]), 7, right=c - 3)
            text(a + 2, y + 9, cell["flag"], 6, True, width=blk_n - 3)
        y += rh
    if len(lines) > len(shown):
        text(xs[0] + 3, y + 9, f"... {len(lines) - len(shown)} more lines "
             "(see the Excel export)", 7, color=grey)
        y += rh
    # totals
    rect(xs[0], y, bx[-1][2], y + rh, fill=(0.93, 0.93, 0.93))
    text(xs[0] + 3, y + 9, "TOTAL PRICE", 7, True)
    text(0, y + 9, fmt_money(budget_total(sh)), 7, True, right=xs[5] - 3)
    for k, (a, b_, c) in enumerate(bx):
        if k < len(page_b):
            text(0, y + 9, fmt_money(bidder_total(sh, page_b[k])), 7, True,
                 right=c - 3)
    y += rh
    rect(xs[0], y, bx[-1][2], y + rh)
    text(xs[0] + 3, y + 9, "MATH CHECK (Bid Price - Total)", 7)
    bm = budget_math_check(sh)
    if bm:
        pg.draw_rect(fitz.Rect(xs[4], y, xs[5], y + rh), color=None, fill=red)
    text(0, y + 9, fmt_money(bm), 7, right=xs[5] - 3)
    for k, (a, b_, c) in enumerate(bx):
        if k < len(page_b):
            mc = math_check(sh, page_b[k])
            if mc:
                pg.draw_rect(fitz.Rect(a, y, c, y + rh), color=None,
                             fill=red)
            text(0, y + 9, fmt_money(mc), 7, bool(mc), right=c - 3)
    y += rh
    show_lv = lv_mode != "none" or has_adjustments(sh)
    if show_lv:
        how = [LEVEL_LABEL[lv_mode].lower()] if lv_mode != "none" else []
        if has_adjustments(sh):
            how.append("accepted clarifications")
        rect(xs[0], y, bx[-1][2], y + rh, fill=green)
        text(xs[0] + 3, y + 9, "LEVELED TOTAL (" + ", ".join(how) + ")", 7,
             True, width=desc_w + sum(bud) - 6)
        for k, (a, b_, c) in enumerate(bx):
            if k < len(page_b):
                text(0, y + 9, fmt_money(lv[page_b[k]["id"]]["total"]), 7,
                     True, right=c - 3)
        y += rh
        if lv_mode != "none":
            text(xs[0], y + 9, "* plugged: the bidder excluded the line; "
                 "the budget or the other bidders' median is carried so "
                 "totals compare.", 6, color=grey)
            y += rh
        if has_adjustments(sh):
            text(xs[0], y + 9, "Accepted clarification adjustments are in "
                 "the leveled total (see the Clarifications page).", 6,
                 color=grey)
            y += rh
    # footer
    y += 8
    s = summary(sh)
    low = s["leveled_low_bidder"] if show_lv else s["low_bidder"]
    lowamt = s["leveled_low"] if show_lv else s["low_bid"]
    var, pct = spread(sh, lowamt)
    text(m, y + 10, f"{budget_label(sh, company)}: "
         f"{fmt_money(budget_total(sh)) or '-'}", 9, True)
    text(m + 260, y + 10, f"LOW BIDDER: {low or '-'} "
         f"{fmt_money(lowamt)}", 9, True, width=330)
    if var is not None:
        text(m + 600, y + 10, f"LOW vs BUDGET: {fmt_money(var)}" +
             (f" ({pct}%)" if pct is not None else ""), 9)
    y += 20
    aw = sh["award"]
    text(m, y + 10, "RECOMMENDED AWARD TO: " +
         (bidder_name(sh, aw["bidder"]) if aw["bidder"] else ""), 9, True,
         width=400)
    text(m + 420, y + 10, "AMOUNT: " + (fmt_money(award_amount(sh))
                                         if aw["bidder"] else ""), 9, True)
    text(m + 640, y + 10, "OWNER APPROVAL: " + (aw["approved_by"] or ""),
         9, width=250)
    text(m + 900, y + 10, "DATE: " + (aw["approved_on"] or ""), 9)


def _pdf_clar_page(out, fitz, sh, company):
    """The trade's Clarifications page: per bidder, every qualification /
    exclusion / clarification with its $ adjustment and status, then as
    bid + plugged + accepted = leveled, beside the budget."""
    W, H = 1224, 792
    m = 30
    black, grey = (0, 0, 0), (0.45, 0.45, 0.45)
    shade = (0.93, 0.93, 0.93)
    state = {"pg": None, "y": 0}

    def page():
        pg = out.new_page(width=W, height=H)
        state["pg"], state["y"] = pg, m + 12
        text(m, state["y"], sh["header"].get("project") or "", 14, True,
             width=700)
        state["y"] += 16
        text(m, state["y"], f"CLARIFICATIONS  -  {title(sh)}", 11, True,
             width=700)
        text(m + 760, state["y"], f"{budget_label(sh, company)}: "
             f"{fmt_money(budget_total(sh)) or '-'}", 10, True)
        state["y"] += 14
        return pg

    def text(x, y, s, size=8, bold=False, right=None, color=black,
             width=None):
        font = "hebo" if bold else "helv"
        if width:
            s = _fit(fitz, s, width, size, font)
        s = str(s or "")
        if right is not None:
            x = right - fitz.get_text_length(s, fontname=font, fontsize=size)
        state["pg"].insert_text((x, y), s, fontsize=size, fontname=font,
                                color=color)

    def need(h):
        if state["y"] + h > H - m:
            page()

    cols = [m, m + 110, m + 830, m + 990, m + 1080]   # type, text, $, status
    page()
    lv = leveled(sh)
    bud = budget_total(sh)
    for i, b in enumerate(sh["bidders"]):
        rows = b.get("clar") or []
        if not rows:
            continue
        need(60)
        y = state["y"] + 10
        pg = state["pg"]
        pg.draw_rect(fitz.Rect(m, y - 9, W - m, y + 4), color=None,
                     fill=shade)
        text(m + 3, y, bidder_name(sh, b, i), 9, True, width=500)
        for x, lab in zip(cols, ("TYPE", "TEXT", "ADJUSTMENT", "STATUS")):
            if lab != "TYPE" and lab != "TEXT":
                text(x + 3, y, lab, 7, True)
        state["y"] = y + 6
        for c in rows:
            need(14)
            y = state["y"] + 10
            text(cols[0] + 3, y, c["kind"], 8, width=104)
            text(cols[1] + 3, y, c["text"], 8, width=cols[2] - cols[1] - 8)
            text(0, y, fmt_money(c["amount"]), 8, right=cols[3] - 6)
            st = {"accepted": "ACCEPTED", "rejected": "REJECTED"}.get(
                c["status"], "PENDING")
            text(cols[3] + 3, y, st, 8, c["status"] == "accepted",
                 color=black if c["status"] != "rejected" else grey)
            state["y"] = y + 2
        need(16)
        y = state["y"] + 12
        d = lv[b["id"]]
        line = (f"As bid {fmt_money(d['base']) or '-'}"
                + (f"  + plugged {fmt_money(d['plugged'])}"
                   if d["plugged"] else "")
                + f"  + accepted {fmt_money(d['adjusted'])}"
                + f"  = leveled {fmt_money(d['total']) or '-'}")
        var, pct = spread(sh, d["total"])
        if var is not None:
            line += f"   vs {budget_label(sh, company)} {fmt_money(var)}" + \
                (f" ({pct}%)" if pct is not None else "")
        elif bud is None:
            line += "   (no budget)"
        text(cols[1] + 3, y, line, 8, True, width=W - m - cols[1] - 6)
        state["y"] = y + 6
