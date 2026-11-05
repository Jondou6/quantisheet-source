"""Field encryption for sensitive values (vendor tax IDs and bank details
now; SSN, bank account, date of birth and I-9 files in Phase 2).

A random data key encrypts each field (Fernet: AES-128-CBC + HMAC). The
data key itself is kept in datakey.bin next to the database, protected
with Windows DPAPI for the signed-in user (same idea as QuantiSheet's
secretstore, our own copy). Off Windows there is no DPAPI: the key file is
written owner-only and the encryption status says it isn't DPAPI-protected.
"""
from __future__ import annotations

import base64
import os
import sys

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc1:"
VALUE_PREFIX = "enc2:"        # whole values, by the database layer


class _DPAPI:
    name = "Windows DPAPI (this Windows user)"

    @staticmethod
    def _call(fn_name, data):
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = BLOB()
        fn = getattr(ctypes.windll.crypt32, fn_name)
        if fn_name == "CryptProtectData":
            ok = fn(ctypes.byref(src), "QuantiSheet Back Office", None, None,
                    None, 0, ctypes.byref(out))
        else:
            ok = fn(ctypes.byref(src), None, None, None, None, 0,
                    ctypes.byref(out))
        if not ok:
            raise OSError(f"{fn_name} failed")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)

    def protect(self, data: bytes) -> bytes:
        return b"dpapi:" + self._call("CryptProtectData", data)

    def unprotect(self, blob: bytes) -> bytes:
        return self._call("CryptUnprotectData", blob[len(b"dpapi:"):])


class _OwnerOnlyFile:
    name = "key file, owner-only (no DPAPI on this system)"

    def protect(self, data: bytes) -> bytes:
        return b"plain:" + data

    def unprotect(self, blob: bytes) -> bytes:
        return blob[len(b"plain:"):]


def default_backend():
    return _DPAPI() if sys.platform == "win32" else _OwnerOnlyFile()


class FieldCrypto:
    def __init__(self, folder: str, backend=None):
        self.backend = backend or default_backend()
        self.folder = folder
        self.path = os.path.join(folder, "datakey.bin")
        # The key lives in the OS user's profile (r111.paykeys), not as a
        # readable file next to the database.
        from .r111.paykeys import load_key, old_keys
        key = load_key(folder, self.backend)
        # new values are written with the current key; values still under
        # an earlier (rotated / replaced) key keep opening
        from cryptography.fernet import MultiFernet
        olds = [k for k in old_keys(folder, self.backend) if k != key]
        self._f = MultiFernet([Fernet(key)] + [Fernet(k) for k in olds])
        self._key = key

    def data_key(self) -> bytes:
        """The raw data key, only for wrapping it into an encrypted backup.
        Callers must not write this into a log, an export or the company
        folder."""
        return self._key

    @staticmethod
    def install_key(folder: str, key: bytes, backend=None) -> None:
        """Make `key` this company's data key (restore from another PC).
        Stored sealed in the user profile. A different previous key is
        kept sealed there, not beside the database."""
        from .r111.paykeys import write_key
        write_key(folder, key, backend or default_backend())

    def status(self) -> str:
        return ("Sensitive fields encrypted; data key is sealed in this "
                f"user's profile ({self.backend.name}), not in the company "
                "folder")

    def encrypt(self, value: str | None) -> str | None:
        if value in (None, ""):
            return value
        return PREFIX + self._f.encrypt(str(value).encode("utf-8")).decode("ascii")

    def decrypt(self, token: str | None) -> str | None:
        if token in (None, ""):
            return token
        if not str(token).startswith(PREFIX):
            raise ValueError("not an encrypted field")
        try:
            return self._f.decrypt(token[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken:
            raise ValueError("the data key does not match this field") from None

    # ---- whole values kept encrypted by the database layer (0.13.14) ----
    def encrypt_value(self, value) -> str:
        """Any JSON value (text, int cents, list) as an 'enc2:' token, so
        it comes back with its type (store.AUTO_ENCRYPT)."""
        import json
        return VALUE_PREFIX + self._f.encrypt(json.dumps(value).encode(
            "utf-8")).decode("ascii")

    def decrypt_value(self, token: str):
        import json
        try:
            return json.loads(self._f.decrypt(
                token[len(VALUE_PREFIX):].encode("ascii")).decode("utf-8"))
        except InvalidToken:
            raise ValueError("the data key does not match this value") \
                from None

    def audit_key(self) -> bytes:
        """Key for the audit chain's HMACs, derived from the data key - so
        it lives outside the database (DPAPI-protected datakey.bin) and
        someone who edits the database can't re-sign the chain."""
        import hashlib
        import hmac
        return hmac.new(self._key, b"QuantiSheet audit chain v2",
                        hashlib.sha256).digest()

    def decrypt_bytes(self, data: bytes) -> bytes:
        """An encrypted document file's bytes (no permission check here;
        people-facing callers use Office.decrypt_blob)."""
        try:
            return self._f.decrypt(data)
        except InvalidToken:
            raise ValueError("the data key does not match this file") from None


def mask(value: str | None, keep: int = 4) -> str:
    """'12-3456789' -> '*****6789'."""
    if not value:
        return ""
    digits = [c for c in value if c.isalnum()]
    tail = "".join(digits[-keep:])
    return "*" * max(len(digits) - keep, 0) + tail


BACKUP_ROUNDS = 600_000


def backup_key(passphrase: str, salt: bytes, rounds: int | None = None
               ) -> bytes:
    """Key for encrypted backups from a separate backup passphrase
    (PBKDF2-HMAC-SHA256; `rounds` read back from an older backup)."""
    import hashlib
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt,
                              int(rounds or BACKUP_ROUNDS))
    return base64.urlsafe_b64encode(raw)
