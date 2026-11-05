"""Team-copy update check (updatecheck.py / updatecheck_ui.py): version
compare, only the team copy checks (never the Store copy), signed
manifest, SHA-256 checked before anything runs, silent when offline, the
setting and the IT policy turn it off. No test touches the network."""
import hashlib
import io
import json
import os
import socket
import sys
import urllib.error

import pytest

from app import policy, updatecheck

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = updatecheck.UPDATE_HOST
GOOD_URL = f"https://{H}/QuantiSheet-Team-Setup.exe"
PAYLOAD = b"MZ fake installer bytes " * 1000


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    from app import settings
    d = tmp_path / "home"
    d.mkdir()
    monkeypatch.setattr(settings, "DIR", str(d))
    monkeypatch.setattr(settings, "PATH", str(d / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setenv("QUANTISHEET_POLICY_FILE", str(tmp_path / "none.json"))
    policy.reload()
    yield
    policy.reload()


@pytest.fixture
def it(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"

    def set_(**kw):
        path.write_text(json.dumps(kw))
        monkeypatch.setenv("QUANTISHEET_POLICY_FILE", str(path))
        policy.reload()
    return set_


@pytest.fixture
def team(monkeypatch):
    """Pretend to be the installed team copy (frozen, tester, no package)."""
    from app import betalicense, packaged
    monkeypatch.setattr(updatecheck, "_frozen", lambda: True)
    monkeypatch.setattr(betalicense, "edition", lambda: "tester")
    monkeypatch.setattr(betalicense, "store_package_name", lambda: "")
    monkeypatch.setattr(betalicense, "_package_from_path", lambda exe: "")
    monkeypatch.setattr(packaged, "is_packaged", lambda: False)


@pytest.fixture
def key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from app.betalicense import _b64e
    k = Ed25519PrivateKey.generate()
    pub = _b64e(k.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    return k, pub


def manifest(k, **over):
    from app.betalicense import _b64e
    m = {"channel": "team", "version": "9.0.0", "url": GOOD_URL,
         "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
         "size": len(PAYLOAD), "notes": "Fixes and new things.",
         "published": "2026-11-01"}
    m.update(over)
    return m, json.dumps({"manifest": m, "sig": _b64e(
        k.sign(updatecheck.signed_bytes(m)))}).encode()


def info():
    return {"version": "9.0.0", "url": GOOD_URL,
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "size": len(PAYLOAD), "notes": ""}


# ---- version compare -------------------------------------------------------
@pytest.mark.parametrize("remote,local,newer", [
    ("1.0.2", "1.0.1", True), ("1.0.10", "1.0.9", True),
    ("1.1", "1.0.99", True), ("2.0.0", "1.99.99.99", True),
    ("1.0.1", "1.0.1", False), ("1.0.1.0", "1.0.1", False),
    ("1.0.0", "1.0.1", False), ("0.13.14", "1.0.1", False),
    ("1.0.2b", "1.0.1", False), ("", "1.0.1", False),
    (None, "1.0.1", False), ("1..2", "1.0.1", False),
    ("1.0.0.0.1", "1.0.0", False), ("v1.0.2", "1.0.1", False),
    ("1.0.2", "garbage", False),
])
def test_version_compare(remote, local, newer):
    assert updatecheck.is_newer(remote, local) is newer


# ---- only the team copy ----------------------------------------------------
def test_team_copy_is_eligible(team):
    assert updatecheck.team_build() is True
    assert updatecheck.eligible() == (True, "")


def test_source_runs_and_tests_never_check():
    """Not frozen (source / tests): never, even though edition() says
    tester from the source folder."""
    assert updatecheck.team_build() is False


@pytest.mark.parametrize("what", ["msix", "package_name", "windowsapps",
                                  "store", "public", "error"])
def test_store_and_public_copies_never_check(team, monkeypatch, what):
    from app import betalicense, packaged
    if what == "msix":
        monkeypatch.setattr(packaged, "is_packaged", lambda: True)
    elif what == "package_name":
        monkeypatch.setattr(betalicense, "store_package_name",
                            lambda: "JonDougherty.QuantiSheet_1.0.0.0_x64__x")
    elif what == "windowsapps":
        monkeypatch.setattr(betalicense, "_package_from_path",
                            lambda exe: "JonDougherty.QuantiSheet_1.0.0.0")
    elif what == "store":
        monkeypatch.setattr(betalicense, "edition", lambda: "store")
    elif what == "public":
        monkeypatch.setattr(betalicense, "edition", lambda: "public")
    else:
        def boom():
            raise RuntimeError("x")
        monkeypatch.setattr(betalicense, "edition", boom)
    assert updatecheck.team_build() is False
    called = []
    st, _ = updatecheck.check(fetch=lambda: called.append(1) or b"",
                              manual=True)
    assert st == "ineligible" and called == []
    from app import settings
    assert settings.get(updatecheck.S_LAST) is None   # nothing recorded


def test_store_window_gets_no_update_menu(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QMenu
    from app import betalicense, updatecheck_ui
    monkeypatch.setattr(betalicense, "edition", lambda: "store")
    monkeypatch.setattr(updatecheck, "_frozen", lambda: True)
    w = QMainWindow()
    qtbot.addWidget(w)
    m = QMenu(w)
    m.addAction("About QuantiSheet")
    assert updatecheck_ui.install(w, m) is False
    assert [a.text() for a in m.actions()] == ["About QuantiSheet"]


def test_team_window_gets_the_menu_and_setting(qtbot, team, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QMenu
    from app import updatecheck_ui
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")       # no timer
    w = QMainWindow()
    qtbot.addWidget(w)
    m = QMenu(w)
    m.addAction("About QuantiSheet")
    assert updatecheck_ui.install(w, m) is True
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert texts[:2] == ["Check for Updates Now…",
                         "Check for Updates Automatically"]
    assert texts[2].startswith("Reinstall Previous Version")   # Nov 4
    assert texts[3:] == ["About QuantiSheet"]
    now, auto, _back = w._update_actions
    assert auto.isCheckable() and auto.isChecked()
    auto.setChecked(False)
    assert updatecheck.enabled() is False
    assert updatecheck.eligible() == (False, "turned off in settings")
    assert updatecheck.eligible(manual=True) == (True, "")


# ---- IT policy -------------------------------------------------------------
def test_policy_lists_the_update_check():
    assert "DisableUpdateCheck" in policy.SETTINGS
    name, hosts = policy.NETWORK["update"]
    assert name == "DisableUpdateCheck"
    assert set(hosts) == set(updatecheck.MANIFEST_HOSTS |
                             updatecheck.DOWNLOAD_HOSTS)


@pytest.mark.parametrize("setting", ["DisableUpdateCheck", "OfflineMode"])
def test_it_can_turn_it_off(team, it, setting):
    it(**{setting: True})
    called = []
    st, why = updatecheck.check(fetch=lambda: called.append(1), manual=True)
    assert (st, why) == ("ineligible", "turned off by IT") and called == []
    with pytest.raises(policy.Blocked):
        updatecheck._open(updatecheck.MANIFEST_URL,
                          updatecheck.MANIFEST_HOSTS, 1)


# ---- offline and once a day ------------------------------------------------
@pytest.mark.parametrize("err", [
    urllib.error.URLError("no route"), socket.timeout("timed out"),
    ConnectionResetError(), OSError("network unreachable")])
def test_offline_is_silent(team, err):
    def fetch():
        raise err
    assert updatecheck.check(fetch=fetch, now=1000.0) == ("offline", None)


def test_at_most_once_a_day(team, key):
    k, pub = key
    calls = []

    def fetch():
        calls.append(1)
        return manifest(k)[1]
    day = 24 * 3600
    assert updatecheck.check(fetch=fetch, pubkey_text=pub, now=day)[0] == \
        "available"
    assert updatecheck.check(fetch=fetch, pubkey_text=pub,
                             now=day + 3600)[0] == "not_due"
    assert len(calls) == 1
    assert updatecheck.check(fetch=fetch, pubkey_text=pub,
                             now=2 * day + 1)[0] == "available"
    assert updatecheck.check(fetch=fetch, pubkey_text=pub,
                             now=10.0)[0] == "available"   # clock set back
    assert updatecheck.check(fetch=fetch, pubkey_text=pub, now=11.0,
                             manual=True)[0] == "available"
    assert len(calls) == 3 + 1


def test_offline_attempt_also_counts_for_the_day(team):
    def fetch():
        raise OSError("offline")
    updatecheck.check(fetch=fetch, now=5000.0)
    assert updatecheck.check(fetch=fetch, now=5001.0)[0] == "not_due"


# ---- manifest --------------------------------------------------------------
def test_newer_current_and_skip(team, key):
    k, pub = key
    raw = manifest(k)[1]
    st, m = updatecheck.check(fetch=lambda: raw, pubkey_text=pub, now=1.0,
                              local_version="1.0.1")
    assert st == "available" and m["version"] == "9.0.0"
    updatecheck.skip("9.0.0")
    assert updatecheck.check(fetch=lambda: raw, pubkey_text=pub,
                             now=1e9, local_version="1.0.1")[0] == "skipped"
    assert updatecheck.check(fetch=lambda: raw, pubkey_text=pub,
                             manual=True, local_version="1.0.1")[0] == \
        "available"                     # asking by hand still shows it
    assert updatecheck.check(fetch=lambda: raw, pubkey_text=pub,
                             manual=True, local_version="9.0.0")[0] == \
        "current"


@pytest.mark.parametrize("over", [
    {"url": f"http://{H}/x.exe"},
    {"url": "https://evil.example.com/x.exe"},
    {"url": f"https://{H}.evil.com/x.exe"},
    {"url": f"https://user@{H}/x.exe"},
    {"url": f"https://{H}:8443/x.exe"},
    {"sha256": "abc"}, {"sha256": None}, {"size": 0}, {"size": True},
    {"size": "10"}, {"size": 5 * 1024 ** 3}, {"version": "latest"},
    {"channel": "store"}, {"notes": {"html": 1}},
])
def test_bad_manifests_are_refused(team, key, over):
    k, pub = key
    raw = manifest(k, **over)[1]
    with pytest.raises(updatecheck.UpdateError):
        updatecheck.parse_manifest(raw, pub)
    assert updatecheck.check(fetch=lambda: raw, pubkey_text=pub,
                             manual=True)[0] == "error"


def test_tampered_or_unsigned_manifest_is_refused(team, key):
    k, pub = key
    m, raw = manifest(k)
    doc = json.loads(raw)
    doc["manifest"]["sha256"] = "0" * 64              # changed after signing
    with pytest.raises(updatecheck.UpdateError, match="signature"):
        updatecheck.parse_manifest(json.dumps(doc).encode(), pub)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    other = manifest(Ed25519PrivateKey.generate())[1]  # another key
    with pytest.raises(updatecheck.UpdateError, match="signature"):
        updatecheck.parse_manifest(other, pub)
    with pytest.raises(updatecheck.UpdateError, match="no update key"):
        updatecheck.parse_manifest(raw, "")           # fails closed
    for junk in (b"", b"<html>", b"[]", b'{"manifest": 1, "sig": "x"}'):
        with pytest.raises(updatecheck.UpdateError):
            updatecheck.parse_manifest(junk, pub)


def test_oversized_manifest_is_refused(monkeypatch):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(updatecheck, "_open", lambda *a: R(
        b" " * (updatecheck.MAX_MANIFEST + 10)))
    with pytest.raises(updatecheck.UpdateError, match="too large"):
        updatecheck.fetch_manifest()


# ---- what is sent ----------------------------------------------------------
def test_request_is_a_plain_get_with_no_user_data(monkeypatch):
    seen = {}

    class Opener:
        def open(self, req, timeout):
            seen["req"], seen["timeout"] = req, timeout
            raise urllib.error.URLError("stop")
    monkeypatch.setattr(updatecheck.urllib.request, "build_opener",
                        lambda *h: Opener())
    with pytest.raises(urllib.error.URLError):
        updatecheck.fetch_manifest()
    req = seen["req"]
    assert req.get_method() == "GET" and req.data is None
    assert req.full_url == updatecheck.MANIFEST_URL
    assert "?" not in req.full_url and "#" not in req.full_url
    names = {k.lower() for k, _v in req.header_items()}
    assert names <= {"user-agent", "accept", "cache-control"}
    assert dict(req.header_items())["User-agent"] == "QuantiSheet"
    from app import __version__
    assert __version__ not in json.dumps(req.header_items())
    assert seen["timeout"] == updatecheck.TIMEOUT


def test_redirects_only_to_allowed_https():
    h = updatecheck._SafeRedirects(updatecheck.MANIFEST_HOSTS)
    for bad in (f"http://{H}/team/version.json",
                "https://evil.example.com/version.json"):
        with pytest.raises(updatecheck.UpdateError):
            h.redirect_request(None, None, 302, "", {}, bad)
    with pytest.raises(updatecheck.UpdateError):
        updatecheck._open(f"http://{H}/x",
                          updatecheck.MANIFEST_HOSTS, 1)


# ---- download, hash, install -----------------------------------------------
class _Stream(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_good_download_is_kept(tmp_path):
    p = updatecheck.download(info(), folder=str(tmp_path),
                             opener=lambda u: _Stream(PAYLOAD))
    with open(p, "rb") as f:
        assert f.read() == PAYLOAD
    assert updatecheck.ready_download(info(), str(tmp_path)) == p


@pytest.mark.parametrize("body", [PAYLOAD[:-1] + b"X",       # same size
                                  PAYLOAD[:-10],             # short
                                  PAYLOAD + b"extra"])       # long
def test_hash_mismatch_is_rejected_and_deleted(tmp_path, body):
    d = tmp_path / "dl"
    with pytest.raises(updatecheck.HashMismatch):
        updatecheck.download(info(), folder=str(d),
                             opener=lambda u: _Stream(body))
    assert os.listdir(d) == []          # no .part, no installer


def test_cancelled_download_leaves_nothing(tmp_path):
    d = tmp_path / "dl"
    with pytest.raises(updatecheck.UpdateError, match="cancelled"):
        updatecheck.download(info(), folder=str(d),
                             opener=lambda u: _Stream(PAYLOAD),
                             cancelled=lambda: True)
    assert os.listdir(d) == []


def test_installer_rechecked_right_before_it_runs(tmp_path):
    p = updatecheck.download(info(), folder=str(tmp_path),
                             opener=lambda u: _Stream(PAYLOAD))
    ran = []
    with open(p, "r+b") as f:                  # swapped after download
        f.write(b"XX")
    with pytest.raises(updatecheck.HashMismatch):
        updatecheck.launch_installer(p, info(), run=ran.append)
    assert ran == [] and not os.path.exists(p)


def test_installer_runs_quietly_and_reopens(tmp_path):
    """Nov 3 (Jon): an update installs like normal software - after Update
    now, no setup screens; QuantiSheet opens again when it's done. Never
    elevated by QuantiSheet."""
    p = updatecheck.download(info(), folder=str(tmp_path),
                             opener=lambda u: _Stream(PAYLOAD))
    ran = []
    assert updatecheck.launch_installer(p, info(), run=ran.append)
    assert ran == [[p, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/CLOSEAPPLICATIONS", "/QSRELAUNCH"]]
    with open(os.path.join(ROOT, "app", "updatecheck.py"),
              encoding="utf-8") as f:
        src = f.read()
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    for switch in ("runas", "/VERYSILENT", "ShellExecute("):
        assert switch not in code
    iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),
               encoding="utf-8").read()
    assert 'Check: WantRelaunch' in iss and "'/QSRELAUNCH'" in iss


def test_update_now_downloads_then_installs(qtbot, team, tmp_path,
                                            monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QWidget
    from app import updatecheck_ui
    w = QMainWindow()
    w.setCentralWidget(QWidget())
    qtbot.addWidget(w)
    monkeypatch.setattr(updatecheck, "ready_download", lambda i: None)
    p = updatecheck.download(info(), folder=str(tmp_path),
                             opener=lambda u: _Stream(PAYLOAD))
    monkeypatch.setattr(updatecheck, "download", lambda i, **k: p)
    ran, closes = [], []
    monkeypatch.setattr(updatecheck, "launch_installer",
                        lambda path, i, run=None: ran.append(path) or True)
    n = updatecheck_ui.UpdateNotice(w, info())
    keep = {"ok": False}
    monkeypatch.setattr(w, "close", lambda: closes.append(1) or keep["ok"])
    n.b1.click()                                   # Update now
    qtbot.waitUntil(lambda: bool(closes), timeout=5000)
    assert ran == []                     # Cancel on unsaved work: waits
    assert n.b1.text() == "Update now"
    keep["ok"] = True
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "quit", lambda *a: None)
    n.b1.click()
    assert ran == [p]


def test_download_only_from_allowed_hosts(team, key):
    k, pub = key
    with pytest.raises(updatecheck.UpdateError):
        updatecheck._open("https://evil.example.com/x.exe",
                          updatecheck.DOWNLOAD_HOSTS, 1)


# ---- notice ----------------------------------------------------------------
def test_notice_offers_download_later_skip(qtbot, team):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMainWindow, QWidget
    from app import settings, updatecheck_ui
    w = QMainWindow()
    w.setCentralWidget(QWidget())
    qtbot.addWidget(w)
    i = dict(info(), notes="<b>bold</b> <img src=x>")
    n = updatecheck_ui.UpdateNotice(w, i)
    assert [b.text() for b in (n.b1, n.b2, n.b3)] == [
        "Update now", "Later", "Skip this version"]
    assert n.notes.textFormat() == Qt.PlainText
    assert not n.isWindow()                    # inside the window, no dialog
    n.b3.click()
    assert settings.get(updatecheck.S_SKIP) == "9.0.0"


def test_automatic_check_is_silent_unless_newer(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QMessageBox
    from app import updatecheck_ui
    boxes = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: boxes.append(a))
    w = QMainWindow()
    qtbot.addWidget(w)
    for st in ("offline", "error", "current", "not_due", "ineligible"):
        updatecheck_ui._show(w, st, None, False)
    assert boxes == []
    updatecheck_ui._show(w, "offline", None, True)    # asked by hand
    assert len(boxes) == 1


# ---- privacy page and build tool -------------------------------------------
def test_privacy_page_says_what_each_copy_does(monkeypatch, team):
    from app import betalicense, legal
    html = legal.privacy_html()
    assert "Update check (team copy)" in html
    assert "Check for Updates Automatically" in html
    assert "DisableUpdateCheck" in html
    monkeypatch.setattr(betalicense, "edition", lambda: "store")
    html = legal.privacy_html()
    # Nov 2 (Jon: "yes add store route"): the Store copy asks the Store
    # whether an update is waiting and shows a reminder; the Store installs
    assert "updated by the Microsoft Store" in html
    assert "never downloads or installs updates" in html
    assert "asks the Microsoft Store" in html and "Nothing is sent to us" in html


def test_build_tool_makes_a_manifest_the_program_accepts(tmp_path, key):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import make_update_manifest as tool
    k, pub = key
    exe = tmp_path / "setup.exe"
    exe.write_bytes(PAYLOAD)
    doc = tool.build(k, str(exe), GOOD_URL, "notes", "9.0.0")
    m = updatecheck.parse_manifest(json.dumps(doc).encode(), pub)
    assert m["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert m["size"] == len(PAYLOAD)


def test_one_host_value_drives_everything():
    """R2 hosting (Chief, Oct 31): one UPDATE_BASE; manifest and installer
    on the same host; the IT policy list follows it."""
    from urllib.parse import urlparse
    assert updatecheck.MANIFEST_URL.startswith(updatecheck.UPDATE_BASE)
    assert urlparse(updatecheck.MANIFEST_URL).scheme == "https"
    assert updatecheck.MANIFEST_HOSTS == updatecheck.DOWNLOAD_HOSTS == \
        {updatecheck.UPDATE_HOST}
    assert policy.NETWORK["update"][1] == [updatecheck.UPDATE_HOST]
    assert "pages.dev" not in updatecheck.UPDATE_BASE
