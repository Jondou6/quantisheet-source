"""Acrobat-style in-place editing (app/textedit.py) and sharp rendering on
scaled displays."""
import base64
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor                       # noqa: E402

from app import annotate                                     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401

PARA = ("The contractor shall furnish all labor, materials and equipment "
        "required to complete the concrete work shown on the drawings.")


def _png(w=40, h=30, rgb=(200, 30, 30)):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, rgb)
    return pix.tobytes("png")


def _doc(tmp_path, image=True):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 60), "1.1 SUMMARY", fontsize=12, fontname="hebo")
    assert p.insert_textbox(fitz.Rect(72, 80, 400, 160), PARA, fontsize=10,
                            fontname="helv") >= 0
    if image:
        p.insert_image(fitz.Rect(300, 400, 380, 460), stream=_png())
    path = tmp_path / "doc.pdf"
    d.save(str(path))
    return str(path)


def _pt(v, word):
    w = [w for w in v.pg.get_text("words") if w[4] == word][0]
    return annotate.from_page(v.pg, fitz.Rect(w[:4])).tl + (2, 2)


def test_html_replace_block_op():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 100), "Old words here", fontsize=12)
    html = ('<p style="margin:0;text-align:left"><span style="font-size:'
            '12.00pt;font-family:sans-serif;color:#000000">New </span>'
            '<span style="font-size:12.00pt;font-family:sans-serif;'
            'font-weight:bold;color:#cc0000">bold</span></p>')
    ok = annotate.apply_op(d, annotate.new_op(
        "replace_block", 0, rect=[70, 88, 300, 104], text="New bold",
        html=html, size=12, color=[0, 0, 0], font="Helvetica"))
    assert ok
    t = p.get_text()
    assert "Old" not in t and "New" in t and "bold" in t
    spans = [s for b in p.get_text("dict")["blocks"] for ln in b["lines"]
             for s in ln["spans"] if s["text"].strip()]
    bold = [s for s in spans if "bold" in s["text"]][0]
    assert abs(bold["size"] - 12) < 1.0          # css pt == PDF points
    assert bold["color"] == 0xcc0000


def test_inline_edit_paragraph(qapp, win, tmp_path):
    win.open_path(_doc(tmp_path, image=False))
    v = win._view
    v.set_tool("edit_text")
    ctl = v.editctl
    assert ctl.active and any(b["kind"] == "text" for b in ctl.blocks)
    ctl.open(_pt(v, "furnish"))
    assert ctl.editor is not None and ctl.bar is not None
    assert ctl.editor.toPlainText().startswith("The contractor")
    ed = ctl.editor
    ed.setPlainText(ed.toPlainText().replace("concrete work",
                                             "cast-in-place concrete work"))
    # make one word bold from the format bar
    doc = ed.document()
    cur = QTextCursor(doc)
    i = ed.toPlainText().index("furnish")
    cur.setPosition(i)
    cur.setPosition(i + len("furnish"), QTextCursor.KeepAnchor)
    ed.setTextCursor(cur)
    ctl.set_bold(True)
    assert ctl.commit()
    text = " ".join(v.pg.get_text().split())
    assert "cast-in-place concrete work" in text
    assert "1.1 SUMMARY" in text                  # other text untouched
    spans = [s for b in v.pg.get_text("dict")["blocks"]
             for ln in b.get("lines", []) for s in ln["spans"]]
    assert any("furnish" in s["text"] and s["flags"] & 16 for s in spans)
    win.undo()
    assert "cast-in-place" not in v.pg.get_text()
    # Esc / cancel leaves the page alone
    ctl.open(_pt(v, "furnish"))
    ctl.editor.setPlainText("nothing")
    ctl.cancel()
    assert "nothing" not in v.pg.get_text()
    v.set_tool(None)
    assert not ctl.active


def test_add_new_text(qapp, win, tmp_path):
    win.open_path(_doc(tmp_path, image=False))
    v = win._view
    v.set_tool("edit_text")
    ctl = v.editctl
    ctl.open(fitz.Point(80, 300), new=True)
    ctl.editor.setPlainText("Verify in field")
    assert ctl.commit()
    t = v.pg.get_text()
    assert "Verify in field" in t and "1.1 SUMMARY" in t
    # empty new text does nothing
    ctl.open(fitz.Point(80, 500), new=True)
    assert ctl.commit() == 0


def test_move_resize_delete_replace_image(qapp, win, tmp_path):
    win.open_path(_doc(tmp_path))
    v = win._view
    v.set_tool("edit_text")
    ctl = v.editctl
    imgs = [b for b in ctl.blocks if b["kind"] == "image"]
    assert len(imgs) == 1
    ctl.sel_image = imgs[0]
    assert ctl.image_op("move_image", rect=fitz.Rect(100, 500, 220, 590))
    info = v.pg.get_image_info()
    assert len(info) == 1
    bb = fitz.Rect(info[0]["bbox"])
    assert abs(bb.x0 - 100) < 1 and abs(bb.y0 - 500) < 1
    assert abs(bb.width - 120) < 1                 # resized
    assert "1.1 SUMMARY" in v.pg.get_text()
    qapp.processEvents()
    ctl.refresh()
    ctl.sel_image = [b for b in ctl.blocks if b["kind"] == "image"][0]
    data = base64.b64encode(_png(rgb=(20, 20, 200))).decode("ascii")
    assert ctl.image_op("replace_image", data=data)
    assert len(v.pg.get_image_info()) == 1
    ctl.refresh()
    ctl.sel_image = [b for b in ctl.blocks if b["kind"] == "image"][0]
    assert ctl.image_op("delete_image")
    assert v.pg.get_image_info() == []
    win.undo()
    assert len(v.pg.get_image_info()) == 1


def test_renders_at_display_scaling(qapp, win, tmp_path, monkeypatch):
    win.open_path(_doc(tmp_path, image=False))
    v = win._view
    v._render()
    logical = (v.width(), v.height())
    w1 = v.rendered.width()
    monkeypatch.setattr(v, "_dpr", lambda: 1.5)
    v._tiles.clear()
    v._preview = None
    v._render()
    assert (v.width(), v.height()) == logical       # same size on screen
    assert v.rendered.width() >= w1 * 1.45          # 1.5x the pixels
    assert abs(v.rendered.devicePixelRatio() - 1.5) < 1e-6
    v.repaint()                                     # paints without error


def test_done_editing_button_and_esc_leave_edit_mode(win, qapp):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    v = win._view
    win.set_tool("edit_text")
    ctl = v.editctl
    assert ctl.active and ctl.done_btn is not None
    assert not ctl.done_btn.isHidden()
    ctl.done_btn.click()                       # the button
    assert v.tool is None and not ctl.active
    assert ctl.done_btn.isHidden()
    assert win._tool_actions[None].isChecked()
    win.set_tool("edit_text")                  # and Esc
    assert ctl.active
    QApplication.sendEvent(v, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                        Qt.NoModifier))
    assert v.tool is None and not ctl.active
    assert win._tool_actions[None].isChecked()


def test_edit_box_is_white_in_dark_theme(qapp, win, tmp_path):
    """Jon, Oct 28: editing text made a black box - the editor's style
    sheet had a QColor (not CSS) in it, so Qt dropped the whole sheet and
    the dark theme showed through."""
    from app import theme
    theme.apply(qapp, "dark")
    try:
        win.open_path(_doc(tmp_path, image=False))
        v = win._view
        v.set_tool("edit_text")
        ctl = v.editctl
        ctl.open(_pt(v, "furnish"))
        ed = ctl.editor
        assert "QColor" not in ed.styleSheet()
        qapp.processEvents()
        img = ed.grab().toImage()
        light = sum(1 for x in range(0, img.width(), 4)
                    for y in range(0, img.height(), 4)
                    if img.pixelColor(x, y).lightness() > 200)
        tot = len(range(0, img.width(), 4)) * len(range(0, img.height(), 4))
        assert light > tot * 0.6, (light, tot)
        ctl.cancel()
    finally:
        theme.apply(qapp, "light")
