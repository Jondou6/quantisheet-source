"""Takeoff items, PlanSwift-style: make an item in the Takeoff panel, click
it, and every click on the drawing adds to it - no "What are you
counting?" dialog. Items live in the PDF, even with no markups."""
import os

import fitz
import pytest
from PySide6.QtWidgets import QInputDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, takeoff_items                       # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401

GREEN = (0.1, 0.62, 0.25)


def _no_dialog(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("asked what you're counting")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(boom))


def _counts(v, group):
    return [it for it in annotate.takeoff_items(v.doc)
            if it["type"] == "count" and it["group"] == group]


def _colors(v, group):
    """Colors of the item's takeoff markups on this page."""
    out = []
    for a in annotate.iter_annots(v.pg):
        subj = (a.info or {}).get("subject", "")
        if subj.startswith(annotate.TAKEOFF + ":") and \
                subj.split(":")[4] == group:
            out.append(tuple(round(x, 2)
                             for x in annotate.markup_color(v.doc, a)))
    return out


def _row(t, name):
    for i in range(t.items.topLevelItemCount()):
        if t.items.topLevelItem(i).text(0) == name:
            return t.items.topLevelItem(i)
    return None


def test_click_item_then_count_without_dialog(win, monkeypatch):
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    it = t.new_item("Outlets", "count", color=GREEN)
    assert it is not None and it["total"] == 0
    assert _row(t, "Outlets").text(1) == "0 ea"
    # making it starts taking it off: the count tool, its name and color
    assert v.tool == "count" and v.count_group == "Outlets"
    assert t.active == ("Outlets", "count")
    assert "Taking off: Outlets (count)" in win.statusBar().currentMessage()
    _no_dialog(monkeypatch)
    assert v.commit_click("count", fitz.Point(80, 300))
    assert v.commit_click("count", fitz.Point(120, 300))
    assert len(_counts(v, "Outlets")) == 2
    assert set(_colors(v, "Outlets")) == {tuple(round(x, 2) for x in GREEN)}
    # the panel catches up after the marks (page_changed -> panel timer)
    assert win._panel_timer.isActive()
    win._refresh_panels()
    assert _row(t, "Outlets").text(1) == "2 ea"
    assert t.item("Outlets", "count")["n"] == 2
    # clicking the item in the list again: still no dialog
    win.set_tool(None)
    assert t.active is None and getattr(v, "takeoff_item", None) is None
    t._item_clicked(_row(t, "Outlets"))
    assert v.tool == "count" and t.active == ("Outlets", "count")
    # picking another tool ends it
    win.set_tool("add_rect")
    assert t.active is None


def test_length_item_needs_scale_then_measures(win, monkeypatch):
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    _no_dialog(monkeypatch)
    t.new_item("Wall Type A", "length", color=GREEN)
    assert v.tool == "calibrate" and t.active is None    # no scale yet
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    t._item_clicked(_row(t, "Wall Type A"))
    assert v.tool == "measure_polylength"
    assert v.style["subject"] == "Wall Type A"
    assert v.commit_points("measure_polylength",
                           [fitz.Point(60, 400), fitz.Point(300, 400)])
    t.refresh()
    assert t.item("Wall Type A", "length")["total"] == pytest.approx(24)


def test_items_persist_recolor_and_delete(win, monkeypatch):
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    t.new_item("Doors", "count", activate=False)
    t.new_item("Carpet", "area", activate=False)
    assert win.save_file()
    d = fitz.open(win._path)
    try:                                  # there with no markups at all
        assert not any(list(p.annots()) for p in d)
        names = {(i["name"], i["type"]) for i in takeoff_items.items(d)}
        assert {("Doors", "count"), ("Carpet", "area")} <= names
    finally:
        d.close()
    # colors are told apart: Carpet got the next unused one
    assert t.item("Doors", "count")["color"] != \
        t.item("Carpet", "area")["color"]
    # recolor its markups
    t._item_clicked(_row(t, "Doors"))
    _no_dialog(monkeypatch)
    v.commit_click("count", fitz.Point(80, 300))
    v.commit_click("count", fitz.Point(120, 300))
    assert t.recolor_item("Doors", "count", (0.0, 0.0, 1.0))
    assert set(_colors(v, "Doors")) == {(0.0, 0.0, 1.0)}
    assert t.item("Doors", "count")["color"] == (0.0, 0.0, 1.0)
    assert v.color == [0.0, 0.0, 1.0]           # new clicks match
    # rename goes onto the markups
    assert t.rename_item("Doors", "count", "Doors HM")
    assert len(_counts(v, "Doors HM")) == 2 and not _counts(v, "Doors")
    assert v.count_group == "Doors HM"          # still taking it off
    # delete asks (answered Yes), removes the markups; undo brings them back
    assert t.delete_item("Doors HM", "count")
    assert not _counts(v, "Doors HM")
    assert t.item("Doors HM", "count") is None
    win.undo()
    assert len(_counts(v, "Doors HM")) == 2
    t.refresh()
    assert t.item("Doors HM", "count")["n"] == 2


def test_count_menu_dialog_prefilled_from_item(win, monkeypatch):
    v = win._view
    t = win.takeoff_tree
    t.set_doc(v.doc)
    t.new_item("Switches", "count", color=GREEN)
    seen = {}

    def ask(*a, **k):
        seen["text"] = k.get("text")
        return ("Switches", True)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(ask))
    win.set_tool("count")                       # the menu way still asks
    assert seen["text"] == "Switches"
    assert t.active == ("Switches", "count")    # same name: still on it
