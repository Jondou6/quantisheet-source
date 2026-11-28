"""A PDF dragged out of an Outlook message onto QuantiSheet
(app/outlookdrop.py), Nov 27. Made-up names and bytes only."""
import os
import struct

import pytest

from app import outlookdrop as od

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _descriptor(*names):
    out = struct.pack("<I", len(names))
    for n in names:
        raw = n.encode("utf-16-le")
        out += b"\x00" * 72 + raw + b"\x00" * (520 - len(raw))
    return out


class Mime:
    """The two things a mail program's drag carries."""

    def __init__(self, names=(), data=None, extra=()):
        self._d = {}
        if names:
            self._d[od.NAMES] = _descriptor(*names)
        if data is not None:
            self._d[od.BYTES] = data
        for k in extra:
            self._d[k] = b"x"

    def hasFormat(self, f):
        return f in self._d

    def data(self, f):
        return self._d[f]

    def formats(self):
        return list(self._d)


def test_the_names_of_what_is_dragged_are_read():
    m = Mime(["A-101 Made-up Plan.pdf", "Bid form.docx", "Addendum 2.PDF"])
    assert od.names(m) == ["A-101 Made-up Plan.pdf", "Bid form.docx",
                           "Addendum 2.PDF"]
    assert od.pdf_names(m) == ["A-101 Made-up Plan.pdf", "Addendum 2.PDF"]
    assert od.names(Mime(extra=["text/plain"])) == []
    assert od.parse_names(b"") == [] and od.parse_names(b"\x05\0\0\0") == []
    # a count that lies about how many names follow is not followed
    assert od.parse_names(struct.pack("<I", 9999) + b"\0" * 80) == []


def test_one_pdf_whose_bytes_come_with_the_drag_is_saved(tmp_path):
    paths, wait = od.save(Mime(["Made-up Plan.pdf"], PDF), str(tmp_path))
    assert wait == [] and paths == [str(tmp_path / "Made-up Plan.pdf")]
    assert open(paths[0], "rb").read() == PDF
    # the same name again keeps both
    paths2, _ = od.save(Mime(["Made-up Plan.pdf"], PDF), str(tmp_path))
    assert os.path.basename(paths2[0]) == "Made-up Plan (2).pdf"


def test_only_pdfs_and_nothing_that_only_claims_to_be(tmp_path):
    assert od.save(Mime(["Bid form.docx"], b"PK..."), str(tmp_path)) == \
        ([], [])
    # named .pdf but not a PDF: not saved from the drag; Outlook is asked
    paths, wait = od.save(Mime(["page.pdf"], b"<html>"), str(tmp_path))
    assert paths == [] and wait == ["page.pdf"]
    assert os.listdir(tmp_path) == []
    # a name can't leave the folder
    paths, _ = od.save(Mime(["..\\..\\evil.pdf"], PDF), str(tmp_path))
    assert os.path.dirname(paths[0]) == str(tmp_path)


class Att:
    def __init__(self, name, data=PDF):
        self.FileName = name
        self._data = data

    def SaveAsFile(self, path):
        with open(path, "wb") as f:
            f.write(self._data)


class Coll:
    def __init__(self, items):
        self._i = list(items)
        self.Count = len(self._i)

    def Item(self, n):
        return self._i[n - 1]


class Window:
    def __init__(self, selected=None, item_atts=None, reading=None):
        if selected is not None:
            self.AttachmentSelection = Coll(selected)
        if item_atts is not None:
            self.CurrentItem = type("I", (), {"Attachments":
                                              Coll(item_atts)})()
        if reading is not None:
            item = type("I", (), {"Attachments": Coll(reading)})()
            self.Selection = Coll([item])


def _outlook(win):
    return lambda: type("App", (), {"ActiveWindow": lambda self: win})()


def test_several_dragged_at_once_come_from_outlook_after_the_drop(tmp_path):
    m = Mime(["A-101.pdf", "Notes.docx", "A-102.pdf"], PDF)
    paths, wait = od.save(m, str(tmp_path))
    assert paths == [] and wait == ["A-101.pdf", "A-102.pdf"]
    win = Window(selected=[Att("A-101.pdf"), Att("Notes.docx", b"PK"),
                           Att("A-102.pdf")])
    got = od.later(wait, str(tmp_path), _outlook(win))
    assert sorted(os.path.basename(p) for p in got) == ["A-101.pdf",
                                                        "A-102.pdf"]
    assert sorted(os.listdir(tmp_path)) == ["A-101.pdf", "A-102.pdf"]


def test_nothing_selected_uses_the_open_messages_attachments(tmp_path):
    win = Window(selected=[], item_atts=[Att("Addendum 1.pdf"),
                                         Att("logo.png", b"\x89PNG")])
    got = od.later(["Addendum 1.pdf"], str(tmp_path), _outlook(win))
    assert [os.path.basename(p) for p in got] == ["Addendum 1.pdf"]
    read = Window(reading=[Att("Addendum 2.pdf")])       # the reading pane
    got = od.later(["Addendum 2.pdf"], str(tmp_path), _outlook(read))
    assert [os.path.basename(p) for p in got] == ["Addendum 2.pdf"]


def test_what_outlook_saves_must_be_a_pdf_and_trouble_is_not_an_error(
        tmp_path):
    win = Window(selected=[Att("fake.pdf", b"MZ not a pdf")])
    assert od.later(["fake.pdf"], str(tmp_path), _outlook(win)) == []
    assert os.listdir(tmp_path) == []

    def gone():
        raise OSError("Outlook isn't running")
    assert od.later(["x.pdf"], str(tmp_path), gone) == []


def test_the_running_outlook_is_joined_and_never_started():
    """Nov 28: Windows lists a running Outlook for other programs only
    some of the time. When it isn't listed but is running, it is asked
    for by name (that joins the running one); when it isn't running,
    nothing is started."""
    class Client:
        def __init__(self, listed):
            self.listed, self.calls = listed, []

        def GetActiveObject(self, name):              # noqa: N802
            self.calls.append("listed?")
            if not self.listed:
                raise OSError("not listed")
            return "the running Outlook"

        def Dispatch(self, name):                     # noqa: N802
            self.calls.append("by name")
            return "the running Outlook, joined"
    c = Client(True)
    assert od._running_outlook(c, lambda: True) == "the running Outlook"
    assert c.calls == ["listed?"]
    c = Client(False)
    assert od._running_outlook(c, lambda: True) == \
        "the running Outlook, joined"
    c = Client(False)
    with pytest.raises(OSError):
        od._running_outlook(c, lambda: False)
    assert c.calls == ["listed?"]                 # never started

    class R:
        stdout = '"OUTLOOK.EXE","4321","Console","1","250,000 K"\n'
    assert od._outlook_is_running(lambda *a, **k: R())
    R.stdout = "INFO: No tasks are running which match the criteria.\n"
    assert not od._outlook_is_running(lambda *a, **k: R())

    def boom(*a, **k):
        raise OSError("no tasklist")
    assert not od._outlook_is_running(boom)


def test_the_window_takes_a_mail_drag(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    import fitz
    from PySide6.QtCore import QMimeData, QPoint, Qt
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app import browserhost, settings
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(browserhost, "folder", lambda: str(tmp_path / "dl"))
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Made-up plan from an email")
    data = doc.tobytes()
    doc.close()
    from app.main_window import MainWindow
    w = MainWindow()
    try:
        mime = QMimeData()
        mime.setData(od.NAMES, _descriptor("Made-up Bid Set.pdf"))
        mime.setData(od.BYTES, data)
        assert w._mail_pdfs(mime) == ["Made-up Bid Set.pdf"]
        ev = QDropEvent(QPoint(50, 50), Qt.CopyAction, mime, Qt.LeftButton,
                        Qt.NoModifier)
        w.dropEvent(ev)
        assert ev.isAccepted()
        assert os.path.normcase(w._path) == os.path.normcase(
            str(tmp_path / "dl" / "Made-up Bid Set.pdf"))
        other = QMimeData()                      # a Word file: not taken
        other.setData(od.NAMES, _descriptor("Bid form.docx"))
        assert w._mail_pdfs(other) == []
    finally:
        for i in range(w.tabs.count()):
            v = getattr(w.tabs.widget(i), "view", None)
            if v is not None:
                v.dirty = False
        w.close()
        app.processEvents()


def test_a_whole_email_dragged_brings_its_pdfs(tmp_path):
    """Nov 28: an email dragged from the message list, not its attachment."""
    m = Mime(["Made-up addendum notice.msg"])
    assert od.pdf_names(m) == [] and od.wanted(m) == [od.WHOLE]
    assert od.save(m, str(tmp_path)) == ([], [od.WHOLE])
    mail1 = type("I", (), {"Attachments": Coll(
        [Att("Addendum 3.pdf"), Att("image001.png", b"\x89PNG"),
         Att("fake.pdf", b"MZ")])})()
    meeting = type("I", (), {})()                # nothing attached to it
    mail2 = type("I", (), {"Attachments": Coll([Att("A-201.PDF")])})()
    win = type("W", (), {"Selection": Coll([mail1, meeting, mail2])})()
    got = od.later([od.WHOLE], str(tmp_path), _outlook(win))
    assert [os.path.basename(p) for p in got] == ["Addendum 3.pdf",
                                                  "A-201.pdf"]
    assert "fake.pdf" not in os.listdir(tmp_path)
    assert "image001.png" not in os.listdir(tmp_path)
    # an email open in its own window
    one = Window(item_atts=[Att("Bid form.pdf"), Att("Notes.docx", b"PK")])
    got = od.later([od.WHOLE], str(tmp_path), _outlook(one))
    assert [os.path.basename(p) for p in got] == ["Bid form.pdf"]
    # an email with no PDF, and Outlook not there: nothing, no error
    none = Window(item_atts=[Att("Notes.docx", b"PK")])
    assert od.later([od.WHOLE], str(tmp_path), _outlook(none)) == []

    def gone():
        raise OSError("no Outlook")
    assert od.later([od.WHOLE], str(tmp_path), gone) == []
    # a PDF dragged along with an email: the PDF by name, as before
    both = Mime(["Note.msg", "A-101.pdf"])
    assert od.wanted(both) == ["A-101.pdf"]
    # anything else is still not taken
    assert od.wanted(Mime(["Bid form.docx"])) == []


def test_no_more_than_ten_emails_from_one_drag(tmp_path):
    mails = [type("I", (), {"Attachments": Coll([Att(f"P{i}.pdf")])})()
             for i in range(14)]
    win = type("W", (), {"Selection": Coll(mails)})()
    got = od.later([od.WHOLE], str(tmp_path), _outlook(win))
    assert len(got) == od.MAX_MAILS


def test_the_log_reader_leaves_file_names_out():
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "diag_maillog", os.path.join(here, "tools", "diag_maillog.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = ("10:00 INFO app.outlookdrop: mail drop: 1 PDF came with the "
            "drag itself\n10:01 INFO x: something else\n"
            "10:02 INFO app.outlookdrop: mail drag not opened (Made-up "
            "Job A-101.pdf); it carried: FileGroupDescriptorW\n")
    got = mod.lines(text)
    assert len(got) == 2 and "Made-up" not in got[1]
    assert "it carried: FileGroupDescriptorW" in got[1]
