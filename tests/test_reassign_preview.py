"""Reassign (rename an item onto its markups): before anything moves the
person sees how many pieces on how many pages will move - and whether
they join an item that already exists - and can say no. One Undo puts
them back."""
import os

import fitz
from PySide6.QtWidgets import QInputDialog, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, takeoff_items                       # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def _counts(v, group):
    return [it for it in annotate.takeoff_items(v.doc)
            if it["type"] == "count" and it["group"] == group]


def _three_doors(win, monkeypatch):
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked"))))
    t.new_item("Doors", "count")
    for x in (80, 120, 160):
        assert v.commit_click("count", fitz.Point(x, 300))
    t.new_item("Doors HM", "count", activate=False)
    t.refresh()
    return v, t


def test_preview_counts_pieces_pages_and_merge(win, monkeypatch):
    v, t = _three_doors(win, monkeypatch)
    p = takeoff_items.reassign_preview(v.doc, "Doors", "count", "Doors HM")
    assert p["pieces"] == 3 and p["pages"] == [v.page]
    assert p["merge"] is True
    p2 = takeoff_items.reassign_preview(v.doc, "Doors", "count", "Doors WD")
    assert p2["merge"] is False and p2["pieces"] == 3
    assert "3 pieces on 1 page" in takeoff_items.reassign_text(p, "Doors",
                                                               "Doors HM")


def test_rename_asks_with_count_and_no_leaves_it(win, monkeypatch):
    v, t = _three_doors(win, monkeypatch)
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: ("Doors HM", True)))

    def no(parent, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))
    assert t.rename_item("Doors", "count") == 0
    assert asked and "3 pieces on 1 page" in asked[0]
    assert "already" in asked[0]                 # joins an existing item
    assert len(_counts(v, "Doors")) == 3 and not _counts(v, "Doors HM")

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert t.rename_item("Doors", "count") == 1
    assert len(_counts(v, "Doors HM")) == 3 and not _counts(v, "Doors")
    win.undo()                                   # one step puts them back
    assert len(_counts(v, "Doors")) == 3
