"""Made-up data shared by the estimate line / cost book picker / export /
quick $/SF tests."""
import fitz

from app import annotate, costbook

PPU = 10.0                       # 10 pt per ft (calibrate 100 pt = 10 ft)


def blank_doc():
    d = fitz.open()
    d.new_page(width=1224, height=792)
    return d


def area(doc, group, w_ft, h_ft, page=0, x0=40.0, y0=40.0):
    """A w x h ft area markup in `group` (value w*h sq ft)."""
    w, h = w_ft * PPU, h_ft * PPU
    annotate.apply_op(doc, annotate.new_op(
        "add_polygon", page,
        pts=[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]],
        measure={"type": "area", "value": float(w_ft * h_ft),
                 "unit": "sq ft", "group": group}))


def markup_count(doc):
    return sum(len(list(doc[i].annots())) for i in range(doc.page_count))


def make_book():
    """'Test Book': 3 made-up items in divisions 01, 03 and 09."""
    return costbook.Book({
        "name": "Test Book", "effective": "2026-01-01", "escalation": 0.0,
        "items": {
            "03 31 13.35": {"desc": "Test slab", "unit": "sf",
                            "material": 2.10},
            "09 29 10.30": {"desc": "Test gyp board", "unit": "sf",
                            "material": 0.55},
            "01 54 33.10": {"desc": "Test scaffold", "unit": "mo",
                            "material": 300.0}}})
