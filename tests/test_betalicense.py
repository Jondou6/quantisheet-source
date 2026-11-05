"""Beta tester license keys and the first-run license dialog."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.hazmat.primitives.asymmetric.ed25519 import \
    Ed25519PrivateKey                                          # noqa: E402

from app import betalicense as bl, legal, settings              # noqa: E402
from test_gui import qapp                                       # noqa: E402,F401


@pytest.fixture
def store(monkeypatch, tmp_path):
    d = {}
    monkeypatch.setattr(bl, "_seen_file", lambda: str(tmp_path / ".seen"))
    monkeypatch.setattr(settings, "get", lambda k, default=None:
                        d.get(k, default))
    monkeypatch.setattr(settings, "set", lambda k, v: d.__setitem__(k, v))
    return d


@pytest.fixture
def keys(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pub = bl._b64e(priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    monkeypatch.setattr(bl, "public_key_text", lambda: pub)
    return priv, pub


def test_key_round_trip(store, keys):
    priv, pub = keys
    k = bl.make_key(priv, "Jane Smith", "j@x.com", "Smith Builders", 30,
                    today=dt.date(2026, 10, 1))
    ok, info, msg = bl.check(k, now=dt.date(2026, 10, 15))
    assert ok and info["n"] == "Jane Smith" and info["x"] == "2026-10-31"
    assert "Jane Smith" in msg
    # line breaks from an email are fine
    ok2, _, _ = bl.check(k[:30] + "\n  " + k[30:], now=dt.date(2026, 10, 15))
    assert ok2
    # expired
    ok, _, msg = bl.check(k, now=dt.date(2026, 11, 1))
    assert not ok and "ended" in msg


def test_forged_and_damaged_keys(store, keys):
    priv, pub = keys
    k = bl.make_key(priv, "Jane", days=30)
    body, sig = k[len(bl.PREFIX):].split(".")
    import json
    info = json.loads(bl._b64d(body))
    info["x"] = "2099-01-01"                      # stretch the end date
    forged = bl.PREFIX + bl._b64e(json.dumps(
        info, separators=(",", ":"), sort_keys=True).encode()) + "." + sig
    assert not bl.check(forged)[0]
    other = bl.make_key(Ed25519PrivateKey.generate(), "Mallory", days=30)
    assert not bl.check(other)[0]                 # someone else's signer
    assert not bl.check("hello")[0]
    assert not bl.check(k[:-6])[0]


def test_clock_rollback(store, keys, tmp_path):
    store["beta_seen"] = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    assert bl.today() == dt.date.today() + dt.timedelta(days=5)
    # wiping the setting doesn't help: the second copy remembers
    store.clear()
    (tmp_path / ".seen").write_text(
        (dt.date.today() + dt.timedelta(days=3)).isoformat())
    assert bl.today() == dt.date.today() + dt.timedelta(days=3)


def test_gate_and_dialog(qapp, store, keys, monkeypatch):
    priv, _ = keys
    monkeypatch.delenv("QUANTISHEET_BETA", raising=False)
    assert bl.gate()                              # source folder: no key
    monkeypatch.setenv("QUANTISHEET_BETA", "1")
    assert bl.required() and bl.current() is None
    dlg = bl.LicenseDialog()
    assert not dlg.ok.isEnabled()
    dlg.key.setPlainText(bl.make_key(priv, "Jane", company="Acme", days=10))
    assert dlg.ok.isEnabled()                     # no agreement to tick
    assert not hasattr(dlg, "agree") and not hasattr(dlg, "terms")
    dlg._go()
    assert dlg.result() == 1
    assert bl.current()["n"] == "Jane" and bl.accepted()
    assert "licensed to Jane (Acme)" in bl.label()
    assert bl.gate()                              # now passes silently
    dlg.close()


def test_no_agreement_and_about(store, keys):
    """Jon, Oct 30: "Get rid of agreement"."""
    priv, _ = keys
    assert not hasattr(legal, "beta_terms_html")
    assert "Beta Agreement" not in [n for n, _ in legal.LegalDialog.PAGES]
    assert bl.accepted()
    store["beta_key"] = bl.make_key(priv, "Jane", days=10)
    assert "Licensed to" in legal.about_html()


def test_window_title_and_menu(qapp, store, keys, monkeypatch):
    priv, _ = keys
    store["beta_key"] = bl.make_key(priv, "Jane", days=10)
    from app.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    w = MainWindow()
    assert "licensed to Jane" in w.windowTitle()
    names = [a.text() for a in w._help_menu.actions()]
    assert "Enter License Key…" in names and "Beta Agreement" not in names
    dlg = w.enter_license(show=False)
    assert "Jane" in dlg.status.text()
    dlg.close()
    w.close()


def test_key_tool(tmp_path, monkeypatch):
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "beta_keys", os.path.join(root, "tools", "beta_keys.py"))
    bk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bk)
    monkeypatch.setattr(bk, "KEYS", str(tmp_path))
    monkeypatch.setattr(bk, "PRIV", str(tmp_path / "k.pem"))
    monkeypatch.setattr(bk, "LOG", str(tmp_path / "log.csv"))
    monkeypatch.setattr(bk, "PUB", str(tmp_path / "pub.txt"))
    bk.init()
    pub = open(tmp_path / "pub.txt").read().strip()
    k = bk.issue("Bob Jones", company="BJ Co", days=5)
    assert bl.check(k, pub, now=dt.date.today())[0]
    assert (tmp_path / "Key - Bob Jones.txt").exists()
    assert "Bob Jones" in open(tmp_path / "log.csv").read()


def test_store_copy_has_no_beta_key_or_printer(qapp, store, monkeypatch):
    """The Microsoft Store copy (Jon, Oct 30): no key, no "Beta" wording,
    no Beta Agreement, no QuantiSheet printer."""
    monkeypatch.setattr(bl, "is_store", lambda: True)
    from app import __version__, main
    from app.legal import LegalDialog
    from app.main_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    assert main.splash_version_text() == f"Version {__version__}"
    w = MainWindow()
    names = [a.text() for a in w._help_menu.actions()]
    for gone in ("Enter License Key…", "Beta Agreement",
                 "Add the QuantiSheet Printer…"):
        assert gone not in names, gone
    assert "Terms of Service" in names and "Privacy" in names
    dlg = LegalDialog(w)
    tabs = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert "Beta Agreement" not in tabs and "Privacy" in tabs
    dlg.close()
    w.close()


def test_store_edition_needs_no_key(monkeypatch):
    monkeypatch.setattr(bl, "edition", lambda: "store")
    monkeypatch.setattr(bl.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bl, "KEY_REQUIRED", False)
    monkeypatch.delenv("QUANTISHEET_BETA", raising=False)
    assert bl.is_store() and not bl.required()
    monkeypatch.setattr(bl, "edition", lambda: "public")
    assert bl.required()
