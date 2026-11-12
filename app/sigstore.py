"""Where your drawn signature is kept (Nov 11).

It used to sit in settings.json as plain text, readable by anything that
could read the file. It is now kept in its own file in the settings
folder, encrypted by Windows for your Windows account (DPAPI): another
user of the PC, or a copy of the file on another computer, can't open it.
A signature found in settings.json is moved here the first time it is
asked for.

On a system without DPAPI (not Windows) the file is kept unencrypted and
marked so; QuantiSheet ships for Windows.
"""
import base64
import json
import logging
import os
import sys

from . import settings

log = logging.getLogger(__name__)
KINDS = ("signature", "initials")
MAGIC_DPAPI, MAGIC_PLAIN = b"QSSIG1\n", b"QSSIG0\n"
_ENTROPY = b"QuantiSheet drawn signature"


def path(kind):
    return os.path.join(settings.DIR, f"{kind}.sig")


def protected():
    """Is the signature encrypted for this Windows account here?"""
    return sys.platform == "win32"


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    src, ent, out = blob(data), blob(_ENTROPY), BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(src), None,
                                      ctypes.byref(ent), None, None, 0x01,
                                      ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(src), None,
                                        ctypes.byref(ent), None, None, 0x01,
                                        ctypes.byref(out))
    if not ok:
        raise OSError("Windows could not " + ("protect" if protect else
                                              "open") + " the signature.")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _valid(data):
    return isinstance(data, dict) and bool(data.get("strokes"))


def save(kind, data):
    """Keep the drawn signature (the dict signature.py makes)."""
    if kind not in KINDS:
        raise ValueError(f"Not a signature kind: {kind!r}")
    if not _valid(data):
        raise ValueError("There is nothing drawn to keep.")
    raw = json.dumps(data).encode("utf-8")
    if protected():
        body = MAGIC_DPAPI + base64.b64encode(_dpapi(raw, True))
    else:
        body = MAGIC_PLAIN + base64.b64encode(raw)
    os.makedirs(settings.DIR, exist_ok=True)
    tmp = path(kind) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path(kind))
    if settings.get(kind) is not None:      # no plain copy left behind
        settings.set(kind, None)


def _read(kind):
    try:
        with open(path(kind), "rb") as f:
            body = f.read()
    except OSError:
        return None
    try:
        if body.startswith(MAGIC_DPAPI):
            raw = _dpapi(base64.b64decode(body[len(MAGIC_DPAPI):]), False)
        elif body.startswith(MAGIC_PLAIN):
            raw = base64.b64decode(body[len(MAGIC_PLAIN):])
        else:
            return None
        data = json.loads(raw.decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        # another Windows account's file, or a damaged one: not usable
        log.warning("the saved %s couldn't be opened", kind, exc_info=True)
        return None
    return data if _valid(data) else None


def load(kind):
    """The saved signature, or None. One still in settings.json is moved
    into the protected file first."""
    if kind not in KINDS:
        return None
    old = settings.get(kind)
    if _valid(old):
        try:
            save(kind, old)
        except Exception:                                 # noqa: BLE001
            log.warning("could not move the %s", kind, exc_info=True)
            return old
    return _read(kind)


def forget(kind):
    """Remove the saved signature (the file is emptied, then renamed so
    nothing reads it; QuantiSheet doesn't delete files here)."""
    if settings.get(kind) is not None:
        settings.set(kind, None)
    p = path(kind)
    if os.path.isfile(p):
        with open(p, "wb") as f:
            f.write(b"")
