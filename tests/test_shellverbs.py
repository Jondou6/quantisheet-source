"""Nov 3 (#1): File Explorer right-click actions. Made-up files."""
import os

import fitz
import pytest

from app import shellverbs as SV

HERE = os.path.dirname(os.path.abspath(__file__))


def _pdf(path, text, pages=1):
    d = fitz.open()
    for i in range(pages):
        d.new_page().insert_text((72, 72), f"{text} {i}")
    d.save(path)
    return path


def test_parse():
    assert SV.parse(["qs.exe", "--qs-reduce", '"C:\\a b.pdf"']) == (
        SV.REDUCE, "C:\\a b.pdf")
    assert SV.parse(["qs.exe", "C:\\a.pdf"]) is None
    assert SV.parse(["qs.exe", "--qs-convert"]) is None


def test_reduce_writes_beside_and_keeps_the_original(tmp_path):
    src = _pdf(str(tmp_path / "Plan.pdf"), "PLAN", 3)
    before = open(src, "rb").read()
    out, a, b = SV.reduce(src)
    assert os.path.basename(out) == "Plan (reduced).pdf"
    assert open(src, "rb").read() == before and a > 0 and b > 0
    assert os.path.basename(SV.reduce(src)[0]) == "Plan (reduced 2).pdf"


def test_combine_folder_in_name_order(tmp_path):
    for n in ("A-10.pdf", "A-2.pdf", "A-1.pdf"):
        _pdf(str(tmp_path / n), n)
    (tmp_path / "notes.txt").write_text("x")
    doc, files = SV.combine_folder(str(tmp_path))
    assert [os.path.basename(f) for f in files] == ["A-1.pdf", "A-2.pdf",
                                                    "A-10.pdf"]
    assert doc.page_count == 3 and [t[1] for t in doc.get_toc()] == [
        "A-1", "A-2", "A-10"]


def test_run_in_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    opened = []

    class W:
        def open_document(self, doc, title):
            opened.append(title)
    _pdf(str(tmp_path / "A.pdf"), "A")
    assert SV.run_in_window(W(), SV.COMBINE, str(tmp_path))
    assert opened == [f"{tmp_path.name} - Combined.pdf"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert SV.run_in_window(W(), SV.COMBINE, str(empty)) is None


def test_installer_adds_the_verbs():
    iss = open(os.path.join(HERE, "..", "installer", "quantisheet.iss"),
               encoding="utf-8", errors="replace").read()
    assert 'Name: "shellverbs"' in iss
    for key in ("SystemFileAssociations\\.pdf\\shell\\QuantiSheet.Reduce",
                "SystemFileAssociations\\.docx\\shell\\QuantiSheet.Convert",
                "Directory\\shell\\QuantiSheet.Combine",
                "Directory\\Background\\shell\\QuantiSheet.Combine"):
        assert key in iss, key
    assert "--qs-combine-folder" in iss and "--qs-reduce" in iss
    assert "Adobe" not in iss and "Bluebeam" not in iss
