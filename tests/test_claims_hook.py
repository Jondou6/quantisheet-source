"""T17: the one hook to the optional ClaimIT program.
settings.DIR is on tmp_path; the real ~/.quantisheet and its price DB are
never used."""
import importlib.util
import json
import os
import sys

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import make_sample                                             # noqa: E402
from app import annotate, claims_hook, pricedb, settings       # noqa: E402
from test_gui import qapp, win                                 # noqa: E402,F401

REAL_DIR = os.path.join(os.path.expanduser("~"), ".quantisheet")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path / "cfg"


@pytest.fixture
def no_claims(monkeypatch, cfg):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "quantisheet_claims" else real(name, *a, **k)
    monkeypatch.setattr(claims_hook.importlib.util, "find_spec", fake)


def _plan(tmp_path):
    path = str(tmp_path / "sample.pdf")
    make_sample.make(path)
    d = fitz.open(path)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[100, 100], [200, 100], [200, 200], [100, 200]],
        label="Interior Wall: 100.00 sq ft",
        measure={"type": "area", "value": 100, "unit": "sq ft",
                 "group": "Interior Wall"}))
    cnt = annotate.new_op("add_count", 0, pt=[300, 300], n=1,
                          measure={"type": "count", "value": 1, "unit": "ea",
                                   "group": "Toilet"})
    annotate.apply_op(d, cnt)
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=cnt["id"],
                                         multiplier=3))
    out = str(tmp_path / "plan.pdf")
    d.save(out)
    d.close()
    return out


def test_price_db_path_is_never_the_real_one(cfg):
    p = os.path.realpath(pricedb.path())
    assert p.startswith(os.path.realpath(str(cfg)))
    assert not p.startswith(os.path.realpath(REAL_DIR) + os.sep)


def test_t17_absent_module_no_launcher(no_claims):
    assert claims_hook.launcher() is None


def test_t17_absent_module_no_menu_item(no_claims, win):
    from PySide6.QtWidgets import QMenu
    texts = [a.text() for m in win.menuBar().findChildren(QMenu)
             for a in m.actions()]
    assert "Export Estimate (CSV)…" in texts
    assert "ClaimIT (Insurance Claim Estimate)…" not in texts


def test_t17_present_module_menu_item(cfg, win):
    if importlib.util.find_spec("quantisheet_claims") is None:
        pytest.skip("quantisheet_claims not beside app/")
    from PySide6.QtWidgets import QMenu
    texts = [a.text() for m in win.menuBar().findChildren(QMenu)
             for a in m.actions()]
    assert "ClaimIT (Insurance Claim Estimate)…" in texts


def test_t17_launcher_from_source_and_setting(cfg, tmp_path, monkeypatch):
    if importlib.util.find_spec("quantisheet_claims") is not None:
        assert claims_hook.launcher() == [sys.executable, "-m", "quantisheet_claims"]
    exe = tmp_path / "ClaimIT.exe"
    exe.write_bytes(b"")
    settings.set("claims_exe", str(exe))
    assert claims_hook.launcher() == [str(exe)]


def test_t17_frozen_sibling_folder(cfg, tmp_path, monkeypatch):
    inst = tmp_path / "Programs" / "QuantiSheet"
    inst.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(inst / "QuantiSheet.exe"))
    assert claims_hook.launcher() is None
    # ClaimIT\ClaimIT.exe beside QuantiSheet's folder
    sib = tmp_path / "Programs" / "ClaimIT"
    sib.mkdir()
    (sib / "ClaimIT.exe").write_bytes(b"")
    assert claims_hook.launcher() == [str(sib / "ClaimIT.exe")]


def test_t17_snapshot_read_only_and_counts(cfg, tmp_path):
    path = _plan(tmp_path)
    before = open(path, "rb").read()
    doc = fitz.open(path)
    emb = doc.embfile_names()
    snap = claims_hook.snapshot(doc)
    assert doc.is_dirty is False
    assert doc.embfile_names() == emb
    doc.close()
    assert open(path, "rb").read() == before
    assert snap["interface_version"] == 1
    assert snap["source"]["file"] == "plan.pdf"
    by = {i["name"]: i for i in snap["items"]}
    assert by["Toilet"]["qty"] == "3.0000" and by["Toilet"]["unit"] == "ea"
    assert by["Interior Wall"]["qty"] == "100.0000"
    assert by["Interior Wall"]["page_label"] == "1"
    assert by["Interior Wall"]["color"].startswith("#")      # from markup_items
    for it in snap["items"]:
        assert set(it) == {"name", "qty", "unit", "page_label", "color"}
        assert all(isinstance(v, str) for v in it.values())
        assert it["color"] == "" or (len(it["color"]) == 7 and it["color"][0] == "#")


def test_t17_launch_writes_temp_snapshot_and_starts_process(cfg, tmp_path):
    if claims_hook.launcher() is None:
        pytest.skip("quantisheet_claims not beside app/")
    doc = fitz.open(_plan(tmp_path))
    seen = {}

    def fake_popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return "proc"
    assert claims_hook.launch(doc, popen=fake_popen) == "proc"
    args = seen["args"]
    assert seen["kw"]["shell"] is False and "--takeoff" in args
    snap_path = args[args.index("--takeoff") + 1]
    assert os.path.basename(os.path.dirname(snap_path)).startswith("quantisheet-claims-")
    assert settings._is_temp(snap_path)
    assert doc.is_dirty is False
    data = json.load(open(snap_path, encoding="utf-8"))
    assert data["interface_version"] == 1
    interface = pytest.importorskip("quantisheet_claims.interface")
    s = interface.load_snapshot(snap_path)
    assert not s.rejected and len(s.items) == len(data["items"])


def test_t17_launch_without_module_raises(no_claims):
    with pytest.raises(RuntimeError):
        claims_hook.launch(None)
