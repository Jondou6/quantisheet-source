"""On big sets, whole-set jobs (Auto-Markup, exports, redaction search) run
on a worker thread with a progress box instead of freezing the window."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def _sync_bg(monkeypatch):
    from app import bg
    calls = []

    def run(fn, ok, err, owner):
        calls.append(fn)
        try:
            ok(fn())
        except Exception as e:                  # pragma: no cover
            err(str(e))
    monkeypatch.setattr(bg, "run", run)
    return calls


def test_auto_markup_big_set_runs_off_thread(win, monkeypatch):
    from app import main_window, rules
    calls = _sync_bg(monkeypatch)
    monkeypatch.setattr(main_window.MainWindow, "BIG_SET", 0)
    monkeypatch.setattr(main_window.QMessageBox, "information",
                        lambda *a, **k: 0)
    seen = {}

    def find(doc):
        seen["doc"] = doc
        return []
    monkeypatch.setattr(rules, "find_marks", find)
    win.auto_markup()
    assert calls and seen["doc"] is not win._view.doc


def test_export_word_big_set_runs_off_thread(win, monkeypatch, tmp_path):
    from app import main_window
    calls = _sync_bg(monkeypatch)
    monkeypatch.setattr(main_window.MainWindow, "BIG_SET", 0)
    out = str(tmp_path / "x.docx")
    monkeypatch.setattr(win, "_ask_save", lambda *a, **k: out)
    assert win.export_as("docx") == out
    assert calls and os.path.getsize(out) > 0


def test_word_export_skips_tables_on_drawing_sheets(monkeypatch, tmp_path):
    from app import acrobat
    d = fitz.open()
    d.new_page(width=2448, height=1584)          # 34 x 22 in sheet
    d[0].insert_text((100, 100), "GENERAL NOTES")
    monkeypatch.setattr(acrobat, "_tables", lambda p: (_ for _ in ()).throw(
        AssertionError("tables searched on a drawing sheet")))
    acrobat.export_word(d, str(tmp_path / "d.docx"))


def test_redaction_search_waits_and_runs_off_thread(qapp, monkeypatch):
    from app import acrobat_dialogs
    calls = _sync_bg(monkeypatch)
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 72), f"call 555-123-456{i}")
    monkeypatch.setattr(acrobat_dialogs.RedactDialog, "BIG", 0)
    dlg = acrobat_dialogs.RedactDialog(d)
    dlg.text.setText("call")                      # typing: no search yet
    assert not calls and dlg.result.text() == "Searching..."
    dlg._timer.timeout.emit()                      # typing paused
    assert calls and len(dlg.hits) == 3 and dlg.go.isEnabled()
