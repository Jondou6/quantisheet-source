"""The main window's code is in parts (Nov 25 optimization list): menus
and ribbon, AI commands, exports/imports/printing. MainWindow still has
every method, and no method is in two places."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = {"mw_menus.py": "MenusMixin", "mw_ai.py": "AiCommandsMixin",
         "mw_exchange.py": "ExchangeMixin"}


def _methods(fname, cls):
    tree = ast.parse(open(os.path.join(ROOT, "app", fname),
                          encoding="utf-8").read())
    c = next(n for n in tree.body if isinstance(n, ast.ClassDef) and
             n.name == cls)
    return {m.name for m in c.body if isinstance(m, ast.FunctionDef)}


def test_each_method_lives_in_one_place():
    seen = {}
    for f, cls in [("main_window.py", "MainWindow")] + list(PARTS.items()):
        for m in _methods(f, cls):
            assert m not in seen, f"{m} in {seen.get(m)} and {f}"
            seen[m] = f
    assert {"_build_menus", "ai_summary", "export_heavybid"} <= set(seen)


def test_main_window_inherits_the_parts():
    from app import main_window, mw_ai, mw_exchange, mw_menus
    mro = main_window.MainWindow.__mro__
    for mod, cls in ((mw_menus, "MenusMixin"), (mw_ai, "AiCommandsMixin"),
                     (mw_exchange, "ExchangeMixin")):
        assert getattr(mod, cls) in mro
    assert mro.index(mw_exchange.ExchangeMixin) < mro.index(
        main_window.QMainWindow)
    for m in ("_build_menus", "ai_summary", "export_heavybid", "print_to"):
        assert callable(getattr(main_window.MainWindow, m))


def test_main_window_is_smaller():
    n = open(os.path.join(ROOT, "app", "main_window.py"),
             encoding="utf-8").read().count("\n")
    assert n < 7500
