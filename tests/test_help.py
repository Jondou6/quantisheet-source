"""Help menu: Help Center tutorials, practice drawings, About and terms."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog                        # noqa: E402

from app import annotate, autowalls, batchlink, helpcenter, legal, \
    practice, tradetakeoff as tt                             # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def test_practice_set(tmp_path):
    p = practice.make(str(tmp_path / "practice.pdf"))
    d = fitz.open(p)
    assert d.page_count == 4
    sc = annotate.read_scales(d)
    assert all(sc.get(i) for i in (0, 1, 2))
    sm = autowalls.summary(autowalls.walls(d[0], 18, "ft"),
                           autowalls.doors(d[0], 18, "ft"))
    assert {"Wall 8in", "Wall 5in"} <= set(sm["walls"])
    assert sum(sm["doors"].values()) == 3
    names = {g["name"] for g in tt.mep_runs(d[1], 18, "ft") if g["labelled"]}
    assert {'2" CW', '1" HW', '4" SAN'} <= names
    counts = {c["name"]: len(c["hits"]) for c in tt.legend_counts(d)}
    assert counts == {"DUPLEX RECEPTACLE": 8, "JUNCTION BOX": 3}
    assert batchlink.find_refs(d)                      # A-101 <-> A-501


def test_help_menu_and_center(qapp, win, monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    for t in helpcenter.T:                         # every Show Me works
        for name in t["try"]:
            assert win.command(name) is not None, (t["id"], name)
    assert win.command("Help Center & Tutorials").shortcut().toString() \
        == "F1"
    assert "Help" in win.ribbon.pages
    assert win.ribbon.help_button.menu() is win._help_menu
    dlg = win.help_center("scale")
    assert dlg.current["id"] == "scale"
    dlg.filter("overlay")
    assert not dlg.items["compare"].isHidden()
    assert dlg.items["schedule"].isHidden()
    dlg.filter("")
    dlg.step(1)
    assert dlg.current["id"] == "measure"
    dlg.open_tutorial("trades")
    ran = dlg.show_me()
    assert ran and win._view is not None and win._view.page == 1
    assert "Practice Drawings" in (win._view._path or "")
    dlg.show_shortcuts()
    assert "Ctrl+K" in dlg.body.toPlainText()
    dlg.close()


def test_about_terms(qapp, win, tmp_path):
    dlg = win.about("Terms of Service", show=False)
    assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "Terms of Service"
    assert "No warranty" in dlg.browsers["Terms of Service"].toPlainText()
    assert "AGPL" in dlg.browsers["Third-Party Licenses"].toPlainText()
    assert "QuantiSheet" in dlg.copy_info()
    p = dlg.save_pdf(str(tmp_path / "terms.pdf"))
    assert "Limitation of liability" in fitz.open(p)[0].get_text() or \
        "Limitation of liability" in "".join(pg.get_text()
                                             for pg in fitz.open(p))
    dlg.close()
