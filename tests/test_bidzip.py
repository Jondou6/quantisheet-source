"""Nov 3 (#3): a plan room .zip opened as a job. Made-up files."""
import io
import os
import zipfile

import fitz
import pytest

from app import bidzip


def _pdf(text, big=False, pages=1):
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=2592 if big else 612, height=1728 if big
                        else 792)
        pg.insert_text((72, 72), f"{text} {i + 1}", fontsize=12)
    return d.tobytes()


def _zip(path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("Addendum 01.pdf", _pdf("ADDENDUM NO. 1"))
        z.writestr("A-201 Elevations.pdf", _pdf("ELEVATIONS", big=True))
    plan = _pdf("PLAN", big=True, pages=2)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Bid Set/A-101 Floor Plan.pdf", plan)
        z.writestr("Bid Set/Copy of A-101.pdf", plan)
        z.writestr("Project Manual.pdf", _pdf("SECTION 09 21 16 GYPSUM"))
        z.writestr("Bid Form.docx", b"not a pdf")
        z.writestr("addenda.zip", inner.getvalue())
        z.writestr("../evil.pdf", _pdf("X"))
    return path


def test_unpack_sorts_dedupes_and_lists(tmp_path):
    z = _zip(str(tmp_path / "Job.zip"))
    job = tmp_path / "Job"
    rep = bidzip.unpack(z, str(job))
    names = {k: sorted(os.path.basename(p) for p in v)
             for k, v in rep["files"].items()}
    assert names["Drawings"] == ["A-101 Floor Plan.pdf",
                                 "A-201 Elevations.pdf"]
    assert names["Specs"] == ["Project Manual.pdf"]
    assert names["Addenda"] == ["Addendum 01.pdf"]
    assert names["Other"] == ["Bid Form.docx"]
    assert [os.path.basename(p) for p in rep["not_pdf"]] == ["Bid Form.docx"]
    assert len(rep["duplicates"]) == 1
    assert rep["skipped"] and "outside" in rep["skipped"][0][1]
    assert not (tmp_path / "evil.pdf").exists()
    out, n = bidzip.combine(rep["files"]["Drawings"],
                            str(job / "Drawings" / "Set.pdf"))
    assert n == 3 and len(fitz.open(out).get_toc()) == 2
    t = bidzip.report_text(rep)
    assert "Drawings: 2" in t and "Bid Form.docx" in t


def test_bad_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"nope")
    with pytest.raises(bidzip.ZipJobError):
        bidzip.unpack(str(p), str(tmp_path / "j"))


def test_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    from app.main_window import MainWindow
    w = MainWindow()
    rep = w.open_bid_zip(_zip(str(tmp_path / "J.zip")), str(tmp_path / "J"),
                         setup=False, project=False)
    assert rep["combined"] and w._view.doc.page_count == 3
    w._view.dirty = False
    w.close()
    w.deleteLater()
