"""Accessibility check and PDF/A export."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import accessibility, pdfa                          # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def _doc(pages=3, text=True):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page()
        if text:
            p.insert_text((72, 72), f"Page {i + 1} SPECIFICATIONS")
    p = d[0]
    a = p.add_rect_annot(fitz.Rect(100, 100, 200, 150))
    a.update()
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "project_name"
    w.rect = fitz.Rect(100, 300, 300, 320)
    p.add_widget(w)
    return d


def test_accessibility_check_and_fix(tmp_path):
    d = _doc()
    res = {r["rule"]: r for r in accessibility.check(d)}
    assert not res["title"]["ok"] and res["title"]["fix"]
    assert not res["language"]["ok"]
    assert not res["field_names"]["ok"] and not res["annot_text"]["ok"]
    assert not res["tagged"]["ok"] and res["tagged"]["fix"]
    done = accessibility.fix(d, title="Spec Book")
    assert any("Title" in x for x in done)
    res = {r["rule"]: r for r in accessibility.check(d)}
    assert any("Tagged" in x for x in done)
    for k in ("tagged", "title", "language", "tab_order", "field_names",
              "annot_text"):
        assert res[k]["ok"], k
    assert d.metadata["title"] == "Spec Book"
    blank = fitz.open()
    blank.new_page()
    r = {x["rule"]: x for x in accessibility.check(blank)}
    assert not r["text"]["ok"] and "Make Searchable" in r["text"]["detail"]


def test_pdfa_export_builtin(tmp_path):
    d = _doc()
    d.embfile_add("quantisheet_proposal.json", b'{"x": 1}')
    out = str(tmp_path / "a.pdf")
    res = pdfa.export(d, out, use_ghostscript=False)
    assert res["method"] == "built-in"
    o = fitz.open(out)
    assert "pdfaid:part>3" in o.get_xml_metadata()
    assert "quantisheet_proposal.json" in o.embfile_names()   # job data kept
    for p in o:
        for a in p.annots():
            assert a.flags & fitz.PDF_ANNOT_IS_PRINT
    probs = [m for m, _ in pdfa.check(o)]
    assert not any("metadata" in m for m in probs)


def test_accessibility_window(qapp, win):
    dlg = win.accessibility_check(show=False)
    assert dlg.table.rowCount() == len(accessibility.RULES)
    if dlg.b_fix.isEnabled():
        dlg.fix()
        assert not any(r["fix"] for r in dlg.results)
    assert win.command("Accessibility Check") is not None
    assert win.command("PDF/A (archival)") is not None
    assert win.command("Preflight / PDF/X") is not None
    assert win.command("Request Signatures") is not None
