"""The modern interface: themes, ribbon, command search, start page."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                    # noqa: E402

from app import icons, ribbon, settings, theme               # noqa: E402
from test_gui import ANSWERS, win, qapp                       # noqa: E402,F401


def test_every_ribbon_command_exists(qapp, win):
    assert win._ribbon_missing == []
    assert set(win.ribbon.pages) >= {"Home", "Markup", "Takeoff", "Estimate",
                                      "Review", "Project", "Document",
                                      "Tools"}
    # Nov 4, fewer clicks: Billing, Module, Civil and AI fold into these
    assert not {"Billing", "Module", "Civil", "AI"} & set(win.ribbon.pages)
    assert not win.menuBar().isVisible()
    # shortcuts still work with the menu bar hidden
    assert win.command("Command Search").shortcut().toString() == "Ctrl+K"
    assert win.command("Command Search") in win.actions()
    assert win.command("Labor Rates & Crews") is not None
    # the scale box lives on the Takeoff tab
    assert win.scale_box.window() is win


def test_themes_switch_and_persist(qapp, win, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    assert win.set_theme("dark") == "dark" and theme.is_dark()
    assert settings.get("theme") == "dark"
    assert "#1b1c1f" in QApplication.instance().styleSheet()
    assert win.set_theme("light") == "light"
    assert QApplication.instance().palette().window().color().name() == \
        theme.LIGHT["window"]
    bg, fg = theme.cell_colors("#ffcdcd")
    assert bg.name() == "#ffcdcd"
    theme.apply(QApplication.instance(), "dark")
    bg, fg = theme.cell_colors("#ffcdcd")
    assert bg.value() < 120 and fg.name() == theme.DARK["text"]
    theme.apply(QApplication.instance(), "light")
    QApplication.instance().setStyleSheet("")     # leave other tests alone


def test_rotate_is_a_page_level_undo_step(qapp, win):
    v = win._view
    n = len(v.history.stack)
    win._rotate_pages([0], 90)
    assert v.pg.rotation == 90
    assert v.history.stack[-1][0] == "pages" and len(v.history.stack) == n + 1
    win.undo()
    assert v.doc[0].rotation == 0
    win.redo()
    assert v.doc[0].rotation == 90


def test_icons_render():
    for n in icons.names():
        pm = icons.icon(n).pixmap(24, 24)
        assert not pm.isNull(), n


def test_command_search_finds_and_runs(qapp, win):
    dlg = win.command_search(show=False)
    dlg.input.setText("bid lev")
    first = dlg.list.item(0).data(0x0100)
    assert ribbon.clean(first.text()) == "Bid Leveling"
    dlg.input.setText("area")
    top = [dlg.list.item(i).text() for i in range(min(3, dlg.list.count()))]
    assert top[0] == "Area" and "Auto Area (Click a Room)" in top
    assert not any("1/4" in t for t in top)          # not every scale preset
    dlg.input.setText("ovrly")
    assert "Overlay" in dlg.list.item(0).text()
    assert ribbon.score("zzz", "Area") == 0


def test_start_page_and_ribbon_collapse(qapp, win):
    assert win.start_page.isVisible() or not win.isVisible()
    assert win.start_page.cards
    win.ribbon.set_collapsed(True)
    assert win.ribbon.stack.isHidden()
    win.ribbon.set_collapsed(False)
    win.ribbon.show_page("Estimate")
    assert win.ribbon.current() == "Estimate"


def test_menu_commands_ignore_the_checked_flag(qapp, win):
    # triggered(checked=False) used to arrive as the file path
    for name in ("Import Markups (PDF or XFDF)", "Export Markups (XFDF)",
                 "Link Quantities to Excel"):
        win.command(name).trigger()          # dialogs answer "cancel"


def test_prepare_form_on_a_drawing_is_quick_and_finds_no_walls():
    import time
    import fitz
    from app import acrobat
    d = fitz.open()
    p = d.new_page(width=2592, height=1728)
    sh = p.new_shape()
    for k in range(2000):
        y = 50 + (k % 400) * 4
        sh.draw_line((100 + (k // 400) * 300, y), (380 + (k // 400) * 300, y))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()
    t = time.perf_counter()
    assert acrobat.detect_fields(d) == []
    assert time.perf_counter() - t < 3
