"""Organize Pages: reorder, rotate, duplicate, delete as one step."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                     # noqa: E402
from app.organize import OrganizeDialog, apply_plan          # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def _doc(path, n=4):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"PAGE {i + 1}", fontsize=20)
    d.save(path)
    return path


def _texts(doc):
    return [doc[i].get_text().strip() for i in range(doc.page_count)]


def test_apply_plan(tmp_path):
    d = fitz.open(_doc(str(tmp_path / "a.pdf")))
    apply_plan(d, [(2, 0), (0, 90), (0, 0), (3, 0)])
    assert _texts(d) == ["PAGE 3", "PAGE 1", "PAGE 1", "PAGE 4"]
    assert d[1].rotation == 90 and d[2].rotation == 0


def test_organize_dialog(qapp, win, tmp_path):
    path = _doc(str(tmp_path / "org.pdf"))
    win.open_path(path)
    v = win._view
    annotate.apply_op(v.doc, annotate.new_op("set_scale", 3, ppu=18,
                                             unit="ft", name="1/4"))
    dlg = OrganizeDialog(v.doc, win)
    qapp.processEvents()
    assert dlg.list.count() == 4
    dlg.move(3, 0)                                    # page 4 first
    dlg.list.item(1).setSelected(True)                # old page 1
    dlg.rotate(90)
    dlg.duplicate()
    dlg.list.clearSelection()
    dlg.list.item(4).setSelected(True)                # old page 3
    dlg.delete()
    assert [s for s, _r in dlg.plan()] == [3, 0, 0, 1]
    assert win.organize_pages(dialog=dlg) == 4
    assert _texts(v.doc) == ["PAGE 4", "PAGE 1", "PAGE 1", "PAGE 2"]
    assert v.doc[1].rotation == 90
    assert annotate.read_scales(v.doc).get(0)          # scale moved along
    win.undo()
    assert _texts(v.doc) == ["PAGE 1", "PAGE 2", "PAGE 3", "PAGE 4"]
    dlg.close()
