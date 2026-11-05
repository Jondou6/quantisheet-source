"""Bid Form Autopilot (Nov 3, Jon approved Chief's list, #8): fill the
owner's bid form PDF from the estimate - base bid, the amount in words,
alternates, unit prices and the addenda acknowledged - then a last check
for the bid bond, the signature and the deadline.

The form's fields are found by their names (Base Bid, Amount in Words,
Alternate 1, Addendum 2, Unit Price 3...). Unpriced addenda block it
(the Addenda Gate, estimating/bidgate.py). Nothing is sent anywhere; the
filled form is saved as a new file."""
import datetime
import re
from decimal import ROUND_HALF_UP, Decimal

from . import formlib

_ONES = ("zero one two three four five six seven eight nine ten eleven "
         "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
         "nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_BIG = ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"),
        (1000, "thousand"))

BASE = re.compile(r"base ?bid|lump ?sum|total ?bid|bid ?amount|bid ?price|"
                  r"contract ?sum", re.I)
WORDS = re.compile(r"words|written|in ?letters", re.I)
ALT = re.compile(r"alt(?:ernate)?\W*(?:no\W*)?(\d{1,2})", re.I)
ADD = re.compile(r"add(?:endum|enda|\.)?\W*(?:no\W*)?(\d{1,2})", re.I)
UNIT = re.compile(r"unit ?price\W*(?:no\W*)?(\d{1,3})", re.I)
SIGN = re.compile(r"sign(?:ature|ed)?\b|signer", re.I)
DEADLINE_HOURS = 24


def _words(n):
    n = int(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + _words(n % 100)
                                               if n % 100 else "")
    for size, name in _BIG:
        if n >= size:
            return _words(n // size) + " " + name + (
                " " + _words(n % size) if n % size else "")
    return str(n)


def amount_in_words(amount):
    """$1,234,567.89 -> 'One Million Two Hundred Thirty-Four Thousand Five
    Hundred Sixty-Seven Dollars and 89/100'."""
    a = Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    dollars = int(a)
    cents = int((a - dollars) * 100)
    w = _words(dollars).title().replace("-", "-")
    w = re.sub(r"-([a-z])", lambda m: "-" + m.group(1).upper(), w)
    return f"{w} Dollars and {cents:02d}/100"


def _money(v):
    return f"${Decimal(str(v)):,.2f}"


def base_bid(doc):
    """The proposal's total (with markups), else the estimate's."""
    try:
        from . import proposal
        t = proposal.price(doc, proposal.read(doc)).get("total")
        if t:
            return Decimal(str(t)).quantize(Decimal("0.01"))
    except Exception:                                     # noqa: BLE001
        pass
    from . import estimate_export
    return Decimal(str(estimate_export.summary(doc)["total"])).quantize(
        Decimal("0.01"))


def values(doc, alternates=(), unit_prices=()):
    """What goes on the form: {"base", "words", "alternates": {n: amt},
    "unit_prices": {n: price}, "addenda": {n: date}}."""
    from . import doccontrol
    b = base_bid(doc)
    adds = {}
    try:
        for a in doccontrol.addenda(doc):
            adds[int(a["no"])] = a.get("issued", "")
    except Exception:                                     # noqa: BLE001
        pass
    return {"base": b, "words": amount_in_words(b),
            "alternates": {int(k): Decimal(str(v)) for k, v in
                           dict(alternates).items()},
            "unit_prices": {int(k): Decimal(str(v)) for k, v in
                            dict(unit_prices).items()},
            "addenda": adds}


def row_label(page, w):
    """The words printed on the form's row to the left of field `w` (its
    item's description)."""
    r = w.rect
    words = []
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        cy = (y0 + y1) / 2
        if r.y0 - 2 <= cy <= r.y1 + 2 and x1 <= r.x0 + 1:
            words.append((x0, t))
    return " ".join(t for _x, t in sorted(words))


def our_unit_prices(doc):
    """[(description, unit, unit price)] from the estimate: added lines
    and priced takeoff groups."""
    out = []
    try:
        from . import estimate_lines as EL
        for p in EL.priced(doc):
            q = p.get("quantity") or 0
            if p["total"] and q:
                out.append((p["desc"], p.get("unit", ""),
                            (p["total"] / q).quantize(Decimal("0.01"))))
    except Exception:                                     # noqa: BLE001
        pass
    try:
        from . import estimate
        for g in estimate.lines(doc):
            uc = g.get("unit_cost")
            if uc:
                out.append((g["name"], g.get("unit", ""),
                            Decimal(str(uc)).quantize(Decimal("0.01"))))
    except Exception:                                     # noqa: BLE001
        pass
    return out


def auto_unit_prices(doc, form, cutoff=0.72):
    """Nov 4: {unit price field name: (price, matched item)} - each unit
    price field's row description matched to the estimate's items."""
    from .estimating.levelboard import similar
    ours = our_unit_prices(doc)
    if not ours:
        return {}
    out = {}
    for pg in form:
        for w in formlib._widgets(pg):
            name = _field_text(w)
            if not UNIT.search(name) and not re.search(r"unit ?price", name,
                                                         re.I):
                continue
            label = row_label(pg, w)
            label = re.sub(r"^\s*\d+[.)]?\s*", "", label)
            label = re.sub(r"\$|\bper\b.*$", "", label, flags=re.I).strip()
            if len(label) < 3:
                continue
            best, sc = None, 0.0
            for desc, unit, price in ours:
                v = similar(label, desc)
                if v > sc:
                    best, sc = (desc, price), v
            if best and sc >= cutoff:
                out[str(w.field_name)] = (best[1], best[0])
    return out


def _field_text(w):
    return " ".join(filter(None, [str(w.field_name or ""),
                                  str(getattr(w, "field_label", "") or "")]))


def fill(form, vals, overwrite=True, auto_units=None):
    """Write `vals` into the form's fields. Returns {field: value}.
    `auto_units` {field name: (price, item)} fills unit prices not typed."""
    auto_units = auto_units or {}
    import fitz
    done = {}
    for pg in form:
        for w in formlib._widgets(pg):
            name = _field_text(w)
            is_text = formlib._is_textlike(w)
            is_check = int(w.field_type) == int(
                fitz.PDF_WIDGET_TYPE_CHECKBOX)
            if not overwrite and w.field_value not in (None, "", "Off"):
                continue
            v = None
            m_add = ADD.search(name)
            m_alt = ALT.search(name)
            m_unit = UNIT.search(name)
            if m_add and int(m_add.group(1)) in vals["addenda"]:
                n = int(m_add.group(1))
                if is_check:
                    w.field_value = w.on_state() or True
                    w.update()
                    done[name] = "checked"
                    continue
                v = vals["addenda"][n] or "Received"
            elif m_alt and int(m_alt.group(1)) in vals["alternates"]:
                v = _money(vals["alternates"][int(m_alt.group(1))])
            elif m_unit and int(m_unit.group(1)) in vals["unit_prices"]:
                v = _money(vals["unit_prices"][int(m_unit.group(1))])
            elif str(w.field_name) in auto_units:
                v = _money(auto_units[str(w.field_name)][0])
            elif WORDS.search(name) and not m_alt:
                v = vals["words"]
            elif BASE.search(name):
                v = _money(vals["base"])
            if v is not None and is_text:
                formlib.set_text(form, w, v)
                done[name] = v
    try:
        done.update(formlib.fill_from_job(form))
    except Exception:                                     # noqa: BLE001
        pass
    return done


def final_check(form, filled, deadline=None, bond_ready=None, now=None):
    """[(ok, message)] - bond, signature, deadline, what didn't fill."""
    import fitz
    now = now or datetime.datetime.now()
    out = []
    text = " ".join(pg.get_text("text") for pg in form).lower()
    names = [(_field_text(w), w) for pg in form for w in formlib._widgets(pg)]
    if "bond" in text or any("bond" in n.lower() for n, _w in names):
        if bond_ready is None:
            out.append((False, "The form asks for a bid bond - make sure "
                        "it's attached (tick Bond ready)."))
        else:
            out.append((bool(bond_ready), "Bid bond ready." if bond_ready
                        else "The form asks for a bid bond - not ready."))
    sig = [w for n, w in names if SIGN.search(n) or int(w.field_type) ==
           int(getattr(fitz, "PDF_WIDGET_TYPE_SIGNATURE", -99))]
    if sig:
        signed = any(w.field_value not in (None, "", "Off") for w in sig)
        out.append((signed, "Signed." if signed else
                    "Not signed yet - sign it (Fill & Sign) before it goes "
                    "out."))
    else:
        out.append((False, "No signature field found - sign the form by "
                    "hand or with Fill & Sign."))
    if deadline:
        left = (deadline - now).total_seconds() / 3600
        if left < 0:
            out.append((False, f"The bid was due {deadline:%b %d %I:%M %p}"
                        " - the deadline has passed."))
        elif left < DEADLINE_HOURS:
            out.append((True, f"Due in {left:.0f} hour(s), "
                        f"{deadline:%b %d %I:%M %p}."))
        else:
            out.append((True, f"Due {deadline:%b %d %I:%M %p}."))
    else:
        out.append((False, "No bid deadline given."))
    empty = [n for n, w in names if formlib._is_textlike(w) and
             w.field_value in (None, "") and n not in filled]
    if empty:
        out.append((False, f"{len(empty)} field(s) still empty: " +
                    ", ".join(empty[:8])))
    return out


def run(doc, form_path, out_path, alternates=(), unit_prices=(),
        deadline=None, bond_ready=None):
    """Fill the form and save it as `out_path`. Raises GateError while an
    addendum isn't priced. Returns {"filled", "check", "values"}."""
    import fitz
    from .estimating import bidgate
    block = bidgate.blockers(doc)
    if block:
        raise GateError("Not priced yet: " + ", ".join(f["item"]
                                                       for f in block))
    vals = values(doc, alternates, unit_prices)
    form = fitz.open(form_path)
    auto = auto_unit_prices(doc, form)
    filled = fill(form, vals, auto_units=auto)
    check = final_check(form, filled, deadline, bond_ready)
    used = {k: v for k, v in auto.items() if k in filled}
    if used:
        check.append((True, "Unit prices from the estimate: " + "; ".join(
            f"{k} = {_money(p)} ({item})" for k, (p, item) in
            list(used.items())[:8]) + " - check them."))
    form.save(out_path, garbage=3, deflate=True)
    return {"filled": filled, "check": check, "values": vals,
            "auto_units": used}


class GateError(Exception):
    pass
