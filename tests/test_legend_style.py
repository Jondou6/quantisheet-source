"""Takeoff-style legend and PlanSwift-style count markers
(LEGEND_MATCH_BRIEF items 1-11)."""
import fitz

from app import annotate, legend

PPU = 0.781            # points per foot, as on the CD001 reference sheet
FIRE = "Existing Portable Fire Line To Be Removed"
TREE = "Existing Tree To Be Removed"


def _ft(n):
    return n * PPU


def _demo():
    d = fitz.open()
    d.new_page(width=842, height=595)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft"))
    for pts, ft in (([[100, 100], [100 + _ft(250), 100]], 250.0),
                    ([[100, 140], [100 + _ft(158.25), 140]], 158.25)):
        annotate.apply_op(d, annotate.new_op(
            "add_polyline", 0, pts=pts, color=[0, 0.5, 0.5],
            measure={"type": "length", "value": ft, "unit": "ft",
                     "group": FIRE}))
    for name, sf, x, col in (("Pump House", 36.6, 400, [1, 0, 0]),
                             ("Canopy", 542.2, 500, [0, 0.6, 0])):
        s = _ft(sf ** 0.5)
        annotate.apply_op(d, annotate.new_op(
            "add_polygon", 0, pts=[[x, 300], [x + s, 300], [x + s, 300 + s],
                                   [x, 300 + s]], color=col,
            measure={"type": "area", "value": sf, "unit": "sq ft",
                     "group": name}))
    for i in range(9):
        annotate.apply_op(d, annotate.new_op(
            "add_count", 0, pt=[150 + 25 * i, 450], n=i + 1, color=[1, 1, 0],
            measure={"type": "count", "value": 1, "unit": "ea",
                     "group": TREE}))
    return d


def _legend(d, style):
    rows = legend.rows(d, 0)
    p = {"rect": [40, 40, 200, 60], "title": "Legend", "rows": rows}
    if style:
        p["style"] = style
    assert annotate.apply_op(d, annotate.new_op("add_legend", 0, **p))
    return rows


_KEEP = []          # PyMuPDF: an annot must not outlive its page object


def _parts(d):
    page = d[0]
    _KEEP[:] = [page]
    frame = [a for a in page.annots() if annotate.is_legend(d, a)]
    assert len(frame) == 1
    tag = annotate.tag_of(frame[0])
    parts = [a for a in page.annots() if annotate.tag_of(a) == tag and
             a.xref != frame[0].xref]
    return frame[0], parts


def test_rows_have_raw_fields_and_count_color():
    rows = {r["name"]: r for r in legend.rows(_demo(), 0)}
    t = rows[TREE]
    assert t["type"] == "count" and t["n"] == 9 and t["total"] == 9.0
    assert t["color"] == [1, 1, 0]                 # not the cream box fill
    assert rows[FIRE]["type"] == "length" and rows[FIRE]["n"] == 2
    assert abs(rows[FIRE]["total"] - 408.25) < 0.01
    assert rows["Canopy"]["unit"] == "sq ft"


def test_format_qty_and_label():
    f = legend.format_qty
    assert f({"type": "length", "total": 408.25, "unit": "ft"},
             "takeoff") == "408.3 FT"
    assert f({"type": "area", "total": 36.6, "unit": "sq ft"},
             "takeoff") == "36.6 SQ FT"
    assert f({"type": "count", "total": 9, "n": 9}, "takeoff") == "9.0"
    assert f({"type": "length", "qty": "2  |  396.14 ft"},
             "classic") == "2  |  396.14 ft"
    assert f({"type": "other", "n": 3, "total": None}, "takeoff") == "3"
    row = {"name": TREE, "label": TREE + " (Count)", "kind": "Count"}
    assert legend.format_label(row, "takeoff") == TREE
    assert legend.format_label(row, "classic") == TREE + " (Count)"


def test_takeoff_rows_in_order():
    rows = legend.rows(_demo(), 0)
    got = [(legend.format_label(r, "takeoff"), legend.format_qty(r, "takeoff"))
           for r in rows]
    assert got[0] == (FIRE, "408.3 FT")
    assert got[1][0] == "Pump House" and got[1][1].endswith("SQ FT")
    assert got[2][0] == "Canopy" and got[2][1].endswith("SQ FT")
    assert got[3] == (TREE, "9.0")


def test_takeoff_layout_fonts_and_box():
    d = _demo()
    _legend(d, "takeoff")
    frame, parts = _parts(d)
    assert d.xref_get_key(frame.xref, "PSLegendStyle") == ("string",
                                                           "takeoff")
    assert 44 <= frame.rect.height <= 52
    assert frame.border["width"] == 0.5
    assert abs(frame.opacity - 0.9) < 0.01
    texts = [a for a in parts if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
    assert not [a for a in texts if a.info.get("content") == "Legend"]
    r = fitz.Rect(frame.rect)
    for a in parts:
        assert r.contains(fitz.Rect(a.rect)), a.rect
    qty = [a for a in texts if a.info["content"] == "408.3 FT"][0]
    da = d.xref_get_key(qty.xref, "DA")[1]
    assert "0 0 1 rg" in da                  # blue (FreeText has no bold)
    lab = [a for a in texts if a.info["content"] == FIRE][0]
    assert " 9.0 Tf" in d.xref_get_key(lab.xref, "DA")[1]
    # the swatch sits to the right of the quantity
    sw = [a for a in parts if a.type[0] == fitz.PDF_ANNOT_CIRCLE and
          tuple((a.colors.get("fill") or ())[:3]) == (1.0, 1.0, 0.0) and
          a.opacity and abs(a.opacity - 0.6) < 0.01]
    assert sw and sw[0].rect.x0 > qty.rect.x0
    sq = [a for a in parts if a.type[0] == fitz.PDF_ANNOT_SQUARE and
          tuple(a.colors.get("stroke") or ()) == (0.0, 0.0, 0.0) and
          a.opacity and abs(a.opacity - 0.6) < 0.01]
    assert len(sq) == 3                       # fire line, pump house, canopy


def test_labels_stay_on_one_line_both_styles():
    for style in ("takeoff", None):
        d = _demo()
        _legend(d, style)
        frame, parts = _parts(d)
        names = {FIRE, TREE, "Canopy", "Pump House"}
        for a in parts:
            if a.type[0] != fitz.PDF_ANNOT_FREE_TEXT:
                continue
            c = a.info.get("content", "")
            if any(c.startswith(n) for n in names):
                lines = [x for x in a.get_text().splitlines() if x.strip()]
                assert len(lines) == 1, (style, c, lines)
            assert fitz.Rect(frame.rect).contains(fitz.Rect(a.rect))


def test_no_style_key_draws_classic():
    d = _demo()
    _legend(d, None)
    frame, parts = _parts(d)
    assert d.xref_get_key(frame.xref, "PSLegendStyle")[0] == "null"
    assert [a for a in parts if a.info.get("content") == "Legend"]


def test_refresh_keeps_style():
    d = _demo()
    _legend(d, "takeoff")
    marks = legend.refresh_marks(d, 0)
    assert marks[1][2]["style"] == "takeoff"
    for pno, kind, p in marks:
        annotate.apply_op(d, annotate.new_op(kind, pno, **p))
    frame, _ = _parts(d)
    assert d.xref_get_key(frame.xref, "PSLegendStyle") == ("string",
                                                           "takeoff")


def test_count_marker_is_dot_with_black_number():
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, annotate.new_op(
        "add_count", 0, pt=[100, 100], n=4, color=[1, 1, 0],
        measure={"type": "count", "value": 1, "unit": "ea", "group": "T"}))
    page = d[0]
    num = [a for a in page.annots() if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT]
    dot = [a for a in page.annots() if a.type[0] == fitz.PDF_ANNOT_CIRCLE]
    assert len(num) == 1 and len(dot) == 1
    assert annotate.markup_color(d, num[0]) == [1, 1, 0]
    assert "0 0 0 rg" in d.xref_get_key(num[0].xref, "DA")[1]
    assert tuple(dot[0].colors["fill"][:3]) == (1.0, 1.0, 0.0)
    items = [m for m in annotate.markup_items(d)]
    assert len(items) == 1
