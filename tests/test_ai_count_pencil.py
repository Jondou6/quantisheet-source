"""AI count dots look different from hand counts until a person accepts
them (lines and outlines already go dashed): the dot gets a dashed ring;
Check Takeoff's accept takes the ring off. A second AI run doesn't count
the same device twice. Found on the real JCCH set (95 AI device counts)."""
import fitz

from app import aitakeoff as ait, annotate


def _count(dashes=None, pt=(100.0, 100.0), group="DUPLEX RECEPTACLE"):
    p = {"pt": list(pt), "n": 1, "color": [1, 0, 0],
         "measure": {"type": "count", "value": 1, "unit": "ea",
                     "group": group, "method": "AI takeoff: devices",
                     "confidence": 0.89}}
    if dashes is not None:
        p["dashes"] = dashes
    return (0, "add_count", p)


class _D:
    def __init__(self, a):
        self.border = dict(a.border or {})
        self.tag = annotate.tag_of(a)


def _dot(page):
    return [_D(a) for a in page.annots()
            if a.type[0] == fitz.PDF_ANNOT_CIRCLE]


def _apply(doc, m):
    op = annotate.new_op(m[1], m[0], **m[2])
    annotate.apply_op(doc, op)
    return op


def test_pencil_marks_counts_too():
    marks = [_count()]
    (p, kind, pl), = __import__("app.aitakeoff_ui", fromlist=["x"])._pencil(
        marks)
    assert pl.get("dashes")


def test_ai_count_dot_has_dashed_ring_until_accepted():
    doc = fitz.open()
    doc.new_page()
    op = _apply(doc, _count(dashes=[6, 4]))
    (dot,) = _dot(doc[0])
    b = dot.border or {}
    assert b.get("width", 0) > 0 and list(b.get("dashes") or [])
    # a hand count (no dashes) stays a plain dot
    doc2 = fitz.open()
    doc2.new_page()
    _apply(doc2, _count())
    (plain,) = _dot(doc2[0])
    assert not (plain.border or {}).get("width")
    # accept (by the count's tag, or by the number's xref): plain dot
    annotate.apply_op(doc, annotate.new_op("set_annot", 0, target=op["id"],
                                           status="Accepted", dashes=[]))
    (dot,) = _dot(doc[0])
    assert not (dot.border or {}).get("width")
    op2 = _apply(doc, _count(dashes=[6, 4], pt=(200.0, 100.0)))
    pg = doc[0]
    xref = [a.xref for a in pg.annots() if a.type[0] ==
            fitz.PDF_ANNOT_FREE_TEXT and annotate.tag_of(a) == op2["id"]][0]
    del pg
    annotate.apply_op(doc, annotate.new_op("set_annot", 0, xref=xref,
                                           status="Accepted", dashes=[]))
    rings = [d for d in _dot(doc[0]) if d.tag == op2["id"]]
    assert rings and not (rings[0].border or {}).get("width")


def test_second_run_skips_counts_already_there():
    doc = fitz.open()
    doc.new_page()
    first = [_count(dashes=[6, 4]), _count(dashes=[6, 4], pt=(150, 100))]
    for m in first:
        _apply(doc, m)
    again = first + [_count(pt=(300, 100)),
                     _count(pt=(100, 100), group="GFI RECEPTACLE")]
    kept, dropped = ait.skip_repeats(doc, again)
    assert dropped == 2 and len(kept) == 2
