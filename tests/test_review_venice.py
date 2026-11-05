"""Outside review (Venice.ai, Oct 16): job data in shared PDFs, empty
vocab CSV, runner PID reuse, AI coverage note, testfiles args."""
import importlib.util
import os
import sys

import fitz
import pytest

from app import acrobat2, annotate, jobdata
from app.ai import review
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool(name):
    spec = importlib.util.spec_from_file_location(
        f"_tool_{name}", os.path.join(ROOT, "tools", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _job_doc():
    d = fitz.open()
    for i in range(2):
        d.new_page(width=600, height=400).insert_text((50, 50), f"sheet {i}")
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    jobdata.restore(d, {"quantisheet_estimate.json": b'{"total": 125000}',
                        "quantisheet_money.json": b'{"margin": 0.12}',
                        "quantisheet_audit.json": b'[{"who": "x"}]'})
    d.embfile_add("spec.txt", b"other attachment")
    return d


# ---- H1 ---------------------------------------------------------------------

def test_describe_and_pricing_flag():
    d = _job_doc()
    names = [n for n, _ in jobdata.describe(d)]
    assert "quantisheet_estimate.json" in names and "spec.txt" not in names
    assert jobdata.has_pricing(d)
    clean = fitz.open()
    clean.new_page()
    assert jobdata.describe(clean) == [] and not jobdata.has_pricing(clean)


def test_external_issue_strips_job_data_and_leaves_open_doc(tmp_path):
    d = _job_doc()
    d.new_page().add_text_annot((20, 20), "keep me")
    out = str(tmp_path / "ext.pdf")
    removed = acrobat2.external_issue(d, out)
    assert "quantisheet_estimate.json" in removed
    e = fitz.open(out)
    assert jobdata.names(e) == []
    assert e.embfile_count() == 0
    raw = open(out, "rb").read()
    assert b"125000" not in raw and b"margin" not in raw
    assert any(a.info.get("content") == "keep me"
               for p in e for a in p.annots())
    # the working document still has everything
    assert "quantisheet_estimate.json" in jobdata.names(d)
    assert annotate.read_scales(d)


def test_strip_removes_only_job_files():
    d = _job_doc()
    gone = jobdata.strip(d)
    assert set(gone) >= {"quantisheet_estimate.json", "quantisheet_audit.json"}
    assert d.embfile_names() == ["spec.txt"]


def test_default_sanitize_still_keeps_job_data():
    d = _job_doc()
    acrobat2.sanitize(d)
    assert "quantisheet_estimate.json" in jobdata.names(d)


def test_job_chip_and_export_menu(win, tmp_path):
    path = str(tmp_path / "job.pdf")
    _job_doc().save(path)
    win.open_path(path)
    win._update_status()
    assert win.chip_job.isVisibleTo(win)
    assert "$" in win.chip_job.text()
    assert "estimate" in win.chip_job.toolTip()
    acts = [a.text() for a in win.findChildren(type(win.menuBar().actions()[0]))]
    assert any("External Issue" in t for t in acts)
    out = str(tmp_path / "out.pdf")
    res = win.export_external(out, ask=False)
    assert res and jobdata.names(fitz.open(out)) == []
    assert win.export_external(path, ask=False) is None   # never overwrite


def test_job_chip_hidden_without_job_data(win, tmp_path):
    path = str(tmp_path / "plain.pdf")
    d = fitz.open()
    d.new_page()
    d.save(path)
    win.open_path(path)
    win._update_status()
    assert not win.chip_job.isVisibleTo(win)


# ---- M3 ---------------------------------------------------------------------

@pytest.mark.parametrize("body", ["", "\n", "\ufeff"])
def test_vocab_load_lines_empty_csv(tmp_path, body):
    vocab = _tool("vocab")
    p = tmp_path / "items.csv"
    p.write_text(body, encoding="utf-8")
    assert vocab.load_lines(p, None) == []


def test_vocab_load_lines_normal_csv(tmp_path):
    vocab = _tool("vocab")
    p = tmp_path / "items.csv"
    p.write_text("Code,Description\n1,Sidewalk\n2,Curb\n", encoding="utf-8")
    assert vocab.load_lines(p, None) == ["Sidewalk", "Curb"]


# ---- M4 ---------------------------------------------------------------------

def _runner(tmp_path, monkeypatch, pid, cmdline):
    runner = _tool("runner")
    monkeypatch.setattr(runner, "RUN", str(tmp_path))
    (tmp_path / "runner.alive").write_text(str(pid))
    monkeypatch.setattr(runner, "_cmdline", lambda p: cmdline)
    monkeypatch.setattr(runner.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd))
    runner._stop_old()
    return calls


def test_runner_leaves_recycled_pid_alone(tmp_path, monkeypatch):
    assert _runner(tmp_path, monkeypatch, 4242,
                   r"C:\Program Files\Outlook\OUTLOOK.EXE") == []
    assert _runner(tmp_path, monkeypatch, 4242, "") == []


def test_runner_stops_old_runner(tmp_path, monkeypatch):
    calls = _runner(tmp_path, monkeypatch, 4242,
                    r'"C:\x\.venv\Scripts\python.exe" C:\x\tools\runner.py')
    assert calls and calls[0][:3] == ["taskkill", "/PID", "4242"]


# ---- M5 ---------------------------------------------------------------------

def test_ai_coverage_note_for_long_document():
    d = fitz.open()
    for i in range(40):
        p = d.new_page()
        p.insert_textbox(fitz.Rect(20, 20, 580, 820), ("word " * 400),
                         fontsize=6)
    text, info = review.doc_text_info(d)
    assert info["cut"] and len(text) == review.TEXT_LIMIT
    assert info["total"] > info["sent"]
    note = review.coverage_note(info)
    assert note.startswith("Reviewed 24k of ")
    assert f"of {d.page_count}" in note


def test_ai_coverage_note_short_document():
    d = fitz.open()
    d.new_page().insert_text((50, 50), "short")
    _, info = review.doc_text_info(d)
    assert not info["cut"]
    assert "whole document" in review.coverage_note(info)


def test_summary_mentions_coverage(monkeypatch):
    monkeypatch.setattr(review, "_ollama", lambda *a, **k: "- point")
    s = review.summarize_text("x", True, "Reviewed 24k of 900k characters")
    assert "Reviewed 24k of 900k characters" in s


# ---- L2 ---------------------------------------------------------------------

def test_testfiles_numeric_pattern(monkeypatch, capsys):
    tf = _tool("testfiles")
    seen = []
    monkeypatch.setattr(tf.glob, "glob", lambda pat: seen.append(pat) or [])
    tf.main(["28", "--limit", "60"])
    assert seen and seen[0].endswith(os.path.join("tests", "28.py"))
    seen.clear()
    tf.main(["--limit", "60"])
    assert seen[0].endswith("test_*.py")


# ---- second batch: autosave session, documents panel, audit rev, PPI -------

def test_autosave_offers_copy_from_crashed_session_with_same_pid(
        tmp_path, monkeypatch):
    import json as _json
    from app import autosave
    monkeypatch.setattr(autosave, "folder", lambda: str(tmp_path))
    d = fitz.open()
    d.new_page()
    d.save(str(tmp_path / "a.pdf"))
    # a crashed session whose pid happens to equal ours
    (tmp_path / "a.json").write_text(_json.dumps(
        {"original": "", "title": "Untitled", "saved": "2026-10-16T10:00:00",
         "pages": 1, "pid": os.getpid(), "session": "old-session"}))
    assert [m["title"] for m in autosave.pending()] == ["Untitled"]
    # this session's own copy is still skipped
    (tmp_path / "a.json").write_text(_json.dumps(
        {"original": "", "title": "Untitled", "saved": "2026-10-16T10:00:00",
         "pages": 1, "pid": 999999, "session": autosave.SESSION}))
    assert autosave.pending() == []


def test_documents_panel_caches_page_counts_and_debounces(
        qapp, tmp_path, monkeypatch):
    from app import docks
    for n in ("A101.pdf", "S201.pdf"):
        d = fitz.open()
        d.new_page()
        d.save(str(tmp_path / n))
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    p.finish_counting()
    opened = []
    real = docks._page_count_uncached
    monkeypatch.setattr(docks, "_page_count_uncached",
                        lambda path: opened.append(path) or real(path))
    p.refresh()
    p.refresh()
    assert opened == []                 # counted once, then cached
    assert not p._pending
    calls = []
    monkeypatch.setattr(p, "refresh", lambda *a: calls.append(1))
    for ch in "A10":
        p.filter.setText(p.filter.text() + ch)
    assert calls == [] and p._filter_timer.isActive()
    p._filter_timer.timeout.emit()
    assert calls == [1]


def test_measurement_audit_records_revision():
    from app import audit, revisions
    d = fitz.open()
    d.new_page(width=600, height=400)
    op = annotate.new_op
    annotate.apply_op(d, op("set_scale", 0, ppu=10, unit="ft"))
    annotate.apply_op(d, op("add_polyline", 0, pts=[[10, 10], [110, 10]],
                            measure={"type": "length", "value": 10,
                                     "unit": "ft", "group": "Curb"}))
    revisions.record(d, "Addendum 1")
    annotate.apply_op(d, op("add_polyline", 0, pts=[[10, 50], [210, 50]],
                            measure={"type": "length", "value": 20,
                                     "unit": "ft", "group": "Walk"}))
    recs = {}
    for a in annotate.iter_annots(d[0]):
        s = (a.info or {}).get("subject", "")
        if s.startswith(annotate.TAKEOFF + ":"):
            recs[s.split(":")[4]] = annotate.audit_of(d, a)
    assert recs["Curb"].get("rev") == "Original"
    assert recs["Walk"].get("rev") == "Addendum 1"
    rows = {r["group"]: r["revision"] for r in audit.trail(d)}
    assert rows == {"Curb": "Original", "Walk": "Addendum 1"}


@pytest.mark.parametrize("mod", ["app", "tools"])
def test_escalation_caps_extrapolation_and_flags_fallback(mod):
    if mod == "app":
        from app import bls_core as core
    else:
        core = _tool("bls")
    pts = {"2024-01": 100.0, "2025-01": 110.0}
    r = core.escalation(pts, "2024-01", "2035-01")
    assert r["extrapolated"] == core.MAX_EXTRAPOLATE_MONTHS
    assert r["capped"] and any("capped" in w for w in r["warnings"])
    assert r["factor"] == pytest.approx(1.1 * 1.1 ** 2, rel=1e-6)
    r = core.escalation(pts, "2020-01", "2025-01")
    assert any("before the first" in w for w in r["warnings"])
    r = core.escalation(pts, "2024-01", "2025-01")
    assert r["warnings"] == [] and not r["capped"]


def test_documents_panel_waits_until_shown_and_counts_later(
        qapp, tmp_path, monkeypatch):
    """Start-up: a hidden Documents panel doesn't read the project folder,
    and when it does, names show at once and page counts follow."""
    from app import docks
    for n in ("C101.pdf", "C102.pdf", "C103.pdf", "C104.pdf"):
        d = fitz.open()
        for _ in range(2):
            d.new_page()
        d.save(str(tmp_path / n))
    walked = []
    real_scan = docks.os.scandir
    monkeypatch.setattr(docks.os, "scandir",
                        lambda *a, **k: walked.append(1) or real_scan(*a, **k))
    p = docks.DocumentsPanel(str(tmp_path))
    assert walked == [] and p.tree.topLevelItemCount() == 0
    p.refresh()
    items = [p.tree.topLevelItem(i) for i in range(p.tree.topLevelItemCount())]
    assert [i.text(0) for i in items] == ["C101.pdf", "C102.pdf", "C103.pdf",
                                          "C104.pdf"]
    assert all(i.text(1) == "…" for i in items)       # not opened yet
    p._count_some()
    assert [i.text(1) for i in items][:p.COUNT_BATCH] == ["2"] * p.COUNT_BATCH
    p.finish_counting()
    assert [i.text(1) for i in items] == ["2"] * 4


def test_documents_panel_skips_a_file_that_vanished(qapp, tmp_path,
                                                    monkeypatch):
    """A file deleted (or a share dropping out) between the folder walk and
    reading its date must not stop the listing or the page counting."""
    from app import docks
    for n in ("A1.pdf", "GONE.pdf", "A2.pdf"):
        d = fitz.open()
        d.new_page()
        d.save(str(tmp_path / n))
    real = docks._stat

    def flaky(entry):
        if entry.name == "GONE.pdf":
            raise FileNotFoundError(entry.path)
        return real(entry)
    monkeypatch.setattr(docks, "_stat", flaky)
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    names = [p.tree.topLevelItem(i).text(0)
             for i in range(p.tree.topLevelItemCount())]
    assert names == ["A1.pdf", "A2.pdf"]
    assert p._count_timer.isActive() or not p._pending
    p.finish_counting()
    assert [p.tree.topLevelItem(i).text(1) for i in range(2)] == ["1", "1"]


def test_documents_panel_skips_cloud_only_files(qapp, tmp_path, monkeypatch):
    """Grok F16: a OneDrive file that isn't on this PC is listed, but not
    opened (opening it would download it)."""
    from app import docks
    for n in ("HERE.pdf", "CLOUD.pdf"):
        d = fitz.open()
        d.new_page()
        d.save(str(tmp_path / n))
    monkeypatch.setattr(docks, "_cloud_only",
                        lambda st, path=None: str(path).endswith("CLOUD.pdf"))
    opened = []
    real = docks._page_count_uncached
    monkeypatch.setattr(docks, "_page_count_uncached",
                        lambda p: opened.append(p) or real(p))
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    p.finish_counting()
    rows = {p.tree.topLevelItem(i).text(0): p.tree.topLevelItem(i).text(1)
            for i in range(p.tree.topLevelItemCount())}
    assert rows["CLOUD.pdf"] == "—" and rows["HERE.pdf"] == "1"
    assert not any(x.endswith("CLOUD.pdf") for x in opened)


def test_documents_panel_keeps_collapsed_folders(qapp, tmp_path):
    """Grok F19: a folder you closed stays closed after a refresh."""
    from app import docks
    for sub in ("Civil", "Arch"):
        (tmp_path / sub).mkdir()
        d = fitz.open()
        d.new_page()
        d.save(str(tmp_path / sub / "S1.pdf"))
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    folders = {p.tree.topLevelItem(i).text(0): p.tree.topLevelItem(i)
               for i in range(p.tree.topLevelItemCount())}
    folders["Civil"].setExpanded(False)
    p.refresh()
    folders = {p.tree.topLevelItem(i).text(0): p.tree.topLevelItem(i)
               for i in range(p.tree.topLevelItemCount())}
    assert not folders["Civil"].isExpanded() and folders["Arch"].isExpanded()


def test_documents_panel_retries_after_a_failed_read(qapp, tmp_path,
                                                     monkeypatch):
    """Grok F1: if reading the folder fails, it's read again next time the
    panel is shown (not left half-listed for good)."""
    from app import docks
    d = fitz.open()
    d.new_page()
    d.save(str(tmp_path / "A.pdf"))
    p = docks.DocumentsPanel(str(tmp_path))

    def boom(*a, **k):
        raise PermissionError("share went away")
    p._fill_tree = boom
    p.refresh()                                    # no exception escapes
    assert p._stale is True
    del p._fill_tree
    p.refresh()
    assert p._stale is False and p.tree.topLevelItemCount() == 1



# ---- round 2 (Venice + Grok) ---------------------------------------------

def test_documents_panel_retries_an_unreachable_folder(qapp, tmp_path):
    """Grok N2 / Venice M3: a share that's offline says so and is read
    again next time - not "No project folder chosen." for good."""
    from app import docks
    job = tmp_path / "Job"
    p = docks.DocumentsPanel(str(job))         # not there (share offline)
    p.refresh()
    assert p._stale is True and "Can't reach" in p.label.text()
    job.mkdir()
    d = fitz.open()
    d.new_page()
    d.save(str(job / "C1.pdf"))
    p.refresh()                                # what showing it again does
    assert p._stale is False and p.tree.topLevelItemCount() == 1


def test_documents_panel_lists_deep_folders_and_says_when_it_stops(
        qapp, tmp_path):
    """Grok N3: a/b/c/d/e/L5.pdf is listed; past 8 levels there's a
    notice instead of silence."""
    from app import docks
    deep = tmp_path.joinpath("a", "b", "c", "d", "e")
    deep.mkdir(parents=True)
    d = fitz.open()
    d.new_page()
    d.save(str(deep / "L5.pdf"))
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    paths = [it.data(0, docks.Qt.UserRole) for it in
             p.tree.findItems("L5.pdf", docks.Qt.MatchRecursive)]
    assert paths and paths[0].endswith("L5.pdf")
    assert "levels down" not in p.label.text()
    too = tmp_path.joinpath(*"jklmnopqrs")       # 10 levels
    too.mkdir(parents=True)
    d.save(str(too / "Deep.pdf"))
    p.refresh()
    assert not p.tree.findItems("Deep.pdf", docks.Qt.MatchRecursive)
    assert "levels down" in p.label.text()


def test_documents_panel_unreadable_subfolder_is_noted_and_retried(
        qapp, tmp_path, monkeypatch):
    from app import docks
    (tmp_path / "Locked").mkdir()
    (tmp_path / "Open").mkdir()
    d = fitz.open()
    d.new_page()
    d.save(str(tmp_path / "Open" / "A.pdf"))
    real = docks.os.scandir

    def scan(path):
        if str(path).endswith("Locked"):
            raise PermissionError(path)
        return real(path)
    monkeypatch.setattr(docks.os, "scandir", scan)
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    assert p.tree.findItems("A.pdf", docks.Qt.MatchRecursive)
    assert "couldn't be read" in p.label.text() and p._stale is True


def test_documents_panel_hides_folders_with_no_drawings(qapp, tmp_path):
    """User session 0.12.8: empty folders showed as rows of bare arrows."""
    from app import docks
    (tmp_path / "Empty" / "Deeper").mkdir(parents=True)
    (tmp_path / "Specs").mkdir()
    (tmp_path / "Specs" / "notes.txt").write_text("x")
    (tmp_path / "Civil").mkdir()
    d = fitz.open()
    d.new_page()
    d.save(str(tmp_path / "Civil" / "C101.pdf"))
    p = docks.DocumentsPanel(str(tmp_path))
    p.refresh()
    tops = [p.tree.topLevelItem(i).text(0)
            for i in range(p.tree.topLevelItemCount())]
    assert tops == ["Civil"]
