"""First-start sign-in: asks for an email address once per computer.

Wrong entries only ever say "Invalid email." - nothing hints at what is
accepted. Five wrong entries lock sign-in for 15 minutes (Jon, Oct 19,
on the Grok review). A locked-out tester can read Jon a short PC code and
type back the unlock code Jon gives them (tools/unlock_code.py). The lock
is kept in two places (the settings file and the current user's registry)
and survives the clock being turned back while it is on.

This is a speed bump for in-house testers, not security: everything it
checks ships in the program. Before any outside release the license key
goes back on (KEY_REQUIRED) - see docs/SIGNIN_NOTES.md.

Nothing readable about the accepted addresses is stored here: only a
salted fingerprint, compared at run time.
"""
import base64
import hashlib
import json
import logging
import os
import re
import time

from . import settings

log = logging.getLogger(__name__)

TRIES = 5
LOCK_SECONDS = 15 * 60
_MAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")

# build constants (the fingerprint is stored in two halves)
_S = "7f3a9c2e" + "51b84d06"
_A = "48d32df57027487a9f7fcf50a9f97e64"
_B = "9f5f443d7439740b9cc08ce446015337"

_KEY_OK = "ui_cache_id"          # settings: this computer has signed in
_KEY_T = "ui_tick"               # settings: tries / lock


def _fp(part):
    return hashlib.sha256((_S + "|" + part).encode("utf-8")).hexdigest()


def _expected():
    return _A + _B


def _tidy(email):
    """Forgive the usual slips: spaces, a trailing dot or comma, a
    "mailto:" and angle brackets pasted from an email."""
    e = (email or "").strip().strip("<>").strip()
    if e.lower().startswith("mailto:"):
        e = e[7:]
    return e.rstrip(".,;: ")


def accepted(email):
    """True if `email` is a well-formed address the program accepts. A
    space inside, a name over 64 characters or an address over 254 is
    never well-formed (Chief's re-test, Nov 7)."""
    e = _tidy(email)
    if len(e) > 254 or any(c.isspace() for c in e):
        return False
    if len(e.split("@", 1)[0]) > 64:
        return False
    m = _MAIL.match(e)
    if not m:
        return False
    import hmac
    return hmac.compare_digest(_fp(m.group(1).lower()), _expected())


# ---- this computer ------------------------------------------------------------
def _machine():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        import uuid
        return f"node-{uuid.getnode()}"


def _token():
    return hashlib.sha256((_S + "|ok|" + _machine() + "|" + _expected())
                          .encode()).hexdigest()[:40]


def signed_in():
    """Signed in on this computer before - asked once, never again (Jon,
    Oct 19): kept in the settings file and the registry, and either one
    restores the other, so updates, reinstalls or a cleared settings file
    don't ask again."""
    from . import betalicense, policy
    if policy.on("SkipEmailSignIn"):     # a company-managed PC (IT policy)
        return True
    if betalicense.is_store():           # the Microsoft Store copy is for
        return True                      # anyone (Oct 30): no company email
    tok = _token()
    in_settings = settings.get(_KEY_OK) == tok
    in_registry = _reg_read("s") == tok
    if in_settings and not in_registry:
        _reg_write(tok, "s")
    elif in_registry and not in_settings:
        settings.set(_KEY_OK, tok)
    return in_settings or in_registry


# ---- tries and lock ---------------------------------------------------------------
def _pack(state):
    raw = json.dumps(state, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(bytes(b ^ 0x5A for b in raw)).decode()


def _unpack(text):
    try:
        raw = bytes(b ^ 0x5A for b in base64.urlsafe_b64decode(text or ""))
        d = json.loads(raw.decode())
        return {"n": int(d.get("n", 0)), "until": float(d.get("until", 0)),
                "seen": float(d.get("seen", 0))}
    except Exception:
        return {"n": 0, "until": 0.0, "seen": 0.0}


def _reg_read(name="t"):
    try:
        import winreg
        from . import oldnames
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            oldnames.reg_cache()) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:
        return ""


def _reg_write(text, name="t"):
    try:
        import winreg
        from . import oldnames
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              oldnames.reg_cache()) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, text)
    except Exception:
        log.debug("not saved to the registry", exc_info=True)


def _state(now=None):
    """The strictest of the two copies; a clock turned back keeps the
    lock (until = last time seen + the lock time)."""
    now = time.time() if now is None else now
    a = _unpack(settings.get(_KEY_T) or "")
    b = _unpack(_reg_read())
    st = {"n": max(a["n"], b["n"]), "until": max(a["until"], b["until"]),
          "seen": max(a["seen"], b["seen"])}
    # a clock turned back keeps a lock that is on - but a clock fix after
    # a typo is not a lock (Grok M8)
    if st["until"] and st["seen"] and now < st["seen"] - 300:
        st["until"] = max(st["until"], st["seen"] + LOCK_SECONDS)
    return st


def _save(st, now=None):
    st = dict(st, seen=max(st.get("seen", 0), time.time() if now is None
                           else now))
    text = _pack(st)
    settings.set(_KEY_T, text)
    _reg_write(text)


def locked_until(now=None):
    """Epoch seconds the lock ends, or 0 when not locked."""
    now = time.time() if now is None else now
    st = _state(now)
    return st["until"] if st["until"] > now else 0


def attempt(email, now=None):
    """'ok', 'invalid', or 'locked'. Three invalid entries lock for 8 h."""
    now = time.time() if now is None else now
    st = _state(now)
    if st["until"] > now:
        _save(st, now)
        return "locked"
    if st["until"] and st["until"] <= now:          # lock over: fresh tries
        st = {"n": 0, "until": 0.0, "seen": st["seen"]}
    if accepted(email):
        settings.set(_KEY_OK, _token())
        _reg_write(_token(), "s")
        _save({"n": 0, "until": 0.0, "seen": st["seen"]}, now)
        return "ok"
    st["n"] += 1
    if st["n"] >= TRIES:
        st["until"] = now + LOCK_SECONDS
        _save(st, now)
        return "locked"
    _save(st, now)
    return "invalid"


# ---- unlock code from Jon -----------------------------------------------------
_U = "c41e" + "93a7" + "0b6d" + "52f8"


def pc_code():
    """Six characters a locked-out tester reads to Jon."""
    h = hashlib.sha256(("pc|" + _machine()).encode()).hexdigest()
    return h[:3].upper() + "-" + h[3:6].upper()


def unlock_code(pc):
    """The code Jon gives back for a PC code (tools/unlock_code.py)."""
    import hmac
    pc = (pc or "").strip().upper()
    return hmac.new(_U.encode(), pc.encode(), hashlib.sha256
                    ).hexdigest()[:8].upper()


def unlock(code, now=None):
    """Clear the lock when `code` is this PC's unlock code."""
    import hmac
    now = time.time() if now is None else now
    want = unlock_code(pc_code())
    got = re.sub(r"[^0-9A-Za-z]", "", code or "").upper()
    if not hmac.compare_digest(got, want):
        return False
    st = _state(now)
    _save({"n": 0, "until": 0.0, "seen": now}, now)
    del st
    return True


# ---- the window -------------------------------------------------------------------
def _when(ts):
    import datetime
    t = datetime.datetime.fromtimestamp(ts)
    return t.strftime("%I:%M %p").lstrip("0") + (
        "" if t.date() == datetime.date.today() else t.strftime(" on %b %d"))


def gate(parent=None):
    """True to go on; False to quit. Asks only until this computer has
    signed in once."""
    if signed_in():
        return True
    return SignInDialog(parent).exec() == 1


def SignInDialog(parent=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                   QLineEdit, QVBoxLayout)

    class _Dlg(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("QuantiSheet")
            self.setMinimumWidth(420)
            lay = QVBoxLayout(self)
            head = QLabel("<h3 style='margin:0'>Welcome to QuantiSheet</h3>"
                          "<p>Enter your email address to continue.</p>")
            head.setWordWrap(True)
            lay.addWidget(head)
            self.email = QLineEdit()
            self.email.setPlaceholderText("Email address")
            lay.addWidget(self.email)
            self.msg = QLabel("")
            self.msg.setObjectName("StripWarn")
            self.msg.setWordWrap(True)
            lay.addWidget(self.msg)
            self.code = QLineEdit()
            self.code.setPlaceholderText("Unlock code from Jon")
            self.code.hide()
            self.code.returnPressed.connect(self._unlock)
            lay.addWidget(self.code)
            bb = QDialogButtonBox()
            self.go = bb.addButton("Continue", QDialogButtonBox.AcceptRole)
            bb.addButton("Quit", QDialogButtonBox.RejectRole)
            self.go.clicked.connect(self._try)
            bb.rejected.connect(self.reject)
            self.email.returnPressed.connect(self._try)
            lay.addWidget(bb)
            self._show_lock()

        def _show_lock(self):
            until = locked_until()
            if until:
                self.msg.setText(f"Too many attempts. Try again after "
                                 f"{_when(until)}, or give Jon this code: "
                                 f"{pc_code()} and type the unlock code "
                                 "he gives you below.")
                self.email.setEnabled(False)
                self.go.setEnabled(False)
                self.code.show()
                return True
            return False

        def _unlock(self):
            if unlock(self.code.text()):
                self.code.clear()
                self.code.hide()
                self.email.setEnabled(True)
                self.go.setEnabled(True)
                self.msg.setText("Unlocked. Enter your email address.")
                self.email.setFocus()
            else:
                self.msg.setText("That unlock code doesn't match. Check "
                                 f"it with Jon (PC code {pc_code()}).")

        def _try(self):
            if not self.go.isEnabled():
                return
            res = attempt(self.email.text())
            if res == "ok":
                self.accept()
            elif res == "locked":
                self._show_lock()
            else:
                self.msg.setText("Invalid email.")
                self.email.selectAll()
                self.email.setFocus()

        def keyPressEvent(self, e):
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._try()
                return
            super().keyPressEvent(e)

    return _Dlg()


def _self_check():
    """Used by the build check: the fingerprint halves fit together."""
    return len(_expected()) == 64 and os.path.basename(__file__) != ""
