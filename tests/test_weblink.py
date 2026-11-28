"""quantisheet://open?path=... links (the browser add-on): only ever a PDF
that is already on this computer. Made-up files."""
import os
from urllib.parse import quote

from app import weblink


def _link(path):
    return "quantisheet://open?path=" + quote(path, safe="")


def test_a_saved_pdf_opens(tmp_path):
    p = tmp_path / "QuantiSheet" / "A-101 Made-up Plan.pdf"
    p.parent.mkdir()
    p.write_bytes(b"%PDF-1.4 made-up")
    assert weblink.path_from(_link(str(p))) == os.path.normpath(str(p))
    assert weblink.path_from('"' + _link(str(p)) + '"') == \
        os.path.normpath(str(p))
    assert weblink.path_from("QuantiSheet://open/?path=" +
                             quote(str(p), safe="")) == \
        os.path.normpath(str(p))
    assert weblink.files(["QuantiSheet.exe", _link(str(p)), "x.pdf"]) == [
        os.path.normpath(str(p))]


def test_everything_else_is_ignored(tmp_path):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    for bad in (_link(str(exe)),                          # not a PDF
                _link(str(tmp_path / "missing.pdf")),     # not there
                _link("a.pdf"),                           # not a full path
                _link("\\\\server\\share\\a.pdf"),        # network path
                _link("//server/share/a.pdf"),
                _link("https://example.com/a.pdf"),       # a web address
                _link(str(tmp_path)),                     # a folder
                "quantisheet://run?path=" + quote(str(pdf), safe=""),
                "quantisheet://open?file=" + quote(str(pdf), safe=""),
                "https://open?path=" + quote(str(pdf), safe=""),
                "quantisheet://open?path=" + "A" * 3000,
                "quantisheet://open", "", None, 5):
        assert weblink.path_from(bad) is None, bad
    assert weblink.files(["QuantiSheet.exe", str(pdf), "--new-window"]) == []


def test_setup_and_store_package_register_the_link_type():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    iss = open(os.path.join(root, "installer", "quantisheet.iss"),
               encoding="utf-8-sig").read()
    assert 'Subkey: "Software\\Classes\\quantisheet"; ValueType: string; ' \
           'ValueName: "URL Protocol"' in iss
    assert 'Software\\Classes\\quantisheet\\shell\\open\\command"' in iss
    msix = open(os.path.join(root, "tools", "build_msix.py"),
                encoding="utf-8").read()
    assert '<uap:Protocol Name="quantisheet">' in msix


def _launcher():
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "qs_launcher", os.path.join(root, "quantisheet.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_launcher_gives_a_link_to_the_desktop_app(monkeypatch):
    """Nov 25: Windows starts QuantiSheet.exe "quantisheet://open?..."; the
    launcher sent that to the command-line tools, which stopped with exit
    code 2 before anything opened."""
    import sys
    m = _launcher()
    got = {}
    import app.main
    import app.cli
    monkeypatch.setattr(app.main, "run", lambda argv: got.setdefault(
        "gui", list(argv)) and 0)
    monkeypatch.setattr(app.cli, "main", lambda args: got.setdefault(
        "cli", list(args)) and 2)
    monkeypatch.setattr(m, "_attach_windows_console", lambda: None)
    monkeypatch.setattr(m, "_convert_old_files", lambda: None)
    link = "quantisheet://open?path=C%3A%5CMade-up%5Cplan.pdf"
    monkeypatch.setattr(sys, "argv", ["QuantiSheet.exe", link])
    m.main()
    assert got == {"gui": ["QuantiSheet.exe", link]}
    got.clear()
    monkeypatch.setattr(sys, "argv", ["QuantiSheet.exe", "QUANTISHEET://x"])
    m.main()
    assert "gui" in got
    got.clear()                       # anything else is still a command
    monkeypatch.setattr(sys, "argv", ["QuantiSheet.exe", "info", link])
    m.main()
    assert "cli" in got and "gui" not in got
