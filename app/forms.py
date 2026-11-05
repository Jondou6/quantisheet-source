"""Printable forms (transmittals, registers, punch lists, inspections):
a title, label/value fields, tables that flow onto more pages, paragraphs
and signature lines, drawn with PyMuPDF."""
import datetime as _dt

import fitz

INK = (0, 0, 0)
GREY = (0.4, 0.4, 0.4)
HEAD = (0.88, 0.9, 0.95)


def wrap(text, width, size, font="helv"):
    """Lines of `text` that fit `width` points."""
    out = []
    for para in str(text if text is not None else "").split("\n"):
        line = ""
        for w in para.split(" "):
            trial = f"{line} {w}" if line else w
            if line and fitz.get_text_length(trial, font, size) > width:
                out.append(line)
                line = w
            else:
                line = trial
        while fitz.get_text_length(line, font, size) > width and \
                len(line) > 1:            # one long word: cut it
            cut = len(line)
            while cut > 1 and fitz.get_text_length(line[:cut], font,
                                                   size) > width:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
        out.append(line)
    return out


def flow_text(page, x0, x1, y, text, size, new_page, bottom, bold=False,
              color=INK):
    """Wrapped text from y down, continuing on new_page() (which returns
    (page, top y)) whenever it reaches `bottom`; nothing is cut off.
    Returns (page, y after the text)."""
    font = "hebo" if bold else "helv"
    lh = size * 1.18
    for ln in wrap(text, x1 - x0, size, font):
        if y + lh > bottom:
            page, y = new_page()
        page.insert_text((x0, y + size), ln, fontsize=size, fontname=font,
                         color=color)
        y += lh
    return page, y


def write_box(page, rect, text, size=8, bold=False, align=0, color=INK):
    """Text wrapped into `rect` (top-aligned). Lines that don't fit are
    dropped, the last kept line ending in an ellipsis. align 0/1/2 =
    left/centre/right. Returns the height used."""
    r = fitz.Rect(rect)
    font = "hebo" if bold else "helv"
    lh = size * 1.18
    lines = wrap(text, r.width, size, font)
    fit = max(1, int((r.height + size * 0.25) // lh))
    if len(lines) > fit:
        lines = lines[:fit]
        last = lines[-1]
        while last and fitz.get_text_length(last + "...", font, size) > \
                r.width:
            last = last[:-1]
        lines[-1] = last + "..."
    y = r.y0 + size
    for ln in lines:
        w = fitz.get_text_length(ln, font, size)
        x = r.x0 + (0 if align == 0 else (r.width - w) / 2 if align == 1
                    else r.width - w)
        page.insert_text((x, y), ln, fontsize=size, fontname=font,
                         color=color)
        y += lh
    return len(lines) * lh


class Form:
    def __init__(self, title, subtitle="", landscape=False, company=""):
        self.out = fitz.open()
        self.W, self.H = (792, 612) if landscape else (612, 792)
        self.L, self.R = 36, self.W - 36
        self.title, self.subtitle, self.company = title, subtitle, company
        self.page = None
        self._new()

    def _new(self):
        self.page = self.out.new_page(width=self.W, height=self.H)
        p = self.page
        p.insert_text((self.L, 46), self.title, fontsize=15, fontname="hebo")
        if self.company:
            w = fitz.get_text_length(self.company, "hebo", 9)
            p.insert_text((self.R - w, 46), self.company, fontsize=9,
                          fontname="hebo")
        if self.subtitle:
            p.insert_text((self.L, 60), self.subtitle, fontsize=8.5,
                          color=GREY)
        p.draw_line((self.L, 66), (self.R, 66), color=INK, width=0.8)
        self.y = 80

    def need(self, h):
        if self.y + h > self.H - 40:
            self._new()
            return True
        return False

    def fields(self, pairs, cols=2):
        """[(label, value)] in `cols` columns."""
        colw = (self.R - self.L) / cols
        rows = [pairs[i:i + cols] for i in range(0, len(pairs), cols)]
        for row in rows:
            self.need(15)
            for i, (k, v) in enumerate(row):
                x = self.L + i * colw
                self.page.insert_text((x, self.y + 9), f"{k}:", fontsize=8,
                                      fontname="hebo")
                write_box(self.page, (x + 90, self.y + 0.5, x + colw - 6,
                                      self.y + 14), v, 9)
            self.y += 15
        self.y += 6

    def heading(self, text):
        self.need(30)
        self.y += 8
        self.page.insert_text((self.L, self.y + 9), text, fontsize=11,
                              fontname="hebo")
        self.y += 16

    def para(self, text, size=9):
        if not text:
            return
        lh = size * 1.18
        for ln in wrap(text, self.R - self.L, size):
            self.need(lh)
            self.page.insert_text((self.L, self.y + size), ln,
                                  fontsize=size)
            self.y += lh
        self.y += 6

    def table(self, headers, rows, widths, aligns=None, size=8, fills=None,
              row_h=None):
        """widths are relative; long cell text wraps to two lines."""
        total = float(sum(widths))
        ws = [w / total * (self.R - self.L) for w in widths]
        aligns = aligns or ["l"] * len(headers)
        al = {"l": 0, "c": 1, "r": 2}

        def head():
            x = self.L
            for h, w in zip(headers, ws):
                self.page.draw_rect(fitz.Rect(x, self.y, x + w, self.y + 16),
                                    color=GREY, fill=HEAD, width=0.4)
                write_box(self.page, (x + 2, self.y + 3, x + w - 2,
                                      self.y + 16), h, size, True)
                x += w
            self.y += 16
        self.need(32)
        head()
        for i, row in enumerate(rows):
            lines = 1
            for v, w in zip(row, ws):
                lines = max(lines, min(3, len(wrap(v, w - 4, size))))
            h = row_h or (size * 1.18 * lines + 5)
            if self.need(h):
                head()
            x = self.L
            fill = fills[i] if fills else None
            for v, w, a in zip(row, ws, aligns):
                self.page.draw_rect(fitz.Rect(x, self.y, x + w, self.y + h),
                                    color=GREY, fill=fill, width=0.3)
                write_box(self.page, (x + 2, self.y + 2.5, x + w - 2,
                                      self.y + h), v, size,
                          align=al.get(a, 0))
                x += w
            self.y += h
        self.y += 8

    def signatures(self, labels):
        self.need(50)
        self.y += 28
        n = len(labels)
        w = (self.R - self.L - 20 * (n - 1)) / n
        for i, label in enumerate(labels):
            x = self.L + i * (w + 20)
            self.page.draw_line((x, self.y), (x + w, self.y), color=INK,
                                width=0.5)
            self.page.insert_text((x, self.y + 10), label, fontsize=7.5,
                                  color=GREY)
        self.y += 20

    def save(self, path):
        n = self.out.page_count
        stamp = _dt.date.today().isoformat()
        for i, p in enumerate(self.out):
            p.insert_text((self.L, self.H - 22),
                          f"{self.title}   Printed {stamp}   Page {i + 1} of "
                          f"{n}", fontsize=7, color=GREY)
        self.out.set_metadata({"title": self.title, "creator": "QuantiSheet"})
        self.out.save(path)
        self.out.close()
        return path
