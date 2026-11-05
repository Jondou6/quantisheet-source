"""Edit Text on a paragraph: rewrapped to its box, other text untouched."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401

PARA = ("The contractor shall furnish all labor, materials and equipment "
        "required to complete the concrete work shown on the drawings and "
        "specified herein, including formwork and reinforcement.")


def test_edit_a_paragraph(qapp, win, tmp_path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 60), "1.1 SUMMARY", fontsize=12, fontname="hebo")
    box = fitz.Rect(72, 80, 400, 200)
    assert p.insert_textbox(box, PARA, fontsize=10, fontname="tiro") >= 0
    p.draw_rect(fitz.Rect(60, 70, 420, 210), color=(0, 0, 1))  # a frame
    path = tmp_path / "spec.pdf"
    d.save(str(path))
    win.open_path(str(path))
    v = win._view
    pg = v.pg
    words = [w for w in pg.get_text("words") if w[4] == "furnish"]
    pt = annotate.from_page(pg, fitz.Rect(words[0][:4])).tl + (2, 2)
    blk = v.block_at(pt)
    assert blk["lines"] >= 3 and blk["text"].startswith("The contractor")
    assert "tiro" in fitz.Font("tiro").name.lower() or blk["font"]
    new = PARA.replace("concrete work", "cast-in-place concrete and "
                       "precast concrete work")
    assert v.edit_text_at(pt, new)
    text = " ".join(v.pg.get_text().split())
    assert "cast-in-place concrete and precast concrete work" in text
    assert "1.1 SUMMARY" in text                     # heading untouched
    assert len(v.pg.get_drawings()) >= 1             # the frame stays
    win.undo()
    assert "precast" not in v.pg.get_text()
    # a one-line label still edits as before
    lab = [w for w in v.pg.get_text("words") if w[4] == "SUMMARY"][0]
    pt2 = annotate.from_page(v.pg, fitz.Rect(lab[:4])).tl + (2, 2)
    assert v.edit_text_at(pt2, "1.1 GENERAL")
    assert "1.1 GENERAL" in v.pg.get_text()
