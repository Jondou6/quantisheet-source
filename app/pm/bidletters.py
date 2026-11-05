"""Award (intent to award) and regret letters for a bid package, as PDFs.

The wording is a template kept in the project's settings (Project settings
"award_letter" / "regret_letter"), with {fields} filled in:
{date} {project} {package} {number} {company} {contact} {amount} {gc}
{me} {trades} {scope}. The PDFs are attached to the package so you can open
and edit them in QuantiSheet before you send them.
"""
import os
import re
from datetime import date

import fitz

AWARD = """{date}

{company}
Attn: {contact}

Re: {project} - {package} ({number})
Notice of Intent to Award

Thank you for your bid for {package}. We are pleased to tell you that {gc} \
intends to award this work to {company} for {amount}, subject to a \
subcontract agreement acceptable to both parties.

Before work begins we will need:
  - the signed subcontract (it will follow under separate cover);
  - certificates of insurance naming {gc} and the owner as additional \
insured;
  - your W-9, and payment and performance bonds if the bid documents call \
for them.

This letter is not a notice to proceed. Please do not order materials or \
start work until you receive the executed subcontract.

Please confirm receipt by reply. We look forward to working with you.

Sincerely,

{me}
{gc}"""

REGRET = """{date}

{company}
Attn: {contact}

Re: {project} - {package} ({number})

Thank you for the time and effort you put into your bid for {package}. \
After careful review, {gc} has awarded this work to another firm.

We value your interest and look forward to inviting you to bid on future \
work.

Sincerely,

{me}
{gc}"""


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v or "")


def fields(store, rec, bidder, amount=None):
    gc = store.setting("company_name") or ""
    if not gc:
        from .. import settings
        gc = settings.get("company_name") or ""
    return _Safe(date=date.today().strftime("%B %d, %Y").replace(" 0", " "),
                 project=store.name, package=rec.get("title") or "",
                 number=rec.get("_no") or "",
                 company=bidder.get("company") or "",
                 contact=bidder.get("contact") or bidder.get("company")
                 or "", amount=_money(amount if amount is not None
                                      else bidder.get("amount")),
                 gc=gc or "our company", me=store.me or "",
                 trades=rec.get("trades") or "",
                 scope=rec.get("scope") or "")


def text(store, rec, bidder, kind="award", amount=None):
    tpl = store.setting(f"{kind}_letter") or (AWARD if kind == "award"
                                              else REGRET)
    return tpl.format_map(fields(store, rec, bidder, amount))


def write_pdf(path, body, title=""):
    """A letter page (or more) with `body` as plain text."""
    doc = fitz.open()
    W, H, M = 612, 792, 72
    paras = body.split("\n")
    page = doc.new_page(width=W, height=H)
    y = M
    if title:
        page.insert_text((M, y), title, fontsize=13, fontname="hebo")
        y += 26
    for p in paras:
        if not p.strip():
            y += 10
            continue
        rect = fitz.Rect(M, y, W - M, H - M)
        # how tall is this paragraph?
        h = _height(p, W - 2 * M)
        if y + h > H - M and h <= H - 2 * M:
            page = doc.new_page(width=W, height=H)
            y = M
            rect = fitz.Rect(M, y, W - M, H - M)
        if page.insert_textbox(rect, p, fontsize=10.5, fontname="helv") < 0:
            # didn't fit (longer than a page; insert_textbox then draws
            # nothing), so flow it line by line instead (3 #38)
            from ..forms import flow_text
            page, y = flow_text(page, M, W - M, y, p, 10.5,
                                lambda: (doc.new_page(width=W, height=H), M),
                                H - M)
            y += 2
            continue
        y += h + 2
    doc.set_metadata({"title": title or "Letter", "creator": "QuantiSheet"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def _height(text, width, size=10.5):
    words = text.split(" ")
    lines, cur = 1, 0.0
    for w in words:
        wl = fitz.get_text_length(w + " ", fontname="helv", fontsize=size)
        if cur + wl > width and cur:
            lines += 1
            cur = wl
        else:
            cur += wl
    return lines * size * 1.25


def _drop(path):
    """The letter is copied into the project's attachments; remove the
    working copy so .pm_letters doesn't fill up."""
    try:
        os.remove(path)
    except OSError:
        pass


def make_letters(store, rec, winner, amount=None, regrets=True):
    """Award letter for `winner` and regret letters for the other bidders
    who bid. Returns attachment refs (store.attach) for the package."""
    out = []
    tmp = os.path.join(store.folder, ".pm_letters")
    os.makedirs(tmp, exist_ok=True)
    no = re.sub(r"[^A-Za-z0-9_-]+", "", rec.get("_no") or "BP")

    def safe(name):
        return re.sub(r"[^A-Za-z0-9 _.-]+", "", name or "bidder")[:40]
    body = text(store, rec, winner, "award", amount)
    p = os.path.join(tmp, f"{no} Award - {safe(winner.get('company'))}.pdf")
    write_pdf(p, body)
    ref = store.attach(p)
    _drop(p)
    ref["letter"] = "award"
    ref["company"] = winner.get("company", "")
    ref["email"] = winner.get("email", "")
    out.append(ref)
    if regrets:
        for b in rec.get("bidders") or []:
            if b is winner or b.get("company") == winner.get("company"):
                continue
            if b.get("status") not in ("Bid Received",) and \
                    b.get("amount") in (None, ""):
                continue
            body = text(store, rec, b, "regret")
            p = os.path.join(tmp, f"{no} Regret - "
                                  f"{safe(b.get('company'))}.pdf")
            write_pdf(p, body)
            ref = store.attach(p)
            _drop(p)
            ref["letter"] = "regret"
            ref["company"] = b.get("company", "")
            ref["email"] = b.get("email", "")
            out.append(ref)
    return out
