"""Activity look-ahead for the superintendent's weekly meeting (Oct 21).

The schedule's activities working in the next 2 weeks (1-4), Monday to
Friday, one row each, with a day-by-day grid of the days it works, who is
responsible, % complete, float, and a blank Notes column to write in at
the meeting. Activities behind their baseline, or past their finish but
not marked complete, are flagged at the top.

Dates come from the schedule's own critical-path dates (schedule.cached),
so holidays and links count. PDF (Letter landscape) or Excel.
"""
from datetime import date, timedelta

from . import schedule
from .lookahead import _day, _name

DAY = timedelta(days=1)
HEADERS = ["No.", "Activity", "Area", "Responsible", "Start", "Finish",
           "Days", "%", "Float", "This period", "Flag"]


def window(weeks=2, today=None):
    """(first day, last day) of the look-ahead: Monday of this week (next
    week's from Saturday on) through Friday `weeks` weeks later."""
    today = _day(today) or date.today()
    start = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:
        start += timedelta(days=7)
    return start, start + timedelta(days=7 * int(weeks) - 3)


def workdays(store, start, end, cal=None):
    """The project's workdays from start to end (holidays left out)."""
    cal = cal or schedule.calendar(store)
    out, d = [], start
    while d <= end:
        if cal.is_work(d):
            out.append(d)
        d += DAY
    return out


def rows(store, weeks=2, today=None):
    """The activities for the meeting, by start date: each a dict with
    no, name, area, responsible, start, finish (dates), dur, percent,
    float, critical, milestone, status, period ("Starts", "Finishes",
    "Starts & finishes", "Ongoing"), days (the window's workdays it
    works), flag ("" or why it needs talking about) and late (bool)."""
    today = _day(today) or date.today()
    start, end = window(weeks, today)
    cpm = schedule.cached(store)
    cal = cpm.get("cal")
    days = workdays(store, start, end, cal)
    # the plan's own dates (not pushed to the status date): work planned to
    # be done by now but not marked complete is flagged even when
    # progress updates have already moved it forward (review 0.12.32 #10)
    try:
        planned = {r["_id"]: r for r in schedule.compute(store, None)["rows"]}
    except Exception:                               # noqa: BLE001
        planned = {}
    out = []
    for r in cpm["rows"]:
        if r.get("summary") or r.get("status") == "Complete":
            continue
        es, ef = r["es"], r["ef"]
        behind = schedule.variance(r, cal) or 0
        pf = (planned.get(r["_id"]) or {}).get("ef")
        overdue = ef < today
        past_plan = (not overdue and pf is not None and pf < today and
                     not r.get("summary"))
        in_window = es <= end and ef >= start
        if not (in_window or overdue or past_plan):
            continue
        flag = ""
        if overdue:
            flag = "Past finish - update status"
        elif past_plan:
            flag = f"Planned to finish {pf:%b} {pf.day} - not complete"
        elif behind > 0:
            flag = f"{behind} day(s) behind baseline"
        if es >= start and ef <= end:
            period = "Starts & finishes"
        elif es >= start:
            period = "Starts"
        elif ef <= end:
            period = "Finishes"
        else:
            period = "Ongoing"
        if (overdue or past_plan) and not in_window:
            period = "Overdue"
        milestone = bool(r.get("milestone")) or not r.get("dur")
        out.append({
            "id": r["_id"], "no": r.get("_no") or "",
            "name": r.get("name") or "", "area": r.get("area") or "",
            "responsible": _name(r.get("responsible")),
            "start": es, "finish": ef, "dur": int(r.get("dur") or 0),
            "percent": int(round(float(r.get("percent") or 0))),
            "float": int(r.get("float") or 0),
            "critical": bool(r.get("critical")), "milestone": milestone,
            "status": r.get("status") or "Not Started", "period": period,
            "days": [d for d in days if es <= d <= ef],
            "flag": flag, "late": bool(flag)})
    out.sort(key=lambda x: (not x["late"], x["start"], x["finish"],
                            str(x["no"])))
    return out


def stale(store, today=None, days=7):
    """The status date, if it is more than `days` days old (progress not
    updated), else None."""
    today = _day(today) or date.today()
    dd = _day(store.setting("data_date"))
    return dd if dd and (today - dd).days > days else None


def _title(weeks):
    return f"{int(weeks)}-Week Look-Ahead"


def _subtitle(store, weeks, today, rs):
    s, e = window(weeks, today)
    crit = sum(1 for r in rs if r["critical"])
    late = sum(1 for r in rs if r["late"])
    t = (f"{s:%a %b} {s.day} - {e:%a %b} {e.day}, {e.year}  |  "
         f"{len(rs)} activities, {crit} critical")
    if late:
        t += f", {late} to talk about"
    old = stale(store, today)
    if old:
        t += (f"  |  Progress last updated {old:%b} {old.day} - update it "
              "for true dates")
    return t


def table(rs):
    """Rows as lists under HEADERS."""
    return [[r["no"], r["name"], r["area"], r["responsible"],
             r["start"], r["finish"], r["dur"], r["percent"],
             "Critical" if r["critical"] else f"{r['float']}d",
             r["period"], r["flag"]] for r in rs]


# ------------------------------------------------------------- PDF
W, H = 792, 612                       # Letter landscape
M = 28
INK = (0.12, 0.13, 0.16)
MUTED = (0.42, 0.44, 0.49)
LINE = (0.80, 0.82, 0.86)
FAINT = (0.93, 0.94, 0.96)
ACCENT = (0.15, 0.39, 0.92)
BAR = (0.36, 0.55, 0.93)
CRIT = (0.85, 0.22, 0.20)
LATE = (0.75, 0.10, 0.10)
ROW_H = 20


def _fit(text, size, font, width):
    import fitz
    t = str(text)
    if fitz.get_text_length(t, fontname=font, fontsize=size) <= width:
        return t
    while t and fitz.get_text_length(t + "…", fontname=font,
                                     fontsize=size) > width:
        t = t[:-1]
    return t + "…" if t else ""


def export_pdf(store, path, weeks=2, today=None):
    import fitz
    today = _day(today) or date.today()
    rs = rows(store, weeks, today)
    s, e = window(weeks, today)
    days = workdays(store, s, e)
    doc = fitz.open()
    # fixed columns: (key, header, width)
    fixed = [("no", "No.", 38), ("name", "Activity", 176),
             ("responsible", "Responsible", 84), ("start", "Start", 40),
             ("finish", "Finish", 40), ("percent", "%", 24),
             ("float", "Float", 34)]
    avail = W - 2 * M - sum(w for _k, _h, w in fixed)
    notes_w = 120
    dw = min(22.0, (avail - notes_w) / max(1, len(days)))
    notes_w = avail - dw * len(days)
    title = _title(weeks)
    sub = _subtitle(store, weeks, today, rs)

    def new_page():
        p = doc.new_page(width=W, height=H)
        p.draw_rect(fitz.Rect(0, 0, W, 5), color=None, fill=ACCENT)
        p.insert_text((M, 26), store.name or "", fontsize=8.5,
                      fontname="hebo", color=MUTED)
        p.insert_text((M, 46), title, fontsize=16, fontname="hebo",
                      color=INK)
        p.insert_text((M, 61), _fit(sub, 8.5, "helv", W - 2 * M),
                      fontsize=8.5, fontname="helv", color=MUTED)
        y = 72
        # header rows: week labels over the day columns, then names
        x = M
        p.draw_rect(fitz.Rect(M, y, W - M, y + 30), color=None, fill=FAINT)
        for _k, h, w in fixed:
            p.insert_text((x + 3, y + 25), h, fontsize=7.5, fontname="hebo",
                          color=INK)
            x += w
        x0 = x
        wk = None
        for i, d in enumerate(days):
            mon = d - timedelta(days=d.weekday())
            if mon != wk:
                wk = mon
                p.insert_text((x0 + i * dw + 2, y + 10),
                              _fit(f"Week of {mon:%b} {mon.day}", 7, "hebo",
                                   dw * 5 - 3), fontsize=7, fontname="hebo",
                              color=ACCENT)
                if i:
                    p.draw_line((x0 + i * dw, y), (x0 + i * dw, y + 30),
                                color=LINE, width=0.8)
            p.insert_text((x0 + i * dw + 2, y + 19), f"{d:%a}"[:2],
                          fontsize=6.5, fontname="helv", color=MUTED)
            p.insert_text((x0 + i * dw + 2, y + 27), str(d.day),
                          fontsize=7, fontname="hebo", color=INK)
        p.insert_text((x0 + dw * len(days) + 3, y + 25), "Notes / constraints",
                      fontsize=7.5, fontname="hebo", color=INK)
        p.draw_line((M, y + 30), (W - M, y + 30), color=LINE, width=0.8)
        return p, y + 30

    p, y = new_page()
    if not rs:
        p.insert_text((M, y + 24), "Nothing scheduled in these weeks, and "
                      "nothing overdue.", fontsize=10, fontname="helv",
                      color=MUTED)
    for n, r in enumerate(rs):
        if y + ROW_H > H - 44:
            p, y = new_page()
        if n % 2:
            p.draw_rect(fitz.Rect(M, y, W - M, y + ROW_H), color=None,
                        fill=(0.975, 0.98, 0.985))
        x = M
        color = LATE if r["late"] else INK
        cells = {"no": str(r["no"]),
                 "name": r["name"],
                 "responsible": r["responsible"],
                 "start": f"{r['start']:%b} {r['start'].day}",
                 "finish": f"{r['finish']:%b} {r['finish'].day}",
                 "percent": f"{r['percent']}" if r["percent"] else "",
                 "float": "Crit." if r["critical"] else f"{r['float']}d"}
        for k, _h, w in fixed:
            font = "hebo" if k == "name" and r["critical"] else "helv"
            col = CRIT if k == "float" and r["critical"] else color
            txt = cells[k]
            if k == "name":
                sub_t = r["flag"] or r["area"]
                p.insert_text((x + 3, y + 9), _fit(txt, 8, font, w - 6),
                              fontsize=8, fontname=font, color=col)
                if sub_t:
                    p.insert_text((x + 3, y + 17.5),
                                  _fit(sub_t, 6.5, "helv", w - 6),
                                  fontsize=6.5, fontname="helv",
                                  color=LATE if r["flag"] else MUTED)
            else:
                p.insert_text((x + 3, y + 13), _fit(txt, 7.5, font, w - 5),
                              fontsize=7.5, fontname=font, color=col)
            x += w
        x0 = x
        fill = CRIT if r["critical"] else BAR
        for i, d in enumerate(days):
            cx = x0 + i * dw
            if d in r["days"]:
                if r["milestone"]:
                    c = (cx + dw / 2, y + ROW_H / 2)
                    k = min(dw, ROW_H) * 0.3
                    sh = p.new_shape()
                    sh.draw_polyline([(c[0], c[1] - k), (c[0] + k, c[1]),
                                      (c[0], c[1] + k), (c[0] - k, c[1]),
                                      (c[0], c[1] - k)])
                    sh.finish(color=None, fill=fill, closePath=True)
                    sh.commit()
                else:
                    p.draw_rect(fitz.Rect(cx + 1, y + 5, cx + dw - 1,
                                          y + ROW_H - 5), color=None,
                                fill=fill)
            if i and days[i].weekday() == 0:
                p.draw_line((cx, y), (cx, y + ROW_H), color=LINE, width=0.8)
        # notes: a writing line
        nx = x0 + dw * len(days)
        p.draw_line((nx, y), (nx, y + ROW_H), color=LINE, width=0.5)
        p.draw_line((M, y + ROW_H), (W - M, y + ROW_H), color=LINE,
                    width=0.4)
        y += ROW_H
    # the rest of the last page: ruled lines for the meeting's notes
    if y + 60 < H - 44:
        p.insert_text((M, y + 26), "MEETING NOTES / NEW CONSTRAINTS",
                      fontsize=7.5, fontname="hebo", color=ACCENT)
        yy = y + 48
        while yy < H - 46:
            p.draw_line((M, yy), (W - M, yy), color=LINE, width=0.5)
            yy += 20
    total = doc.page_count
    printed = f"{today:%b} {today.day}, {today.year}"
    for i, pg in enumerate(doc):         # fresh page objects
        yy = H - 22
        pg.draw_rect(fitz.Rect(M, yy - 7, M + 14, yy - 1), color=None,
                     fill=BAR)
        pg.insert_text((M + 18, yy - 1), "working day", fontsize=7,
                       fontname="helv", color=MUTED)
        pg.draw_rect(fitz.Rect(M + 74, yy - 7, M + 88, yy - 1), color=None,
                     fill=CRIT)
        pg.insert_text((M + 92, yy - 1), "critical (no float)", fontsize=7,
                       fontname="helv", color=MUTED)
        pg.insert_text((M + 170, yy - 1), "Red activity = behind baseline "
                       "or past its finish: talk about it.", fontsize=7,
                       fontname="helv", color=LATE)
        pg.insert_text((W - M - 230, yy - 1),
                       f"Printed {printed} from QuantiSheet   Page {i + 1} of "
                       f"{total}", fontsize=7, fontname="helv", color=MUTED)
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


# ------------------------------------------------------------- Excel
def export_xlsx(store, path, weeks=2, today=None):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from .. import safecell
    today = _day(today) or date.today()
    rs = rows(store, weeks, today)
    s, e = window(weeks, today)
    days = workdays(store, s, e)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Look-ahead"
    safecell.append_row(ws, [f"{store.name} - {_title(weeks)}"
                             if store.name else _title(weeks)])
    ws["A1"].font = Font(bold=True, size=13)
    safecell.append_row(ws, [_subtitle(store, weeks, today, rs)])
    head = HEADERS + [f"{d:%a} {d.month}/{d.day}" for d in days] + \
        ["Notes / constraints"]
    safecell.append_row(ws, head)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="bottom")
    bar = PatternFill("solid", fgColor="5B8CEE")
    crit = PatternFill("solid", fgColor="D9383A")
    for r, vals in zip(rs, table(rs)):
        safecell.append_row(ws, vals + ["" for _ in days] + [""])
        row = ws.max_row
        for col in (5, 6):
            ws.cell(row, col).number_format = "mmm d"
        if r["late"]:
            ws.cell(row, 2).font = Font(color="BF1A1A", bold=True)
            ws.cell(row, 11).font = Font(color="BF1A1A")
        for i, d in enumerate(days):
            if d in r["days"]:
                c = ws.cell(row, len(HEADERS) + 1 + i)
                c.fill = crit if r["critical"] else bar
                c.value = "◆" if r["milestone"] else None
    widths = [8, 44, 14, 20, 9, 9, 6, 5, 8, 15, 26] + [5] * len(days) + [36]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "3:3"
    wb.save(path)
    return path


def export(store, path, weeks=2, today=None):
    """PDF or Excel by the file's extension."""
    if str(path).lower().endswith(".xlsx"):
        return export_xlsx(store, path, weeks, today)
    return export_pdf(store, path, weeks, today)
