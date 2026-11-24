"""Beta tester licenses.

Every tester gets their own key, made by you with tools/beta_keys.py (or
make-tester-key.bat). A key names the tester and ends on a date, and it is
signed with your private signing key, which never leaves your computer and
is never shipped with the program. The program carries only the public
half, so it can check a key but nobody can make one.

What that gives you:
  * every installed copy shows who it is licensed to (title bar, About),
    so a copy that turns up somewhere else can be traced to its tester;
  * copies stop working on the key's end date, so a leaked build dies on
    its own; you send new keys to the testers you keep;
  * (no agreement to accept since 1.0.0 - Jon, Oct 30).

The installed (frozen) program requires a key. Running from the source
folder, as you do while developing, does not.
"""
import base64
import datetime as _dt
import json
import os
import sys

from . import settings

PREFIX = "PDFS1-"
_PUBKEY_FILE = "beta_pubkey.txt"


# ---- keys ---------------------------------------------------------------------
def _b64e(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _data_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "app", "data")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def public_key_text():
    try:
        with open(os.path.join(_data_dir(), _PUBKEY_FILE)) as f:
            return f.read().strip()
    except OSError:
        return ""


def make_key(private_key, name, email="", company="", days=90, kid=None,
             today=None):
    """A signed key string for one tester (`private_key` is an
    Ed25519PrivateKey)."""
    import secrets
    today = today or _dt.date.today()
    payload = {"n": name.strip(), "e": email.strip(), "c": company.strip(),
               "i": today.isoformat(),
               "x": (today + _dt.timedelta(days=int(days))).isoformat(),
               "k": kid or secrets.token_hex(3).upper()}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = private_key.sign(body)
    return PREFIX + _b64e(body) + "." + _b64e(sig)


class KeyError_(ValueError):
    pass


def parse(key, pubkey_text=None):
    """The key's details if its signature is good (expiry not checked),
    else raises KeyError_ with a plain reason."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PublicKey
    key = "".join((key or "").split())          # pasted with line breaks
    if not key.startswith(PREFIX) or "." not in key:
        raise KeyError_("That isn't a QuantiSheet beta key.")
    pub = pubkey_text if pubkey_text is not None else public_key_text()
    if not pub:
        raise KeyError_("This copy of QuantiSheet has no license checker. "
                        "Ask for a new installer.")
    try:
        body_s, sig_s = key[len(PREFIX):].split(".", 1)
        body, sig = _b64d(body_s), _b64d(sig_s)
        Ed25519PublicKey.from_public_bytes(_b64d(pub)).verify(sig, body)
        info = json.loads(body)
    except InvalidSignature:
        raise KeyError_("That key isn't valid. Check it was copied "
                        "completely.")
    except Exception:
        raise KeyError_("That key is damaged. Check it was copied "
                        "completely.")
    return info


def _seen_file():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return os.path.join(base, "QuantiSheet", ".seen")


def today():
    """Today, but never earlier than the latest day this program has seen
    (turning the PC's clock back doesn't revive an expired key). The day
    is kept in two places, so editing the settings file isn't enough."""
    t = _dt.date.today()
    seen = []
    for v in (settings.get("beta_seen"), _read_seen()):
        try:
            seen.append(_dt.date.fromisoformat(v))
        except (TypeError, ValueError):
            pass
    s = max(seen) if seen else None
    if s and s > t:
        return s
    if s != t:
        settings.set("beta_seen", t.isoformat())
        try:
            os.makedirs(os.path.dirname(_seen_file()), exist_ok=True)
            with open(_seen_file(), "w") as f:
                f.write(t.isoformat())
        except OSError:
            pass
    return t


def _read_seen():
    """The latest day kept in the clock file (and in the one kept under
    the old folder name before the rename - oldnames)."""
    from . import oldnames
    best = None
    for p in (_seen_file(), oldnames.old_seen_file()):
        if not p:
            continue
        try:
            with open(p) as f:
                v = f.read().strip()
            _dt.date.fromisoformat(v)
        except (OSError, ValueError):
            continue
        best = v if best is None or v > best else best
    return best


def check(key, pubkey_text=None, now=None):
    """(ok, info, message)."""
    try:
        info = parse(key, pubkey_text)
    except KeyError_ as e:
        return False, None, str(e)
    now = now or today()
    try:
        end = _dt.date.fromisoformat(info["x"])
    except Exception:
        return False, info, "That key is damaged."
    if now > end:
        return False, info, (f"The beta license for {info.get('n')} ended "
                             f"on {end:%B %d, %Y}. Ask for a new key.")
    return True, info, f"Licensed to {info.get('n')} until {end:%B %d, %Y}."


# Jon, Oct 16: in-house testing - no key needed for now. Set back to True
# before builds go outside the company.
KEY_REQUIRED = False


def store_package_name():
    """The full name of the Microsoft Store package this copy runs from
    ("<Name>_<version>_<arch>__<publisher id>"), or "" when it isn't
    running from one. Windows says so; a copy outside a package can't
    fake it."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        n = ctypes.c_uint32(0)
        k32 = ctypes.windll.kernel32
        if k32.GetCurrentPackageFullName(ctypes.byref(n), None) != 122:
            return ""                    # 15700: not in a package
        buf = ctypes.create_unicode_buffer(n.value)
        if k32.GetCurrentPackageFullName(ctypes.byref(n), buf) != 0:
            return ""
        return buf.value
    except Exception:                                     # noqa: BLE001
        return ""


def _is_store_copy(stamp, package=None):
    """build.json says "store" (written by tools/build_msix.py) and Windows
    says this copy runs from that Store package."""
    name = stamp.get("package") if isinstance(stamp, dict) else None
    if stamp.get("edition") != "store" or not name:
        return False
    full = store_package_name() if package is None else package
    if not full and package is None:
        full = _package_from_path(sys.executable)
    return bool(full) and full.startswith(name + "_")


def _package_from_path(exe):
    """Backup for store_package_name(): a Store app runs from
    ...\\WindowsApps\\<package full name>\\..., a folder only Windows'
    installer can write to. Returns that folder name, or ""."""
    root = os.path.normpath(os.path.join(
        os.environ.get("ProgramFiles") or r"C:\Program Files", "WindowsApps"))
    path = os.path.normpath(exe or "")
    if not os.path.normcase(path).startswith(os.path.normcase(root) + os.sep):
        return ""                    # only the protected Store folder
    return path[len(root) + 1:].split(os.sep)[0]


def edition():
    """'tester' (in-house builds), 'store' (the Microsoft Store copy) or
    'public' (builds for outside the company, e.g. GitHub). A public build
    always needs a key; the Store copy doesn't - the Store handles who gets
    it (Jon, Oct 30: "do whatever you think is best").

    Fails closed in an installed copy (Fable review M2): it is a tester
    build only if it carries the sealed company contact list (which the
    public build never has) and isn't marked public in build.json -
    deleting or editing build.json can't turn a public build into a
    tester one. From the source folder, build.json decides (default
    tester)."""
    data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    try:
        with open(os.path.join(data, "build.json"), encoding="utf-8") as f:
            stamp = json.load(f)
        marked = stamp.get("edition")
    except Exception:                                     # noqa: BLE001
        stamp, marked = {}, None
    if getattr(sys, "frozen", False):
        # an installed copy is a tester build only with the build PC's
        # signature on "tester" and this version (Venice review S4: an
        # empty contacts.sealed and a deleted build.json used to be
        # enough), plus the sealed contact list
        sealed = os.path.isfile(os.path.join(data, "contacts.sealed"))
        if sealed and tester_stamp_ok(stamp):
            return "tester"
        # the Store copy: no contact list, and only inside its package
        return "store" if not sealed and _is_store_copy(stamp) else "public"
    return marked or "tester"


def is_store():
    """This copy is the Microsoft Store one: no key, no "Beta" wording,
    no QuantiSheet printer (a Store package can't add
    a Windows printer)."""
    try:
        return edition() == "store"
    except Exception:                                     # noqa: BLE001
        return False


def stamp_body(version=None):
    from . import __version__
    return f"quantisheet-tester-build|{version or __version__}".encode()


def make_tester_stamp(private_key, version=None):
    """build.json for an in-house build (tools/build_installer.py)."""
    return {"edition": "tester", "version": version,
            "sig": _b64e(private_key.sign(stamp_body(version)))}


def tester_stamp_ok(stamp, pubkey_text=None):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PublicKey
        if stamp.get("edition") != "tester":
            return False
        pub = pubkey_text if pubkey_text is not None else public_key_text()
        Ed25519PublicKey.from_public_bytes(_b64d(pub)).verify(
            _b64d(stamp["sig"]), stamp_body())
        return True
    except Exception:                                     # noqa: BLE001
        return False


def required():
    """Installed copies need a key when KEY_REQUIRED is on or the build is
    a public one; the source folder never does (QUANTISHEET_BETA=1 forces
    the gate, for testing)."""
    if os.environ.get("QUANTISHEET_BETA") == "1":
        return True
    return (KEY_REQUIRED or edition() == "public") and \
        bool(getattr(sys, "frozen", False))


def _reg(name, value=None):
    """A copy in the current user's registry, so a reinstall or a cleared
    settings file doesn't ask for the key again (Jon, Oct 19)."""
    try:
        import winreg
        from . import oldnames
        path = oldnames.reg_cache()
        if value is None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                return str(winreg.QueryValueEx(k, name)[0])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except Exception:
        return ""
    return value


WARN_DAYS = 14          # warned for this long before the end
GRACE_DAYS = 14         # then opens read-only for this long, then refuses


def _all_keys():
    key = settings.get("beta_key") or _reg("k")
    out = [key] if key else []
    try:
        from . import policy
        it = policy.get("LicenseKey")
        if it:
            out.append(it)
    except Exception:                                     # noqa: BLE001
        pass
    return out


def phase(now=None):
    """(phase, info) for the best key on this PC (review 2, Nov 4 - warn,
    then read-only, then refuse; never stop mid-edit, never silently):
    "ok", "warn" (ends within WARN_DAYS), "readonly" (ended, within
    GRACE_DAYS: files open to look at, saving is off), "expired" (refuse
    to start), "none" (no key)."""
    now = now or today()
    best = None
    for key in _all_keys():
        try:
            info = parse(key)
            end = _dt.date.fromisoformat(info["x"])
        except Exception:                                 # noqa: BLE001
            continue
        if best is None or end > best[1]:
            best = (info, end)
    if best is None:
        return "none", None
    info, end = best
    left = (end - now).days
    if left < -GRACE_DAYS:
        return "expired", info
    if left < 0:
        return "readonly", info
    if left <= WARN_DAYS:
        return "warn", info
    return "ok", info


_READ_ONLY = {"on": False}


def read_only():
    """True while an ended license is in its read-only days."""
    return _READ_ONLY["on"]


READ_ONLY_MESSAGE = ("Your QuantiSheet license has ended, so saving is "
                     "turned off. You can still open and look at files. "
                     "Ask for a new key (Help > License) to keep working.")


def current():
    """The saved, valid license details, or None."""
    key = settings.get("beta_key") or _reg("k")
    if key:
        if not settings.get("beta_key"):
            settings.set("beta_key", key)
        ok, info, _ = check(key)
        if ok:
            return info
    # the IT department's key for every user of this PC (policy.py)
    from . import policy
    it_key = policy.get("LicenseKey")
    if it_key:
        ok, info, _ = check(it_key)
        if ok:
            return info
    return None


def accepted():
    """There is no agreement to accept any more (Jon, Oct 30: "Get rid of
    agreement"). Kept so older callers keep working."""
    return True


def label():
    """'Beta - licensed to Name (Company)' for the title bar, or ''.
    Never on the Store copy, even if a tester key is stored on the PC."""
    if is_store():
        return ""
    info = current()
    if not info:
        return ""
    who = info.get("n", "")
    if info.get("c"):
        who += f" ({info['c']})"
    return f"Beta · licensed to {who} · not for resale"


def days_left(info, now=None):
    now = now or today()
    return (_dt.date.fromisoformat(info["x"]) - now).days


# ---- the first-run dialog --------------------------------------------------------
def gate(parent=None):
    """Make sure there is a valid key. True to go on, False to quit. Does
    nothing when not required()."""
    if not required():
        return True
    if current():
        return True
    ph, _info = phase()
    if ph == "readonly":                 # ended lately: open, but no saves
        _READ_ONLY["on"] = True
        return True
    return LicenseDialog(parent).exec() == 1


def _dialog_classes():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                   QLabel, QPlainTextEdit, QTextBrowser,
                                   QVBoxLayout)
    return (Qt, QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
            QTextBrowser, QVBoxLayout)


def LicenseDialog(parent=None):
    (Qt, QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
     QTextBrowser, QVBoxLayout) = _dialog_classes()
    class _Dlg(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("QuantiSheet - License")
            self.resize(560, 300)
            lay = QVBoxLayout(self)
            head = QLabel("<h2 style='margin:0'>Welcome to QuantiSheet"
                          "</h2><p>Paste the license key you were sent to "
                          "start.</p>")
            head.setWordWrap(True)
            lay.addWidget(head)
            lay.addWidget(QLabel("License key:"))
            self.key = QPlainTextEdit()
            self.key.setPlaceholderText("PDFS1-…")
            self.key.setFixedHeight(70)
            old = settings.get("beta_key") or ""
            self.key.setPlainText(old)
            lay.addWidget(self.key)
            self.status = QLabel("")
            self.status.setWordWrap(True)
            lay.addWidget(self.status)
            bb = QDialogButtonBox()
            self.ok = bb.addButton("Start QuantiSheet",
                                   QDialogButtonBox.AcceptRole)
            bb.addButton("Quit", QDialogButtonBox.RejectRole)
            bb.accepted.connect(self._go)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.key.textChanged.connect(self._update)
            self._update()

        def _update(self):
            k = self.key.toPlainText().strip()
            if not k:
                self.status.setText("")
                good = False
            else:
                good, _, msg = check(k)
                color = "#2e7d32" if good else "#c62828"
                self.status.setText(f"<span style='color:{color}'>{msg}"
                                    "</span>")
            self.ok.setEnabled(good)

        def _go(self):
            k = "".join(self.key.toPlainText().split())
            ok, info, _ = check(k)
            if not ok:
                return
            settings.set("beta_key", k)
            _reg("k", k)
            if not settings.get("author") and info.get("n"):
                settings.set("author", info["n"])
            self.accept()
    return _Dlg()
