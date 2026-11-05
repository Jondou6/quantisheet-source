"""Change Order from a Revision (Nov 3, Jon approved Chief's list, #11):
pick a revised sheet and the sheet it replaces; every takeoff item's
quantity change is priced at the job's own unit prices plus markup, and a
change order proposal PDF is made - a priced summary page, then each
revised sheet with the changed takeoff clouded as backup.

Read only on both drawings; the PDF is a new document."""
import datetime
from decimal import ROUND_HALF_UP, Decimal

import fitz

CENT = Decimal("0.01")
CLOUD_PAD = 6


def _q(v):
    return Decimal(str(v or 0))


def quantities(doc, page):
    """{(group, unit): (qty Decimal, [item rects])} on one page."""
    from . import annotate
    out = {}
    for it in annotate.totals_items(doc):
        if it["page"] != page or not it.get("group"):
            continue
        k = (it["group"], it.get("unit") or "")
        q, rects = out.get(k, (Decimal(0), []))
        q += _q(it.get("value")) * _q(it.get("multiplier") or 1)
        out[k] = (q, rects + [it["rect"]])
    return out


def prices(*docs):
    """{group name: unit cost} - the first document that prices it."""
    from . import estimate
    out = {}
    for d in docs:
        if d is None:
            continue
        try:
            for g in estimate.lines(d):
                uc = _q(g.get("unit_cost"))
                if uc and g["name"] not in out:
                    out[g["name"]] = uc
        except Exception:                                 # noqa: BLE001
            continue
    return out


def delta(old_doc, old_page, new_doc, new_page, markup_pct=10):
    """The priced change: {"lines": [{"item", "unit", "old", "new",
    "change", "unit_price", "amount"}], "subtotal", "markup_pct",
    "markup", "total", "unpriced": [items]}."""
    a = quantities(old_doc, old_page)
    b = quantities(new_doc, new_page)
    up = prices(new_doc, old_doc)
    lines, unpriced = [], []
    for k in sorted(set(a) | set(b)):
        qa = a.get(k, (Decimal(0), []))[0]
        qb = b.get(k, (Decimal(0), []))[0]
        ch = qb - qa
        if abs(ch) < Decimal("0.005"):
            continue
        p = up.get(k[0])
        amt = (ch * p).quantize(CENT, ROUND_HALF_UP) if p else None
        if p is None:
            unpriced.append(k[0])
        lines.append({"item": k[0], "unit": k[1],
                      "old": qa.quantize(CENT), "new": qb.quantize(CENT),
                      "change": ch.quantize(CENT), "unit_price": p,
                      "amount": amt})
    sub = sum((x["amount"] for x in lines if x["amount"] is not None),
              Decimal("0.00"))
    mk = (sub * _q(markup_pct) / 100).quantize(CENT, ROUND_HALF_UP)
    return {"lines": lines, "subtotal": sub, "markup_pct": _q(markup_pct),
            "markup": mk, "total": sub + mk, "unpriced": unpriced,
            "changed_rects": [r for k in b for r in b[k][1]
                              if any(x["item"] == k[0] for x in lines)]}


def _money(v):
    return "" if v is None else (f"-${-v:,.2f}" if v < 0 else f"${v:,.2f}")


def make_pdf(new_doc, new_page, result, path, title="", sheet="",
             company=""):
    """The change order proposal: summary page + the revised sheet with
    the changed takeoff clouded."""
    out = fitz.open()
    pg = out.new_page(width=612, height=792)
    y = 50

    def t(x, text, size=9, bold=False, right=False):
        font = "hebo" if bold else "helv"
        if right:
            w = fitz.get_text_length(str(text), fontname=font, fontsize=size)
            x -= w
        pg.insert_text((x, y), str(text), fontsize=size, fontname=font)
    t(36, "CHANGE ORDER PROPOSAL", 15, True)
    y += 22
    for k, v in (("Project", title), ("From", company),
                 ("Revised sheet", sheet),
                 ("Date", datetime.date.today().isoformat())):
        if v:
            t(36, f"{k}:", 9, True)
            t(130, v)
            y += 14
    y += 10
    cols = (36, 250, 330, 400, 470, 576)
    for x, h in zip(cols, ("Item", "Was", "Now", "Change", "Unit price",
                           "Amount")):
        t(x, h, 8, True, right=x > 300)
    y += 4
    pg.draw_line((36, y), (576, y), width=0.5)
    y += 12
    for ln in result["lines"]:
        if y > 720:
            pg = out.new_page(width=612, height=792)
            y = 50
        t(36, f"{ln['item']} ({ln['unit']})"[:48], 8)
        for x, v in zip(cols[1:],
                        (f"{ln['old']:,}", f"{ln['new']:,}",
                         f"{ln['change']:+,}",
                         _money(ln["unit_price"]) or "no price",
                         _money(ln["amount"]))):
            t(x, v, 8, right=True)
        y += 13
    y += 6
    pg.draw_line((330, y - 8), (576, y - 8), width=0.5)
    for label, v in (("Subtotal", result["subtotal"]),
                     (f"Markup {result['markup_pct']:g}%", result["markup"]),
                     ("Change order total", result["total"])):
        t(470, label, 9, label.startswith("Change"), right=True)
        t(576, _money(v), 9, label.startswith("Change"), right=True)
        y += 14
    if result["unpriced"]:
        y += 8
        t(36, "Not priced (no unit price in the estimate): " +
          ", ".join(result["unpriced"])[:110], 8)
    y += 24
    t(36, "Backup: the revised sheet follows, with the changed takeoff "
      "clouded.", 8)
    out.insert_pdf(new_doc, from_page=new_page, to_page=new_page,
                   annots=True)
    bk = out[-1]
    for r in result["changed_rects"]:
        rr = fitz.Rect(r) + (-CLOUD_PAD, -CLOUD_PAD, CLOUD_PAD, CLOUD_PAD)
        a = bk.add_rect_annot(rr)
        try:
            a.set_border(width=1.5, clouds=1)
        except TypeError:
            a.set_border(width=1.5)
        a.set_colors(stroke=(0.85, 0.1, 0.1))
        a.set_info(subject="Change order backup", title="QuantiSheet")
        a.update()
    out.save(path, garbage=3, deflate=True)
    return path
