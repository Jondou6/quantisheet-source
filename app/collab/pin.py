"""Relay certificate pinning (PR 16 wired, Nov 4).

A company relay usually has its own (self-signed) certificate, made with
tools/relay_cert.py, which prints relay_cert_sha256=AA:BB:... . Put that
in the setting relay_cert_sha256 (or IT policy RelayCertSHA256) and every
wss:// connection to the relay checks that exact certificate - nothing
else is accepted, not even a certificate a public authority signed.
With no pin set, wss:// uses Windows' normal certificate checks.
"""
import hashlib
import hmac
import ssl


class PinMismatch(ConnectionError):
    pass


def pinned():
    """The pinned SHA-256 (64 hex, upper case), or ""."""
    from .. import policy, settings
    raw = ""
    try:
        raw = policy.get("RelayCertSHA256") or ""
    except Exception:                                     # noqa: BLE001
        raw = ""
    raw = raw or settings.get("relay_cert_sha256") or ""
    want = "".join(str(raw).split()).replace(":", "").upper()
    if len(want) != 64 or any(c not in "0123456789ABCDEF" for c in want):
        return ""
    return want


def context(url):
    """An SSL context for `url`, or None (not wss://, or no pin: the
    library's default checks apply)."""
    if not str(url or "").lower().startswith("wss://") or not pinned():
        return None
    ctx = ssl.create_default_context()
    # the pin replaces the authority check: the exact certificate is
    # compared after the handshake (check_der)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def check_der(der, want=None):
    """Raise PinMismatch unless the peer certificate `der` is the pinned
    one."""
    want = want or pinned()
    if not want:
        return True
    got = hashlib.sha256(der or b"").hexdigest().upper()
    if not der or not hmac.compare_digest(got, want):
        raise PinMismatch(
            "The relay's certificate isn't the one this PC was told to "
            "trust (relay_cert_sha256). Nothing was sent. Ask IT whether "
            "the relay certificate was changed.")
    return True


def check_socket(sock):
    """Check a connected socket / SSL object (sync client)."""
    get = getattr(sock, "getpeercert", None)
    if get is None:
        raise PinMismatch("The relay connection isn't encrypted; the pinned "
                          "certificate can't be checked.")
    return check_der(get(binary_form=True))
