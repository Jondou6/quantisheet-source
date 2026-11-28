"""The browser add-on's direct line (app/browserhost.py), Nov 26: Jon's
browser asked where to save every download the add-on started, and
nothing reached QuantiSheet. Made-up data only."""
import base64
import io
import json
import os
import struct

from app import browserhost as bh

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _wire(*msgs):
    out = b""
    for m in msgs:
        body = json.dumps(m).encode()
        out += struct.pack("<I", len(body)) + body
    return io.BytesIO(out)


def _replies(buf):
    buf.seek(0)
    out = []
    while True:
        m = bh.read_message(buf)
        if m is None:
            return out
        out.append(m)


def _send(tmp_path, *msgs):
    opened = []
    rx = bh.Receiver(where=str(tmp_path), opener=opened.append)
    out = io.BytesIO()
    assert bh.serve(_wire(*msgs), out, rx) == 0
    return _replies(out), opened


def test_a_pdf_sent_in_pieces_is_saved_and_opened(tmp_path):
    a, b = PDF[:20], PDF[20:]
    got, opened = _send(
        tmp_path, {"type": "hello"},
        {"type": "begin", "name": "A-101 Made-up Plan.pdf"},
        {"type": "data", "b64": base64.b64encode(a).decode()},
        {"type": "data", "b64": base64.b64encode(b).decode()},
        {"type": "end"})
    assert got[0]["ok"] and got[0]["version"]
    assert got[2] == {"ok": True, "got": 20}
    assert got[3] == {"ok": True, "got": len(PDF)}
    path = got[4]["path"]
    assert got[4]["ok"] and opened == [path]
    assert path == str(tmp_path / "A-101 Made-up Plan.pdf")
    assert open(path, "rb").read() == PDF
    assert os.listdir(tmp_path) == ["A-101 Made-up Plan.pdf"]


def test_the_same_name_twice_keeps_both(tmp_path):
    one = [{"type": "begin", "name": "plan.pdf"},
           {"type": "data", "b64": base64.b64encode(PDF).decode()},
           {"type": "end"}]
    got, opened = _send(tmp_path, *(one + one))
    assert [os.path.basename(p) for p in opened] == ["plan.pdf",
                                                     "plan (2).pdf"]


def test_only_a_pdf_is_ever_written(tmp_path):
    got, opened = _send(
        tmp_path, {"type": "begin", "name": "page.pdf"},
        {"type": "data",
         "b64": base64.b64encode(b"<html>Sign in</html>").decode()},
        {"type": "end"})
    assert got[1] == {"ok": False, "error": "not a PDF"}
    assert not got[2]["ok"] and not opened
    assert os.listdir(tmp_path) == []


def test_the_name_cannot_leave_the_folder_or_change_the_kind_of_file():
    assert bh.safe_name("..\\..\\Windows\\evil.exe") == "evil.exe.pdf"
    assert bh.safe_name("../../x/run.bat") == "run.bat.pdf"
    assert bh.safe_name("D:\\Made-up\\Plans\\a.pdf") == "a.pdf"
    assert bh.safe_name('A<1>:"plan"?.PDF') == "A_1___plan__.pdf"
    assert bh.safe_name("") == "document.pdf"
    assert bh.safe_name("con.pdf") == "_con.pdf"
    assert len(bh.safe_name("x" * 500)) == 124


def test_a_half_sent_file_is_not_kept(tmp_path):
    got, opened = _send(
        tmp_path, {"type": "begin", "name": "plan.pdf"},
        {"type": "data", "b64": base64.b64encode(PDF[:20]).decode()})
    assert os.listdir(tmp_path) == [] and not opened   # the pipe closed
    got, opened = _send(
        tmp_path, {"type": "begin", "name": "plan.pdf"},
        {"type": "data", "b64": base64.b64encode(PDF).decode()},
        {"type": "abort"}, {"type": "end"})
    assert got[2] == {"ok": True} and not got[3]["ok"]
    assert os.listdir(tmp_path) == [] and not opened


def test_bad_messages_are_refused_without_writing(tmp_path, monkeypatch):
    got, opened = _send(tmp_path, {"type": "data", "b64": "AAAA"},
                        {"type": "end"}, {"type": "run", "cmd": "calc"},
                        {"type": "begin", "name": "p.pdf"},
                        {"type": "data", "b64": "not base64!"})
    assert [g["ok"] for g in got] == [False, False, False, True, False]
    assert os.listdir(tmp_path) == [] and not opened
    monkeypatch.setattr(bh, "MAX_BYTES", 60)
    big = base64.b64encode(PDF + b"x" * 40).decode()
    got, opened = _send(tmp_path, {"type": "begin", "name": "p.pdf"},
                        {"type": "data", "b64": big})
    assert got[1] == {"ok": False, "error": "too large"}
    assert os.listdir(tmp_path) == []


def test_the_launcher_knows_a_browser_started_it():
    assert bh.is_host_call(
        ["chrome-extension://klfflmcmedeghfecpbdmfajjhdbhigap/",
         "--parent-window=0"])
    assert not bh.is_host_call(["C:\\Made-up\\plan.pdf"])
    assert not bh.is_host_call(["quantisheet://open?path=x"])
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "quantisheet.py")).read()
    assert src.index("_is_browser(sys.argv[1:])") < \
        src.index("_convert_old_files()\n    args")


def test_setup_registers_the_line_for_the_add_on_only():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = json.load(open(os.path.join(root, "installer", "browser-host.json")))
    assert m["name"] == bh.NAME and m["type"] == "stdio"
    assert m["path"] == "QuantiSheet.exe"
    assert m["allowed_origins"] and "*" not in json.dumps(m)
    ext = json.load(open(os.path.join(root, "browser_extension",
                                      "manifest.json")))
    import hashlib
    der = base64.b64decode(ext["key"])
    ident = "".join(chr(ord("a") + int(c, 16))
                    for c in hashlib.sha256(der).hexdigest()[:32])
    assert f"chrome-extension://{ident}/" in m["allowed_origins"]
    iss = open(os.path.join(root, "installer", "quantisheet.iss")).read()
    for browser in ("Google\\Chrome", "BraveSoftware\\Brave-Browser",
                    "Microsoft\\Edge"):
        assert (f'Software\\{browser}\\NativeMessagingHosts\\'
                'com.quantisheet.open"') in iss
    assert 'Source: "browser-host.json"; DestDir: "{app}"' in iss


def test_it_can_turn_the_add_ons_line_and_links_off(tmp_path, monkeypatch):
    """Nov 28: policy DisableBrowserAddon. The line says so (the add-on
    then tells the user, and does not try another way), and the add-on's
    quantisheet:// links open nothing."""
    from app import policy, weblink
    assert "DisableBrowserAddon" in policy.SETTINGS if hasattr(
        policy, "SETTINGS") else True
    monkeypatch.setattr(policy, "on",
                        lambda name: name == "DisableBrowserAddon")
    got, opened = _send(
        tmp_path, {"type": "hello"}, {"type": "begin", "name": "p.pdf"},
        {"type": "data", "b64": base64.b64encode(PDF).decode()},
        {"type": "end"})
    assert all(g == {"ok": False, "off": True,
                     "error": "turned off by your IT department"}
               for g in got) and len(got) == 4
    assert os.listdir(tmp_path) == [] and not opened
    real = tmp_path / "plan.pdf"
    real.write_bytes(PDF)
    from urllib.parse import quote
    link = "quantisheet://open?path=" + quote(str(real), safe="")
    assert weblink.files(["QuantiSheet.exe", link]) == []
    monkeypatch.setattr(policy, "on", lambda name: False)
    assert weblink.files(["QuantiSheet.exe", link]) == [str(real)]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ext = os.path.join(root, "browser_extension")
    assert "hello.off" in open(os.path.join(ext, "direct.js")).read()
    assert "if (r.off) {" in open(os.path.join(ext, "sw.js")).read()


def test_what_an_interrupted_hand_off_left_is_cleared_after_a_day(tmp_path):
    """Nov 28: a half-sent file and the takeoff notes of a PDF that is
    gone. Only those; never a PDF, never anything newer than a day."""
    import time
    from app import browserhost as bh, webmarks
    assert bh._NOTE == ".pdf" + webmarks.SUFFIX
    old = time.time() - 3 * 24 * 3600

    def make(name, aged=True):
        p = tmp_path / name
        p.write_bytes(b"x")
        if aged:
            os.utime(p, (old, old))
        return p

    part = make(".4321-Made-up Plan.pdf.part")
    new_part = make(".4322-Made-up Plan.pdf.part", aged=False)
    orphan = make("Gone Plan.pdf.qsweb.json")
    new_orphan = make("Gone Plan (2).pdf.qsweb.json", aged=False)
    kept_pdf = make("Kept Plan.pdf")
    kept_note = make("Kept Plan.pdf.qsweb.json")
    other = make("notes.txt")
    lookalike = make("my.part")
    assert bh.tidy(str(tmp_path)) == 2
    assert not part.exists() and not orphan.exists()
    for p in (new_part, new_orphan, kept_pdf, kept_note, other, lookalike):
        assert p.exists()
    assert bh.tidy(str(tmp_path / "not there")) == 0
    # it runs when the next PDF starts to arrive
    part2 = make(".9-Old.pdf.part")
    rx = bh.Receiver(where=str(tmp_path), opener=lambda p: None)
    assert rx.handle({"type": "begin", "name": "New.pdf"})["ok"]
    assert not part2.exists()
    rx.handle({"type": "abort"})
