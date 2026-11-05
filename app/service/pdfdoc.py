"""Letter-size PDFs for the service tools.

The header is the company from proposal.company() (name, address, phone,
email, logo file). A blank company setting leaves the name off; no company
name or logo is written into this module. Widgets are real PDF form fields.
"""
import logging
import os

import fitz

log = logging.getLogger(__name__)

SLATE = (0.15, 0.27, 0.30)
COPPER = (0.70, 0.42, 0.22)
INK = (0.12, 0.14, 0.16)
MUTED = (0.38, 0.40, 0.42)
WHITE = (1, 1, 1)
RULE = (0.78, 0.78, 0.76)
PAGE_W, PAGE_H = 612, 792
LEFT, RIGHT = 36, 576

_COMPANY_KEYS = ("name", "address", "phone", "email", "website", "license",
                 "logo", "signer", "title")


def company(comp=None):
    """The header company. None reads proposal.company()."""
    if comp is None:
        from .. import proposal
        comp = proposal.company()
    comp = comp or {}
    return {k: str(comp.get(k) or "") for k in _COMPANY_KEYS}


def clean(text):
    s = (str(text or "").replace("\u2019", "'").replace("\u2018", "'")
         .replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2013", "-").replace("\u2014", "-")
         .replace("\u2022", "-"))
    return s.encode("latin-1", "replace").decode("latin-1")


def fit(text, width, size, font="helv"):
    text = clean(" ".join(str(text or "").split()))
    if fitz.get_text_length(text, fontname=font, fontsize=size) <= width:
        return text
    while text and fitz.get_text_length(text + "...", fontname=font,
                                        fontsize=size) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def read_fields(path):
    """{field name: value} from a PDF this module wrote."""
    out = {}
    with fitz.open(path) as doc:
        for page in doc:
            for w in page.widgets() or []:
                out[w.field_name] = w.field_value
    return out


class Sheet:
    """One document. `save` writes it and closes it."""

    def __init__(self, title, comp=None, subtitle=""):
        self.comp = company(comp)
        self.title = clean(title or "Service")
        self.subtitle = clean(subtitle or "")
        self.doc = fitz.open()
        self.page = None
        self.y = 0
        self.new_page(first=True)

    def new_page(self, first=False):
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = self._banner(continued=not first)
        return self.page

    def need(self, h):
        if self.y + h > PAGE_H - 40:
            self.new_page()

    def _banner(self, continued=False):
        page, comp = self.page, self.comp
        h = 36 if continued else 58
        page.draw_rect(fitz.Rect(0, 0, PAGE_W, h), color=None, fill=SLATE)
        page.draw_rect(fitz.Rect(0, h, PAGE_W, h + 3), color=None, fill=COPPER)
        x = LEFT
        if comp.get("logo") and os.path.isfile(comp["logo"]) and not continued:
            try:
                page.insert_image(fitz.Rect(LEFT, 8, LEFT + 52, h - 6),
                                  filename=comp["logo"], keep_proportion=True)
                x = LEFT + 60
            except Exception:                             # noqa: BLE001
                log.warning("could not draw the company logo", exc_info=True)
        name = " ".join(comp.get("name", "").split())
        if name:
            page.insert_text((x, 22 if not continued else 16),
                             fit(name, 300, 12, "hebo"), fontsize=12,
                             fontname="hebo", color=WHITE)
        contact = " | ".join(v for v in (comp.get("phone"), comp.get("email"))
                             if v)
        if contact and not continued:
            page.insert_text((x, 38), fit(contact, 300, 8), fontsize=8,
                             fontname="helv", color=(0.86, 0.91, 0.90))
        label = self.title + (" (continued)" if continued else "")
        size = 11 if continued else 13
        tw = fitz.get_text_length(fit(label, 220, size, "hebo"),
                                  fontname="hebo", fontsize=size)
        page.insert_text((RIGHT - tw, 24 if not continued else 16),
                         fit(label, 220, size, "hebo"), fontsize=size,
                         fontname="hebo", color=WHITE)
        if self.subtitle and not continued:
            st = fit(self.subtitle, 220, 8)
            sw = fitz.get_text_length(st, fontname="helv", fontsize=8)
            page.insert_text((RIGHT - sw, 40), st, fontsize=8, fontname="helv",
                             color=(0.86, 0.91, 0.90))
        y = h + 16
        addr = comp.get("address") or ""
        for ln in [clean(a) for a in addr.splitlines() if a.strip()][:3]:
            page.insert_text((LEFT, y), fit(ln, RIGHT - LEFT, 8), fontsize=8,
                             fontname="helv", color=MUTED)
            y += 11
        if comp.get("license") and not continued:
            page.insert_text((LEFT, y), fit("License " + comp["license"],
                                            240, 8), fontsize=8,
                             fontname="helv", color=MUTED)
            y += 11
        return y + 4

    def text(self, x, y, s, size=9, bold=False, color=INK):
        self.page.insert_text((x, y), clean(s), fontsize=size,
                              fontname="hebo" if bold else "helv", color=color)

    def section(self, number, title):
        self.need(28)
        self.y += 16
        self.page.draw_rect(fitz.Rect(LEFT, self.y - 9, LEFT + 3, self.y + 3),
                            color=None, fill=COPPER)
        self.text(LEFT + 10, self.y, f"{number}    {title}", 11, True)
        self.y += 8
        return self.y

    def label(self, x, y, s, size=7.5):
        self.text(x, y, s, size, color=MUTED)

    def rule(self):
        self.page.draw_line((LEFT, self.y), (RIGHT, self.y), color=RULE,
                            width=0.6)

    def text_field(self, name, rect, value="", multiline=False, readonly=False):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(*rect)
        w.text_fontsize = 8
        w.field_value = clean(value)
        w.border_color = (0.72, 0.72, 0.70)
        w.border_width = 0.6
        w.fill_color = (0.985, 0.985, 0.978)
        flags = 0
        if multiline:
            flags |= int(fitz.PDF_TX_FIELD_IS_MULTILINE)
        if readonly:
            flags |= int(fitz.PDF_FIELD_IS_READ_ONLY)
        if flags:
            w.field_flags = flags
        self.page.add_widget(w)
        return w

    def checkbox(self, name, rect, checked=False):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.rect = fitz.Rect(*rect)
        w.border_color = SLATE
        w.border_width = 0.8
        w.fill_color = (1, 1, 1)
        self.page.add_widget(w)
        for live in self.page.widgets() or []:
            if live.field_name == name:
                live.field_value = live.on_state() if checked else "Off"
                live.update()
                break
        return w

    def combo(self, name, rect, choices, value=""):
        choices = [str(c) for c in choices]
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w.rect = fitz.Rect(*rect)
        w.text_fontsize = 8
        w.choice_values = choices or [""]
        w.field_value = value if value in w.choice_values else w.choice_values[0]
        w.border_color = (0.72, 0.72, 0.70)
        w.border_width = 0.6
        w.fill_color = (0.985, 0.985, 0.978)
        self.page.add_widget(w)
        return w

    def save(self, path):
        from ..estimating import _io
        try:
            p = _io.check_user_path(path, (".pdf",))
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            self.doc.set_metadata({"title": self.title,
                                   "author": self.comp.get("name") or "",
                                   "creator": "QuantiSheet"})
            tmp = p + ".part"
            try:
                self.doc.save(tmp, garbage=3, deflate=True)
                os.replace(tmp, p)
            except BaseException:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                raise
            return p
        finally:
            self.doc.close()
