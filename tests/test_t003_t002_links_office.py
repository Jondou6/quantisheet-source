"""Threat model T-003 / T-002 / T-017 (0.13.14): a PDF's link to another
file always asks, never goes to a network path and only opens a PDF;
Office conversion runs with macros forced off; PowerShell by full path."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                  # noqa: E402
import pytest                                                # noqa: E402

from app import acrobat2, main_window as mw                  # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


@pytest.mark.parametrize("raw", [r"\\evil\share\a.pdf", "//evil/s/a.pdf",
                                 "file://evil/share/a.pdf",
                                 "https://example.invalid/a.pdf"])
def test_network_targets_are_blocked(raw):
    path, why = mw.file_link_target(raw, r"C:\plans\main.pdf")
    assert path == "" and "network" in why


def test_only_pdfs_and_relative_from_the_open_file(tmp_path):
    assert mw.file_link_target("run.exe", str(tmp_path / "m.pdf"))[1]
    p, why = mw.file_link_target("sheets/A-101.pdf", str(tmp_path / "m.pdf"))
    assert not why and p == os.path.normpath(
        str(tmp_path / "sheets" / "A-101.pdf"))


def test_file_link_asks_first_and_touches_nothing_on_no(win, tmp_path,
                                                        monkeypatch):
    target = tmp_path / "other.pdf"
    d = fitz.open()
    d.new_page()
    d.save(str(target))
    asked, touched = [], []
    monkeypatch.setattr(mw.QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or
                        mw.QMessageBox.No)
    real = os.path.exists
    monkeypatch.setattr(mw.os.path, "exists",
                        lambda p: touched.append(p) or real(p))
    assert win.follow_link({"kind": fitz.LINK_GOTOR,
                            "file": str(target)}) is False
    assert asked and str(target) in asked[0]
    assert str(target) not in touched            # not even looked at
    monkeypatch.setattr(mw.QMessageBox, "question",
                        lambda *a, **k: mw.QMessageBox.Yes)
    opened = []
    monkeypatch.setattr(win, "open_path", lambda p: opened.append(p) or True)
    assert win.follow_link({"kind": fitz.LINK_GOTOR, "file": str(target)})
    assert opened == [os.path.normpath(str(target))]


def test_network_link_warns_without_asking(win, monkeypatch):
    warned = []
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(mw.QMessageBox, "question",
                        lambda *a, **k: pytest.fail("asked"))
    assert win.follow_link({"kind": fitz.LINK_GOTOR,
                            "file": r"\\evil\share\a.pdf"}) is False
    assert warned and "network" in warned[0]


def test_office_conversion_forces_macros_off():
    for kind in ("word", "excel", "ppt"):
        assert "AutomationSecurity = 3" in acrobat2._PS[kind]
        script = acrobat2._PS[kind]
        assert script.index("AutomationSecurity") < script.index(".Open(")
    assert "EnableEvents = $false" in acrobat2._PS["excel"]


def test_powershell_by_full_path():
    from app import syspaths
    p = syspaths.powershell()
    if os.name == "nt":
        assert os.path.isabs(p) and p.lower().endswith(
            os.path.join("system32", "windowspowershell", "v1.0",
                         "powershell.exe"))


def test_user_writable_folder_is_spotted(tmp_path):
    assert mw.user_writable(str(tmp_path))
    assert not mw.user_writable(str(tmp_path / "no-such-folder"))


@pytest.mark.skipif(os.name != "nt", reason="Windows elevation")
def test_per_user_program_is_never_run_as_admin(win, tmp_path, monkeypatch):
    """T-006: a QuantiSheet.exe in a folder the user can change is not
    started with "runas" - a swapped file would get admin rights."""
    import ctypes
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "QuantiSheet.exe"))
    told = []
    monkeypatch.setattr(mw.QMessageBox, "information",
                        lambda *a, **k: told.append(a[2]))
    monkeypatch.setattr(ctypes.windll.shell32, "ShellExecuteW",
                        lambda *a: pytest.fail("elevated"), raising=False)
    assert win.add_printer(confirm=False) is False
    assert told and "installed just for you" in told[0]


def test_ai_requests_skip_proxies_and_redirects(monkeypatch):
    from app import policy
    from app.ai import review
    op = review._opener()
    # an empty ProxyHandler stands in for the default one, so no system or
    # environment proxy is used (it has nothing to add as a handler)
    assert not any(getattr(h, "proxies", None) for h in op.handlers)
    import urllib.request as ur
    assert not any(type(h) is ur.ProxyHandler and h.proxies
                   for h in op.handlers)
    assert any(isinstance(h, review._NoRedirect) for h in op.handlers)
    monkeypatch.setattr(policy, "get", lambda k, d=None:
                        "file:///C:/x" if k == "AIHost" else d)
    monkeypatch.setattr(policy, "check", lambda what: None)
    with pytest.raises(review.AIError):
        review._allowed_host("http://localhost:11434")
