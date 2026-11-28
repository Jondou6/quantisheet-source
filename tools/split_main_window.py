"""Move groups of MainWindow's methods out of app/main_window.py into
mixin modules (Nov 25 optimization list: "Split up the main window
code"). Run once; the result is ordinary source to review and commit.

    python tools/split_main_window.py [--dry]

Each group becomes app/mw_<name>.py with a class <Name>Mixin holding the
methods word for word, and the imports those methods use (taken from
main_window.py's own import lines, plus `from .main_window import ...`
for names main_window defines above the class). MainWindow then inherits
the mixins, so every method, attribute and test reaches them as before.
"""
import ast
import builtins
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MW = os.path.join(ROOT, "app", "main_window.py")

GROUPS = [
    ("menus", "Menus", "The menus and the ribbon: what is on them and in "
     "which order (split out of main_window.py, Nov 25).",
     lambda n: n in ("_build_menus", "_build_toolbar", "_fill_approved_tiles",
                     "_ribbon_only_actions")),
    ("ai", "AiCommands", "The AI commands of the main window (split out of "
     "main_window.py, Nov 25).",
     lambda n: n.startswith("ai_") or n in ("translate_markups",
                                             "tag_check")),
    ("exchange", "Exchange", "Exports to and imports from other programs, "
     "and printing (split out of main_window.py, Nov 25).",
     lambda n: n.startswith(("export_", "import_")) or n in (
         "link_excel", "buy_quantities", "print_to", "add_printer")),
]


def names_used(node):
    """Global names a function reads (not its own arguments or locals)."""
    loads, stores = set(), set()
    args = set()
    for a in ast.walk(node):
        if isinstance(a, ast.arg):
            args.add(a.arg)
        elif isinstance(a, ast.Name):
            (loads if isinstance(a.ctx, ast.Load) else stores).add(a.id)
        elif isinstance(a, (ast.Import, ast.ImportFrom)):
            for al in a.names:
                stores.add((al.asname or al.name).split(".")[0])
        elif isinstance(a, (ast.FunctionDef, ast.ClassDef)) and a is not node:
            stores.add(a.name)
        elif isinstance(a, ast.ExceptHandler) and a.name:
            stores.add(a.name)
    return loads - stores - args - set(dir(builtins))


def main(argv):
    src = open(MW, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    # where each module-level name comes from
    imported = {}            # name -> import statement text
    defined = set()          # names main_window defines before the class
    for n in tree.body:
        if n is cls:
            break
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                nm = (al.asname or al.name).split(".")[0]
                if isinstance(n, ast.ImportFrom):
                    mod = "." * n.level + (n.module or "")
                    imported[nm] = (mod, al.name, al.asname)
                else:
                    imported[nm] = (None, al.name, al.asname)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
    after = {n.name for n in tree.body[tree.body.index(cls):]
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | \
        {t.id for n in tree.body[tree.body.index(cls):]
         if isinstance(n, ast.Assign) for t in n.targets
         if isinstance(t, ast.Name)}
    methods = [m for m in cls.body if isinstance(m, ast.FunctionDef)]
    taken, made = set(), []
    for key, name, doc, pick in GROUPS:
        ms = [m for m in methods if pick(m.name) and m.name not in taken]
        if not ms:
            continue
        taken |= {m.name for m in ms}
        need = set()
        for m in ms:
            need |= names_used(m)
        unknown = need - set(imported) - defined - after - {"__file__"}
        if unknown:
            raise SystemExit(f"{key}: names from nowhere: {sorted(unknown)}")
        if need & after:
            raise SystemExit(f"{key}: uses names defined after the class: "
                             f"{sorted(need & after)}")
        import textwrap
        out = ['"""' + "\n".join(textwrap.wrap(doc, 72)) + '\n"""\n']
        plain = sorted({imported[n][1] for n in need
                        if n in imported and imported[n][0] is None})
        for p in plain:
            out.append(f"import {p}\n")
        froms = {}
        for n in sorted(need):
            if n in imported and imported[n][0] is not None:
                mod, real, asn = imported[n]
                froms.setdefault(mod, []).append(
                    real + (f" as {asn}" if asn else ""))
        if plain:
            out.append("\n")
        for mod in sorted(froms, key=lambda m: (m.startswith("."), m)):
            items = ", ".join(sorted(froms[mod]))
            out.append(_wrap(f"from {mod} import ", items))
        mine = sorted(n for n in need if n in defined)
        if mine:
            out.append(_wrap("from .main_window import ", ", ".join(mine)))
        out.append(f"\n\nclass {name}Mixin:\n")
        out.append(f'    """MainWindow\'s {key} methods (see main_window.py)."""\n')
        for m in ms:
            start = (m.decorator_list[0].lineno if m.decorator_list
                     else m.lineno) - 1
            # keep the comment lines directly above the method
            while start > 0 and lines[start - 1].strip().startswith("#"):
                start -= 1
            out.append("\n")
            out.extend(lines[start:m.end_lineno])
        made.append((key, name, ms, "".join(out)))
    # main_window without the moved methods
    drop = []
    for _k, _n, ms, _t in made:
        for m in ms:
            start = (m.decorator_list[0].lineno if m.decorator_list
                     else m.lineno) - 1
            while start > 0 and lines[start - 1].strip().startswith("#"):
                start -= 1
            end = m.end_lineno
            # and the blank line after it
            while end < len(lines) and not lines[end].strip():
                end += 1
            drop.append((start, end))
    keep = []
    i = 0
    for a, b in sorted(drop):
        keep.extend(lines[i:a])
        i = b
    keep.extend(lines[i:])
    text = "".join(keep)
    imp = "".join(f"from .mw_{k} import {n}Mixin                        "
                  "# noqa: E402\n".replace("                        ",
                                           " " * max(1, 22 - len(k) - len(n)))
                  for k, n, _m, _t in made)
    text = text.replace("\n\nclass MainWindow(QMainWindow):",
                        "\n\n# the window's methods, by part (Nov 25)\n" + imp +
                        "\n\nclass MainWindow(" + ", ".join(
                            f"{n}Mixin" for _k, n, _m, _t in made) +
                        ", QMainWindow):", 1)
    print(f"main_window.py: {len(lines)} -> {text.count(chr(10))} lines")
    for k, n, ms, t in made:
        print(f"app/mw_{k}.py: {len(ms)} methods, {t.count(chr(10))} lines")
    if "--dry" in argv:
        return 0
    for k, n, ms, t in made:
        with open(os.path.join(ROOT, "app", f"mw_{k}.py"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(t)
    with open(MW, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return 0


def _wrap(head, items):
    one = head + items + "\n"
    if len(one) <= 79:
        return one
    parts, cur = [], head + "("
    for it in items.split(", "):
        add = it + ", "
        if len(cur) + len(add) > 78:
            parts.append(cur.rstrip() + "\n")
            cur = "    "
        cur += add
    parts.append(cur.rstrip(", ") + ")\n")
    return "".join(parts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
