"""AI tab: AI Takeoff of a whole set, and voice commands."""
import importlib.util
import os
import sys
import time

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, practice, voice   # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _civil():
    spec = importlib.util.spec_from_file_location(
        "civil_real", os.path.join(ROOT, "tools", "civil_real.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _set():
    d = fitz.open()
    practice.floor_plan(d)                 # A-101, rooms with SF tags
    practice.mep_plan(d)                   # P-101, pipes + legend devices
    practice.detail_sheet(d)               # A-501, details: skipped
    civ, truth = _civil().make(3)          # C-201 sewer plan & profile
    d.insert_pdf(civ)
    return d, truth


# ---- AI Takeoff ---------------------------------------------------------------------
def test_classify_sheets():
    assert ait.discipline("C-201", "") == "civil"
    assert ait.discipline("P1.02", "") == "plumbing"
    assert ait.discipline("FP-101", "") == "fire protection"
    assert ait.discipline("", "SANITARY SEWER PLAN AND PROFILE") == "civil"
    assert ait.sheet_kind("WALL SECTIONS") == "detail"
    assert ait.sheet_kind("FLOOR PLAN") == "plan"
    assert ait.sheet_kind("ENLARGED PLAN AND DETAILS") == "plan"


def test_ai_takeoff_whole_set():
    d, truth = _set()
    rows = ait.plan_set(d)
    by = {r["number"]: r for r in rows}
    assert by["A-101"]["engines"] == ["rooms"]
    assert by["C-201"]["engines"] == ["civil"]
    assert set(by["P-101"]["engines"]) == {"pipes", "devices"}
    assert by["A-501"]["engines"] == [] and by["A-501"]["kind"] == "detail"
    assert by["C-201"]["scale"][1] == pytest.approx(72 / 40)
    t = time.time()
    res = ait.run(d, rows)
    assert time.time() - t < 60
    tot = ait.totals(res)
    assert tot["rooms"] >= 4
    assert tot["structures"].get("manhole") == truth["manholes"]
    sewer8 = sum(v for n, v in tot["pipe"].items()
                 if n.startswith('8" PVC sanitary'))
    assert abs(sewer8 - truth["lf"]["8"]) / truth["lf"]["8"] < 0.02
    assert any("CW" in n for n in tot["pipe"]), tot["pipe"]
    assert tot["devices"], "legend devices"
    assert res["assemblies"]
    text = ait.summary_text(rows, res)
    assert "Rooms:" in text and "manhole" in text
    for p, kind, payload in res["marks"]:
        annotate.apply_op(d, annotate.new_op(kind, p, **payload))
    items = annotate.takeoff_items(d)
    assert sum(1 for i in items if i["page"] == 2) == 0   # details skipped


def test_ai_takeoff_dialog_and_ribbon(qapp, win, tmp_path):
    d, truth = _set()
    path = str(tmp_path / "set.pdf")
    d.save(path)
    win.open_path(path)
    names = list(win.ribbon.pages)
    assert "AI" in names, names
    assert "Takeoff" in names, names
    assert not [m for m in win._ribbon_missing if "AI" in m or "Voice" in m]
    dlg = win.ai_takeoff(show=False)
    rows = dlg.read()
    assert len(rows) == 4 and dlg.run_btn.isEnabled()
    # the takeoff runs off the window's thread (Oct 22: "Not Responding"
    # on a 309-sheet set): run() returns at once, the result lands later
    assert dlg.run() is None
    assert not dlg.run_btn.isEnabled()          # busy
    import time
    t0 = time.time()
    while dlg.result is None and time.time() - t0 < 120:
        qapp.processEvents()
        time.sleep(0.02)
    res = dlg.result
    assert res and res["marks"] and "Rooms:" in dlg.summary.toPlainText()
    assert annotate.takeoff_items(win._view.doc)
    assert dlg.run_btn.isEnabled() and "Done - added" in dlg.status.text()


# ---- voice ----------------------------------------------------------------------------
@pytest.mark.parametrize("text, want", [
    ("next page", ("command", "Next Page")),
    ("Please zoom in", ("command", "Zoom In")),
    ("go to page twelve", ("page", 12)),
    ("page one hundred five", ("page", 105)),
    ("go to sheet c two oh one", ("sheet", "C201")),
    ("go to sheet a dash one oh two", ("sheet", "A-102")),
    ("open sheet p one point oh two", ("sheet", "P1.02")),
    ("zoom to two hundred percent", ("zoom", 200)),
    ("search for digester", ("search", "digester")),
    ("AI takeoff", ("command", "AI Takeoff (Whole Set)")),
    ("stop listening", ("stop", None)),
    ("the quick brown fox", (None, None)),
])
def test_interpret(text, want):
    assert voice.interpret(text) == want


def test_numbers_and_grammar():
    assert voice.words_to_int("twenty three") == 23
    assert voice.words_to_int("two hundred") == 200
    assert voice.words_to_int("banana") is None
    assert voice.int_to_words(147) == "one hundred forty seven"
    g = voice.grammar_phrases()
    assert "go to page forty two" in g and "next page" in g


def test_every_voice_command_exists(qapp, win):
    missing = sorted({c for c in voice.PHRASES.values()
                      if win.command(c) is None})
    assert not missing, missing


def test_voice_does_things(qapp, win, tmp_path):
    d, truth = _set()
    path = str(tmp_path / "set.pdf")
    d.save(path)
    win.open_path(path)
    from app.voice_ui import VoiceControl
    vc = VoiceControl(win)
    assert vc.do("go to page three") == "page 3" and win._view.page == 2
    assert vc.do("go to sheet c two oh one") == "sheet C201"
    assert win._view.page == 3
    assert vc.do("previous page") == "Previous Page"
    assert win._view.page == 2
    assert vc.do("zoom to two hundred percent")
    assert abs(win._view.zoom - 2.0) < 0.01
    assert vc.do("search for floor plan")
    assert vc.do("mumble mumble") == ""


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="Windows speech recognition")
def test_windows_speech_engine_starts():
    states = []
    lis = voice.Listener(lambda *a: None, lambda s, m: states.append((s, m)))
    assert lis.start()
    t = time.time()
    while time.time() - t < 25 and not any(
            s in ("listening", "error", "stopped") for s, _ in states):
        time.sleep(0.2)
    lis.stop()
    got = [s for s, _ in states]
    # with a microphone it listens; without one it says so plainly
    assert "listening" in got or "error" in got, states
    if "error" in got:
        msg = next(m for s, m in states if s == "error")
        assert "microphone" in msg.lower() or "speech" in msg.lower()
