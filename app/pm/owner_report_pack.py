"""Owner report pack (HELD patch on 0.13.13): the sections an owner asks
for that the Weekly Owner Report doesn't have yet - dashboard, executive
summary, owner actions, work planned, schedule detail, the full inclement
weather log, manpower against plan, budget and billing, the PCO log,
RFI/submittal aging, long-lead items, permits and testing, safety,
quality and punch, risks, meetings, site logistics and distribution.

Drawn with the report's own helpers (owner_report._Ctx / _Flow: section
bars, header-fill tables, Liberation Sans, the std page title and logo)
so the pages read as the same report. The content comes from
rep["pack"] - {"sections": [{"key", "title", "place": "front" | "detail"
| "end", "new_page", "footer", "blocks": [...]}]} - filled by the office
(or a script) from the project's records; this module only lays it out.

Block types: bar, text (lead, size, color, bold), bullets, sample, table
(cols [[header, width, align]], rows, size, title), rag ([[area, G|Y|R,
why]]), kpis ([[label, value, note]]), actions ([[no, text, due, ref]]),
chart (an S-curve: series of [date, percent]), space, page.
A cell is text or {"text", "bold", "color", "fill"}; colors by name.
No signature or sign-off block, by design.

Presets (option report_preset): "" - the full report (page 1, every
section, photos, plans, logs); "weekly" - a short weekly update: a
tightened page 1 (weekly_page1: status line, executive summary, work in
progress, weather days against the allowance, top owner actions), the
sections placed "weekly", then the photo pages; "monthly" - the optional
monthly appendix: the front / detail / end sections, key plan, work areas,
before/after and the attached logs, no page 1 and no photo pages.
A section shows in the presets listed in its "presets" (default
["full"]), so a pack without the key prints as before."""
import logging

from . import owner_report as orp
from .owner_report import (BAR_H, BLACK, FS, GREY_TEXT, RED, X0, X1, _Flow,
                           _clean, _day, _tlen, wrap)

log = logging.getLogger(__name__)

PLACES = ("front", "detail", "end", "weekly")
PRESETS = {"": "full", "full": "full", "weekly": "weekly",
           "monthly": "monthly"}
BOTTOM = 572.0                     # pack pages keep clear of the footer
GREEN = (0.0, 0.69, 0.31)          # the weather log's claimed green
AMBER = (1.0, 0.851, 0.4)          # the weather log's day yellow
COLORS = {"black": BLACK, "grey": GREY_TEXT, "red": RED, "green": GREEN,
          "amber": (0.75, 0.5, 0.0), "blue": orp.BAR_BLUE,
          "white": (1, 1, 1)}
FILLS = {"head": None, "red": (0.98, 0.85, 0.85), "amber": (1.0, 0.95, 0.8),
         "green": (0.87, 0.95, 0.87), "grey": (0.93, 0.93, 0.93),
         "bar": None}
RAG = {"G": (GREEN, (1, 1, 1), "GREEN"), "Y": (AMBER, BLACK, "YELLOW"),
       "R": (RED, (1, 1, 1), "ACTION")}


def _col(v, default=BLACK):
    if isinstance(v, (list, tuple)):
        return tuple(v)
    return COLORS.get(v or "", default)


class PackFlow(_Flow):
    """_Flow with a lower page bottom (the footer line) and wrapped,
    multi-line table rows in the report's table style."""

    def need(self, h):
        if self.page is None or self.y + h > BOTTOM:
            self.new()

    def text(self, s, size=FS, bold=False, color=BLACK, x=41.5,
             width=X1 - 43.0, lead=None):
        """A paragraph; `lead` (bold) runs in at the start."""
        ctx = self.ctx
        pitch = size + 3.5
        if not lead:
            return super().text(s, size, bold, color, x, width)
        lw = _tlen(lead + " ", size, True)
        words = _clean(s).split()
        first, rest = [], list(words)
        while rest and _tlen(" ".join(first + rest[:1]), size, bold) <= \
                width - lw:
            first.append(rest.pop(0))
        self.need(pitch)
        ctx.text(self.page, x, self.y + size + 1.5, lead, size=size,
                 bold=True, color=color)
        ctx.text(self.page, x + lw, self.y + size + 1.5, " ".join(first),
                 size=size, bold=bold, color=color)
        self.y += pitch
        if rest:
            super().text(" ".join(rest), size, bold, color, x, width)

    def wtable(self, cols, rows, size=7.6, title=None, head=True):
        ctx = self.ctx
        tot = sum(float(c[1]) for c in cols)
        ws = [float(c[1]) * (X1 - X0) / tot for c in cols]
        aligns = [c[2] if len(c) > 2 else "left" for c in cols]
        pitch = size * 1.22
        pad = 11.7 - pitch                    # one line = the form's 11.7

        def cell_lines(c, w, bold):
            s = c.get("text", "") if isinstance(c, dict) else c
            s = "" if s is None else str(s)
            out = []
            for part in s.split("\n"):
                out += wrap(part, w - 4, size, bold) or [""]
            return out

        def draw_row(row, bold_row=False, fill=None):
            cells = []
            for c, w in zip(row, ws):
                b = bold_row or (isinstance(c, dict) and c.get("bold"))
                cells.append((c, cell_lines(c, w, b), b))
            n = max(len(x[1]) for x in cells)
            h = n * pitch + pad
            if self.y + h > BOTTOM:
                self.new()
                if title:
                    self.bar(title + " (continued)")
                if head:
                    draw_head()
            if fill:
                ctx.rect(self.page, (X0, self.y, X1, self.y + h),
                         color=None, fill=fill)
            x = X0
            for (c, lines, b), w, al in zip(cells, ws, aligns):
                if isinstance(c, dict) and c.get("fill"):
                    f = c["fill"]
                    f = FILLS.get(f) or ctx.headfill if isinstance(f, str) \
                        else tuple(f)
                    ctx.rect(self.page, (x, self.y, x + w, self.y + h),
                             color=None, fill=f)
                color = _col(c.get("color")) if isinstance(c, dict) \
                    else BLACK
                for k, ln in enumerate(lines):
                    yy = self.y + 8.6 + k * pitch - (FS - size) * 0.35
                    if al == "right":
                        ctx.text(self.page, x + w - 2, yy, ln, size=size,
                                 bold=b, color=color, align="right")
                    elif al == "center":
                        ctx.text(self.page, x + w / 2, yy, ln, size=size,
                                 bold=b, color=color, align="center")
                    else:
                        ctx.text(self.page, x + 2, yy, ln, size=size,
                                 bold=b, color=color)
                x += w
            ctx.rect(self.page, (X0, self.y, X1, self.y + h))
            x = X0
            for w in ws[:-1]:
                x += w
                ctx.line(self.page, (x, self.y), (x, self.y + h),
                         width=0.3)
            self.y += h

        def draw_head():
            draw_row([c[0] for c in cols], True, ctx.headfill)

        # a table that fits on one page starts on a new page rather than
        # leave a lone row or two behind
        est = (len(rows) + 1) * (pitch + pad) + (BAR_H if title else 0)
        if est <= BOTTOM - orp.PAGE_TOP and self.page is not None and \
                self.y + est > BOTTOM:
            self.new()
        if title:
            self.bar(title)
        self.need(2 * (pitch + pad))
        if head:
            draw_head()
        for row in rows:
            fill = None
            if isinstance(row, dict):
                fill = FILLS.get(row.get("fill")) if isinstance(
                    row.get("fill"), str) else row.get("fill")
                row = row["cells"]
            draw_row(row, False, fill)
        self.y += 6


# ---------------------------------------------------------------- blocks
def _rag(fl, items):
    ctx = fl.ctx
    n = len(items)
    gap = 4.0
    w = (X1 - X0 - gap * (n - 1)) / max(n, 1)
    h = 34.0
    fl.need(h + 6)
    for i, it in enumerate(items):
        area, code = it[0], (it[1] or "G").upper()[:1]
        fill, fg, word = RAG.get(code, RAG["G"])
        x = X0 + i * (w + gap)
        ctx.rect(fl.page, (x, fl.y, x + w, fl.y + h), fill=fill, width=0.5)
        ctx.text(fl.page, x + w / 2, fl.y + 13, area.upper(), size=8.2,
                 bold=True, color=fg, align="center", width=w - 4)
        ctx.text(fl.page, x + w / 2, fl.y + 27, word, size=10, bold=True,
                 color=fg, align="center", width=w - 4)
    fl.y += h + 6
    rows = []
    for it in items:
        code = (it[1] or "G").upper()[:1]
        fill, fg, word = RAG.get(code, RAG["G"])
        rows.append([{"text": it[0], "bold": True},
                     {"text": word, "bold": True, "fill": fill,
                      "color": fg}, it[2] if len(it) > 2 else ""])
    fl.wtable([["Area", 90], ["Status", 55, "center"],
               ["What it means for you", 570]], rows, size=7.8)


def _kpis(fl, items, per_row=4):
    ctx = fl.ctx
    gap = 4.0
    w = (X1 - X0 - gap * (per_row - 1)) / per_row
    h = 40.0
    for r0 in range(0, len(items), per_row):
        fl.need(h + 4)
        for i, it in enumerate(items[r0:r0 + per_row]):
            x = X0 + i * (w + gap)
            ctx.rect(fl.page, (x, fl.y, x + w, fl.y + 11.7),
                     fill=ctx.headfill)
            ctx.rect(fl.page, (x, fl.y, x + w, fl.y + h))
            ctx.text(fl.page, x + 3, fl.y + 8.6, it[0], size=7.4, bold=True,
                     width=w - 6)
            ctx.text(fl.page, x + 3, fl.y + 25.5, it[1], size=12,
                     bold=True, color=_col(it[3] if len(it) > 3 else None),
                     width=w - 6)
            if len(it) > 2 and it[2]:
                ctx.text(fl.page, x + 3, fl.y + 35.5, it[2], size=6.3,
                         color=GREY_TEXT, width=w - 6)
        fl.y += h + 4
    fl.y += 2


def _actions(fl, items, title):
    """OWNER ACTION REQUIRED: a red-ruled box with the asks and dates."""
    ctx = fl.ctx
    rows = [[{"text": str(it[0]), "bold": True},
             it[1], {"text": it[2], "bold": True, "color": "red"},
             it[3] if len(it) > 3 else ""] for it in items]
    y0 = fl.y
    page = fl.page
    fl.wtable([["#", 18, "center"], [title, 470], ["Needed by", 70],
               ["Ref", 120]], rows, size=7.8)
    if fl.page is page:
        ctx.rect(page, (X0 - 1.2, y0 - 1.2, X1 + 1.2, fl.y - 6 + 1.2),
                 color=RED, width=1.4)


def _chart(fl, b):
    """An S-curve: cumulative % against dates, axis and grid in the
    report's greys, series in the report's bar blue / critical red."""
    ctx = fl.ctx
    h = float(b.get("height") or 170)
    fl.need(h + 14)
    p = fl.page
    top = fl.y
    ctx.text(p, X0 + 2, top + 9, b.get("title") or "", size=8.2, bold=True)
    x0, x1 = X0 + 34, X1 - 190
    y0, y1 = top + 16, top + h - 16
    d0, d1 = _day(b["x0"]), _day(b["x1"])
    span = max(1, (d1 - d0).days)

    def X(d):
        return x0 + (x1 - x0) * ((_day(d) - d0).days / span)

    def Y(v):
        return y1 - (y1 - y0) * float(v) / 100.0
    for v in range(0, 101, 20):
        ctx.line(p, (x0, Y(v)), (x1, Y(v)), color=(0.8, 0.8, 0.8),
                 width=0.3)
        ctx.text(p, x0 - 3, Y(v) + 2.5, f"{v}%", size=6.3, align="right")
    for t in b.get("ticks") or []:
        ctx.line(p, (X(t), y1), (X(t), y1 + 3), width=0.4)
        d = _day(t)
        ctx.text(p, X(t), y1 + 10, f"{d:%b} '{d:%y}", size=6.0,
                 align="center")
    ctx.rect(p, (x0, y0, x1, y1), width=0.5)
    ly = y0 + 4
    for s in b.get("series") or []:
        col = _col(s.get("color"))
        pts = [(X(d), Y(v)) for d, v in s.get("points") or []]
        if len(pts) >= 2:
            p.draw_polyline(pts, color=col, width=float(s.get("width", 1.4)),
                            dashes="[3 2] 0" if s.get("dash") else None)
        for d, v in s.get("marks") or []:
            p.draw_circle((X(d), Y(v)), 2.8, color=col, fill=col)
        ctx.rect(p, (x1 + 12, ly, x1 + 22, ly + 6), color=None, fill=col)
        ctx.text(p, x1 + 26, ly + 5.6, s.get("label") or "", size=6.8,
                 width=X1 - x1 - 28)
        ly += 12
    fl.y = top + h + 6


def _block(fl, b):
    t = b.get("t")
    if t == "bar":
        fl.bar(b.get("text") or "")
    elif t == "text":
        fl.text(b.get("text") or "", size=float(b.get("size") or FS),
                bold=bool(b.get("bold")), color=_col(b.get("color")),
                lead=b.get("lead"))
        fl.y += float(b.get("after", 2))
    elif t == "bullets":
        size = float(b.get("size") or FS)
        for it in b.get("items") or []:
            lines = wrap(it, X1 - 60, size)
            for k, ln in enumerate(lines):
                fl.need(size + 3.5)
                if k == 0:
                    fl.ctx.text(fl.page, 41.5, fl.y + size + 1.5, "-",
                                size=size)
                fl.ctx.text(fl.page, 52.0, fl.y + size + 1.5, ln, size=size)
                fl.y += size + 3.5
        fl.y += 3
    elif t == "sample":
        fl.text("[SAMPLE DATA] " + (b.get("text") or ""), size=6.8,
                bold=True, color=RED)
        fl.y += 3
    elif t == "table":
        fl.wtable(b["cols"], b.get("rows") or [], float(b.get("size") or 7.6),
                  b.get("title"))
    elif t == "rag":
        _rag(fl, b.get("items") or [])
    elif t == "kpis":
        _kpis(fl, b.get("items") or [], int(b.get("per_row") or 4))
    elif t == "actions":
        _actions(fl, b.get("items") or [],
                 b.get("title") or "What we need from you")
    elif t == "chart":
        _chart(fl, b)
    elif t == "space":
        fl.y += float(b.get("h") or 6)
    elif t == "page":
        fl.new()
    else:
        log.warning("owner pack: unknown block %r", t)


def preset(ctx):
    """The build's preset: "" (full), "weekly" or "monthly". An unknown
    name builds the full report and says so."""
    name = str(ctx.opts.get("report_preset") or "").strip().lower()
    if name not in PRESETS:
        w = f"Unknown report preset {name!r}; built the full report"
        if w not in ctx.warnings:
            ctx.warnings.append(w)
        return ""
    return "" if PRESETS[name] == "full" else name


def sections(rep, place=None, preset_name=None):
    if preset_name is None:
        preset_name = str(((rep.get("options") or {}).get("report_preset"))
                          or "").strip().lower()
    want = PRESETS.get(preset_name, "full")
    secs = [s for s in ((rep.get("pack") or {}).get("sections") or [])
            if s.get("include", True) and
            want in (s.get("presets") or ["full"])]
    if place:
        secs = [s for s in secs if (s.get("place") or "detail") == place]
    return secs


def add_sections(ctx, page_map, place):
    """Draw the pack's sections for one place in the report: front (after
    page 1), detail (after the look-ahead), end (after the logs)."""
    secs = sections(ctx.rep, place, preset(ctx))
    if not secs:
        return
    fl = PackFlow(ctx)
    for s in secs:
        if fl.page is None or s.get("new_page", True) or \
                fl.y > BOTTOM - 140:
            fl.new()
        a = ctx.doc.page_count
        fl.bar(s.get("title") or s.get("key") or "")
        for b in s.get("blocks") or []:
            _block(fl, b)
        page_map.append(orp._span("pack_" + (s.get("key") or "section"),
                                  a, ctx.doc.page_count))
        ctx.pack_footer = getattr(ctx, "pack_footer", {})
        for pno in range(a, ctx.doc.page_count + 1):
            ctx.pack_footer.setdefault(pno, s.get("footer") or
                                       s.get("title") or "")


def add_footers(ctx, page_map):
    """The logs' footer (label | long date | Page i of n) on the pack
    pages, one count for each footer label."""
    from . import owner_report_logs as orl
    pf = getattr(ctx, "pack_footer", {}) or {}
    groups = {}
    for pno in sorted(pf):
        groups.setdefault(pf[pno], []).append(pno - 1)
    rd = _day(ctx.rep.get("date") or ctx.rep.get("week_ending"))
    long_date = f"{rd:%B} {rd.day}, {rd.year}" if rd else ""
    if preset(ctx):
        # weekly / monthly: the document's own page numbers, so they match
        # the contents and "see page n" references (same footer style)
        n = ctx.doc.page_count
        no = str(ctx.rep.get("report_no") or "").strip()
        if no and orp.options(ctx.rep).get("auto_pack"):
            # G23: the report number in the footer of the pack pages (the
            # photo and plan pages fill the form's page, as before)
            long_date = f"{long_date}  |  Report #{no}"
        for label, pnos in groups.items():
            for pno in pnos:
                page = ctx.doc[pno]
                w, h = page.rect.width, page.rect.height
                orl._put(page, 48, h - 24, label, 7.5)
                orl._put(page, w / 2, h - 24, long_date, 7.5, align="center")
                orl._put(page, w - 36, h - 24, f"Page {pno + 1} of {n}", 7.5,
                         align="right")
        return
    for label, pnos in groups.items():
        orl._footers(ctx.doc, pnos, label, long_date)


# ---------------------------------------------------------------- presets
STATUS_H = 23.0


def _wip_grid(ctx, p, y0, title):
    """The page-1 WORK IN PROGRESS bar and trade grid, moved to y0 (the
    same boxes, ticks and label columns as owner_report._page1)."""
    dy = y0 - orp.WIP_Y
    ctx.section_bar(p, y0, title, center=True)
    ticked = set(ctx.rep.get("trades") or [])
    for c, col in enumerate(orp.trade_list(ctx.t)):
        for r, trade in enumerate(col):
            bx, by = orp.BOX_X[c], orp.BOX_Y[r] + dy
            ctx.rect(p, (bx, by, bx + orp.BOX_W, by + orp.BOX_H), width=1.0)
            if trade in ticked:
                orp._check(p, bx, by)
            nxt = orp.LABEL_X[c + 1] - 26 if c < 3 else X1
            ctx.text(p, orp.LABEL_X[c], by + 7.2, trade,
                     width=nxt - orp.LABEL_X[c])
    return orp.BOX_Y[-1] + dy + orp.BOX_H


def _status_line(ctx, p, y, items):
    """STATUS | one coloured tile per area (Schedule, Cost, Safety ...):
    "AREA: GREEN / YELLOW / RED" and, below it, a few words why."""
    lab = 58.0
    ctx.rect(p, (X0, y, X0 + lab, y + STATUS_H), fill=ctx.bar)
    ctx.text(p, X0 + 1.5, y + STATUS_H / 2 + 3.0, "STATUS", bold=True)
    n = max(len(items), 1)
    w = (X1 - X0 - lab) / n
    for i, it in enumerate(items):
        code = (it[1] or "G").upper()[:1]
        fill, fg, word = RAG.get(code, RAG["G"])
        word = "RED" if code == "R" else word
        x = X0 + lab + i * w
        ctx.rect(p, (x, y, x + w, y + STATUS_H), fill=fill)
        ctx.text(p, x + 3, y + 9.0, f"{it[0].upper()}: {word}", bold=True,
                 color=fg, width=w - 6)
        why = it[2] if len(it) > 2 else ""
        if why:
            size = 7.0
            while size > 5.6 and _tlen(why, size) > w - 6:
                size -= 0.2
            ctx.text(p, x + 3, y + 18.5, why, size=size, color=fg,
                     width=w - 6)
    return y + STATUS_H


def weekly_page1(ctx, page_map):
    """The weekly preset's page 1: the report's own header (title, logo,
    REPORT # / JOB NUMBER / JOB NAME / DATE), then a status line, the
    WORK IN PROGRESS grid, INCLEMENT WEATHER DAYS against the allowance,
    EXECUTIVE SUMMARY and OWNER ACTION REQUIRED (top 3). Content from
    rep["pack"]["weekly"]: {"status": [[area, G|Y|R, why]], "summary":
    [sentences], "actions": [[no, text, due, ref]], "allowance": {"label",
    "days", "sample"}, "weather_note"}."""
    rep, t = ctx.rep, ctx.t
    wk = (rep.get("pack") or {}).get("weekly") or {}
    sec = dict(orp.DEFAULT_TEMPLATE["sections"], **(t.get("sections") or {}))
    p = ctx.page1_top()
    first = ctx.doc.page_count
    y = orp.LOGO1[3] + 3.0
    if wk.get("status"):
        y = _status_line(ctx, p, y, wk["status"]) + 5.0
    y = _wip_grid(ctx, p, y, sec["wip"]) + 6.0
    # INCLEMENT WEATHER DAYS (the app's bar) + the allowance
    imp, cl = orp.weather_counts(rep)
    ctx.section_bar(p, y, sec["weather"])
    ctx.text(p, orp.IMPACT_X, y + 8.6, f"IMPACTED WEATHER DAYS: {imp}",
             bold=True)
    ctx.text(p, orp.CLAIM_X, y + 8.6, f"CLAIMED WEATHER DAYS: {cl}",
             bold=True)
    al = wk.get("allowance") or {}
    if al.get("days") is not None:
        label = (al.get("label") or "allowance").upper()
        ctx.text(p, 520.0, y + 8.6, f"{label}: {al['days']}", bold=True,
                 width=X1 - 522.0)
    ry = y + (orp.WEATHER_RULE - orp.WEATHER_Y)
    note = wk.get("weather_note") or ""
    tag = "[SAMPLE DATA] allowance is a placeholder. " if al.get("sample") \
        else ""
    x = 41.5
    if tag:
        ctx.text(p, x, ry - 3.0, tag, size=7.4, bold=True, color=RED)
        x += _tlen(tag, 7.4, True)
    ctx.text(p, x, ry - 3.0, note, size=7.4, width=X1 - x - 2)
    ctx.line(p, (X0, ry), (X1, ry), width=0.75)
    # EXECUTIVE SUMMARY + OWNER ACTION REQUIRED in the pack's flow
    fl = PackFlow(ctx)
    fl.page, fl.y = p, ry + 8.0
    fl.bar("EXECUTIVE SUMMARY")
    fl.y += 2.0
    fl.text(" ".join(wk.get("summary") or []), size=FS)
    fl.y += 6.0
    acts = wk.get("actions") or []
    if acts:
        fl.bar("OWNER ACTION REQUIRED")
        fl.y += 2.0
        _actions(fl, acts[:3], wk.get("actions_title") or
                 "What we need from you this week")
    if fl.page is not p:
        ctx.warnings.append("Weekly page 1 ran onto a second page")
    page_map.append(("page1", first))


def monthly_setup(ctx):
    """The monthly preset: its own title on every page, and the photo
    numbers (and pages, e.g. "W6" in the weekly report) that the key plan
    and before/after pages refer to, since the appendix has no photo
    pages. From rep["pack"]["monthly"]: {"title", "photo_pages":
    {photo name: page label}}."""
    mo = (ctx.rep.get("pack") or {}).get("monthly") or {}
    if mo.get("title"):
        ctx.title = mo["title"]
    pages = mo.get("photo_pages") or {}
    # the key plan note names the report the photos are in (G24)
    ctx.photo_report = mo.get("photo_report") or ("weekly" if pages else "")
    for i, ph in enumerate(orp.printed_photos(ctx.rep), 1):
        k = orp._photo_key(ph.get("ref"))
        ctx.photo_no[k] = i
        name = (ph.get("ref") or {}).get("name") or ""
        if name in pages:
            ctx.photo_page[k] = pages[name]
