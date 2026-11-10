"""Menu catalog for the other developer, and the package boundaries."""
import ast
import os

import pytest

from app.service.menu import ENTRIES
from r111_support import isolate, qapp  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_window_is_listed_once():
    labels = [e["label"] for e in ENTRIES]
    assert labels == [
        "Service Work Order…",
        "Service Agreements…",
        "Maintenance Checklist…",
        "Agreement Visit Calendar…",
        "Refrigerant Log…",
        "Backflow Test Report…",
        "Flat-Rate Pricebook…",
        "Truck Stock…",
        "Tech Recommendations…",
        "T&M Tag…",
        "Build-to-Service Handover…",
        "Dispatch Board…",
        "Customer History…",
        "Good / Better / Best Quotes…",
        "Tune-up Planner…",
        "Warranty Registrations…",
        "Changeout Proposal…",
        "Load Report…",
        "Service Settings…",
    ]
    assert len(labels) == len(set(labels))
    for entry in ENTRIES:
        assert entry["where"].startswith("New Service ribbon tab")
        assert entry["call"].startswith("app.service.")
        assert entry["call"].endswith(".open_window")


def test_each_call_opens_a_window(qapp):
    import importlib
    for entry in ENTRIES:
        mod_name, fn = entry["call"].rsplit(".", 1)
        win = getattr(importlib.import_module(mod_name), fn)()
        assert win.isVisible()
        assert win.windowTitle()
        win.close()


def test_service_package_does_not_import_back_office_or_the_network():
    banned = ("quantisheet_backoffice", "requests", "urllib", "http.client",
              "socket")
    for base in (os.path.join(ROOT, "app", "service"),):
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                tree = ast.parse(open(path, encoding="utf-8").read())
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mods = [node.module]
                    for mod in mods:
                        for word in banned:
                            assert word not in mod, f"{path} imports {mod}"
