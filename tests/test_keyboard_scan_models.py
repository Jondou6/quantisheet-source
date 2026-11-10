"""Nov 5: keyboard-only audit of the main dialogs, Check Scan Quality
(Document menu) and Local AI Models (Review menu)."""
import io
import os
import sys

import fitz
import pytest
from PIL import Image, ImageDraw

from test_gui import ANSWERS, win, qapp                       # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))


def _scan_pdf(path, dpi, tilt=0.0):
    w_px, h_px = int(8.5 * dpi), int(11 * dpi)
    im = Image.new("L", (w_px, h_px), 255)
    d = ImageDraw.Draw(im)
    for i in range(30):
        y = int(h_px * 0.1) + i * int(h_px * 0.025)
        d.rectangle([int(w_px * 0.1), y, int(w_px * 0.85),
                     y + max(int(dpi * 0.06), 2)], fill=0)
    if tilt:
        im = im.rotate(tilt, fillcolor=255, expand=False)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    doc = fitz.open()
    doc.new_page(width=612, height=792).insert_image(
        fitz.Rect(0, 0, 612, 792), stream=buf.getvalue())
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 72), "A typed page, not a scan")
    doc.save(path)
    doc.close()
    return path


def test_keyboard_audit_finds_an_unreachable_button(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton, \
        QVBoxLayout
    from app import a11y
    d = QDialog()
    lay = QVBoxLayout(d)
    ok, bad, field = QPushButton("OK"), QPushButton("Hidden from Tab"), \
        QLineEdit()
    field.setAccessibleName("Name")
    bad.setFocusPolicy(Qt.NoFocus)
    for x in (field, ok, bad):
        lay.addWidget(x)
    d.show()
    assert a11y.tab_chain(d)[:2] == [field, ok]
    assert a11y.keyboard_audit(d) == [("QPushButton", "Hidden from Tab",
                                       "Tab never reaches it")]
    d.close()


def test_main_dialogs_are_keyboard_reachable(win, tmp_path):
    import keyboard_audit
    w = win
    path = _scan_pdf(str(tmp_path / "kbd_scan.pdf"), 150)
    assert w.open_path(path)
    lines = []
    found = keyboard_audit.run(w, report=lines.append)
    assert len(found) >= 16
    assert not any(found.values()), "\n".join(lines)


def test_scan_quality_flags_coarse_and_passes_good(tmp_path):
    from app import scan_check
    with fitz.open(_scan_pdf(str(tmp_path / "coarse.pdf"), 100)) as doc:
        res = scan_check.check(doc, languages=["eng"])
    first, second = res["pages"]
    assert first["scan"] and first["dpi"] == 100
    assert any("100 DPI" in r for r in first["reasons"])
    assert not second["scan"] and second["reasons"] == []
    assert res["scans"] == 1 and res["poor"] == 1
    assert "1 of 1 scanned page(s) may read badly" in \
        scan_check.summary(res)[0]
    good = fitz.open(_scan_pdf(str(tmp_path / "good.pdf"), 300))
    res = scan_check.check(good, languages=["eng"])
    assert res["pages"][0]["dpi"] == 300 and res["poor"] == 0
    assert abs(res["pages"][0]["skew"]) < 1
    with fitz.open(_scan_pdf(str(tmp_path / "tilt.pdf"), 300,
                             tilt=5)) as tilted:
        res = scan_check.check(tilted, languages=["eng"])
    assert res["poor"] == 1 and abs(res["pages"][0]["skew"]) >= 2
    # a missing language pack is said once, for the whole check
    res = scan_check.check(good, languages=["spa"])
    assert res["languages"] and "English" in res["languages"][0]
    assert scan_check.check(good, limit=0, languages=["eng"])["skipped"] == 2
    good.close()


def test_scan_quality_on_the_document_menu(win, tmp_path):
    w = win
    a = w.command("Check Scan Quality")
    assert a is not None
    assert w.open_path(_scan_pdf(str(tmp_path / "s.pdf"), 100))
    dlg = w.scan_quality(languages=["eng"])
    assert dlg.isVisible() and dlg.table.rowCount() == 1
    assert dlg.table.item(0, 1).text() == "100"
    dlg.go(0)
    dlg.close()


def test_local_ai_models_window(win):
    from app.ai import models
    w = win
    assert w.command("Local AI Models") is not None
    inv = models.Inventory(
        [models.InstalledModel("llama3.2:3b", 2 * models.GB,
                               parameter_size="3.2B", quantization="Q4_K_M",
                               family="llama")],
        2 * models.GB, models.DiskSpace("C:\\", 500 * models.GB,
                                        100 * models.GB),
        models.recommend_size(16 * models.GB))
    dlg = w.ai_models(fetch=lambda: inv)
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 0).text() == "llama3.2:3b"
    assert "1 model(s) installed" in dlg.status.text()
    assert "ollama pull" in dlg.advice.text()

    def down():
        raise models.OllamaError("connection refused")
    dlg.fetch = down
    assert dlg.refresh() is None
    assert "isn't answering" in dlg.status.text()
    assert dlg.table.rowCount() == 0

    def far():
        raise models.NotLocalError("Only this PC's AI can be listed.")
    dlg.fetch = far
    dlg.refresh()
    assert "only reads the model list" in dlg.status.text()
    dlg.close()
