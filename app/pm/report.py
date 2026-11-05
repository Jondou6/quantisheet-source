"""Printable PDFs of Project Center items (one RFI, a punch list, a daily
log...) and Excel logs. These are what gets emailed and filed."""
import logging
import os
from datetime import date

import fitz

from . import schema
from .widgets import show_date
from .weather import summary as weather_summary

W, H = 612, 792
M = 42
INK = (0.12, 0.13, 0.16)
MUTED = (0.42, 0.44, 0.49)
LINE = (0.84, 0.86, 0.89)
ACCENT = (0.15, 0.39, 0.92)


def fmt(field, v, store=None):
    t = field["type"] if field else "text"
    if v in (None, "", [], {}):
        return ""
    if t == "date":
        return show_date(v)
    if t == "money":
        try:
            return f"${float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
    if t == "people":
        return "; ".join(v) if isinstance(v, list) else str(v)
    if t == "ref" and store is not None:
        r = store.get(field["ref"], v)
        if r:
            tf = schema.TOOLS[field["ref"]].get("title_field", "title")
            return f"{r.get('_no', '')} {r.get(tf, '')}".strip()
        return ""
    if t == "weather":
        return weather_summary(v)
    if t == "attachments":
        return ", ".join(a.get("name", "") for a in v)
    return str(v)


class _Doc:
    def __init__(self, title, project, subtitle=""):
        self.doc = fitz.open()
        self.title, self.project, self.subtitle = title, project, subtitle
        self.page = None
        self.y = 0
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page(width=W, height=H)
        p = self.page
        p.draw_rect(fitz.Rect(0, 0, W, 6), color=None, fill=ACCENT)
        p.insert_text((M, 34), self.project or "", fontsize=9,
                      fontname="hebo", color=MUTED)
        p.insert_text((M, 56), self.title, fontsize=17, fontname="hebo",
                      color=INK)
        if self.subtitle:
            p.insert_text((M, 72), self.subtitle[:110], fontsize=9.5,
                          fontname="helv", color=MUTED)
        p.draw_line((M, 82), (W - M, 82), color=LINE, width=0.8)
        self.y = 96

    def need(self, h):
        if self.y + h > H - 50:
            self.new_page()

    def heading(self, text):
        self.need(30)
        self.page.insert_text((M, self.y + 10), text.upper(), fontsize=8,
                              fontname="hebo", color=ACCENT)
        self.y += 18

    def text(self, text, size=9.5, font="helv", indent=0, color=INK):
        width = W - 2 * M - indent
        for para in str(text).split("\n"):
            lines = _wrap(para, size, font, width) or [""]
            for ln in lines:
                self.need(size + 4)
                self.page.insert_text((M + indent, self.y + size), ln,
                                      fontsize=size, fontname=font,
                                      color=color)
                self.y += size + 3.5
        self.y += 4

    def grid(self, pairs, cols=2):
        colw = (W - 2 * M) / cols
        pairs = [p for p in pairs if p[1]]
        for i in range(0, len(pairs), cols):
            row = pairs[i:i + cols]
            heights = []
            for k, (label, val) in enumerate(row):
                lines = _wrap(val, 9.5, "helv", colw - 12)
                heights.append(len(lines))
            h = 12 + 13 * max(heights or [1])
            self.need(h + 4)
            for k, (label, val) in enumerate(row):
                x = M + k * colw
                self.page.insert_text((x, self.y + 8), label, fontsize=7.5,
                                      fontname="helv", color=MUTED)
                yy = self.y + 20
                for ln in _wrap(val, 9.5, "helv", colw - 12):
                    self.page.insert_text((x, yy), ln, fontsize=9.5,
                                          fontname="helv", color=INK)
                    yy += 13
            self.y += h + 4

    def table(self, headers, rows, widths=None):
        n = len(headers)
        total = W - 2 * M
        widths = widths or [total / n] * n
        scale = total / sum(widths)
        widths = [w * scale for w in widths]

        def head():
            self.need(22)
            x = M
            self.page.draw_rect(fitz.Rect(M, self.y, W - M, self.y + 16),
                                color=None, fill=(0.95, 0.96, 0.97))
            for h_, w in zip(headers, widths):
                self.page.insert_text((x + 3, self.y + 11),
                                      _clip(h_, 7.5, "hebo", w - 6),
                                      fontsize=7.5, fontname="hebo",
                                      color=MUTED)
                x += w
            self.y += 18
        head()
        for row in rows:
            cells = [_wrap(str(c if c is not None else ""), 8.5, "helv",
                           w - 6)[:6] or [""]
                     for c, w in zip(row, widths)]
            h = 4 + 11 * max(len(c) for c in cells)
            if self.y + h > H - 50:
                self.new_page()
                head()
            x = M
            for lines, w in zip(cells, widths):
                yy = self.y + 9
                for ln in lines:
                    self.page.insert_text((x + 3, yy), ln, fontsize=8.5,
                                          fontname="helv", color=INK)
                    yy += 11
                x += w
            self.y += h
            self.page.draw_line((M, self.y), (W - M, self.y), color=LINE,
                                width=0.5)
        self.y += 8

    def image(self, path, max_w=250, max_h=190):
        try:
            pix = fitz.Pixmap(path)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            # a 12 MP phone photo printed 250 pt wide: shrink it to ~2x the
            # printed size so the PDF doesn't carry every full image (#37)
            while pix.width > max_w * 4 or pix.height > max_h * 4:
                pix.shrink(1)
        except Exception:
            return False
        r = min(max_w / pix.width, max_h / pix.height, 1)
        w, h = pix.width * r, pix.height * r
        return w, h, pix

    def photos(self, paths):
        x = M
        row_h = 0
        for p in paths:
            got = self.image(p)
            if not got:
                continue
            w, h, pix = got
            if x + w > W - M:
                x = M
                self.y += row_h + 8
                row_h = 0
            if self.y + h > H - 50:
                self.new_page()
                x, row_h = M, 0
            self.page.insert_image(fitz.Rect(x, self.y, x + w, self.y + h),
                                   pixmap=pix)
            x += w + 8
            row_h = max(row_h, h)
        self.y += row_h + 10

    def finish(self, path):
        n = self.doc.page_count
        today = show_date(date.today().isoformat())
        for i, p in enumerate(self.doc):
            p.insert_text((M, H - 24), f"Printed {today} from QuantiSheet",
                          fontsize=7.5, fontname="helv", color=MUTED)
            p.insert_text((W - M - 50, H - 24), f"Page {i + 1} of {n}",
                          fontsize=7.5, fontname="helv", color=MUTED)
        self.doc.save(path, garbage=3, deflate=True)
        self.doc.close()
        return path


def _width(text, size, font):
    return fitz.get_text_length(text, fontname=font, fontsize=size)


def _clip(text, size, font, width):
    t = str(text)
    while t and _width(t, size, font) > width:
        t = t[:-1]
    return t


def _wrap(text, size, font, width):
    out = []
    for para in str(text or "").split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w).strip()
            if _width(cand, size, font) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while _width(w, size, font) > width and len(w) > 1:
                k = len(w)
                while k > 1 and _width(w[:k], size, font) > width:
                    k -= 1
                out.append(w[:k])
                w = w[k:]
            line = w
        out.append(line)
    return out


def record_pdf(store, key, rec, path):
    t = schema.TOOLS[key]
    tf = t.get("title_field", "title")
    title = f"{t['one']} {rec.get('_no', '')}".strip()
    sub = fmt(schema.field(key, tf), rec.get(tf), store)
    d = _Doc(title, store.name, sub)
    simple, longs, lines, threads, files = [], [], [], [], []
    for f in t["fields"]:
        v = rec.get(f["key"])
        if v in (None, "", [], {}):
            continue
        if f["type"] == "long":
            longs.append((f["label"], v))
        elif f["type"] == "lines":
            lines.append((f, v))
        elif f["type"] == "thread":
            threads.append(v)
        elif f["type"] == "attachments":
            files += v
        elif f["key"] != tf:
            simple.append((f["label"], fmt(f, v, store)))
    ball = schema.ball_in_court(key, rec)
    if ball:
        simple.insert(1, ("Ball in court", ball))
    simple.append(("Created", f"{show_date(rec.get('_created', '')[:10])} "
                              f"by {rec.get('_by', '')}"))
    d.grid(simple)
    for label, v in longs:
        d.heading(label)
        d.text(v)
    for f, rows in lines:
        d.heading(f["label"])
        d.table([c[1] for c in f["cols"]],
                [[fmt({"type": c[2]}, r.get(c[0])) for c in f["cols"]]
                 for r in rows])
    for msgs in threads:
        d.heading("Discussion")
        for m in msgs:
            d.text(f"{m.get('by', '')}  ·  "
                   f"{m.get('at', '').replace('T', ' ')}", 8, "hebo",
                   color=MUTED)
            d.text(m.get("text", ""), indent=8)
    if files:
        d.heading("Attachments")
        imgs = []
        for a in files:
            d.text(f"•  {a.get('name')}", 9)
            if (a.get("ext") or "").lower() in (".jpg", ".jpeg", ".png"):
                try:
                    imgs.append(store.attachment_path(a))
                except Exception:
                    logging.getLogger(__name__).debug("ignored error", exc_info=True)
        if imgs:
            d.photos(imgs[:12])
    return d.finish(path)


def col_label(key, c):
    if c.startswith("_"):
        return {"_no": "No.", "_ball": "Ball in court", "_items": "Items",
                "_progress": "Checked", "_weekday": "Day",
                "_workers": "Workers", "_open_topics": "Open topics",
                "_late": "Late", "_approved": "Approved changes",
                "_revised": "Revised", "_committed": "Committed",
                "_actual": "Actual cost", "_fac": "Forecast at completion",
                "_variance": "Variance", "_flag": "Check",
                "_original": "Original",
                "_invoiced": "Invoiced", "_paid": "Paid",
                "_remaining": "Left to invoice", "_cost": "Cost",
                "_price": "Price to owner", "_billed": "Billed to date",
                "_pct": "% billed", "_this_period": "This period",
                "_due": "Payment due", "_invited": "Invited",
                "_will": "Bidding", "_received": "Bids in",
                "_low": "Low bid", "_start": "Start", "_finish": "Finish",
                "_float": "Float", "_compliance": "Compliance"}.get(c, c)
    f = schema.field(key, c)
    return f["label"] if f else c


def cell(store, key, rec, c):
    """Text for list column c of rec (schema columns plus computed ones)."""
    if c == "_ball":
        return schema.ball_in_court(key, rec) or ""
    if c == "_items":
        return str(len(store.find("submittal", package=rec["_id"])))
    if c == "_progress":
        items = rec.get("items") or []
        done = sum(1 for i in items if i.get("result"))
        return f"{done}/{len(items)}" if items else ""
    if c == "_weekday":
        try:
            return f"{date.fromisoformat(rec.get('date')):%a}"
        except (TypeError, ValueError):
            return ""
    if c == "_workers":
        n = 0
        for r in rec.get("manpower") or []:
            try:
                n += int(float(r.get("workers") or 0))
            except ValueError:
                pass
        return str(n) if n else ""
    if c == "_open_topics":
        return str(sum(1 for r in rec.get("topics") or []
                       if (r.get("status") or "Open") == "Open"))
    if c == "_late":
        exp = rec.get("expected") or rec.get("promised")
        need = rec.get("needed")
        if exp and need and exp > need and rec.get("status") != "Delivered":
            return "Late"
        return ""
    if key == "bidpkg" and c.startswith("_") and c != "_no":
        bs = rec.get("bidders") or []
        if c == "_invited":
            return str(len(bs)) if bs else ""
        if c == "_will":
            return str(sum(1 for b in bs if b.get("status") in
                           ("Will Bid", "Bid Received", "Awarded")))
        if c == "_received":
            return str(sum(1 for b in bs if b.get("amount") or
                           b.get("status") == "Bid Received"))
        from .bidforms import num
        amts = [a for a in (num(b.get("amount")) for b in bs)
                if a is not None]           # "$1,200" no longer crashes (#39)
        return f"${min(amts):,.0f}" if amts else ""
    if key in ("budget", "commitment", "event", "contract", "payapp",
               "subpay",
               "cost") and c.startswith("_") and c != "_no":
        from . import cost
        return cost.cell(store, key, rec, c)
    if key == "activity" and c in ("_start", "_finish", "_float"):
        from . import schedule
        return schedule.cell(store, rec, c)
    if c.startswith("_"):
        return str(rec.get(c, ""))
    return fmt(schema.field(key, c), rec.get(c), store)


def list_pdf(store, key, recs, path, title=None):
    t = schema.TOOLS[key]
    cols = t["columns"]
    d = _Doc(title or f"{t['title']} log", store.name,
             f"{len(recs)} item(s)")
    widths = [2.4 if c in (t.get("title_field"), "title", "subject", "item")
              else 1.2 for c in cols]
    d.table([col_label(key, c) for c in cols],
            [[cell(store, key, r, c) for c in cols] for r in recs], widths)
    return d.finish(path)


def list_xlsx(store, key, recs, path):
    from ..acrobat import write_xlsx
    t = schema.TOOLS[key]
    simple = [f for f in t["fields"] if f["type"] not in
              ("lines", "thread", "attachments")]
    rows = [["No."] + [f["label"] for f in simple] + ["Ball in court",
                                                       "Created", "By"]]
    for r in recs:
        rows.append([r.get("_no", "")] +
                    [fmt(f, r.get(f["key"]), store) for f in simple] +
                    [schema.ball_in_court(key, r) or "",
                     (r.get("_created") or "")[:10], r.get("_by", "")])
    write_xlsx(path, [(t["title"], rows)])
    return path


def safe_name(text):
    import re
    return re.sub(r'[\\/:*?"<>|]+', "_", text).strip() or "item"


def temp_pdf(store, key, rec):
    import tempfile
    t = schema.TOOLS[key]
    tf = t.get("title_field", "title")
    name = safe_name(f"{rec.get('_no', '')} {rec.get(tf, '')}"[:80])
    d = tempfile.mkdtemp(prefix="quantisheet-")
    return record_pdf(store, key, rec, os.path.join(d, name + ".pdf"))
