"""Brief P1-01 tests 1.1 and 1.3 from QuantiSheet's side, plus the hook's
snapshot (P1-02 producer). settings.DIR is on tmp_path; the real
~/.quantisheet and its price DB are never used."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import make_sample                                             # noqa: E402
from app import backoffice_hook, settings                      # noqa: E402
from test_gui import qapp, win                                 # noqa: E402,F401

ITEM = "QuantiSheet Back Office…"
REAL_DIR = os.path.join(os.path.expanduser("~"), ".quantisheet")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path / "cfg"


@pytest.fixture
def no_backoffice(monkeypatch, cfg):
    """The quantisheet_backoffice folder as if deleted."""
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "quantisheet_backoffice" else real(name, *a, **k)
    monkeypatch.setattr(backoffice_hook.importlib.util, "find_spec", fake)


def _menu_texts(w):
    from PySide6.QtWidgets import QMenu
    return [a.text() for m in w.menuBar().findChildren(QMenu)
            for a in m.actions()]


def test_1_1_absent_module_no_launcher(no_backoffice):
    assert backoffice_hook.launcher() is None
    with pytest.raises(RuntimeError, match="not installed"):
        backoffice_hook.launch(None, popen=lambda *a, **k: None)


def test_1_1_absent_module_no_menu_item(no_backoffice, win):
    texts = _menu_texts(win)
    assert "Export Estimate (CSV)…" in texts
    assert ITEM not in texts


@pytest.fixture
def broken_menu(cfg, monkeypatch):
    """Review fix: any error inside add_menu_item (here addAction itself
    fails on a bad text) must never break QuantiSheet's menu build."""
    monkeypatch.setattr(backoffice_hook, "launcher", lambda: ["x"])
    monkeypatch.setattr(backoffice_hook, "MENU_TEXT", object())


def test_menu_item_error_never_breaks_host_menu(broken_menu, win):
    from PySide6.QtWidgets import QMenu
    titles = [m.title() for m in win.menuBar().findChildren(QMenu)]
    assert "&Module" in titles and "&Billing" in titles
    texts = _menu_texts(win)
    assert "Export Estimate (CSV)…" in texts
    assert ITEM not in texts


def test_add_menu_item_swallows_errors_from_connect(cfg, monkeypatch):
    monkeypatch.setattr(backoffice_hook, "launcher", lambda: ["x"])

    class Act:
        class triggered:                                 # noqa: N801
            @staticmethod
            def connect(fn):
                raise RuntimeError("signal broke")

    class Menu:
        def addAction(self, text):                       # noqa: N802
            return Act()

    assert backoffice_hook.add_menu_item(object(), Menu()) is None


def test_1_1_present_module_menu_item(cfg, win):
    if importlib.util.find_spec("quantisheet_backoffice") is None:
        pytest.skip("quantisheet_backoffice not beside app/")
    assert ITEM in _menu_texts(win)
    assert backoffice_hook.launcher() == [sys.executable, "-m",
                                          "quantisheet_backoffice"]


def test_launcher_from_setting_and_frozen_sibling(cfg, tmp_path, monkeypatch):
    exe = tmp_path / "QuantiSheetBackOffice.exe"
    exe.write_bytes(b"")
    settings.set("backoffice_exe", str(exe))
    assert backoffice_hook.launcher() == [str(exe)]
    settings.set("backoffice_exe", "")
    inst = tmp_path / "Programs" / "QuantiSheet"
    inst.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(inst / "QuantiSheet.exe"))
    assert backoffice_hook.launcher() is None
    sib = tmp_path / "Programs" / "QuantiSheetBackOffice"
    sib.mkdir()
    (sib / "QuantiSheetBackOffice.exe").write_bytes(b"")
    assert backoffice_hook.launcher() == [str(sib / "QuantiSheetBackOffice.exe")]


def _no_floats(o):
    if isinstance(o, float):
        raise AssertionError(f"float {o!r} in the snapshot")
    if isinstance(o, dict):
        for v in o.values():
            _no_floats(v)
    elif isinstance(o, list):
        for v in o:
            _no_floats(v)


def test_snapshot_from_billing_doc_is_read_only(cfg, tmp_path):
    import fitz
    from app import money
    path = str(tmp_path / "plan.pdf")
    make_sample.make(path)
    doc = fitz.open(path)
    data = money.read(doc)
    data["info"].update(project="Example Clinic", contract_no="2611")
    data["sov"] = [{"item": "1", "csi": "03-3000", "desc": "Concrete",
                    "scheduled": 100000.0}]
    data["payapps"] = [{"no": 1, "period_to": "2026-09-30",
                        "date": "2026-09-30", "status": "draft",
                        "lines": {"1": {"work": 25000.0, "stored": 0.0}}}]
    money.write(doc, data)
    doc.saveIncr()
    doc.close()
    h0 = hashlib.sha256(open(path, "rb").read()).hexdigest()
    doc = fitz.open(path)
    snap = backoffice_hook.snapshot(doc)
    assert not doc.is_dirty                         # nothing written
    _no_floats(snap)
    assert snap["interface_version"] == 1
    assert snap["project"]["number"] == "2611"
    assert snap["contract"]["sov"][0]["scheduled"] == "100000.00"
    a = snap["payapps"][0]
    assert a["summary"]["4"] == "25000.00" and a["summary"]["8"] == "22500.00"
    p = backoffice_hook.write_snapshot(doc)
    assert os.path.basename(os.path.dirname(p)).startswith(
        "quantisheet-backoffice-")
    assert settings._is_temp(p)
    json.load(open(p, encoding="utf-8"))
    doc.close()
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == h0


def test_launch_no_shell_and_snapshot_arg(cfg, monkeypatch):
    if importlib.util.find_spec("quantisheet_backoffice") is None:
        pytest.skip("quantisheet_backoffice not beside app/")
    seen = {}

    def popen(args, **kw):
        seen.update(args=args, kw=kw)
    backoffice_hook.launch(None, popen=popen)
    assert seen["args"] == [sys.executable, "-m", "quantisheet_backoffice"]
    assert seen["kw"]["shell"] is False


def test_1_3_back_office_crash_leaves_quantisheet_and_pdf_alone(cfg, win,
                                                                tmp_path):
    if importlib.util.find_spec("quantisheet_backoffice") is None:
        pytest.skip("quantisheet_backoffice not beside app/")
    pdf = win._path
    h0 = hashlib.sha256(open(pdf, "rb").read()).hexdigest()
    env = dict(os.environ, QS_BACKOFFICE_HOME=str(tmp_path / "bo"),
               PYTHONPATH=os.pathsep.join([os.path.dirname(
                   os.path.dirname(backoffice_hook.__file__))] +
                   [p for p in os.environ.get("PYTHONPATH", "").split(
                       os.pathsep) if p]))

    def popen(args, **kw):
        return subprocess.Popen(args, env=env, cwd=str(tmp_path), **kw)
    proc = backoffice_hook.launch(win._view.doc, popen=popen,
                                  extra=["--crash-for-test"])
    rc = proc.wait(timeout=120)
    assert rc == 3                                   # it crashed on purpose
    assert os.path.isfile(tmp_path / "bo" / "crash.log")
    for _ in range(5):                               # QuantiSheet carries on
        qapp_ = __import__("PySide6.QtWidgets", fromlist=["QApplication"])
        qapp_.QApplication.processEvents()
        time.sleep(0.01)
    assert win._view is not None and win._view.doc is not None
    assert win._view.doc.page_count >= 1
    assert not win._view.dirty
    assert hashlib.sha256(open(pdf, "rb").read()).hexdigest() == h0


def test_menu_item_opens_back_office_with_snapshot(cfg, win):
    if importlib.util.find_spec("quantisheet_backoffice") is None:
        pytest.skip("quantisheet_backoffice not beside app/")
    seen = {}
    act = next(a for m in win.menuBar().findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QMenu"]).QMenu)
        for a in m.actions() if a.text() == ITEM)
    assert act is not None
    backoffice_hook.open_from_window(
        win, popen=lambda args, **kw: seen.update(args=args, kw=kw))
    assert seen["args"][:3] == [sys.executable, "-m", "quantisheet_backoffice"]
    assert seen["args"][3] == "--snapshot"
    snap = json.load(open(seen["args"][4], encoding="utf-8"))
    _no_floats(snap)
    assert snap["interface_version"] == 1
    assert not win._view.dirty


def test_snapshot_daily_log_manpower_for_field_report(cfg, tmp_path):
    """P2-10: Daily Log manpower (head count, hours each) and time card
    production go across; weather, notes and visitors do not."""
    from app.pm.store import ProjectStore
    from quantisheet_backoffice import interface
    s = ProjectStore(str(tmp_path / "proj"))
    s.set_setting("number", "2611")
    s.save_record("daily", {"date": "2026-10-20", "status": "Submitted",
                            "weather": "rain", "work": "poured footings",
                            "manpower": [{"company": "Example Builders",
                                          "trade": "Concrete", "workers": 6,
                                          "hours": 8.0,
                                          "notes": "footings"}]})
    s.save_record("timecard", {"date": "2026-10-20", "foreman": "R. Silva",
                               "crew": [], "production": [
                                   {"cost_code": "03-3000", "qty": 42.5,
                                    "unit": "CY", "hours": 32}]})
    snap = backoffice_hook.snapshot(store=s)
    _no_floats(snap)
    (dl,) = snap["daily_logs"]
    assert dl["date"] == "2026-10-20"
    assert dl["manpower"] == [{"company": "Example Builders",
                               "trade": "Concrete", "workers": "6",
                               "hours": "8.0000"}]
    assert "rain" not in json.dumps(snap) and "footings" not in json.dumps(snap)
    loaded = interface.load_snapshot(snap)
    assert not loaded.rejected
    assert len(loaded.sections["daily_logs"]) == 1
    (tc,) = loaded.sections["timecards"].values()
    assert tc["production"][0]["qty"] == "42.5000"
