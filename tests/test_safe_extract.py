"""Extract a PDF attachment into a fresh temp directory, or refuse it."""
import os
import tempfile
import stat

import fitz
import pytest

from app.safe_extract import DENY_EXT, ExtractError, extract

_BLOCKED = (
    ".exe", ".lnk", ".bat", ".js", ".vbs", ".ps1", ".scr", ".cmd",
    ".msi", ".com", ".hta", ".jar",
)


def _doc():
    d = fitz.open()
    d.new_page()
    return d


def test_embedded_pdf_is_written_and_not_executed(tmp_path):
    doc = _doc()
    payload = b"%PDF-1.4 made-up attachment"
    doc.embfile_add("specs/note.pdf", payload, filename="specs/note.pdf")
    path = extract(doc, "specs/note.pdf", [".pdf"])
    assert os.path.isfile(path)
    assert os.path.basename(path) == "note.pdf"
    assert os.path.basename(os.path.dirname(path)).startswith(
        "quantisheet-extract-")
    # the test reads it; extract() does not open it again
    with open(path, "rb") as f:
        assert f.read() == payload
    assert stat.S_IMODE(os.stat(path).st_mode) & 0o111 == 0
    # a second call gets its own directory
    again = extract(doc, "note.pdf", "pdf")
    assert os.path.dirname(again) != os.path.dirname(path)
    assert os.path.basename(again) == "note.pdf"


def test_file_attachment_annotation(tmp_path):
    doc = _doc()
    doc[0].add_file_annot((72, 72), b"photo-bytes", "site.png")
    path = extract(doc, "site.png", {".png", ".pdf"})
    with open(path, "rb") as f:
        assert f.read() == b"photo-bytes"
    assert os.path.basename(path) == "site.png"


def test_blocked_extensions_never_win_the_allow_list():
    for ext in _BLOCKED:
        assert ext in DENY_EXT
        doc = _doc()
        name = "payload" + ext
        doc.embfile_add(name, b"MZ", filename=name)
        before = set(os.listdir(tempfile.gettempdir()))
        with pytest.raises(ExtractError, match="blocked"):
            extract(doc, name, [ext, ".pdf"])
        doc.close()
    # a dangerous extension hiding in front of an allowed one
    doc = _doc()
    doc.embfile_add("report.exe.pdf", b"x", filename="report.exe.pdf")
    with pytest.raises(ExtractError, match="blocked"):
        extract(doc, "report.exe.pdf", [".pdf"])
    doc = _doc()
    doc.embfile_add("Report.PDF.EXE", b"x", filename="Report.PDF.EXE")
    with pytest.raises(ExtractError, match="blocked"):
        extract(doc, "report.pdf.exe", [".pdf", ".exe"])


def test_allow_list_and_missing_name():
    doc = _doc()
    doc.embfile_add("note.txt", b"hello", filename="note.txt")
    with pytest.raises(ExtractError, match="allow-list"):
        extract(doc, "note.txt", [".pdf"])
    with pytest.raises(ExtractError, match="allow-list"):
        extract(doc, "note.txt", [])
    with pytest.raises(ExtractError, match="No attachment"):
        extract(doc, "missing.pdf", [".pdf"])
    with pytest.raises(ExtractError):
        extract("some.pdf", "note.txt", [".txt"])
    with pytest.raises(ExtractError):
        extract(doc, "note.txt", None)


def test_path_traversal_stays_in_the_temp_dir(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not touch")
    doc = _doc()
    doc.embfile_add("..\\..\\secret.txt", b"inside-the-pdf",
                    filename="..\\..\\secret.txt")
    path = extract(doc, "..\\..\\secret.txt", [".txt"])
    assert os.path.basename(path) == "secret.txt"
    assert os.path.realpath(path).startswith(
        os.path.realpath(os.path.dirname(path)))
    assert not os.path.realpath(path).startswith(os.path.realpath(tmp_path))
    assert secret.read_text() == "do not touch"
    with open(path, "rb") as f:
        assert f.read() == b"inside-the-pdf"

    doc2 = _doc()
    doc2.embfile_add("C:\\Windows\\note.pdf", b"pdf-bytes",
                     filename="C:\\Windows\\note.pdf")
    path = extract(doc2, "C:\\Windows\\note.pdf", ".pdf")
    assert os.path.basename(path) == "note.pdf"
    assert os.sep + "Windows" + os.sep not in path

    doc3 = _doc()
    doc3.embfile_add("\\\\server\\share\\note.pdf", b"pdf-bytes",
                     filename="\\\\server\\share\\note.pdf")
    path = extract(doc3, "\\\\server\\share\\note.pdf", [".pdf"])
    assert os.path.dirname(path) != "" and os.path.basename(path) == "note.pdf"


def test_bad_names_are_refused():
    doc = _doc()
    doc.embfile_add("ok.pdf", b"x", filename="ok.pdf")
    for name in ("note.pdf:hidden.exe", "note.pdf\x00.exe", "CON.pdf",
                 "nul.txt", "..", ""):
        # the stored file is ok.pdf; asking for a bad name fails closed
        with pytest.raises(ExtractError):
            extract(doc, name, [".pdf", ".txt", ".exe"])
    doc2 = _doc()
    doc2.embfile_add("CON.txt", b"x", filename="CON.txt")
    with pytest.raises(ExtractError):
        extract(doc2, "CON.txt", [".txt"])


def test_source_does_not_launch_anything():
    import app.safe_extract as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for word in ("subprocess", "startfile", "webbrowser", "os.system", "Popen"):
        assert word not in src


def test_size_limit():
    """Nov 4: the gap noted on PR 15 - no attachment over the limit."""
    doc = _doc()
    doc.embfile_add("big.pdf", b"%PDF-1.4\n" + b"0" * 5000,
                    filename="big.pdf")
    with pytest.raises(ExtractError, match="too big"):
        extract(doc, "big.pdf", ".pdf", max_bytes=1000)
    assert extract(doc, "big.pdf", ".pdf")
