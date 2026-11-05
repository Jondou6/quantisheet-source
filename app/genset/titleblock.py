"""The title block (a 4.5 in strip down the right side of every sheet)
and the review watermark."""
import fitz

from . import CREATOR, DISCLAIMER
from .draw import (GREY, INK, LIGHT, MARGIN, RED, SHEET_H, SHEET_W, TB_W,
                   fit, line, rect, text)


def border(page):
    rect(page, fitz.Rect(MARGIN, MARGIN, SHEET_W - MARGIN, SHEET_H - MARGIN),
         width=1.6)


def watermark(page):
    """Light grey diagonal FOR REVIEW - NOT FOR SEALING across the sheet."""
    c = fitz.Point((SHEET_W - TB_W) / 2, SHEET_H / 2 + 40)
    text(page, c.x, c.y, DISCLAIMER, 120, bold=True, color=(0.92, 0.92,
                                                            0.93),
         align="center", rotate=-30)


def titleblock(page, plan, sheet_no, title, scale_label):
    x0 = SHEET_W - MARGIN - TB_W
    x1 = SHEET_W - MARGIN
    y = MARGIN
    line(page, fitz.Point(x0, MARGIN), fitz.Point(x0, SHEET_H - MARGIN),
         width=1.6)
    pj = plan["project"]
    pad = 16

    def field(label, value, h=54, size=13, bold=False, color=INK):
        nonlocal y
        text(page, x0 + pad, y + 18, label.upper(), 7, color=GREY)
        v, sz = fit(value, size, bold, x1 - x0 - 2 * pad)
        text(page, x0 + pad, y + 18 + size + 6, v, sz, bold=bold,
             color=color)
        y += h
        line(page, fitz.Point(x0, y), fitz.Point(x1, y), color=GREY,
             width=0.4)

    # firm
    firm, fsz = fit(pj.get("firm") or "[FIRM NAME]", 16, True,
                    x1 - x0 - 2 * pad)
    text(page, x0 + pad, y + 34, firm, fsz, bold=True)
    text(page, x0 + pad, y + 54, "[FIRM ADDRESS]", 10, color=GREY)
    y += 76
    line(page, fitz.Point(x0, y), fitz.Point(x1, y), width=0.8)
    field("Project", pj.get("name") or "Untitled Project", size=14,
          bold=True)
    field("Address", pj.get("address") or "ADDRESS TBD")
    y_sheet_area = SHEET_H - MARGIN - 420
    # sheet title and number at the bottom of the strip
    y = y_sheet_area
    line(page, fitz.Point(x0, y), fitz.Point(x1, y), width=0.8)
    field("Sheet title", title.upper(), h=64, size=14, bold=True)
    field("Scale", scale_label or "AS NOTED", h=46, size=11)
    field("Date", pj.get("date") or "", h=46, size=11)
    field("Drawn", CREATOR, h=46, size=10)
    # revision box (empty)
    text(page, x0 + pad, y + 16, "REVISIONS", 7, color=GREY)
    for i in range(3):
        line(page, fitz.Point(x0 + pad, y + 32 + i * 14),
             fitz.Point(x1 - pad, y + 32 + i * 14), color=LIGHT, width=0.4)
    y += 78
    line(page, fitz.Point(x0, y), fitz.Point(x1, y), color=GREY, width=0.4)
    text(page, x0 + pad, y + 24, DISCLAIMER, 14, bold=True, color=RED)
    y += 36
    line(page, fitz.Point(x0, y), fitz.Point(x1, y), width=0.8)
    text(page, x0 + pad, y + 14, "SHEET", 7, color=GREY)
    text(page, (x0 + x1) / 2, y + 62, sheet_no, 40, bold=True,
         align="center")


def start_sheet(doc, plan, sheet_no, title, scale_label):
    """A new ARCH D page with border, watermark and title block."""
    from .draw import ensure_fonts
    page = doc.new_page(width=SHEET_W, height=SHEET_H)
    ensure_fonts(page)
    watermark(page)
    border(page)
    titleblock(page, plan, sheet_no, title, scale_label)
    return page
