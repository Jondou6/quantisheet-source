"""Menu wiring list, and the boundaries for release 1.1.1."""
import ast
import os

from quantisheet_backoffice.r111 import menu

ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "r111")
BANNED_IMPORTS = {"socket", "urllib", "requests", "http", "smtplib",
                  "google", "app"}
BANNED_TEXT = ("procore", "quickbooks", "bluebeam", "planswift",
               "buildertrend", "autodesk", "on-screen takeoff")


def test_menu_entries_resolve_and_copy_yesterday_is_listed():
    labels = [e["label"] for e in menu.ENTRIES]
    assert "Copy Yesterday's Crews" in labels
    assert "Checklist templates" in labels
    assert "Waiting on me" in labels
    assert "Import job cost report…" in labels
    for entry in menu.ENTRIES:
        assert entry["where"] and entry["call"].startswith(
            "quantisheet_backoffice.r111.")
        assert callable(menu.resolve(entry["call"]))
        low = entry["label"].lower()
        for word in BANNED_TEXT:
            assert word not in low


def test_modules_do_not_import_the_host_or_the_network():
    for name in os.listdir(ROOT):
        if not name.endswith(".py"):
            continue
        path = os.path.join(ROOT, name)
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for mod in mods:
                head = mod.split(".")[0]
                assert head not in BANNED_IMPORTS, f"{name} imports {mod}"
                assert mod != "app" and not mod.startswith("app.")
        text = open(path, encoding="utf-8").read().lower()
        assert "example builders" not in text
        assert "logo.png" not in text
        for word in ("procore", "quickbooks", "bluebeam", "planswift"):
            assert word not in text, name
