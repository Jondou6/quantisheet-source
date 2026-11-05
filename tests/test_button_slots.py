"""A button's clicked(bool) must never reach a method whose first
parameter has a default: Qt passes checked=False into it, so e.g.
import_files(paths=None) got paths=False and silently did nothing (Jon,
Oct 22: "Import Bid Tab... I clicked on it and nothing happened"). Such
buttons are connected through a lambda that calls the method with no
arguments."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _problems():
    out = []
    for root, _, files in os.walk(os.path.join(ROOT, "app")):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            tree = ast.parse(open(p, encoding="utf-8").read())
            for cls in [n for n in ast.walk(tree)
                        if isinstance(n, ast.ClassDef)]:
                meths = {m.name: m for m in cls.body
                         if isinstance(m, ast.FunctionDef)}

                def defaulted(name):
                    m = meths.get(name)
                    if not m:
                        return False
                    args = m.args.args[1:]
                    return bool(args) and len(m.args.defaults) == len(args)

                def is_btn_connect(n):
                    return (isinstance(n, ast.Call) and
                            isinstance(n.func, ast.Attribute) and
                            n.func.attr == "connect" and n.args and
                            isinstance(n.func.value, ast.Attribute) and
                            n.func.value.attr in ("clicked", "triggered"))
                for n in ast.walk(cls):
                    if is_btn_connect(n):
                        a = n.args[0]
                        if isinstance(a, ast.Attribute) and \
                                isinstance(a.value, ast.Name) and \
                                a.value.id == "self" and defaulted(a.attr):
                            out.append(f"{p}:{n.lineno} self.{a.attr}")
                for loop in [n for n in ast.walk(cls)
                             if isinstance(n, ast.For)]:
                    bad = [x.attr for x in ast.walk(loop.iter)
                           if isinstance(x, ast.Attribute) and
                           isinstance(x.value, ast.Name) and
                           x.value.id == "self" and defaulted(x.attr)]
                    if not bad:
                        continue
                    for n in ast.walk(loop):
                        if is_btn_connect(n) and \
                                isinstance(n.args[0], ast.Name):
                            out.append(f"{p}:{n.lineno} {bad}")
    return out


def test_no_button_passes_checked_into_a_defaulted_parameter():
    assert _problems() == []
