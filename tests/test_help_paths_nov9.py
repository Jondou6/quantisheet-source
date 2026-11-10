"""Every "Tab > Command" the Help Center names is really there (Venice's
first review, #23: Help said "Estimate > Bid Form Workbook" when the
command was on another tab). A path is right when the command is on that
ribbon tab or in the menu of that name."""
import html
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import qapp, win                                 # noqa: E402,F401

PATH = re.compile(r"([A-Z][A-Za-z ]{2,16}?)(?: tab)? &gt; <b>([^<]+)</b>|"
                  r"([A-Z][A-Za-z ]{2,16}?)(?: tab)? > <b>([^<]+)</b>")


def _paths():
    from app import helpcenter, quickaccess
    out = set()
    for t in helpcenter.T:
        for text in [t["goal"]] + list(t["steps"]) + list(t["tips"]):
            for m in PATH.finditer(text):
                tab = (m.group(1) or m.group(3)).strip()
                cmd = html.unescape(m.group(2) or m.group(4)).strip()
                # "Markup > Takeoff > X": the last name before > is the tab
                tab = tab.split(" > ")[-1]
                if tab in quickaccess.TAB_ORDER:
                    out.add((tab, cmd))
    return sorted(out)


def _menu_commands(win):
    """{menu title: every command under it, sub-menus included}."""
    out = {}

    def walk(menu, into):
        for a in menu.actions():
            if a.menu() is not None:
                walk(a.menu(), into)
            elif a.text():
                into.add(a.text().replace("&", "").replace("…", "")
                         .rstrip(". ").strip().lower())
    for a in win.menuBar().actions():
        if a.menu() is not None:
            walk(a.menu(), out.setdefault(a.text().replace("&", ""), set()))
    return out


def test_help_paths_point_at_real_places(win):
    from app import quickaccess
    menus = _menu_commands(win)
    wrong = []
    for tab, cmd in _paths():
        key = cmd.replace("…", "").rstrip(". ").strip().lower()
        act = win.command(cmd)
        if act is None:
            continue                 # a group or panel name, not a command
        hit = quickaccess.where_is(win, act)
        on_tab = hit[1] if hit else None
        if on_tab == tab or key in menus.get(tab, ()):
            continue
        homes = sorted(m for m, cs in menus.items() if key in cs)
        wrong.append(f"{tab} > {cmd}  (is on: tab {on_tab}, menu {homes})")
    assert not wrong, "\n".join(wrong)


def test_the_paths_are_found():
    assert len(_paths()) > 30                    # the scan itself works
