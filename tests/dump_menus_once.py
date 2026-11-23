"""Not part of the suite: writes every menu command and ribbon button of the
main window to .run/menus.json for the user guide check.
Run: pytest tests/dump_menus_once.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_gui import win, qapp  # noqa: F401,E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clean(t):
    return t.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _tree(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        tip = a.statusTip() or (a.toolTip() if _clean(a.toolTip()) !=
                                _clean(a.text()) else "")
        item = {"text": _clean(a.text()), "keys": a.shortcut().toString(),
                "tip": tip}
        if a.menu() is not None:
            item["menu"] = _tree(a.menu())
        out.append(item)
    return out


def test_dump(win):
    data = {"menus": _tree(win.menuBar()), "ribbon": {}}
    for name, page in win.ribbon.pages.items():
        groups = {}
        for gname, g in page.groups.items():
            btns = []
            for b in g.buttons:
                a = b.defaultAction()
                e = {"label": b.text(), "action": _clean(a.text()) if a else "",
                     "tip": (a.toolTip() if a else b.toolTip()) or ""}
                if b.menu() is not None:
                    e["menu"] = _tree(b.menu())
                btns.append(e)
            groups[gname] = btns
        data["ribbon"][name] = groups
    os.makedirs(os.path.join(ROOT, ".run"), exist_ok=True)
    with open(os.path.join(ROOT, ".run", "menus.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    assert data["menus"]
