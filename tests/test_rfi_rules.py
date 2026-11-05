"""v36 Find RFIs: rule checks measured against a synthetic 50-sheet sewer
set with planted problems (tests/rfi_civil_set.py)."""
import os
import time

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ai import rfi_finder, rfi_rules                    # noqa: E402
from rfi_civil_set import PLANTED, make_set                  # noqa: E402


def _scan(tmp_path, alt=False):
    p, s = str(tmp_path / "plans.pdf"), str(tmp_path / "specs.pdf")
    assert make_set(p, s, alt=alt) == 50
    t = time.perf_counter()
    with fitz.open(p) as d:
        plans = rfi_finder.gather(d)
    with fitz.open(s) as d:
        specs = rfi_finder.gather(d, "specs")
    found = rfi_rules.find(plans, specs)
    return found, time.perf_counter() - t


def _keys(found):
    for f in found:                    # a grouped open-scope item lists its
        for s in f.get("items") or [f["subject"]]:           # notes (NW-19)
            yield f["kind"], s


def _pr(found):
    got = set(_keys(found))
    tp = len(got & set(PLANTED))
    return tp / max(len(got), 1), tp / len(PLANTED), got


@pytest.mark.parametrize("alt", [False, True])
def test_precision_recall_on_planted_set(tmp_path, alt):
    found, _secs = _scan(tmp_path, alt)
    precision, recall, got = _pr(found)
    assert set(PLANTED) - got == set(), "missed"
    assert got - set(PLANTED) == set(), "false findings"
    assert precision == recall == 1.0
    assert len(list(_keys(found))) == len(got)  # one finding per problem


def test_open_scope_notes_are_one_low_item_listed_last(tmp_path):
    found, _ = _scan(tmp_path)
    scope = [f for f in found if f["kind"] == "open_scope"]
    assert len(scope) == 1 and scope[0]["severity"] == "low"
    assert set(scope[0]["items"]) == {"SERVICE LATERALS BY OTHERS",
                                      "BYPASS PUMPING PLAN TBD"}
    assert found[-1] is scope[0]
    assert len(scope[0]["cites"]) == 2
    text = rfi_rules.draft(scope[0])
    assert "SERVICE LATERALS BY OTHERS" in text.upper()
    assert text.count("?") == 1


def test_one_open_scope_note_stays_as_it_was():
    pages = [(0, "C-101", "PLAN", "BYPASS PUMPING PLAN TBD\n")]
    f = rfi_rules.find(pages)
    assert [(x["kind"], x["subject"]) for x in f] == [
        ("open_scope", "BYPASS PUMPING PLAN TBD")]
    assert "items" not in f[0]


def test_fifty_sheets_under_three_seconds(tmp_path):
    _found, secs = _scan(tmp_path)
    assert secs < 3.0


def test_every_finding_cites_sheet_and_quote(tmp_path):
    found, _ = _scan(tmp_path)
    plans = fitz.open(str(tmp_path / "plans.pdf"))
    for f in found:
        assert f["cites"] and f["reference"]
        for c in f["cites"]:
            if c["doc"] == "plans":
                # the quote really is on the cited page (checked, not trusted)
                assert plans[c["page"]].search_for(c["quote"][:40]), c
    conflict = next(f for f in found if f["kind"] == "pipe_conflict")
    assert len(conflict["cites"]) == 2
    assert conflict["cites"][0]["sheet"] != conflict["cites"][1]["sheet"]


def test_draft_is_a_complete_rfi(tmp_path):
    found, _ = _scan(tmp_path)
    f = next(x for x in found if x["subject"] == "MH-5/MH-6")
    text = rfi_rules.draft(f)
    for part in ("Subject:", "References: Sheet C-102; Sheet C-122",
                 "Question:", '8" PVC', '10" PVC', "Proposed resolution:",
                 "Cost impact: TBD", "Schedule impact: TBD"):
        assert part in text, part
    assert text.count("?") == 1                # one question per RFI


def test_verify_in_field_is_not_an_rfi(tmp_path):
    found, _ = _scan(tmp_path)
    assert not any("VERIFY IN FIELD" in f["quote"] for f in found)


def test_clean_runs_raise_nothing():
    text = ("MH-1 TO MH-2  200 LF 8\" PVC SDR-35 @ 0.50%\n"
            "SAN MH-1  RIM=530.00  INV IN=521.10  INV OUT=521.00\n"
            "SAN MH-2  RIM=529.00  INV IN=520.00  INV OUT=519.90\n"
            "MH-2 TO MH-3  100 LF 10\" PVC SDR-35 @ 0.30%\n"
            "SAN MH-3  RIM=528.00  INV IN=519.60  INV OUT=519.50\n")
    pages = [(0, "C-101", "PLAN", text), (1, "C-201", "PROFILE", text)]
    assert rfi_rules.find(pages) == []


def test_ft_per_ft_slope_and_adverse_inverts():
    text = ("MH-1 TO MH-2  100 LF 8\" PVC SDR-35 @ 0.0050 FT/FT\n"
            "SAN MH-1  RIM=530.00  INV OUT=520.00\n"
            "SAN MH-2  RIM=529.00  INV IN=520.20\n"
            "SAN MH-3  RIM=529.00  INV IN=519.20\n")
    f = rfi_rules.find([(0, "C-101", "", text)])
    assert [x["kind"] for x in f] == ["slope_math"]
    assert "-0.20%" in f[0]["question"]


def test_polish_keeps_numbers_or_is_rejected(tmp_path):
    found, _ = _scan(tmp_path)
    f = next(x for x in found if x["kind"] == "slope_math")
    pieces = []

    def good(prompt, on_text):
        assert len(prompt) < 1500             # findings, not drawing text
        out = "Please confirm: " + f["question"]
        for w in out.split(" "):
            on_text(w + " ")
        return out
    text, ok = rfi_rules.polish(f, ask=good, on_text=pieces.append)
    assert ok and pieces and text.startswith("Please confirm")

    def bad(prompt, on_text):
        return "Which slope governs for the run from MH-17 to MH-18?"
    text, ok = rfi_rules.polish(f, ask=bad)
    assert not ok and text == f["question"]


def test_panel_drafts_rfis(qapp, tmp_path):
    from app.rfi_ui import RfiFindingsPanel
    found, _ = _scan(tmp_path)
    made = []
    p = RfiFindingsPanel(on_draft=lambda sel, spec: made.extend(sel) or sel)
    p.set_findings(found)
    assert p.table.rowCount() == len(found)
    assert "Question:" in p.text.toPlainText()
    p._draft()                                  # nothing ticked: current row
    assert len(made) == 1 and made[0]["draft"].startswith("Subject:")
    p.set_checked({0, 1, 2})
    made.clear()
    p._draft()
    assert len(made) == 3
    p.table.selectRow(1)
    p._polish(ask=lambda pr, cb: (cb("x"), "Confirm. " + found[1]["question"])[1],
              wait=True)
    assert p.drafts[1].count("Confirm. ") == 1


def test_find_rfis_panel_in_the_app(win, tmp_path):
    from PySide6.QtWidgets import QApplication
    p, s = str(tmp_path / "plans.pdf"), str(tmp_path / "specs.pdf")
    make_set(p, s)
    assert win.open_path(p)
    t = time.perf_counter()
    panel = win.ai_find_rfis(spec_path=s)
    while not panel.findings and time.perf_counter() - t < 10:
        QApplication.processEvents()
        time.sleep(0.01)
    assert len(list(_keys(panel.findings))) == len(PLANTED)
    assert time.perf_counter() - t < 3.0        # first results under 3 s
    panel.set_checked({0})
    panel._draft()
    from app import rfilog
    log = rfilog.items(win._view.doc)
    assert len(log) == 1 and log[0]["question"].startswith("Subject:")
    assert log[0]["markup"]                     # cloud on the drawing
    panel.close()


from test_gui import win, qapp                              # noqa: E402,F401


def test_real_set_noise_is_filtered():
    """Patterns that were false findings on a 309-sheet plant set."""
    pages = [
        (0, "G001", "GENERAL", "EQUIPMENT SCHEDULE\nP-1 PUMP\nF-1 FAN\n"),
        (1, "E008", "POWER PLAN", "P-100-024 LOOP\nEX. RTU-3\nF-2\n"),
        (2, "G002", "ABBREVIATIONS", "NIC NOT IN CONTRACT\n"),
        (3, "R100", "AS-BUILT", "THIS DRAWING REFLECTS AS-BUILT CONDITIONS "
         "REPORTED BY OTHERS\nACTUAL DIMENSIONS TO BE DETERMINED BY "
         "EQUIPMENT FURNISHED\n"),
        (4, "S311", "DETAILS", "DETAIL 1\nDETAIL 3\n"),
        (5, "S308", "PLAN", "SEE DET 5/S311\n")]
    assert rfi_rules.find(pages) == []
