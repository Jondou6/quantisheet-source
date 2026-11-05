"""Nov 1: Count by Label shows its hits before counting, with wildcards
for tag families (P-# -> P-1 ... P-12)."""
import pytest

fitz = pytest.importorskip("fitz")

from app import annotate, autocount, label_search as ls  # noqa: E402

WORDS = [("P-1", 60, 100), ("P-2", 140, 100), ("P-10", 220, 100),
         ("P-1A", 300, 100), ("PANEL", 380, 100), ("D1", 60, 200),
         ("D10", 140, 200), ("DA", 220, 200), ("WH-2", 300, 200),
         ("WH-2B", 380, 200), ("P-2", 460, 400)]


def _doc():
    d = fitz.open()
    pg = d.new_page(width=612, height=500)
    for t, x, y in WORDS:
        pg.insert_text((x, y), t, fontsize=9)
    return d


@pytest.fixture(autouse=True)
def _all_on_plan(monkeypatch):
    monkeypatch.setattr(autocount, "_in_plan_area", lambda page, rects: rects)


def _texts(hits):
    return sorted(h["text"] for h in hits)


def test_number_wildcard():
    assert _texts(ls.search(_doc(), "P-#")) == ["P-1", "P-10", "P-2", "P-2"]


def test_any_letters_and_one_letter():
    assert _texts(ls.search(_doc(), "WH-*")) == ["WH-2", "WH-2B"]
    assert _texts(ls.search(_doc(), "D?")) == ["D1", "DA"]


def test_no_wildcard_is_whole_word_as_before():
    assert _texts(ls.search(_doc(), "D1")) == ["D1"]
    assert _texts(ls.search(_doc(), "p-2")) == ["P-2", "P-2"]


def test_grouped_in_tag_order():
    g = ls.by_text(ls.search(_doc(), "P-#"))
    assert list(g) == ["P-1", "P-2", "P-10"]
    assert len(g["P-2"]) == 2


def test_schedule_and_legend_hits_listed_not_dropped(monkeypatch):
    monkeypatch.setattr(autocount, "_in_plan_area",
                        lambda page, rects: [r for r in rects if r[1] < 300])
    hits = ls.search(_doc(), "P-2")
    assert len(hits) == 2
    assert sorted(h["in_plan"] for h in hits) == [False, True]
    every = ls.search(_doc(), "P-2", plan_area_only=False)
    assert all(h["in_plan"] for h in every)


def test_count_per_tag_or_as_one_item():
    d = _doc()
    g = ls.by_text(ls.search(d, "P-#"))
    marks = ls.count_marks(g, d)
    assert sorted({m[2]["measure"]["group"] for m in marks}) == \
        ["P-1", "P-10", "P-2"]
    d2 = _doc()
    g2 = ls.by_text(ls.search(d2, "P-#"))
    marks2 = ls.count_marks(g2, d2, one_item="Plumbing fixture")
    assert {m[2]["measure"]["group"] for m in marks2} == {"Plumbing fixture"}
    assert sorted(m[2]["n"] for m in marks2) == [1, 2, 3, 4]   # numbered once
    for i, (p, k, pl) in enumerate(marks2):
        annotate.apply_op(d2, {"kind": k, "page": p, "id": f"x{i}",
                               "payload": pl}, fresh=True)
    its = [it for it in annotate.totals_items(d2)
           if it["group"] == "Plumbing fixture"]
    assert len(its) == 4                                     # counted


def test_empty_or_punctuation_only():
    assert ls.search(_doc(), "") == []
    assert ls.search(_doc(), " - ") == []


# ---- the window ------------------------------------------------------------
from test_gui import win, qapp  # noqa: E402,F401


def test_window_untick_then_count(win):
    from PySide6.QtCore import Qt
    dlg = win.auto_count_label(show=False, text="EXIT")
    n = dlg.find(quiet=True)
    assert n >= 3
    top = dlg.tree.topLevelItem(0)
    top.child(0).setCheckState(0, Qt.Unchecked)            # a wrong one
    ticked = sum(len(v) for v in dlg.ticked().values())
    assert ticked == n - 1
    assert dlg.count() == ticked
    assert sum(1 for i in annotate.takeoff_items(win._view.doc)
               if i["group"] == "EXIT") == ticked
