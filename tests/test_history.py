"""Page-level undo for markups, full snapshots for everything else."""
import fitz

from app import annotate
from app.history import History


def _doc(n=3):
    d = fitz.open()
    for i in range(n):
        d.new_page(width=612, height=792).insert_text((72, 100), f"Page {i}")
    return d


def _types(doc, pno):
    return [a.type[1] for a in doc[pno].annots()]


def _mark(h, doc, pno, kind, **payload):
    before = h.begin_pages(doc, [pno])
    assert annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    h.commit_pages(doc, before)


def _reload(doc, pages):
    for p in pages:
        doc.reload_page(doc[p])


def test_markup_undo_redo_in_place():
    d = _doc()
    h = History(lambda: d.tobytes())
    _mark(h, d, 0, "add_rect", rect=[100, 100, 200, 200])
    _mark(h, d, 0, "add_textbox", rect=[100, 300, 300, 340], text="Hello")
    _mark(h, d, 1, "add_cloud", rect=[50, 50, 150, 150])
    assert h.stack[-1][0] == "pages"
    assert _types(d, 0) == ["Square", "FreeText"]

    _reload(d, h.undo(d))                       # cloud on page 2 gone
    assert _types(d, 1) == []
    _reload(d, h.undo(d))                       # text box gone
    assert _types(d, 0) == ["Square"]
    _reload(d, h.redo(d))
    assert _types(d, 0) == ["Square", "FreeText"]
    assert "Hello" in [a.info["content"] for a in d[0].annots()]
    _reload(d, h.redo(d))
    assert _types(d, 1) == ["Square"]
    assert not h.can_redo()


def test_change_and_delete_are_undoable():
    d = _doc()
    h = History(lambda: d.tobytes())
    _mark(h, d, 0, "add_rect", rect=[100, 100, 200, 200], color=[1, 0, 0])
    xref = d[0].first_annot.xref
    _mark(h, d, 0, "set_annot", xref=xref, color=[0, 0, 1])
    assert d[0].first_annot.colors["stroke"] == [0, 0, 1]
    _reload(d, h.undo(d))
    assert d[0].first_annot.colors["stroke"] == [1, 0, 0]
    # appearance stream restored too: page renders red, not blue
    pix = d[0].get_pixmap(dpi=72, clip=fitz.Rect(98, 98, 103, 202))
    reds = [pix.pixel(x, y) for x in range(pix.width)
            for y in range(pix.height)]
    assert any(r > 200 and b < 80 for r, g, b in reds)
    _mark(h, d, 0, "delete_annot", xref=xref)
    assert _types(d, 0) == []
    _reload(d, h.undo(d))
    assert _types(d, 0) == ["Square"]


def test_mixed_with_full_steps_and_saving(tmp_path):
    d = _doc()
    h = History(lambda: d.tobytes())
    _mark(h, d, 0, "add_rect", rect=[100, 100, 200, 200])
    d[1].set_rotation(90)                       # a page operation
    h.snapshot()
    _mark(h, d, 2, "add_ellipse", rect=[100, 100, 200, 200])

    _reload(d, h.undo(d))                       # ellipse (in place)
    assert _types(d, 2) == []
    data = h.undo(d)                            # rotation: rebuilt bytes
    assert isinstance(data, bytes)
    d = fitz.open(stream=data, filetype="pdf")
    assert d[1].rotation == 0
    assert _types(d, 0) == ["Square"]           # earlier markup kept
    _reload(d, h.undo(d))
    assert _types(d, 0) == []
    _reload(d, h.redo(d))
    assert _types(d, 0) == ["Square"]
    d = fitz.open(stream=h.redo(d), filetype="pdf")
    assert d[1].rotation == 90
    _reload(d, h.redo(d))
    assert _types(d, 2) == ["Circle"]
    out = tmp_path / "out.pdf"
    d.save(out, garbage=1, deflate=True)
    again = fitz.open(out)
    assert _types(again, 0) == ["Square"] and _types(again, 2) == ["Circle"]


def test_trim_keeps_recent_steps():
    d = _doc(1)
    h = History(lambda: d.tobytes(), limit=10)
    for i in range(25):
        _mark(h, d, 0, "add_rect", rect=[10 + i, 10, 20 + i, 20])
    assert len(h.stack) <= 11
    assert h.stack[0][0] == "full"
    steps = 0
    while h.can_undo():
        res = h.undo(d)
        if isinstance(res, bytes):
            d = fitz.open(stream=res, filetype="pdf")
        else:
            _reload(d, res)
        steps += 1
    assert steps >= 5
    assert len(_types(d, 0)) == 25 - steps


def test_new_edit_after_undo_drops_redo():
    d = _doc(1)
    h = History(lambda: d.tobytes())
    _mark(h, d, 0, "add_rect", rect=[10, 10, 50, 50])
    _reload(d, h.undo(d))
    _mark(h, d, 0, "add_ellipse", rect=[10, 10, 50, 50])
    assert not h.can_redo()
    assert _types(d, 0) == ["Circle"]
