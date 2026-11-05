"""Nov 1: the count library - symbols kept once, tried on each new plan
set, found copies added as counts in review (out of the totals)."""
import json
import os

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("cv2")

from app import annotate, autocount, count_library, settings, uncounted  # noqa: E402,E501

SPOTS = [(100, 100), (300, 100), (500, 100), (100, 300), (300, 300)]


def _symbol(page, x, y):
    sh = page.new_shape()
    sh.draw_circle(fitz.Point(x, y), 8)
    sh.draw_line(fitz.Point(x - 8, y), fitz.Point(x + 8, y))
    sh.draw_line(fitz.Point(x, y - 8), fitz.Point(x, y + 8))
    sh.draw_rect(fitz.Rect(x + 9, y - 3, x + 13, y + 3))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()


def _doc(spots=SPOTS):
    d = fitz.open()
    pg = d.new_page(width=700, height=450)
    for x, y in spots:
        _symbol(pg, x, y)
    return d


def _box(x, y):
    return fitz.Rect(x - 11, y - 11, x + 15, y + 11)


@pytest.fixture(autouse=True)
def _lib(monkeypatch, tmp_path):
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "home"))
    real_get = settings.get
    monkeypatch.setattr(settings, "get", lambda k, d=None:
                        None if k == "count_library" else real_get(k, d))
    monkeypatch.setattr(count_library, "_picture_on", lambda: True)
    monkeypatch.setattr(uncounted, "_picture_on", lambda: True)
    yield tmp_path


def _all_plan(page, rects):              # no title block / legend in tests
    return rects


def _png():
    d = _doc()
    return autocount.symbol_template(d[0], _box(*SPOTS[0]))


def test_add_list_rename_remove(_lib):
    png = _png()
    assert count_library.add("  Duplex   Outlet ", png) == "Duplex Outlet"
    assert count_library.path().startswith(str(_lib))
    assert not count_library.is_shared()
    es = count_library.entries()
    assert [e["name"] for e in es] == ["Duplex Outlet"]
    assert es[0]["png"] == png and es[0]["added"]
    assert count_library.has("duplex outlet")
    count_library.add("DUPLEX OUTLET", png)            # same name replaces
    assert len(count_library.entries()) == 1
    assert count_library.rename("Duplex Outlet", "Outlet")
    assert count_library.names() == ["Outlet"]
    assert count_library.remove("outlet")
    assert count_library.entries() == []
    with pytest.raises(ValueError):
        count_library.add("", png)


def test_file_is_plain_json_and_bad_file_is_empty(_lib):
    count_library.add("Outlet", _png())
    with open(count_library.path(), encoding="utf-8") as f:
        d = json.load(f)
    assert d["kind"] == "QuantiSheet count library"
    assert "Outlet" in d["entries"]
    with open(count_library.path(), "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert count_library.entries() == []


def test_shared_price_database_shares_the_library(monkeypatch, tmp_path):
    from app import pricedb
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(pricedb, "path", lambda: str(share / "prices.db"))
    monkeypatch.setattr(pricedb, "is_shared", lambda p=None: True)
    assert count_library.path() == str(share / count_library.FILENAME)
    count_library.add("Outlet", _png())
    assert os.path.exists(share / count_library.FILENAME)
    assert count_library.is_shared()


def test_add_from_drawing_needs_a_saved_sample():
    d = _doc()
    with pytest.raises(LookupError):
        count_library.add_from_drawing(d, "Outlet")
    uncounted.save_sample(d, "Outlet", autocount.symbol_template(
        d[0], _box(*SPOTS[0])))
    assert count_library.add_from_drawing(d, "Outlet") == "Outlet"


def test_tried_on_a_new_set_found_as_counts_in_review():
    count_library.add("Outlet", _png())
    new = _doc([(150, 150), (400, 150), (150, 350)])    # another job
    kept, info = count_library.try_on(new, plan_filter=_all_plan)
    assert len(kept["Outlet"]) == 3
    marks = count_library.review_marks(kept, new)
    for i, (p, k, pl) in enumerate(marks):
        assert pl["badge"] and pl["dashes"]
        assert pl["measure"]["method"].endswith(annotate.REVIEW_SUFFIX)
        annotate.apply_op(new, {"kind": k, "page": p, "id": f"m{i}",
                                "payload": pl}, fresh=True)
    its = [it for it in annotate.takeoff_items(new) if it["group"] == "Outlet"]
    assert len(its) == 3 and all(it["pending"] for it in its)
    assert not [it for it in annotate.totals_items(new)
                if it["group"] == "Outlet"]                # not in totals
    # a second try finds nothing new: they're all counted now
    kept2, info2 = count_library.try_on(new, plan_filter=_all_plan)
    assert kept2["Outlet"] == [] and info2["already"] == 3


def test_only_ticked_names_and_pages():
    count_library.add("Outlet", _png())
    count_library.add("Other", _png())
    d = _doc()
    d.new_page(width=700, height=450)
    kept, _ = count_library.try_on(d, pages=[1], names_=["outlet"],
                                   plan_filter=_all_plan)
    assert list(kept) == ["Outlet"] and kept["Outlet"] == []


def test_same_spot_two_entries_counted_once():
    count_library.add("Outlet", _png())
    count_library.add("Receptacle", _png())             # the same picture
    kept, info = count_library.try_on(_doc(), plan_filter=_all_plan)
    assert sum(len(h) for h in kept.values()) == len(SPOTS)
    assert info["dropped"] == len(SPOTS)


def test_title_block_and_legends_left_out():
    count_library.add("Outlet", _png())

    def drop_top_row(page, rects):
        return [r for r in rects if r[1] > 200]
    kept, info = count_library.try_on(_doc(), plan_filter=drop_top_row)
    assert len(kept["Outlet"]) == 2 and info["left_out"] == 3


def test_picture_switch_honoured(monkeypatch):
    count_library.add("Outlet", _png())
    monkeypatch.setattr(count_library, "_picture_on", lambda: False)
    with pytest.raises(RuntimeError):
        count_library.try_on(_doc())


def test_stop():
    count_library.add("Outlet", _png())
    kept, info = count_library.try_on(_doc(), plan_filter=_all_plan,
                                      progress=lambda i, n, name: False)
    assert info["stopped"] and kept == {}


# ---- the window ------------------------------------------------------------
from test_gui import win, qapp  # noqa: E402,F401


def test_window_add_from_a_count_and_find(win, monkeypatch):
    from app import count_library_ui
    v = win._view
    pg = v.doc[v.page]
    clear = [(380, 450), (460, 450), (540, 450), (380, 530), (460, 530)]
    for x, y in clear:                     # where the sample sheet is empty
        _symbol(pg, x, y)
    png = autocount.symbol_template(pg, _box(*clear[0]))
    uncounted.save_sample(v.doc, "Outlet", png)
    assert v.add_to_count_library("Outlet") == "Outlet"
    monkeypatch.setattr(autocount, "_in_plan_area",
                        lambda page, rects: rects)
    dlg = win.try_count_library(show=False)
    assert dlg.chosen() == ["Outlet"]
    dlg.where.setCurrentIndex(0)                         # this page
    n = dlg.run(quiet=True)
    assert n == len(clear)
    assert sum(1 for it in annotate.takeoff_items(v.doc)
               if it["group"] == "Outlet" and it["pending"]) == len(clear)
    assert count_library_ui.TITLE == "Count Library"
