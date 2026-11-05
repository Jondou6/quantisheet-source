"""Nothing a user sees compares QuantiSheet with another program (Jon,
Oct 30, before the Store). Export and import names that say which
program a file is for (Sage 300, QuickBooks IIF, HeavyBid, MS Project,
P6, DXF, RSMeans, EagleView) stay - Jon: "exporting to you can leave",
imports too. This checks every text in the program (not docstrings or
comments) for programs we only ever compared ourselves with."""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIVALS = re.compile(r"\b(acrobat|bluebeam|revu|planswift|procore|togal|"
                    r"stackct|on-?screen takeoff|foxit|stirling|trimble|"
                    r"plangrid|buildertrend|kreo|drawboard)\b", re.I)


def _texts(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                id(n) not in docs:
            yield n.lineno, n.value


def test_no_comparison_with_another_program_in_any_text():
    bad = []
    for pkg in ("app", "quantisheet_claims", "quantisheet_backoffice"):
        for p in glob.glob(os.path.join(ROOT, pkg, "**", "*.py"),
                           recursive=True):
            rel = os.path.relpath(p, ROOT)
            if os.sep + "tests" + os.sep in p or "host_tests" in p or \
                    rel.endswith("oldnames.py"):
                continue
            bad += [f"{rel}:{ln}: {t[:80]!r}" for ln, t in _texts(p)
                    if RIVALS.search(t)]
    assert bad == []


def test_web_pages_and_help_files_too():
    bad = []
    for ext in ("html", "js", "md", "txt", "adml", "iss"):
        for p in glob.glob(os.path.join(ROOT, "app", "**", "*." + ext),
                           recursive=True) + glob.glob(
                os.path.join(ROOT, "installer", "**", "*." + ext),
                recursive=True):
            with open(p, encoding="utf-8", errors="replace") as f:
                bad += [f"{os.path.relpath(p, ROOT)}:{i}" for i, ln in
                        enumerate(f, 1) if RIVALS.search(ln)]
    assert bad == []
