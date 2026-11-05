"""Spec book sections: find, bookmark, split."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import specs                                        # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401

BOOK = [("SECTION 03 30 00", "CAST-IN-PLACE CONCRETE", 3),
        ("SECTION 033500 - CONCRETE FINISHING", None, 2),
        ("SECTION 09 91 23", "INTERIOR PAINTING", 2),
        ("Section 26 05 19 - Low-Voltage Conductors", None, 1)]


def _book():
    d = fitz.open()
    cover = d.new_page()
    cover.insert_text((72, 300), "PROJECT MANUAL", fontsize=24)
    for head, title, n in BOOK:
        for k in range(n):
            p = d.new_page()
            if k == 0:
                p.insert_text((72, 72), head, fontsize=12)
                if title:
                    p.insert_text((72, 90), title, fontsize=12)
            else:
                p.insert_text((72, 72), "PART 2 - PRODUCTS", fontsize=10)
            p.insert_text((72, 500), "2.1 MATERIALS: lorem ipsum",
                          fontsize=9)
    return d


def test_find_bookmark_split(tmp_path):
    d = _book()
    s = specs.find_sections(d)
    assert [x["number"] for x in s] == ["03 30 00", "03 35 00", "09 91 23",
                                        "26 05 19"]
    assert s[0]["title"] == "Cast-In-Place Concrete"
    assert s[1]["title"] == "Concrete Finishing"
    assert (s[0]["start"], s[0]["end"]) == (1, 3)
    assert s[-1]["end"] == d.page_count - 1
    n = specs.bookmark(d, s)
    toc = d.get_toc()
    assert n == len(toc) == 7                     # 3 divisions + 4 sections
    assert toc[0][1].startswith("Division 03")
    paths = specs.split(d, s, str(tmp_path / "out"))
    assert len(paths) == 4 and fitz.open(paths[0]).page_count == 3


def test_spec_window(qapp, win, tmp_path):
    p = tmp_path / "manual.pdf"
    _book().save(str(p))
    win.open_path(str(p))
    dlg = win.spec_sections(show=False)
    assert dlg.table.rowCount() == 4
    dlg.add_bookmarks()
    assert len(win._view.doc.get_toc()) == 7
    assert len(dlg.split(str(tmp_path / "secs"))) == 4
