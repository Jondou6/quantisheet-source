"""RFC 3161 timestamp client.

Off unless the setting ``timestamp_url`` is a non-empty URL. Nothing is
contacted while that setting is empty. ``SUGGESTED_TIMESTAMP_URL`` is a
public server you can copy into the setting; it is not used on its own.

``request_timestamp`` posts a timestamp request and checks the token it
gets back. ``verify_timestamp`` checks a token already in hand: the
signature, the message imprint, and the time-stamping use on the
certificate. Neither call builds a chain to a public CA and neither
fetches revocation data. Pass ``certs`` to require a particular
certificate (a pin).

``for_signing`` is the URL to give ``app.sign.signer.sign_pdf`` as
``tsa_url``. ``sign_pdf`` talks to the server itself; use
``request_timestamp`` when you want the token and a check here.

Suggested server (not enabled): http://timestamp.digicert.com
UNVERIFIED that this host is the one you want. Confirm it before saving
it into the setting. Tests never call it.
"""
import hashlib
import urllib.error
import urllib.parse
import urllib.request

from .. import settings

SETTING = "timestamp_url"
# Documented suggestion only. timestamp_url() does not return this unless
# the setting is saved as this value.
SUGGESTED_TIMESTAMP_URL = "http://timestamp.digicert.com"
_MAX_RESPONSE = 2 * 1024 * 1024
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class TimestampError(Exception):
    """The timestamp could not be obtained or does not check out."""


class TimestampDisabled(TimestampError):
    """``timestamp_url`` is empty, and no URL was passed in."""


class TimestampRejected(TimestampError):
    """The server answered, and refused or the token does not match."""


class Timestamp:
    """A token that has been checked against the data it claims to cover."""

    def __init__(self, token, gen_time, policy, hash_algorithm, serial,
                 signer, fingerprint):
        self.token = token                  # ContentInfo DER
        self.gen_time = gen_time
        self.policy = policy
        self.hash_algorithm = hash_algorithm
        self.serial = serial
        self.signer = signer
        self.fingerprint = fingerprint      # SHA-256 of the signer cert

    def __bytes__(self):
        return self.token


def timestamp_url():
    """The configured server, or ``""`` when timestamping is off."""
    raw = settings.get(SETTING, "")
    if raw is None:
        return ""
    return str(raw).strip()


def enabled():
    """True when ``timestamp_url`` is set."""
    return bool(timestamp_url())


def for_signing():
    """URL for ``sign_pdf(..., tsa_url=)``, or None when timestamping is off.

    Does not contact the network.
    """
    return timestamp_url() or None


def request_timestamp(data, url=None, *, hash_algo="sha256", timeout=15,
                      certs=None):
    """Ask the timestamp server to stamp ``data`` and check the token.

    ``url`` overrides the setting for this call. With no ``url`` and an
    empty setting, raises TimestampDisabled and does not open a socket.
    Returns a Timestamp. The token bytes are ``timestamp.token``.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TimestampError("Pass the bytes to stamp, not a path.")
    target = timestamp_url() if url is None else str(url).strip()
    if not target:
        raise TimestampDisabled(
            "Timestamping is off (setting timestamp_url is empty). "
            f"{SUGGESTED_TIMESTAMP_URL} is a suggested server and is not "
            "used unless timestamp_url is set to it.")
    algo = _algo(hash_algo)
    digest = hashlib.new(algo, data).digest()
    nonce, body = _request_body(digest, algo)
    raw = _post(target, body, timeout)
    token = _token_from_response(raw, nonce)
    return verify_timestamp(token.dump(), bytes(data), certs=certs)


def verify_timestamp(token, data, *, certs=None):
    """Check ``token`` (ContentInfo or TimeStampResp DER, or a Timestamp).

    Raises TimestampError when the signature, the imprint, or the
    certificate does not check. Returns a Timestamp when it does.
    ``certs``, when given, is PEM/DER certificates or SHA-256 fingerprints;
    the signer must be one of them.
    """
    if isinstance(token, Timestamp):
        token = token.token
    if not isinstance(data, (bytes, bytearray)):
        raise TimestampError("Pass the bytes that were stamped, not a path.")
    if not isinstance(token, (bytes, bytearray)) or not token:
        raise TimestampError("The timestamp token is empty.")
    from pyhanko.sign.general import extract_signer_info
    from pyhanko.sign.validation.generic_cms import (
        extract_certs_for_validation, validate_sig_integrity)

    signed, token_der = _signed_data(bytes(token))

    try:
        cert_info = extract_certs_for_validation(signed)
        cert = cert_info.signer_cert
        signer_info = extract_signer_info(signed)
    except Exception as e:
        raise TimestampError(
            "The timestamp token has no usable signer certificate.") from e

    content = signed["encap_content_info"]["content"]
    # ParsableOctetString.native is the parsed TSTInfo. The signature's
    # message-digest is over the DER bytes, which are .contents.
    tst_bytes = getattr(content, "contents", None)
    if isinstance(tst_bytes, memoryview):
        tst_bytes = bytes(tst_bytes)
    if not isinstance(tst_bytes, (bytes, bytearray)) or not tst_bytes:
        raise TimestampError("The timestamp token has no TSTInfo.")
    md_name = signer_info["digest_algorithm"]["algorithm"].native
    try:
        actual = hashlib.new(md_name, tst_bytes).digest()
    except ValueError as e:
        raise TimestampError(f"Unknown hash {md_name}.") from e
    try:
        intact, valid = validate_sig_integrity(
            signer_info, cert, "tst_info", actual)
    except Exception as e:
        raise TimestampError("The timestamp signature could not be checked.") from e
    if not (intact and valid):
        raise TimestampError("The timestamp signature is not valid.")

    try:
        info = content.parsed
    except Exception as e:
        raise TimestampError("The timestamp token has no TSTInfo.") from e
    imprint = info["message_imprint"]["hashed_message"].native
    imprint_algo = info["message_imprint"]["hash_algorithm"]["algorithm"].native
    try:
        expect = hashlib.new(imprint_algo, bytes(data)).digest()
    except ValueError as e:
        raise TimestampError(f"Unknown hash {imprint_algo}.") from e
    if not _eq(expect, imprint):
        raise TimestampError("The timestamp does not cover this data.")
    _require_time_stamping(cert)
    fingerprint = _cert_fingerprint(cert)
    if certs is not None and not _pin_ok(cert, fingerprint, certs):
        raise TimestampError(
            "The timestamp certificate is not one of the pinned certificates.")
    policy = info["policy"].native
    return Timestamp(
        token=token_der,
        gen_time=info["gen_time"].native,
        policy=str(policy) if policy is not None else "",
        hash_algorithm=imprint_algo,
        serial=info["serial_number"].native,
        signer=cert.subject.human_friendly,
        fingerprint=fingerprint,
    )


def _signed_data(token):
    """(SignedData, ContentInfo DER) from a token or a full TimeStampResp."""
    from asn1crypto import cms, tsp
    try:
        parsed = cms.ContentInfo.load(token)
        if parsed["content_type"].native == "signed_data":
            return parsed["content"], token
    except Exception:
        parsed = None
    try:
        resp = tsp.TimeStampResp.load(token)
        content_info = resp["time_stamp_token"]
        if content_info["content_type"].native != "signed_data":
            raise TimestampError("The timestamp token could not be read.")
        return content_info["content"], content_info.dump()
    except TimestampError:
        raise
    except Exception as e:
        raise TimestampError("The timestamp token could not be read.") from e


def _eq(a, b):
    import hmac
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _algo(name):
    algo = str(name or "").lower().replace("-", "")
    if algo not in ("sha256", "sha384", "sha512"):
        raise TimestampError("hash_algo must be sha256, sha384 or sha512.")
    return algo


def _request_body(digest, algo):
    from asn1crypto import algos, cms, tsp
    from pyhanko.sign.timestamps.common_utils import get_nonce
    nonce = get_nonce()
    req = tsp.TimeStampReq({
        "version": 1,
        "message_imprint": tsp.MessageImprint({
            "hash_algorithm": algos.DigestAlgorithm({"algorithm": algo}),
            "hashed_message": digest,
        }),
        "cert_req": True,
        "nonce": cms.Integer(nonce),
    })
    return nonce, req.dump()


def _token_from_response(raw, nonce):
    from asn1crypto import tsp
    from pyhanko.sign.timestamps.common_utils import (
        TimestampRequestError, handle_tsp_response)
    try:
        resp = tsp.TimeStampResp.load(raw)
    except Exception as e:
        raise TimestampError("The timestamp server did not return a token.") from e
    status = resp["status"]["status"].native
    if status not in ("granted", "granted_with_mods"):
        try:
            handle_tsp_response(resp, nonce)
        except TimestampRequestError as e:
            raise TimestampRejected(str(e)) from e
        raise TimestampRejected(f"Timestamp server status is {status}.")
    if status == "granted_with_mods":
        # handle_tsp_response only accepts "granted". RFC 3161 also allows
        # grantedWithMods. The nonce check is the same.
        got = _response_nonce(resp)
        if nonce is not None and got != nonce:
            raise TimestampRejected("The timestamp server sent a different nonce.")
        return resp["time_stamp_token"]
    try:
        return handle_tsp_response(resp, nonce)
    except TimestampRequestError as e:
        raise TimestampRejected(str(e)) from e
    except AttributeError as e:
        # pyHanko formats a nonce mismatch with nonce.hex(), and our nonce
        # is an int. The mismatch itself is what matters.
        raise TimestampRejected(
            "The timestamp server sent a different nonce.") from e


def _response_nonce(resp):
    try:
        return resp["time_stamp_token"]["content"]["encap_content_info"][
            "content"].parsed["nonce"].native
    except Exception:
        return None


def _post(url, body, timeout):
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise TimestampError("timestamp_url must be an http or https URL.")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/timestamp-query",
            "Accept": "application/timestamp-reply",
        })
    # A redirect would send the imprint to some other host. Refuse it.
    # Loopback skips environment proxies so a test server is not sent off-box.
    # Passing ProxyHandler disables the default one build_opener would add.
    host = (parts.hostname or "").lower()
    proxy = urllib.request.ProxyHandler(
        {} if host in _LOOPBACK else urllib.request.getproxies())
    opener = urllib.request.build_opener(_NoRedirect(), proxy)
    try:
        http = opener.open(req, timeout=timeout)
    except TimestampError:
        raise
    except urllib.error.HTTPError as e:
        raise TimestampRejected(
            f"Timestamp server returned HTTP {e.code}.") from e
    except urllib.error.URLError as e:
        raise TimestampError(
            f"Could not reach the timestamp server ({e.reason}).") from e
    with http:
        payload = http.read(_MAX_RESPONSE + 1)
    if len(payload) > _MAX_RESPONSE:
        raise TimestampError("The timestamp response is too large.")
    if not payload:
        raise TimestampError("The timestamp server returned an empty body.")
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TimestampRejected(
            f"The timestamp server redirected the request ({code}).")


def _require_time_stamping(cert):
    try:
        eku = cert.extended_key_usage_value
        native = list(eku.native) if eku is not None else []
    except Exception as e:
        raise TimestampError(
            "The timestamp certificate could not be read.") from e
    if "time_stamping" not in native:
        raise TimestampError(
            "The timestamp certificate does not have the timeStamping use.")


def _cert_fingerprint(cert):
    digest = hashlib.sha256(cert.dump()).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def _pin_ok(cert, fingerprint, certs):
    if isinstance(certs, (bytes, bytearray, str)):
        certs = [certs]
    want_fp = fingerprint.replace(":", "").upper()
    der = cert.dump()
    for item in certs:
        if isinstance(item, str) and "BEGIN CERTIFICATE" not in item:
            text = "".join(item.split()).replace(":", "").upper()
            if len(text) == 64 and _eq(text.encode("ascii"), want_fp.encode("ascii")):
                return True
            continue
        try:
            loaded = _load_cert(item)
        except Exception:
            continue
        if loaded.dump() == der:
            return True
        if _eq(_cert_fingerprint(loaded).replace(":", "").encode("ascii"),
               want_fp.encode("ascii")):
            return True
    return False


def _load_cert(item):
    from asn1crypto import x509
    if isinstance(item, str):
        item = item.encode("ascii", "replace")
    data = bytes(item)
    if b"BEGIN CERTIFICATE" in data:
        from cryptography import x509 as cx509
        from cryptography.hazmat.primitives import serialization
        pem = cx509.load_pem_x509_certificate(data)
        data = pem.public_bytes(serialization.Encoding.DER)
    return x509.Certificate.load(data)
