"""The customer quote's own small PDF renderer (r36 v2 step 5).

Up to step 4 the quote PDF borrowed Create Proposal's private drawing
helpers (its _Writer, _header, _lines and _acceptance); a later change
to proposal.py's internals could have broken the quote. This is a copy
of just what the quote uses - same letter page, margins, fonts, colours,
heading / paragraph spacing, company header and acceptance block - so
the quote looks exactly as before (tests/test_r36_quote_pdf_own.py checks
every span and line against the step-4 output) and only changes when
this file does. Drawn directly with PyMuPDF (base-14 fonts)."""
import datetime
import logging
import os

import fitz

log = logging.getLogger(__name__)

NAVY = (0.12, 0.23, 0.37)
GREY = (0.4, 0.4, 0.4)
INK = (0.13, 0.13, 0.13)
RULE = (0.75, 0.75, 0.75)
PAPER = fitz.paper_rect("letter")
LEFT, RIGHT, TOP, BOTTOM = 50, PAPER.width - 50, 50, PAPER.height - 62


def clean(text):
    """Base-14 fonts cover Latin-1; swap the usual typographic marks."""
    return (str(text or "").replace("\u2019", "'").replace("\u2018", "'")
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2022", "-"))


def bullet_lines(text):
    """The non-blank lines of a typed list, without bullets."""
    return [ln.strip(" -\u2022\t") for ln in str(text or "").splitlines()
            if ln.strip(" -\u2022\t")]


def wrap(text, width, size, font="helv"):
    out = []
    for para in clean(text).split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            trial = (line + " " + w) if line else w
            if fitz.get_text_length(trial, fontname=font, fontsize=size) \
                    <= width or not line:
                line = trial
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Writer:
    """A cursor that flows text down pages."""

    def __init__(self, doc):
        self.doc = doc
        self.page = None
        self.y = TOP
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page(width=PAPER.width, height=PAPER.height)
        self.y = TOP

    def need(self, h):
        if self.y + h > BOTTOM:
            self.new_page()

    def text(self, x, y, s, size=10, font="helv", color=INK, align="left",
             right=None):
        s = clean(s)
        if align == "right":
            x = (right or RIGHT) - fitz.get_text_length(
                s, fontname=font, fontsize=size)
        self.page.insert_text((x, y), s, fontsize=size, fontname=font,
                              color=color)

    def para(self, s, size=10, x=LEFT, width=None, color=INK, gap=3,
             font="helv"):
        width = width or (RIGHT - x)
        lh = size * 1.3
        for ln in wrap(s, width, size, font):
            self.need(lh)
            self.y += lh
            self.text(x, self.y - size * 0.25, ln, size, font, color)
        self.y += gap

    def heading(self, s):
        self.need(40)
        self.y += 14
        self.y += 13
        self.text(LEFT, self.y, s, 12, "hebo", NAVY)
        self.y += 6

    def rule(self, color=RULE, width=0.6):
        self.page.draw_line((LEFT, self.y), (RIGHT, self.y), color=color,
                            width=width)


def header(w, data, comp):
    """Company name, logo and contact line; PROPOSAL, number, date and
    valid-until on the right; prepared for / project side by side."""
    top = TOP
    x = LEFT
    logo = comp.get("logo")
    y = top
    if logo and os.path.isfile(logo):
        try:
            r = fitz.Rect(LEFT, top, LEFT + 170, top + 60)
            w.page.insert_image(r, filename=logo, keep_proportion=True)
            y = top + 64
        except Exception:                                 # noqa: BLE001
            log.warning("could not add logo %s", logo, exc_info=True)
    y += 14
    w.text(x, y, comp.get("name") or "Your Company", 13, "hebo")
    contact = [comp.get("address", "").replace("\n", ", "),
               " | ".join(v for v in (comp.get("phone"), comp.get("email"),
                                      comp.get("website")) if v),
               f"License {comp['license']}" if comp.get("license") else ""]
    for ln in [c for c in contact if c]:
        y += 11
        w.text(x, y, ln, 8.5, color=GREY)
    try:
        date = datetime.date.fromisoformat(str(data.get("date")))
    except ValueError:
        date = datetime.date.today()
    until = date + datetime.timedelta(days=int(_num(data.get("valid_days"),
                                                    30)))
    ry = top + 22
    w.text(0, ry, "PROPOSAL", 24, "hebo", NAVY, align="right")
    for ln in (f"No. {data.get('number', '')}", f"Date: {date:%B %d, %Y}",
               f"Valid until: {until:%B %d, %Y}"):
        ry += 12
        w.text(0, ry, ln, 9, color=GREY, align="right")
    w.y = max(y, ry) + 12
    w.rule(INK, 0.8)
    col = (RIGHT - LEFT) / 2
    left = [("hebo", data.get("client") or "")]
    if data.get("attention"):
        left.append(("helv", "Attn: " + data["attention"]))
    left += [("helv", ln) for ln in str(data.get("client_address") or "")
             .splitlines() if ln.strip()]
    right = [("hebo", data.get("project") or "")] + \
        [("helv", ln) for ln in str(data.get("project_address") or "")
         .splitlines() if ln.strip()]
    y0 = w.y + 18
    w.text(LEFT, y0, "PREPARED FOR", 8, "hebo", NAVY)
    w.text(LEFT + col, y0, "PROJECT", 8, "hebo", NAVY)
    ys = []
    for x0, items in ((LEFT, left), (LEFT + col, right)):
        y = y0
        for font, ln in items:
            for part in wrap(ln, col - 12, 10, font):
                y += 13
                w.text(x0, y, part, 10, font)
        ys.append(y)
    w.y = max(ys) + 6


def acceptance(w, data, comp):
    """The signature block (kept on one page)."""
    w.need(150)
    w.heading("Acceptance")
    w.para("The prices, scope and terms above are accepted. You are "
           "authorized to do the work as described.", 9, color=GREY)
    col = (RIGHT - LEFT) / 2
    y = w.y + 44
    for x0, who, sub in (
            (LEFT, data.get("client") or "Client", ""),
            (LEFT + col, comp.get("signer") or comp.get("name") or
             "Contractor", comp.get("title") or "")):
        w.page.draw_line((x0, y), (x0 + col - 30, y), color=INK, width=0.7)
        w.text(x0, y + 13, who, 10, "hebo")
        yy = y + 13
        if sub:
            yy += 11
            w.text(x0, yy, sub, 8.5, color=GREY)
        w.text(x0, yy + 11, "Signature / Date", 8.5, color=GREY)
    w.y = y + 50
