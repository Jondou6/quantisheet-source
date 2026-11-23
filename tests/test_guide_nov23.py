"""The Features and How-To Guide (Jon, Nov 23): in the install's help
folder, on the Help menu, the Help tab's Learn group and the Help Center,
and opened in a tab from a read-only copy. Made-up files only."""
import os
import stat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import qapp, win                                 # noqa: E402,F401


def _fake_pdf(path, words="Made-up guide"):
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), words)
    d.save(path)
    d.close()
    return path


def test_guide_ships_in_the_help_folder():
    from app import helpcenter
    src = helpcenter.guide_source()
    assert src.replace("\\", "/").endswith(
        "app/data/help/QuantiSheet-Features-and-How-To.pdf")
    assert os.path.isfile(src)
    import fitz
    d = fitz.open(src)
    assert d.page_count > 10
    assert "QuantiSheet" in d[0].get_text()
    d.close()
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import ship_check
    assert ship_check.why("app/data/help/" + helpcenter.GUIDE_NAME) is None


def test_guide_copy_is_read_only_and_refreshed(tmp_path):
    from app import helpcenter
    src = _fake_pdf(str(tmp_path / "src.pdf"))
    out = tmp_path / "help"
    dst = helpcenter.guide_copy(src, str(out))
    assert os.path.isfile(dst) and not os.stat(dst).st_mode & stat.S_IWRITE
    first = os.path.getsize(dst)
    # same guide: the copy stays
    assert helpcenter.guide_copy(src, str(out)) == dst
    # a newer install's guide replaces the read-only copy
    _fake_pdf(src, "Made-up guide, newer and longer " * 5)
    os.utime(src, (os.path.getmtime(src) + 10,) * 2)
    dst2 = helpcenter.guide_copy(src, str(out))
    assert dst2 == dst and os.path.getsize(dst) != first
    assert not os.stat(dst).st_mode & stat.S_IWRITE
    os.chmod(dst, stat.S_IREAD | stat.S_IWRITE)
    assert helpcenter.guide_copy(str(tmp_path / "none.pdf"), str(out)) is None


def test_guide_on_menu_ribbon_and_help_center(win, tmp_path, monkeypatch):
    from app import helpcenter, quickaccess
    names = [a.text() for a in win._help_menu.actions()]
    i = names.index("Help Center && Tutorials…")
    assert names[i + 1] == "Features && How-To Guide (PDF)"
    act = win.command("Features & How-To Guide (PDF)")
    assert act is not None
    hit = quickaccess.where_is(win, act)
    assert hit and hit[1] == "Help"
    src = _fake_pdf(str(tmp_path / "g.pdf"))
    monkeypatch.setattr(helpcenter, "guide_source", lambda: src)
    monkeypatch.setattr(helpcenter.settings, "DIR", str(tmp_path / "qs"))
    opened = []
    monkeypatch.setattr(win, "open_path", lambda p: opened.append(p))
    path = win.open_guide(show=False)
    assert opened == [path] and path.endswith(helpcenter.GUIDE_NAME)
    hc = helpcenter.HelpCenter(win)
    from PySide6.QtWidgets import QPushButton
    b = [x for x in hc.findChildren(QPushButton)
         if x.text() == "Features && How-To Guide (PDF)"]
    assert b
    b[0].click()
    assert len(opened) == 2
    hc.close()
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    monkeypatch.setattr(helpcenter, "guide_source",
                        lambda: str(tmp_path / "missing.pdf"))
    assert win.open_guide(show=False) is None
