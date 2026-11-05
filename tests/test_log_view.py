"""Log tail and the LogViewer dialog (app/log_view.py). Offscreen Qt."""
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton          # noqa: E402

LOG = """\
2026-11-04 12:00:00,001 DEBUG quantisheet: dbg
2026-11-04 12:00:01,002 INFO quantisheet: hello
2026-11-04 12:00:02,003 WARNING quantisheet: low disk
2026-11-04 12:00:03,004 ERROR quantisheet: broke
Traceback (most recent call last):
  File "example.py", line 1, in <module>
ValueError: sample
2026-11-04 12:00:04,005 CRITICAL quantisheet: stop
2026-11-04 12:00:05,006 WARNING quantisheet: again
"""


def _log(tmp_path, monkeypatch, text=LOG):
    from app import log_view
    path = tmp_path / "quantisheet.log"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(log_view, "log_path", lambda: str(path))
    return path


def test_tail_keeps_warning_and_above_with_the_traceback(tmp_path, monkeypatch):
    from app import log_view
    _log(tmp_path, monkeypatch)
    lines = log_view.tail(10)
    text = "\n".join(lines)
    assert "hello" not in text and "dbg" not in text
    assert "low disk" in text
    assert "ValueError: sample" in text
    assert "again" in text
    assert lines[0].startswith("2026-11-04 12:00:02,003 WARNING")


def test_tail_n_is_records_and_level_can_be_raised(tmp_path, monkeypatch):
    from app import log_view
    _log(tmp_path, monkeypatch)
    # last two records: CRITICAL "stop", WARNING "again" — no traceback
    lines = log_view.tail(2)
    assert len(lines) == 2
    assert lines[0].endswith("stop") and lines[1].endswith("again")
    errors = log_view.tail(10, level="ERROR")
    assert any(ln.endswith("broke") for ln in errors)
    assert any("ValueError: sample" in ln for ln in errors)
    assert not any("low disk" in ln for ln in errors)
    assert not any("again" in ln for ln in errors)


def test_tail_missing_log_and_bad_level(tmp_path, monkeypatch):
    from app import log_view
    monkeypatch.setattr(log_view, "log_path",
                        lambda: str(tmp_path / "missing.log"))
    assert log_view.tail(5) == []
    assert log_view.tail(0) == []
    try:
        log_view.tail(5, level="NOISE")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown level was accepted")


def test_log_path_prefers_the_logging_setup_then_the_log_folder(
        tmp_path, monkeypatch):
    from app import log_view
    import app.main as main_mod
    path = tmp_path / "quantisheet.log"
    path.write_text("", encoding="utf-8")
    handler = logging.FileHandler(str(path), encoding="utf-8")
    logger = logging.getLogger("quantisheet")
    logger.addHandler(handler)
    try:
        assert log_view.log_path() == handler.baseFilename
    finally:
        logger.removeHandler(handler)
        handler.close()
    monkeypatch.setattr(log_view, "_from_logging", lambda: "")
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(tmp_path / "other"))
    assert log_view.log_path() == os.path.join(
        str(tmp_path / "other"), "quantisheet.log")


def test_viewer_refresh_and_copy(tmp_path, monkeypatch):
    from app import log_view
    path = _log(tmp_path, monkeypatch,
                "2026-11-04 12:00:00,001 WARNING quantisheet: first warning\n"
                "2026-11-04 12:00:01,002 INFO quantisheet: ignore me\n")
    app = QApplication.instance() or QApplication([])
    dialog = log_view.LogViewer()
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    assert set(buttons) >= {"Copy", "Refresh"}
    shown = dialog.view.toPlainText()
    assert "first warning" in shown
    assert "ignore me" not in shown
    path.write_text(
        "2026-11-04 12:00:00,001 WARNING quantisheet: first warning\n"
        "2026-11-04 12:00:02,003 ERROR quantisheet: second problem\n",
        encoding="utf-8")
    buttons["Refresh"].click()
    assert "second problem" in dialog.view.toPlainText()
    app.clipboard().clear()
    buttons["Copy"].click()
    assert "second problem" in app.clipboard().text()
    dialog.close()
    dialog.deleteLater()


def test_viewer_says_when_nothing_is_at_the_level(tmp_path, monkeypatch):
    from app import log_view
    _log(tmp_path, monkeypatch,
         "2026-11-04 12:00:01,002 INFO quantisheet: only info\n")
    app = QApplication.instance() or QApplication([])
    dialog = log_view.LogViewer()
    assert "no log lines" in dialog.view.toPlainText()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
