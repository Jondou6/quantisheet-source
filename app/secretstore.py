"""Secrets kept encrypted for this Windows user (DPAPI).

set_secret()/get_secret() store a value in settings as "dpapi:<base64>",
encrypted with CryptProtectData for the signed-in Windows user, so a copy
of settings.json (backups, a synced folder, another account on the PC)
doesn't give the secret away. A plain value from an older version is
encrypted the first time it is read.

protect()/unprotect() do the same for raw bytes (the signing key's
passphrase). Off Windows there is no DPAPI: values stay as they were, and
a warning is logged once.
"""
import base64
import logging
import sys

from . import settings

log = logging.getLogger(__name__)
PREFIX = "dpapi:"
_warned = set()


class _DPAPI:
    """CryptProtectData / CryptUnprotectData, per user."""

    @staticmethod
    def protect(data):
        try:
            import win32crypt
            return win32crypt.CryptProtectData(data, "QuantiSheet", None,
                                               None, None, 0)
        except ImportError:
            return _ctypes_call("CryptProtectData", data)

    @staticmethod
    def unprotect(blob):
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]
        except ImportError:
            return _ctypes_call("CryptUnprotectData", blob)


def _ctypes_call(name, data):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = getattr(ctypes.windll.crypt32, name)
    if name == "CryptProtectData":
        ok = fn(ctypes.byref(src), "QuantiSheet", None, None, None, 0,
                ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(src), None, None, None, None, 0,
                ctypes.byref(out))
    if not ok:
        raise OSError(f"{name} failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _backend():
    """The encryption backend, or None where there is none (not Windows)."""
    return _DPAPI if sys.platform == "win32" else None


def available():
    return _backend() is not None


def _warn(what):
    if what not in _warned:
        _warned.add(what)
        log.warning("%s is not encrypted: Windows DPAPI isn't available on "
                    "this system, so it is stored as before.", what)


def protect(data, what="secret"):
    """bytes -> encrypted bytes, or None without DPAPI."""
    b = _backend()
    if b is None:
        _warn(what)
        return None
    return b.protect(bytes(data))


def unprotect(blob):
    b = _backend()
    if b is None:
        raise OSError("Windows DPAPI isn't available on this system.")
    return b.unprotect(bytes(blob))


def set_secret(key, value):
    value = value or ""
    if not value:
        settings.set(key, "")
        return
    blob = protect(value.encode("utf-8"), key)
    settings.set(key, value if blob is None else
                 PREFIX + base64.b64encode(blob).decode("ascii"))


def get_secret(key):
    raw = settings.get(key) or ""
    if not raw:
        return ""
    if raw.startswith(PREFIX):
        try:
            return unprotect(base64.b64decode(raw[len(PREFIX):])) \
                .decode("utf-8")
        except Exception:
            log.warning("could not decrypt %s (another Windows user or PC?)",
                        key, exc_info=True)
            return ""
    if available():                     # plain value from an older version
        set_secret(key, raw)
    else:
        _warn(key)
    return raw
