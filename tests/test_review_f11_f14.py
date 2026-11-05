"""Review findings F11 (old name still visible), F12 (owner report opens a
stored Wunderground link without the scheme check) and F14 (the build
spec needs the icons). Made-up data only (example.invalid)."""
import os
import re
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ---- F11 ------------------------------------------------------------------
def test_starter_cost_book_shows_the_quantisheet_name():
    from app import costbook
    assert costbook.display_name("QuantiSheet Starter 2026") == \
        "QuantiSheet Starter 2026"
    assert costbook.display_name("RSMeans + QuantiSheet Starter 2026") == \
        "RSMeans + QuantiSheet Starter 2026"
    assert costbook.display_name("Example Co Book") == "Example Co Book"
    assert costbook.display_name(None) is None
    # stored under the old name, so existing price databases keep working
    assert os.path.isfile(os.path.join(costbook.SHIPPED,
                                       "QuantiSheet Starter 2026.json"))


def test_cost_book_lists_use_the_shown_name():
    for rel in (("app", "estimate_ui.py"), ("app", "estimating_ui.py"),
                ("app", "ppi_ui.py"), ("app", "pricedb_ui.py")):
        assert "display_name(" in _read(*rel), rel


def test_relay_example_uses_the_new_name():
    for rel in (("docs", "IT_DEPLOYMENT.md"), ("app", "policy.py"),
                ("tools", "make_admx.py"),
                ("installer", "policy", "en-US", "QuantiSheet.adml")):
        text = _read(*rel)
        assert "ws://pdfstudio-relay" not in text, rel
        assert "ws://quantisheet-relay:8765" in text, rel


def test_email_message_id_domain(tmp_path, monkeypatch):
    from app import mail
    msg = {"to": ["est@example.invalid"], "cc": [], "subject": "Example",
           "body": "Example body", "attachments": []}
    path = mail.to_eml(msg, str(tmp_path / "x.eml"))
    head = open(path, encoding="utf-8", errors="replace").read()
    mid = re.search(r"^Message-ID:\s*(\S+)", head, re.M | re.I).group(1)
    assert mid.endswith("@quantisheet.local>")
    assert "pdfstudio.local" not in head


# ---- F12 ------------------------------------------------------------------
class _Store:
    def __init__(self, url):
        self.s = {"wunderground_url": url}

    def setting(self, k):
        return self.s.get(k)

    def set_setting(self, k, v):
        self.s[k] = v


@pytest.mark.parametrize("url,ok", [
    ("https://www.wunderground.com/forecast/us/example", True),
    ("http://example.invalid/forecast", True),
    ("file:///C:/Windows/System32/calc.exe", False),
    ("javascript:alert(1)", False), ("ms-settings:", False),
    ("\\\\server\\share\\x.exe", False), ("mailto:x@example.invalid", False)])
def test_stored_wunderground_link_is_checked(monkeypatch, url, ok):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    from app.pm import owner_report_ui as ui
    opened, warned = [], []
    monkeypatch.delenv("QUANTISHEET_NO_OPEN", raising=False)
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda u: opened.append(u.toString())))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[2])))
    me = SimpleNamespace(store=_Store(url))
    got = ui.OwnerReportWindow.open_wunderground(me)
    if ok:
        assert got == url and opened and not warned
    else:
        assert got is None and opened == [] and warned
        assert me.store.setting("wunderground_url") == ""   # asked again


# ---- F14 ------------------------------------------------------------------
def test_spec_guards_the_optional_images():
    spec = _read("quantisheet.spec")
    for name in ("icon.png", "splash.png", "icon.ico"):
        assert f'os.path.exists(os.path.join(ROOT, "{name}"))' in spec, name
        # every line that bundles it sits under its exists() guard
        for m in re.finditer(r'^(\s*)datas \+= \[\(os\.path\.join\(ROOT, "'
                             + re.escape(name) + '"', spec, re.M):
            assert m.group(1), f"{name} bundled without a guard"
