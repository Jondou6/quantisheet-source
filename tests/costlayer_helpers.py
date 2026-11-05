import fitz
from app import annotate


def wall(doc, page, ft, x=10, group="Interior Wall"):
    annotate.apply_op(doc, annotate.new_op(
        "add_polyline", page, pts=[[x, 10], [x + 100, 10]],
        measure={"type": "length", "value": float(ft), "unit": "ft",
                 "group": group}))


def door(doc, page, x, y=50, group="Door"):
    annotate.apply_op(doc, annotate.new_op(
        "add_count", page, pt=[x, y], n=1, color=[1, 0, 0],
        measure={"type": "count", "value": 1, "unit": "ea", "group": group}))


def blank(pages=1):
    d = fitz.open()
    for _ in range(pages):
        d.new_page()
    return d


LIB_ROWS = [
    # code, desc, unit, trade, activity, resource, type, component, qty/unit, cunit, rate
    ["00100", "Interior wall 2x4 / GWB", "LF", "Framing", "00100.01", "LAB01", "L",
     "Carpenter", "0.25", "HR", "60.00"],
    ["00100", "Interior wall 2x4 / GWB", "LF", "Framing", "00100.01", "MAT01", "M",
     "Studs and plates", "1.5", "EA", "4.00"],
    ["00100", "Interior wall 2x4 / GWB", "LF", "Framing", "00100.02", "EQ001", "E",
     "Lift rental", "0.02", "DAY", "150.00"],
    ["00200", "Hollow metal door", "EA", "Doors", "00200.01", "LAB02", "L",
     "Installer", "2", "HR", "55.00"],
    ["00200", "Hollow metal door", "EA", "Doors", "00200.01", "MAT02", "M",
     "Door + frame", "1", "EA", "450.00"],
]
