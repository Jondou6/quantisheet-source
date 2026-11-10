"""Fewer clicks (Nov 4) and QuantiSheet opening twice. Made-up files."""
import os
import time

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QPoint, Qt                             # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox           # noqa: E402

from app import quickaccess as QA, settings, singleinstance       # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path


@pytest.fixture
def win(qapp, cfg, monkeypatch):
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)   # never block
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")       # no background jobs
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1300, 900)
    yield w, cfg
    for v in w._all_views():
        v.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _plan(path, pages=2, size=(2592, 1728), scale=True):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=size[0], height=size[1])
        p.insert_text((100, 200), "GENERAL NOTES apply to all sheets",
                      fontsize=24)
        p.insert_text((size[0] - 500, size[1] - 120), f"A{i + 1}.1",
                      fontsize=20)
        if scale:
            p.insert_text((size[0] - 500, size[1] - 80),
                          'SCALE: 1/4" = 1\'-0"', fontsize=14)
    d.save(path)
    return path


# ---- opening twice --------------------------------------------------------------

def test_second_start_waits_for_the_first_then_hands_over():
    tries = []

    def hand(paths):
        tries.append(list(paths))
        return len(tries) >= 3          # the first copy is up on the 3rd try
    assert singleinstance.bring_forward([], wait_s=5, sleep=lambda s: None,
                                        hand=hand)
    assert tries == [[], [], []]


def test_second_start_gives_up_when_nobody_answers():
    t0 = time.monotonic()
    assert not singleinstance.bring_forward(
        ["a.pdf"], wait_s=0.0, sleep=lambda s: None, hand=lambda p: False)
    assert time.monotonic() - t0 < 1


def test_listener_brings_window_forward_with_no_files(qapp, monkeypatch):
    """A real second start (its own process) hands over to this one."""
    import subprocess
    import sys
    pipe = f"QuantiSheet-test-{os.getpid()}"
    monkeypatch.setenv("QUANTISHEET_PIPE", pipe)        # never the real one
    got = []
    srv = singleinstance.listen(lambda paths: got.append(paths))
    if srv is None:
        pytest.skip("local sockets unavailable here")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; sys.path.insert(0, %r);"
            "from PySide6.QtCore import QCoreApplication;"
            "app = QCoreApplication([]);"
            "from app import singleinstance as s;"
            "print('OK' if s.hand_over([], 3000) else 'NO')" % root)
    try:
        p = subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(os.environ, QUANTISHEET_PIPE=pipe))
        end = time.monotonic() + 20
        while p.poll() is None and time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)
        for _ in range(20):
            qapp.processEvents()
        out = p.communicate(timeout=5)[0].decode().strip()
        assert out.endswith("OK") and got == [[]], (out, got)
    finally:
        srv.close()


def test_claim_is_true_off_windows_or_first(monkeypatch):
    if os.name != "nt":
        assert singleinstance.claim() is True


def test_second_claim_sees_the_first(tmp_path):
    """Nov 5 (Jon: a second PDF opened a second QuantiSheet): the start-up
    lock must notice one already held. Run in a fresh process with a
    lock name of its own."""
    if os.name != "nt":
        pytest.skip("Windows lock")
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; sys.path.insert(0, %r);"
            "from app import singleinstance as s;"
            "a = s.claim(); b = s.claim(); print(a, b)" % root)
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        timeout=60, env=dict(os.environ, QUANTISHEET_PIPE=f"QS-claim-test-"
                             f"{os.getpid()}")).stdout.strip()
    assert out.endswith("True False"), out


def test_new_window_command(win):
    import sys
    w, _ = win
    calls = []
    w.new_window(popen=lambda cmd, **k: calls.append(cmd))
    assert calls and calls[0][-1] == "--new-window"
    assert calls[0][0] == sys.executable
    assert w.command("New Window") is not None


# ---- 10. fewer tabs ----------------------------------------------------------------

def test_tabs_fold_into_their_parents(win):
    w, _ = win
    tabs = list(w.ribbon.pages)
    for gone in ("Module", "Civil"):
        assert gone not in tabs
    assert "AI" in tabs
    assert len(tabs) <= 13                 # folded tabs + Service, Billing, AI
    assert w._ribbon_missing == []
    # Nov 5: Billing split back out of Project, and sits right after it
    assert QA.fold("Billing", "Contract") == ("Billing", "Contract")
    assert tabs.index("Billing") == tabs.index("Project") + 1
    # left to right as listed (an AI group folded into Project no longer
    # pulls Project ahead of Markup), and the buttons show that order
    known = [t for t in QA.TAB_ORDER if t in tabs]
    assert tabs[:len(known)] == known
    row = w.ribbon.tab_row
    xs = [row.indexOf(w.ribbon.pages[t].tab_button) for t in tabs]
    assert xs == sorted(xs)
    proj = w.ribbon.page("Project")
    assert len(proj.groups) <= 10, list(proj.groups)
    assert "Billing" not in " ".join(proj.groups)
    docs = [b.defaultAction() for b in proj.groups["Documents"].buttons]
    assert w.command("Submittal Log") in docs
    assert "Submittals" not in proj.groups
    assert QA.fold("Civil", "Takeoff") == ("Estimate", "Civil Takeoff")
    # AI review tools live on the AI tab only (Nov 6)
    assert QA.fold("AI", "Review") == ("AI", "Review")
    assert QA.fold("Takeoff", "Measure") == ("Takeoff", "Measure")
    for name in ("ADA Checker", "Change Orders", "Haul Calculator",
                 "AI Takeoff (Whole Set)", "Contract & Billing"):
        assert QA.where_is(w, w.command(name)) is not None, name


def test_classic_tabs_setting(cfg):
    settings.set(QA.S_CLASSIC, True)
    assert QA.fold("Billing", "Contract") == ("Billing", "Contract")
    assert QA.fold("Module", "ADA") == ("Module", "ADA")


def test_tabs_follow_the_open_file(win):
    w, tmp = win
    w.show()
    hide = QA.update_tabs(w)
    assert {"Markup", "Billing"} <= hide                    # nothing open
    # Nov 6 (Jon): Takeoff stays on the top ribbon, file or not
    assert "Takeoff" not in hide
    assert w.ribbon.pages["Takeoff"].tab_button.isVisible()
    assert w.open_path(_plan(str(tmp / "plans.pdf")))
    assert "Takeoff" not in QA.update_tabs(w)
    assert w.ribbon.pages["Takeoff"].tab_button.isVisible()
    spec = fitz.open()
    spec.new_page(width=612, height=792).insert_text((72, 72), "SECTION 01")
    spec.save(str(tmp / "spec.pdf"))
    assert w.open_path(str(tmp / "spec.pdf"))
    assert "Takeoff" not in QA.update_tabs(w)               # a document too
    settings.set(QA.S_SHOW_ALL, True)
    assert QA.update_tabs(w) == set()


def test_roles_set_pins_and_tabs(win):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    QA.apply_role(w, "office")
    assert "Takeoff" in QA.update_tabs(w)
    assert QA.pins()[:2] == ["QuantiSheet Back Office", "Open"]
    assert "Combine Files" in w.quick_bar.names()
    QA.apply_role(w, "estimator")
    assert "Takeoff" not in QA.update_tabs(w)


def test_welcome_only_on_a_fresh_copy(cfg, monkeypatch):
    assert QA.needs_welcome()
    settings.set(QA.S_WELCOME, True)
    assert not QA.needs_welcome()
    settings.set(QA.S_WELCOME, False)
    monkeypatch.setattr(settings, "recent", lambda *a, **k: ["x.pdf"])
    assert not QA.needs_welcome()          # been using it: no welcome


def test_welcome_dialog_picks_a_role(win):
    w, _ = win
    dlg = QA.first_run(w, show=False)
    assert dlg is not None
    dlg.pick("pm")
    assert settings.get(QA.S_ROLE) == "pm" and settings.get(QA.S_WELCOME)
    assert "New RFI" in QA.pins()
    assert QA.first_run(w, show=False) is None


# ---- 1. quick bar ----------------------------------------------------------------

def test_quick_bar_shows_pins_in_every_layout(win):
    w, _ = win
    qb = w.quick_bar
    assert qb.names()[:4] == ["Calibrate (Set Scale)", "Length", "Area",
                              "Count"]
    assert "Compare" in qb.names()
    assert qb.export_button is not None
    QA.pin(w, "Polylength")
    assert qb.names()[-1] == "Polylength"
    QA.move_pin(w, "Polylength", 0)
    assert qb.names()[0] == "Polylength"
    QA.pin(w, "Polylength", False)
    assert "Polylength" not in qb.names()
    assert not w.quick_bar.isHidden()


def test_right_click_a_ribbon_button_to_pin(win):
    w, _ = win
    a = w.command("Volume")
    m = QA.menu_for_button(w, a)
    assert [x.text() for x in m.actions()] == ["Pin to Quick Bar"]
    m.actions()[0].trigger()
    assert "Volume" in w.quick_bar.names()
    assert [x.text() for x in QA.menu_for_button(w, a).actions()] == \
        ["Unpin From Quick Bar"]


# ---- 2. right-click on paper -----------------------------------------------------

def test_right_click_on_paper_has_tools(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    v = w._view
    v._menu_pt = fitz.Point(120, 195)        # on "GENERAL NOTES"
    w._menu_no_exec = True
    m = w._view_menu(QPoint(10, 10))
    labels = [a.text() for a in m.actions() if a.text()]
    for want in ("Set Scale…", "Length", "Area", "Count", "Edit Text Here",
                 "Snapshot", "New RFI Here…", "Marquee Zoom", "Fit Page"):
        assert want in labels, want
    assert labels.index("Set Scale…") < labels.index("Marquee Zoom")
    v._menu_pt = fitz.Point(2000, 900)      # blank: no Edit Text Here
    m = w._view_menu(QPoint(10, 10))
    assert "Edit Text Here" not in [a.text() for a in m.actions()]


def test_new_rfi_here(win, qapp, monkeypatch):
    from app import rfi_ui
    monkeypatch.setattr(rfi_ui.RfiDialog, "exec", lambda self: 1)
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    w.new_rfi_at(fitz.Point(300, 400))
    from app import rfilog
    its = rfilog.items(w._view.doc)
    assert its and its[-1].get("page") == 0


# ---- 3. Ctrl+K ------------------------------------------------------------------

def test_ctrl_k_finds_sheets_items_tools(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf"), pages=3))
    qapp.processEvents()
    dlg = w.command_search(show=False)
    dlg.input.setText("page 3")
    labels = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    assert any("page 3" in t.lower() for t in labels)
    dlg.input.setText("")
    assert not any(t.startswith(("Sheet ", "Page ")) for t in
                   [dlg.list.item(i).text() for i in range(dlg.list.count())])
    extras = QA.palette_extras(w)
    kinds = {p for p, _a in extras}
    assert "Go to sheet" in kinds and "Tool Chest" in kinds
    # jump to page 3
    a = next(a for p, a in extras if p == "Go to sheet" and "page 3" in
             a.text().lower())
    a.trigger()
    assert w._view.page == 2


def test_show_me_where(win, qapp):
    w, _ = win
    w.show()
    qapp.processEvents()
    a = w.command("Haul Calculator")
    assert QA.reveal(w, a, ms=10) == "Estimate"
    assert w.ribbon.current() == "Estimate"


# ---- 4. scale on open -------------------------------------------------------------

def test_scale_read_on_open(win, qapp):
    w, tmp = win
    path = _plan(str(tmp / "scaled.pdf"), pages=2)
    assert w.open_path(path)
    from app import annotate
    n = QA.auto_scale_on_open(w, w._view, path, wait=True)
    assert n == 2
    assert len(annotate.read_scales(w._view.doc)) == 2
    # already scaled: nothing to do
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) is None
    settings.set(QA.S_AUTO_SCALE, False)
    p2 = _plan(str(tmp / "s2.pdf"))
    assert w.open_path(p2)
    assert QA.auto_scale_on_open(w, w._view, p2, wait=True) is None


def test_scale_chip_menu(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf"), scale=False))
    m = QA.scale_menu(w)
    labels = [a.text() for a in m.actions()]
    assert any(t.startswith("Set Scale (Calibrate)") for t in labels)
    assert "Standard Scales" in labels
    assert w.command("Calibrate (Set Scale)").shortcut().toString() == \
        "Shift+S"
    assert QA.make_chip_clickable(w) is w.chip_scale


# ---- 5. number keys -----------------------------------------------------------------

def test_number_keys_pick_tool_chest_tools(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    from app import takeoff
    fam = next(iter(takeoff.PRESETS.values()))
    name, (ppu, unit) = fam[0]
    w.apply_scale_preset(name, ppu, unit, all_pages=True)   # no calibrate
    tools = QA.chest_tools(w)
    assert tools
    got = w._number_key(1)
    assert got is tools[0]
    assert w._view.tool == tools[0]["tool"]
    assert w._number_key(99) is None
    first = w.chest.tree.topLevelItem(0).child(0).text(0)
    assert first.startswith("1  ")


# ---- 6. Export ------------------------------------------------------------------

def test_one_export_button_remembers(win, monkeypatch):
    w, _ = win
    acts = QA.export_actions(w)
    assert len(acts) >= 5
    label, a = acts[0]
    hits = []
    a.triggered.connect(lambda *_: hits.append(1))
    monkeypatch.setattr(a, "trigger", lambda: hits.append(1))
    QA.run_export(w, label)
    assert settings.get(QA.S_LAST_EXPORT) == label and hits
    assert w.quick_bar.export_button.text().startswith("Export:")


# ---- 7. Compare --------------------------------------------------------------------

def test_newest_revision_is_picked(tmp_path):
    cur = tmp_path / "Plans Rev 2.pdf"
    for name, age in (("Plans Rev 1.pdf", 300), ("Plans Rev 3.pdf", 10),
                      ("Specs.pdf", 1)):
        _plan(str(tmp_path / name), pages=1)
        t = time.time() - age
        os.utime(tmp_path / name, (t, t))
    _plan(str(cur), pages=1)
    assert os.path.basename(QA.newest_revision(str(cur))) == \
        "Plans Rev 3.pdf"
    assert QA.newest_revision(str(tmp_path / "nope" / "x.pdf")) is None


def test_compare_window_runs_the_mode(win, monkeypatch):
    w, tmp = win
    a = _plan(str(tmp / "Plans A.pdf"), pages=1)
    b = _plan(str(tmp / "Plans B.pdf"), pages=1)
    assert w.open_path(a)
    calls = []
    monkeypatch.setattr(w, "compare_revisions", lambda o: calls.append(
        ("overlay", o)))
    monkeypatch.setattr(w, "compare_visual", lambda o: calls.append(
        ("changes", o)))
    monkeypatch.setattr(w, "compare_with", lambda o: calls.append(("text", o)))
    dlg = w.compare(show=False)
    assert dlg.other.text() == b
    for i, mode in enumerate(("overlay", "changes", "text")):
        dlg = w.compare(show=False)
        dlg.group.button(i).setChecked(True)
        dlg.go()
        assert calls[-1] == (mode, b)
    assert settings.get("compare_mode") == "text"
    assert w.command("Compare").shortcut().toString() == "Ctrl+Alt+C"


# ---- 8. double-click edits text ------------------------------------------------

def test_double_click_text_edits_in_place(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    v = w._view
    w.set_tool(None)
    assert v.edit_text_here(fitz.Point(120, 195))
    assert v.tool == "edit_text"
    w.set_tool(None)
    assert not v.edit_text_here(fitz.Point(2000, 900))
    assert w.command("Edit Text").shortcut().toString() == "Ctrl+E"


# ---- 9. pages panel drag ----------------------------------------------------------

def test_drop_pdf_on_pages_inserts_there(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf"), pages=3))
    extra = _plan(str(tmp / "extra.pdf"), pages=2)
    assert w.insert_pdfs_at([extra], 1) == 2
    assert w._view.doc.page_count == 5


def test_drag_pages_out_makes_a_file(win, qapp):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "set.pdf"), pages=3))
    qapp.processEvents()
    out = w.thumbs.drag_out_file([1])
    assert out and os.path.isfile(out) and out.endswith("set - page 2.pdf")
    assert fitz.open(out).page_count == 1
    out = w.thumbs.drag_out_file([0, 1, 2])
    assert out.endswith("pages 1-3.pdf")


# ---- 10. shortcuts -----------------------------------------------------------------

def test_customize_shortcuts_moves_a_key(win):
    w, _ = win
    taken = QA.set_shortcut(w, "Volume", "Ctrl+Alt+C")
    assert taken is w.command("Compare")
    assert w.command("Compare").shortcut().isEmpty()
    assert w.command("Volume").shortcut().toString() == "Ctrl+Alt+C"
    w.command("Volume").setShortcut("")
    assert QA.apply_shortcuts(w) >= 1
    assert w.command("Volume").shortcut().toString() == "Ctrl+Alt+C"
    dlg = w.customize_shortcuts(show=False)
    assert "Volume" in dlg.edits
    dlg.find.setText("volume")
    assert any(not dlg.table.isRowHidden(r) for r in range(dlg.table.rowCount()))


def test_link_excel_has_open(win, monkeypatch):
    w, _ = win
    assert hasattr(w, "_open_file_external")


# ---- review P1 items (Nov 4) ----------------------------------------------------------

def test_f10_opens_every_menu(win):
    w, _ = win
    m = QA.menus_popup(w, show=False)
    titles = [a.text().replace("&", "") for a in m.actions()]
    assert "File" in titles and len(titles) >= 8


def test_typing_in_a_field_never_fires_tool_keys(win, qapp):
    """QS-010 (verify): single-key tool shortcuts while typing."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit
    w, tmp = win
    w.show()
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    w.set_tool(None)
    e = QLineEdit(w)
    e.show()
    e.setFocus()
    qapp.processEvents()
    QTest.keyClicks(e, "select area count line")
    qapp.processEvents()
    assert e.text() == "select area count line"
    assert w._view.tool is None


def test_auto_read_scale_is_flagged_until_confirmed(win, qapp):
    w, tmp = win
    path = _plan(str(tmp / "s.pdf"), pages=1)
    assert w.open_path(path)
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) == 1
    w._update_status()
    assert "click to confirm" in w.chip_scale.text()
    labels = [a.text() for a in QA.scale_menu(w).actions()]
    assert "Scale Looks Right (Confirm)" in labels
    QA.confirm_scale(w)
    assert "confirm" not in w.chip_scale.text()


def test_read_scale_does_not_mark_the_file_changed(win, qapp):
    """Reviews 1 + 2 (Nov 4): opening and closing a set must not ask to
    save, and AutoSave must not write a guess into the file."""
    w, tmp = win
    path = _plan(str(tmp / "nodirty.pdf"), pages=2)
    assert w.open_path(path)
    w._view.dirty = False
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) == 2
    assert not w._view.dirty
    assert QA.unconfirmed_pages(w._view.doc) == {0, 1}


def test_unconfirmed_flag_survives_save_and_reopen(win, qapp, tmp_path):
    w, tmp = win
    path = _plan(str(tmp / "keep.pdf"), pages=2)
    assert w.open_path(path)
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) == 2
    out = str(tmp_path / "saved.pdf")
    w._view.doc.save(out)
    import fitz
    d = fitz.open(out)
    try:
        assert QA.unconfirmed_pages(d) == {0, 1}
        src = QA.scale_sources(d)
        assert src[0]["src"] == "titleblock" and src[0]["confirmed"] is None
    finally:
        d.close()
    # confirming one sheet is kept in the file too
    QA.confirm_scale(w, all_pages=False)
    assert w._view.dirty
    assert QA.unconfirmed_pages(w._view.doc) == {1}
    assert QA.scale_sources(w._view.doc)[0]["confirmed"]["at"]


def test_a_scale_set_by_hand_is_not_flagged(win, qapp):
    w, tmp = win
    path = _plan(str(tmp / "hand.pdf"), pages=1)
    assert w.open_path(path)
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) == 1
    from app import annotate
    sc = annotate.read_scales(w._view.doc)[0]
    annotate.apply_op(w._view.doc, annotate.new_op(
        "set_scale", 0, ppu=sc["ppu"] * 2, unit=sc["unit"], name=""))
    assert QA.unconfirmed_pages(w._view.doc) == set()


def test_first_measurement_on_an_unconfirmed_sheet_asks(win, qapp):
    w, tmp = win
    path = _plan(str(tmp / "gate.pdf"), pages=1)
    assert w.open_path(path)
    assert QA.auto_scale_on_open(w, w._view, path, wait=True) == 1
    v = w._view
    asked = []

    def ask(_w, text, pick):
        asked.append(text)
        return pick
    assert QA.scale_gate(w, v, "measure_length",
                         ask=lambda a, t: ask(a, t, "set")) == "calibrate"
    assert QA.scale_gate(w, v, "measure_area",
                         ask=lambda a, t: ask(a, t, None)) is None
    assert QA.scale_gate(w, v, "measure_area",
                         ask=lambda a, t: ask(a, t, "anyway")) == \
        "measure_area"
    n = len(asked)
    # asked once per sheet: "Measure Anyway" isn't asked again
    assert QA.scale_gate(w, v, "measure_length",
                         ask=lambda a, t: ask(a, t, "set")) == \
        "measure_length"
    assert len(asked) == n and "title block" in asked[0]
    # not a measuring tool, or a confirmed sheet: no question
    assert QA.scale_gate(w, v, "add_cloud", ask=None) == "add_cloud"


def test_takeoff_keys_chip_stands_out(win):
    w, _ = win
    b = w.workflow_boost if hasattr(w, "workflow_boost") else None
    if b is None:
        from app import quickaccess as workflow_boost
        b = next((c for c in w.children()
                  if isinstance(c, workflow_boost.WorkflowBoost)), None)
    assert b is not None
    b.set_takeoff_keys(True)
    assert b.keys_chip.objectName() == "StatusChipAccent"
    assert "F8" in w.measure_bar.keys.text()       # where you're looking
    assert not w.measure_bar.keys.isHidden()
    assert "Takeoff ON" in b.keys_chip.text()
    b.set_takeoff_keys(False)
    assert b.keys_chip.objectName() == "StatusChipButton"


def test_flatten_and_pdfa_warn_about_takeoff(win, qapp, monkeypatch):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    qapp.processEvents()
    from app import takeoff
    fam = next(iter(takeoff.PRESETS.values()))
    name, (ppu, unit) = fam[0]
    w.apply_scale_preset(name, ppu, unit, all_pages=True)
    w._view.commit_rect("measure_area", fitz.Rect(300, 300, 600, 600)) \
        if hasattr(w._view, "commit_rect") else None
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    w.flatten()
    assert asked and "Flatten" not in asked[0][:0]
    assert w.export_pdfa() is None
    assert any("won't include QuantiSheet's job data" in t for t in asked)


def test_hidden_commands_have_buttons(win, qapp):
    """QS-037: Typical Count, Convert To, Service Records, Option Quote."""
    w, tmp = win
    assert "Service" in w.ribbon.pages
    for name, tab in (("Set Typical Count", "Takeoff"),
                      ("Copy Several Times", "Takeoff"),
                      ("Show Uncounted Copies", "Takeoff"),
                      ("Convert Selected To", "Takeoff"),
                      ("Equipment & Service Records", "Service"),
                      ("Customer Quote With Options", "Service")):
        a = w.command(name)
        assert a is not None, name
        assert QA.where_is(w, a)[1] == tab, name
    # nothing selected: says so instead of failing
    assert w.open_path(_plan(str(tmp / "p.pdf")))
    w.command("Set Typical Count").trigger()
    assert w._view.selected is None


def test_service_tab_has_the_service_desk(win):
    w, _ = win
    for name in ("Service Work Order", "Service Agreements",
                 "Refrigerant Log", "Backflow Test Report",
                 "Flat-Rate Pricebook", "Truck Stock", "Tech Recommendations",
                 "T&M Tag", "Build-to-Service Handover", "Dispatch Board",
                 "Customer History", "Agreement Visit Calendar",
                 "Maintenance Checklist", "Good / Better / Best Quotes",
                 "Tune-up Planner", "Warranty Registrations",
                 "Changeout Proposal", "Load Report"):
        a = w.command(name)
        assert a is not None, name
        assert QA.where_is(w, a)[1] == "Service", name
    win_ = w.command("Backflow Test Report").trigger()
    assert getattr(w, "_service_windows", [])
    for sw in w._service_windows:
        sw.close()


# ---- QS-038 / QS-039 (Nov 4) ------------------------------------------------

def test_welcome_has_tour_choice_and_bring_data(win):
    w, _ = win
    dlg = QA.first_run(w, show=False)
    assert dlg is not None and dlg.tour.isChecked()
    texts = [b.text() for b in dlg.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert any("Another PC" in t for t in texts)
    assert any("Keyboard Shortcuts" in t for t in texts)
    dlg.pick(None)


def test_tooltips_say_what_a_command_does(win):
    w, _ = win
    found = QA.apply_tips(w)
    missing = sorted(set(QA.TIPS) - set(found))
    assert not missing, missing                 # every tip names a command
    a = w.command("Tags vs Schedule Check")
    assert "not in the" in a.toolTip() and a.statusTip()
    sage = w.command("Export to Sage 300 Job Cost (CSV)")
    assert "reversal" in sage.toolTip()


# ---- reviews 1 + 2 (Nov 4): placement ------------------------------------------

def test_every_role_pin_is_a_real_command(win):
    w, _ = win
    for key, role in QA.ROLES.items():
        missing = [n for n in role["pins"] if QA.find(w, n) is None and
                   n != "QuantiSheet Back Office"]   # only when installed
        assert not missing, (key, missing)
    assert QA.ROLES["service"]["pins"][:2] == ["Service Work Order",
                                              "Dispatch Board"]


def test_new_takeoff_commands_are_on_the_ribbon(win):
    w, _ = win
    from app.ribbon import RibbonButton, clean
    page = w.ribbon.pages["Takeoff"]
    names = {clean(b.defaultAction().text()) for b in
             page.findChildren(RibbonButton) if b.defaultAction()}
    for n in ("Buy Quantities (Sheets, Boxes, Rolls)",
              "Typical Sheet (Count This Sheet N Times)",
              "Carry Takeoff Forward to a Revised Set",
              "Tags vs Schedule Check"):
        assert n in names, n
    est = {clean(b.defaultAction().text()) for b in
           w.ribbon.pages["Estimate"].findChildren(RibbonButton)
           if b.defaultAction()}
    assert {"Bid Form Workbook", "Builder's Risk Quote Request"} <= est
    assert not [m for m in w._ribbon_missing if "Typical" in str(m) or
                "Buy Quantities" in str(m) or "Bid Form" in str(m)]


def test_one_compare_button_on_the_ribbon(win):
    w, _ = win
    from app.ribbon import RibbonButton, clean
    for tab in ("Home", "Review"):
        if tab not in w.ribbon.pages:
            continue
        names = [clean(b.defaultAction().text()) for b in
                 w.ribbon.pages[tab].findChildren(RibbonButton)
                 if b.defaultAction()]
        assert "Compare" in names, tab
        for old in ("Compare Revisions (Overlay)",
                    "Quick Compare (Same Sheets)", "Compare Text With"):
            assert old not in names, (tab, old)


def test_upgrading_tester_gets_the_ribbon_card_once(win, monkeypatch):
    w, _ = win
    monkeypatch.setattr(settings, "recent", lambda *a, **k: ["old.pdf"])
    assert QA.needs_upgrade_card()
    card = QA.first_run(w, show=False)
    assert isinstance(card, QA.UpgradeCard)
    texts = [b.text() for b in card.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert "Put It Back How It Was" in texts
    assert "Keep the New Layout" in texts
    card.classic()
    assert settings.get(QA.S_CLASSIC) is True
    assert not QA.needs_upgrade_card()                  # once only


def test_upgrade_card_role_pick(win, monkeypatch):
    w, _ = win
    monkeypatch.setattr(settings, "recent", lambda *a, **k: ["old.pdf"])
    card = QA.first_run(w, show=False)
    card.pick("service")
    assert settings.get(QA.S_ROLE) == "service"
    assert QA.pins()[0] == "Service Work Order"
    assert QA.first_run(w, show=False) is None



def test_tabs_follow_never_hide_the_tab_you_are_on(win):
    w, tmp = win
    w.show()
    assert w.open_path(_plan(str(tmp / "plans.pdf")))
    QA.update_tabs(w)
    w.ribbon.show_page("Markup")     # (Takeoff stays shown now - Nov 6)
    w.close_tab(w.tabs.currentIndex())         # nothing open now
    hide = QA.update_tabs(w)
    assert "Markup" in hide                     # would hide...
    assert w.ribbon.current() == "Markup"       # ...but not while you're on it
    assert w.ribbon.pages["Markup"].tab_button.isVisible()


def test_ctrl_k_finds_punch_items_and_changes(win):
    w, tmp = win
    assert w.open_path(_plan(str(tmp / "pk.pdf")))
    from app import money, qa
    qa.add_punch(w._view.doc, "Touch up paint at door 12", page=0)
    money.new_change(w._view.doc, "Owner added outlets", amount=1200)
    names = [a.text() for kind, a in QA.palette_extras(w)
             if kind in ("Punch item", "Change")]
    assert any("Touch up paint" in n for n in names)
    assert any("Owner added outlets" in n for n in names)


def test_start_page_has_the_service_desk(win):
    w, _ = win
    labels = [c.text() for c in w.start_page.cards]
    assert any("Service desk" in t for t in labels)
    assert any("Compare revisions" in t for t in labels)
