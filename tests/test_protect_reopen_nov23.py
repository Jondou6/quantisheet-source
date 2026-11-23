"""A password-protected PDF reopens with its pages showing, and Remove
Security writes a copy that opens without a password (Nov 23, Chief: video
62 - reading needs_pass after authenticate() dropped MuPDF's key). Also the
signing times in Signature Requests show in local time."""
import datetime as dt
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from test_gui import win, qapp, ANSWERS  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def _protected(path, pw="Example-pw-1"):
    d = fitz.open()
    p = d.new_page()
    p.insert_textbox(fitz.Rect(54, 54, 558, 300),
                     "PROTECTED SAMPLE SHEET A-101\nExample text.",
                     fontsize=18)
    p.draw_rect(fitz.Rect(100, 400, 500, 700), color=(0, 0, 0), width=4)
    d.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pw,
           owner_pw="Example-owner-2", permissions=int(fitz.PDF_PERM_PRINT))
    d.close()
    return str(path)


def _ink(page):
    pix = page.get_pixmap(dpi=40)
    s = pix.samples
    return sum(1 for i in range(0, len(s), pix.n) if s[i] < 128)


def test_reopen_with_password_and_remove_security(win, tmp_path):
    from test_gui import ANSWERS
    path = _protected(tmp_path / "locked.pdf")
    ANSWERS["text"] = "Example-pw-1"
    assert win.open_path(path)
    doc = win._view.doc
    win._view._base_bytes()                  # what every open does
    assert "PROTECTED SAMPLE SHEET" in doc[0].get_text()
    assert _ink(doc[0]) > 50                 # not a blank page
    out = str(tmp_path / "locked_unlocked.pdf")
    ANSWERS["save"] = out
    assert win.unprotect() == out
    d = fitz.open(out)
    assert not d.needs_pass
    assert "PROTECTED SAMPLE SHEET" in d[0].get_text()
    assert _ink(d[0]) > 50
    d.close()


def test_signing_time_is_local():
    from app.esign_ui import local_time
    stamp = "2026-11-23T16:28:00Z"
    want = dt.datetime(2026, 11, 23, 16, 28,
                       tzinfo=dt.timezone.utc).astimezone()
    got = local_time(stamp)
    assert got.startswith(f"Nov {want.day}, 2026 ")
    assert got.endswith(("AM", "PM")) and f":{want:%M}" in got
    assert local_time("not a time") == "not a time"
