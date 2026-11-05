"""Printable schedule: basis narrative, activity table, and a Gantt.

Bars for longest-path work are drawn in red. Other bars are blue. The
table lists the predecessor that drives each activity. Uses the PDF
library already in the program (PyMuPDF). No product names appear in
the pages.
"""
import datetime as _dt

import fitz

from .model import as_date

PAGE = fitz.Rect(0, 0, 1224, 792)
RED = (0.75, 0.12, 0.12)
BLUE = (0.15, 0.35, 0.62)
GREY = (0.4, 0.4, 0.4)
INK = (0.1, 0.1, 0.1)


def export_pdf(doc, path):
    out = fitz.open()
    _narrative(out, doc)
    _table(out, doc)
    _gantt(out, doc)
    out.save(path)
    out.close()
    return path


def _narrative(doc_pdf, doc):
    text = doc.get("narrative") or "No basis of schedule was written."
    status = "FINISHED" if doc.get("status") == "finished" else "NOT FINISHED"
    title = f"Basis of schedule - {status}"
    page = doc_pdf.new_page(width=PAGE.width, height=PAGE.height)
    page.insert_textbox(fitz.Rect(36, 28, PAGE.width - 36, 60), title,
                        fontsize=16, fontname="hebo", color=INK)
    score = (doc.get("rubric") or {}).get("score")
    health = (doc.get("health") or {}).get("score")
    page.insert_textbox(
        fitz.Rect(36, 62, PAGE.width - 36, 84),
        f"Completeness {score}    Schedule health {health}",
        fontsize=10, fontname="helv", color=GREY)
    rect = fitz.Rect(36, 92, PAGE.width - 36, PAGE.height - 36)
    page.insert_textbox(rect, text, fontsize=10, fontname="helv", color=INK,
                        align=fitz.TEXT_ALIGN_LEFT)


def _rows(doc):
    return [a for a in doc.get("activities") or () if a.get("es")]


def _table(doc_pdf, doc):
    rows = _rows(doc)
    page = None
    y = 0
    headers = ("ID", "Activity", "Dur", "Start", "Finish", "Float", "Driven by")

    def new():
        nonlocal page, y
        page = doc_pdf.new_page(width=PAGE.width, height=PAGE.height)
        y = 36
        page.insert_text((36, y), "Activities", fontsize=14, fontname="hebo",
                         color=INK)
        y += 22
        _header(page, y, headers)
        y += 16

    new()
    for a in rows:
        if y > PAGE.height - 40:
            new()
        vals = (
            a.get("code") or "",
            (a.get("name") or "")[:42],
            _dur(a),
            a.get("es") or "",
            a.get("ef") or "",
            "" if a.get("total_float_days") is None else f"{a['total_float_days']:.0f}",
            (a.get("driving_pred") or "")[:16],
        )
        color = RED if a.get("longest_path") else INK
        _line(page, y, vals, color)
        y += 14


def _header(page, y, headers):
    _line(page, y, headers, GREY)


def _line(page, y, vals, color):
    xs = (36, 100, 360, 400, 470, 540, 590)
    for x, val in zip(xs, vals):
        page.insert_text((x, y), str(val), fontsize=8, fontname="helv", color=color)


def _dur(a):
    if a.get("type") in ("start_ms", "finish_ms"):
        return "0"
    days = a.get("dur_days")
    return "" if days is None else f"{days:.0f}"


def _gantt(doc_pdf, doc):
    rows = _rows(doc)
    if not rows:
        return
    start = min(as_date(a["es"]) for a in rows)
    finish = max(as_date(a["ef"]) for a in rows)
    if finish <= start:
        finish = start + _dt.timedelta(days=1)
    span = max(1, (finish - start).days)
    page = doc_pdf.new_page(width=PAGE.width, height=PAGE.height)
    page.insert_text((36, 36), "Schedule", fontsize=14, fontname="hebo", color=INK)
    page.insert_text((36, 52),
                     "Red bars are the longest path. The label is the driving predecessor.",
                     fontsize=9, fontname="helv", color=GREY)
    left, right = 220, PAGE.width - 36
    top = 70
    width = right - left
    # Month ticks.
    d = _dt.date(start.year, start.month, 1)
    while d <= finish:
        x = left + (d - start).days / span * width
        if left <= x <= right:
            page.draw_line((x, top), (x, PAGE.height - 30), color=(0.85, 0.85, 0.85),
                           width=0.4)
            page.insert_text((x + 2, top - 4), d.strftime("%b %Y"), fontsize=7,
                             fontname="helv", color=GREY)
        month = d.month + 1
        year = d.year + (1 if month == 13 else 0)
        d = _dt.date(year, 1 if month == 13 else month, 1)
    y = top + 8
    for a in rows:
        if y > PAGE.height - 28:
            page = doc_pdf.new_page(width=PAGE.width, height=PAGE.height)
            y = 36
        es, ef = as_date(a["es"]), as_date(a["ef"])
        x0 = left + (es - start).days / span * width
        x1 = left + max(1, (ef - start).days + 1) / span * width
        color = RED if a.get("longest_path") else BLUE
        page.insert_text((36, y + 8), (a.get("name") or "")[:28], fontsize=7,
                         fontname="helv", color=INK)
        page.draw_rect(fitz.Rect(x0, y, max(x0 + 3, x1), y + 8),
                       color=color, fill=color)
        y += 12
