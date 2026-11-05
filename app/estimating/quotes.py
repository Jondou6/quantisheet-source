"""Customer Quote with options: a client-ready quote PDF from every
priced item of the estimate (items.py), with

  * your markup (% on cost) or margin (% of the price) - the customer sees
    prices only, never cost or markup;
  * inclusions and exclusions;
  * Good / Better / Best (or your own names) options: each estimate line
    goes in the base scope, in one option, or in the optional items; an
    option's total is the base plus its own lines, and the customer picks
    one;
  * optional items the customer may add one by one;
  * friendly line names (v2 step 4): a clean name instead of the raw
    takeoff group name (friendly_name), or your own name for a line
    ("names" in the quote settings). The estimate itself is unchanged.

The quote's settings are kept in the PDF (quantisheet_estimate_quotes.json)
with the drawings. Client and project details, and your company details,
come from Create Proposal (proposal.py) - nothing is typed twice.

Line prices are rounded to the cent, and every total is the sum of the
rounded line prices, so the quote always adds up.
"""
import datetime
import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .. import dmoney, embfiles
from . import _io, safedb

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_quotes.json"
VERSION = 1
MODES = ("markup", "margin")
DEFAULT_TIERS = ["Good", "Better", "Best"]
BASE, OPTION = "base", "option"


class QuoteError(ValueError):
    pass


def blank():
    return {"version": VERSION, "mode": "markup", "pct": "0",
            "tiers": list(DEFAULT_TIERS), "assign": {}, "tier_notes": {},
            "inclusions": [], "exclusions": [], "selected_tier": "",
            "accepted_options": [], "title": "", "notes": "", "names": {}}


def _clean(spec):
    s = blank()
    if isinstance(spec, dict):
        for k in s:
            if k in spec and spec[k] is not None:
                s[k] = spec[k]
    s["mode"] = s["mode"] if s["mode"] in MODES else "markup"
    s["tiers"] = [str(t).strip() for t in s["tiers"] if str(t).strip()][:6]
    for k in ("inclusions", "exclusions", "accepted_options"):
        v = s[k]
        if isinstance(v, str):
            v = v.splitlines()
        s[k] = [str(x).strip() for x in v if str(x).strip()]
    s["assign"] = {str(k): str(v) for k, v in dict(s["assign"]).items()}
    s["tier_notes"] = {str(k): str(v) for k, v in
                       dict(s["tier_notes"]).items()}
    s["names"] = {str(k): " ".join(str(v).split())[:200] for k, v in
                  dict(s["names"] or {}).items() if str(v).strip()}
    return s


# words kept in capitals in a friendly name (pipe, finish and code terms)
KEEP_CAPS = {"HDPE", "HVAC", "GFCI", "EIFS", "EPDM", "CPVC", "ASTM", "NEMA",
             "AWWA", "ANSI", "OSHA", "FRP", "LVT", "VCT", "TPO", "PEX"}
_DROP = re.compile(r",?\s*\bdepth unknown\b", re.I)


def friendly_name(raw):
    """A takeoff group name as a customer reads it: no AI ', depth
    unknown', words in capitals of 4 letters or more in Title case (short
    ones - PVC, ADA - and KEEP_CAPS stay), the first word capitalized,
    spaces tidied. A name in mixed case keeps its words."""
    t = " ".join(_DROP.sub("", str(raw or "")).split()).strip(" ,;-")

    def word(m):
        w = m.group(0)
        if w.isupper() and len(w) >= 4 and w not in KEEP_CAPS:
            return w.capitalize()
        return w
    t = re.sub(r"[A-Za-z]+", word, t)
    parts = t.split(" ")
    for i, w in enumerate(parts):
        if w[:1].isalpha():
            parts[i] = w[0].upper() + w[1:]
            break
    return " ".join(parts)


def read(doc):
    try:
        if doc is not None and FILE in embfiles.names(doc):
            return _clean(json.loads(embfiles.get(doc, FILE).decode("utf-8")))
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the quote options", exc_info=True)
    return blank()


def write(doc, spec):
    embfiles.put(doc, FILE, json.dumps(_clean(spec), indent=1).encode(
        "utf-8"), "QuantiSheet customer quote options")


def factor(spec):
    """Price = cost x factor."""
    if dmoney.bad(spec.get("pct")):
        raise QuoteError(f"Can't read {spec.get('pct')!r} as a percent.")
    try:
        pct = dmoney.D(spec.get("pct") or 0)
    except (InvalidOperation, ValueError, TypeError):
        raise QuoteError(f"Can't read {spec.get('pct')!r} as a percent.")
    if spec.get("mode") == "margin":
        if not Decimal(0) <= pct < Decimal(100):
            raise QuoteError("A margin is at least 0 % and under 100 %.")
        return Decimal(1) / (Decimal(1) - pct / 100)
    if pct < Decimal(-100):
        raise QuoteError("A markup can't be under -100 %.")
    return Decimal(1) + pct / 100


@safedb.read_only
def compute(doc, spec=None, job=None, lib=None):
    """{"base": {cost, price, lines}, "tiers": [{name, note, cost, price,
    total, lines}], "options": [{id, desc, qty, unit, price, accepted}],
    "selected": {tier, options, total}} - every amount a Decimal. A line
    in a tier that isn't in the spec's tier list counts in the base.
    Every priced item of the estimate is a quote line (items.collect:
    added lines, takeoff groups priced by a unit cost, assemblies and,
    with the civil job, civil activities)."""
    from . import items
    spec = _clean(spec if spec is not None else read(doc))
    f = factor(spec)
    rows = items.collect(doc, job, lib)["items"] \
        if doc is not None or job is not None else []
    base = {"cost": Decimal("0.00"), "price": Decimal("0.00"), "lines": []}
    tiers = {t: {"name": t, "note": spec["tier_notes"].get(t, ""),
                 "cost": Decimal("0.00"), "price": Decimal("0.00"),
                 "lines": []} for t in spec["tiers"]}
    options = []
    for r in rows:
        price = dmoney.cents(r["total"] * f)
        line = {"id": r["id"], "kind": r["kind"],
                "desc": spec["names"].get(r["id"]) or friendly_name(r["desc"]),
                "takeoff_name": r["desc"],
                "qty": r["qty"], "unit": r["unit"], "cost": r["total"],
                "price": price}
        where = spec["assign"].get(r["id"], BASE)
        if where == OPTION:
            options.append(dict(line, accepted=r["id"] in
                                spec["accepted_options"]))
            continue
        box = tiers.get(where, base)
        box["cost"] += r["total"]
        box["price"] += price
        box["lines"].append(line)
    used = [t for t in tiers.values()]
    if not any(t["lines"] for t in used) and not any(
            v in tiers for v in spec["assign"].values()):
        used = []                     # no tiers in use: one price
    for t in used:
        t["total"] = base["price"] + t["price"]
    opt_total = sum((o["price"] for o in options if o["accepted"]),
                    Decimal("0.00"))
    if used:
        pick = next((t for t in used if t["name"] == spec["selected_tier"]),
                    None)
        total = pick["total"] + opt_total if pick else None
    else:
        pick, total = None, base["price"] + opt_total
    return {"base": base, "tiers": used, "options": options,
            "selected": {"tier": pick["name"] if pick else "",
                         "options": opt_total, "total": total},
            "mode": spec["mode"], "spec": spec}


def qty_text(q, unit=""):
    """A quantity as the customer reads it: at most 2 decimals, no
    trailing zeros (277.6622 -> 277.66; 12.0000 -> 12)."""
    if not isinstance(q, Decimal):
        return ""
    r = q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    t = f"{r.normalize():f}" if r else "0"
    return f"{t} {unit}".strip()


def _fit(text, width, size):
    """`text` cut (with ...) to fit `width` points in Helvetica `size`."""
    import fitz
    if fitz.get_text_length(text, "helv", size) <= width:
        return text
    while text and fitz.get_text_length(text + "...", "helv", size) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def select(doc, tier, options=()):
    """The customer's choice: one tier ('' for none) and optional items."""
    spec = read(doc)
    if tier and tier not in spec["tiers"]:
        raise QuoteError(f"No option named {tier!r} on this quote.")
    spec["selected_tier"] = tier or ""
    spec["accepted_options"] = [str(x) for x in options]
    write(doc, spec)
    return compute(doc, spec)


# ---- output ----------------------------------------------------------------

def _rows(q):
    out = [["Base", ln["desc"], ln["qty"], ln["unit"], ln["price"]]
           for ln in q["base"]["lines"]]
    for t in q["tiers"]:
        out += [[t["name"], ln["desc"], ln["qty"], ln["unit"], ln["price"]]
                for ln in t["lines"]]
        out.append([t["name"], f"{t['name']} total (with base)", "", "",
                    t["total"]])
    out += [["Optional", o["desc"], o["qty"], o["unit"], o["price"]]
            for o in q["options"]]
    return out


def export_csv(doc, path, spec=None, job=None, lib=None):
    """The quote's lines as a plain CSV (or .xlsx): Section, Description,
    Quantity, Unit, Price - prices only, for any accounting or CRM
    program's generic import."""
    return _io.write_table(path, ["Section", "Description", "Quantity",
                                  "Unit", "Price"],
                           _rows(compute(doc, spec, job, lib)), "Quote")


def make_pdf(doc, spec=None, comp=None, data=None, job=None, lib=None):
    """The quote as a new PDF (fitz.Document), drawn by its own renderer
    (quote_pdf.py, v2 step 5); company and proposal details come from
    proposal.company() / proposal.read()."""
    import fitz
    from .. import proposal as P
    from . import quote_pdf as R
    q = compute(doc, spec, job, lib)
    spec = q["spec"]
    comp = comp if comp is not None else P.company()
    data = data if data is not None else (P.read(doc) if doc is not None
                                          else {})
    data = dict(data)
    data.setdefault("date", datetime.date.today().isoformat())
    out = fitz.open()
    w = R.Writer(out)
    R.header(w, data, comp)
    fmt = dmoney.fmt

    def table(lines, title=None, total=None, total_label="Total"):
        if title:
            w.heading(title)
        for ln in lines:
            w.need(16)
            w.y += 14
            qty = qty_text(ln.get("qty"), ln["unit"])
            w.text(R.LEFT, w.y, _fit(ln["desc"], 322, 10), 10)
            w.text(R.LEFT + 330, w.y, qty, 9, color=R.GREY)
            w.text(0, w.y, fmt(ln["price"]), 10, align="right")
        if total is not None:
            w.need(20)
            w.y += 6
            w.rule()
            w.y += 13
            w.text(R.LEFT, w.y, total_label, 10.5, "hebo")
            w.text(0, w.y, fmt(total), 10.5, "hebo", align="right")
            w.y += 4

    title = spec["title"] or "Quote"
    w.heading(title)
    if data.get("project"):
        w.para(f"Project: {data['project']}", 10)
    if q["base"]["lines"]:
        table(q["base"]["lines"], "Included in every option" if q["tiers"]
              else "Scope", q["base"]["price"],
              "Base" if q["tiers"] else "Total")
    for t in q["tiers"]:
        table(t["lines"], f"Option: {t['name']}", t["total"],
              f"{t['name']} - total with base")
        if t["note"]:
            w.para(t["note"], 9, color=R.GREY)
    if q["options"]:
        w.heading("Optional items (add any)")
        table([dict(o, desc=("[x] " if o["accepted"] else "[  ] ") +
                    o["desc"]) for o in q["options"]])
    for head, key in (("Inclusions", "inclusions"),
                      ("Exclusions", "exclusions")):
        items = spec[key] or R.bullet_lines(data.get(key))
        if items:
            w.heading(head)
            for it in items:
                w.para("- " + it, 10)
    if q["tiers"]:
        w.heading("Your choice")
        w.para("Option chosen: " + (q["selected"]["tier"] or
                                    "_______________"), 10)
        if q["selected"]["total"] is not None:
            w.para("Total with the optional items checked: " +
                   fmt(q["selected"]["total"]), 10, font="hebo")
    elif q["options"]:
        w.para("Total with the optional items checked: " +
               fmt(q["selected"]["total"]), 10, font="hebo")
    if spec["notes"]:
        w.heading("Notes")
        w.para(spec["notes"])
    if data.get("terms"):
        w.heading("Terms")
        w.para(data["terms"])
    R.acceptance(w, data, comp)
    out.set_metadata({"title": f"{title} - {data.get('project', '')}",
                      "author": comp.get("name", ""),
                      "creator": "QuantiSheet"})
    return out


def save_pdf(doc, path, spec=None, comp=None, data=None, job=None, lib=None):
    import os
    p = _io.check_user_path(path, (".pdf",))
    out = make_pdf(doc, spec, comp, data, job, lib)
    tmp = p + ".part"
    try:
        try:
            out.save(tmp, garbage=3, deflate=True)
        finally:
            out.close()
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return p


# ---- service option quotes ---------------------------------------------------
# A good / better / best quote built from service lines (a flat-rate task
# or a technician recommendation) rather than from a drawing. Prices passed
# in are already customer prices; this does not apply the estimate markup.
# The customer still sees prices only.

def service_option_quote(lines, title="Recommended work", tiers=None,
                         notes="", inclusions=None, exclusions=None,
                         selected_tier=""):
    """Same shape as compute(), from lines that are not on a drawing.

    Each line is {desc, price, qty, unit, cost, tier, photo, accepted, id}.
    `price` and `cost` are per unit. `tier` is "base", "option", or one of
    the tier names (Good / Better / Best unless you pass `tiers`).
    """
    spec = _clean({"title": title or "Recommended work", "notes": notes or "",
                   "tiers": list(DEFAULT_TIERS if tiers is None else tiers),
                   "inclusions": list(inclusions or []),
                   "exclusions": list(exclusions or []),
                   "selected_tier": selected_tier or ""})
    base = {"cost": Decimal("0.00"), "price": Decimal("0.00"), "lines": []}
    boxes = {t: {"name": t, "note": spec["tier_notes"].get(t, ""),
                 "cost": Decimal("0.00"), "price": Decimal("0.00"),
                 "lines": []} for t in spec["tiers"]}
    options = []
    named = False
    for i, raw in enumerate(list(lines or [])):
        if not isinstance(raw, dict):
            raise QuoteError("Each quote line needs a description and a price.")
        desc = " ".join(str(raw.get("desc") or "").split())[:300]
        if not desc:
            raise QuoteError("Each quote line needs a description.")
        if dmoney.bad(raw.get("price"), blank_ok=False):
            raise QuoteError(f"Can't read the price for {desc!r}.")
        if dmoney.bad(raw.get("qty", 1), blank_ok=False):
            raise QuoteError(f"Can't read the quantity for {desc!r}.")
        each = dmoney.cents(raw.get("price"))
        qty = dmoney.D(raw.get("qty", 1))
        if qty <= 0:
            raise QuoteError("Quantity must be more than zero.")
        cost_each = dmoney.cents(raw.get("cost") or 0)
        price = dmoney.cents(qty * each)
        cost = dmoney.cents(qty * cost_each)
        line = {"id": str(raw.get("id") or i + 1), "kind": "service",
                "desc": desc, "takeoff_name": desc, "qty": qty,
                "unit": " ".join(str(raw.get("unit") or "ea").split())[:20]
                or "ea", "cost": cost, "price": price}
        photo = str(raw.get("photo") or "").strip()
        if photo:
            line["photo"] = photo
        where = str(raw.get("tier") or OPTION).strip() or OPTION
        if where == OPTION:
            options.append(dict(line, accepted=bool(raw.get("accepted"))))
            continue
        named = named or where in boxes
        box = boxes.get(where, base)
        box["cost"] += cost
        box["price"] += price
        box["lines"].append(line)
    used = list(boxes.values())
    if not any(t["lines"] for t in used) and not named:
        used = []
    for t in used:
        t["total"] = base["price"] + t["price"]
    opt_total = sum((o["price"] for o in options if o["accepted"]),
                    Decimal("0.00"))
    if used:
        pick = next((t for t in used if t["name"] == spec["selected_tier"]),
                    None)
        total = pick["total"] + opt_total if pick else None
    else:
        pick, total = None, base["price"] + opt_total
    return {"base": base, "tiers": used, "options": options,
            "selected": {"tier": pick["name"] if pick else "",
                         "options": opt_total, "total": total},
            "mode": spec["mode"], "spec": spec}


def _service_quote_header(w, comp, title, data):
    """Company from the caller (proposal.company() when omitted). No stand-in
    name is printed when the company name is blank."""
    import os
    import fitz
    from . import quote_pdf as R
    page = w.page
    page.draw_rect(fitz.Rect(0, 0, R.PAPER.width, 56), color=None,
                   fill=(0.15, 0.27, 0.30))
    page.draw_rect(fitz.Rect(0, 56, R.PAPER.width, 60), color=None,
                   fill=(0.70, 0.42, 0.22))
    comp = comp or {}
    x = R.LEFT
    logo = str(comp.get("logo") or "")
    if logo and os.path.isfile(logo):
        try:
            page.insert_image(fitz.Rect(R.LEFT, 8, R.LEFT + 48, 50),
                              filename=logo, keep_proportion=True)
            x = R.LEFT + 56
        except Exception:                                 # noqa: BLE001
            log.warning("could not add logo", exc_info=True)
    name = " ".join(str(comp.get("name") or "").split())
    if name:
        w.text(x, 24, name, 12, "hebo", color=(1, 1, 1))
    contact = "   ".join(v for v in (str(comp.get("phone") or ""),
                                     str(comp.get("email") or "")) if v)
    if contact:
        w.text(x, 40, contact, 8, color=(0.86, 0.91, 0.90))
    w.text(0, 28, title or "Quote", 13, "hebo", color=(1, 1, 1), align="right")
    if data.get("date"):
        w.text(0, 44, str(data["date"]), 8, color=(0.86, 0.91, 0.90),
               align="right")
    w.y = 72
    for ln in [a.strip() for a in str(comp.get("address") or "").splitlines()
               if a.strip()][:3]:
        w.y += 11
        w.text(R.LEFT, w.y, ln, 8, color=R.GREY)
    w.y += 6
    w.rule()


def _service_quote_line(w, ln):
    import os
    import fitz
    from . import quote_pdf as R
    w.need(16)
    w.y += 14
    w.text(R.LEFT, w.y, _fit(ln["desc"], 322, 10), 10)
    w.text(R.LEFT + 330, w.y, qty_text(ln.get("qty"), ln.get("unit") or ""),
           9, color=R.GREY)
    w.text(0, w.y, dmoney.fmt(ln["price"]), 10, align="right")
    photo = ln.get("photo") or ""
    if photo and os.path.isfile(photo):
        w.need(110)
        w.y += 6
        try:
            w.page.insert_image(fitz.Rect(R.LEFT, w.y, R.LEFT + 140, w.y + 96),
                                filename=photo, keep_proportion=True)
            w.y += 100
        except Exception:                                 # noqa: BLE001
            log.warning("could not add a line photo", exc_info=True)


def render_service_quote(q, comp=None, data=None):
    """The option quote as a new PDF. Company and date come from
    proposal.company() / today when omitted. Prices only; no cost."""
    import fitz
    from .. import proposal as P
    from . import quote_pdf as R
    if comp is None:
        comp = P.company()
    data = dict(data or {})
    data.setdefault("date", datetime.date.today().isoformat())
    spec = q["spec"]
    out = fitz.open()
    w = R.Writer(out)
    title = spec.get("title") or "Quote"
    _service_quote_header(w, comp, title, data)

    def table(lines, heading=None, total=None, total_label="Total"):
        if heading:
            w.heading(heading)
        for ln in lines:
            _service_quote_line(w, ln)
        if total is not None:
            w.need(20)
            w.y += 6
            w.rule()
            w.y += 13
            w.text(R.LEFT, w.y, total_label, 10.5, "hebo")
            w.text(0, w.y, dmoney.fmt(total), 10.5, "hebo", align="right")
            w.y += 4

    w.heading(title)
    if data.get("project"):
        w.para(f"Project: {data['project']}", 10)
    if q["base"]["lines"]:
        table(q["base"]["lines"], "Included in every option" if q["tiers"]
              else "Scope", q["base"]["price"],
              "Base" if q["tiers"] else "Total")
    for t in q["tiers"]:
        table(t["lines"], f"Option: {t['name']}", t["total"],
              f"{t['name']} - total with base")
        if t.get("note"):
            w.para(t["note"], 9, color=R.GREY)
    if q["options"]:
        w.heading("Optional items (add any)")
        table([dict(o, desc=("[x] " if o["accepted"] else "[  ] ") + o["desc"])
               for o in q["options"]])
    for head, key in (("Inclusions", "inclusions"),
                      ("Exclusions", "exclusions")):
        items = spec.get(key) or []
        if items:
            w.heading(head)
            for it in items:
                w.para("- " + it, 10)
    if q["tiers"]:
        w.heading("Your choice")
        w.para("Option chosen: " + (q["selected"]["tier"] or
                                    "_______________"), 10)
        if q["selected"]["total"] is not None:
            w.para("Total with the optional items checked: " +
                   dmoney.fmt(q["selected"]["total"]), 10, font="hebo")
    elif q["options"] or q["base"]["lines"]:
        if q["selected"]["total"] is not None:
            w.para("Total with the optional items checked: " +
                   dmoney.fmt(q["selected"]["total"]), 10, font="hebo")
    if spec.get("notes"):
        w.heading("Notes")
        w.para(spec["notes"])
    R.acceptance(w, data, comp)
    out.set_metadata({"title": title,
                      "author": (comp or {}).get("name") or "",
                      "creator": "QuantiSheet"})
    return out


def save_service_quote(path, q, comp=None, data=None):
    import os
    p = _io.check_user_path(path, (".pdf",))
    out = render_service_quote(q, comp, data)
    tmp = p + ".part"
    try:
        try:
            out.save(tmp, garbage=3, deflate=True)
        finally:
            out.close()
        os.replace(tmp, p)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return p
