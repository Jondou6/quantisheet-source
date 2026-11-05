"""Stage 4: Find searches big sets a few sheets at a time, so the window
keeps answering (it froze for 10 s on the 309-sheet plant set)."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

from app.panels import SearchBar                               # noqa: E402


def _big(pages=80):
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page()
        pg.insert_text((72, 72), f"SHEET {i + 1}", fontsize=14)
        if i % 10 == 3:
            pg.insert_text((72, 120), "VERIFY INVERT AT MH-3", fontsize=11)
    return d


def _pump(app, cond, secs=20):
    end = time.time() + secs
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    return cond()


def test_big_set_is_searched_in_the_background():
    app = QApplication.instance() or QApplication([])
    bar = SearchBar()
    shown = []
    bar.show_hit.connect(lambda p, r, hits: shown.append(p))
    doc = _big()
    bar.open_bar(doc)
    bar.edit.setText("MH-3")
    bar.step(1)
    assert bar.searching()                     # returned straight away
    assert _pump(app, lambda: not bar.searching())
    assert shown and shown[0] == 3             # first match: sheet 4
    assert len(bar.hits) == 8                  # sheets 4, 14, ... 74
    assert bar.count.text() == "1 of 8"
    bar.step(1)
    assert shown[-1] == 13


def test_typing_again_cancels_the_old_search():
    app = QApplication.instance() or QApplication([])
    bar = SearchBar()
    bar.open_bar(_big())
    bar.edit.setText("MH-3")
    bar.step(1)
    bar.edit.setText("SHEET 80")
    assert not bar.searching()
    bar.step(1)
    assert _pump(app, lambda: not bar.searching())
    assert [p for p, _ in bar.hits] == [79]


def test_small_documents_still_search_at_once():
    bar = SearchBar()
    bar.open_bar(_big(10))
    bar.edit.setText("MH-3")
    bar.step(1)
    assert not bar.searching() and len(bar.hits) == 1


def test_nothing_found():
    app = QApplication.instance() or QApplication([])
    bar = SearchBar()
    shown = []
    bar.show_hit.connect(lambda p, r, hits: shown.append(p))
    bar.open_bar(_big())
    bar.edit.setText("NOT ON ANY SHEET")
    bar.step(1)
    assert _pump(app, lambda: not bar.searching())
    assert shown == [-1] and bar.count.text() == "No matches"
