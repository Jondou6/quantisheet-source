"""Digital signatures with pyHanko.

Without a certificate of your own, a self-signed one is created ONCE in
~/.quantisheet (settings.DIR) and reused, so every signature you make shows the same
identity. (The original generated a brand-new key for every signature and
overwrote the previous one.) Self-signed signatures prove the document
hasn't changed since signing, but other people's PDF readers will show the
signer as "unknown" unless they trust your certificate.

On Windows the private key is stored encrypted (PKCS#8 with a random
passphrase) and the passphrase is protected with DPAPI for this Windows
user (signing_key.pem.dpapi), so copying the .quantisheet folder doesn't copy
a usable key. A plain key from an older version is converted the first
time it is used; the key itself (and so the signer identity) is kept.
Off Windows the key stays as before and a warning is logged.
"""
import datetime
import os
import tempfile

from .. import settings

DEFAULT_DIR = settings.DIR             # the per-user data folder


def _pass_file(key_path):
    return key_path + ".dpapi"


def key_passphrase(key_path):
    """The DPAPI-protected passphrase of our own key, or None (plain key)."""
    pf = _pass_file(key_path)
    if not os.path.exists(pf):
        return None
    from .. import secretstore
    with open(pf, "rb") as f:
        return secretstore.unprotect(f.read())


_own_passphrase = key_passphrase      # sign_pdf's argument shadows it


def _write_key(key_path, key):
    """Write `key` encrypted under a new DPAPI-held passphrase when DPAPI is
    available, else plain (readable only by this user)."""
    import secrets
    from cryptography.hazmat.primitives import serialization
    from .. import secretstore
    pw = secrets.token_urlsafe(32).encode()
    blob = secretstore.protect(pw, "The signing key")
    enc = serialization.BestAvailableEncryption(pw) if blob is not None \
        else serialization.NoEncryption()
    data = key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, enc)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    tmp = key_path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if blob is not None:
        with open(_pass_file(key_path) + ".tmp", "wb") as f:
            f.write(blob)
        os.replace(_pass_file(key_path) + ".tmp", _pass_file(key_path))
    os.replace(tmp, key_path)


def migrate_key(key_path):
    """Encrypt a plain key left by an older version (same key). True when
    it was converted."""
    from cryptography.hazmat.primitives import serialization
    from .. import secretstore
    if not secretstore.available() or not os.path.exists(key_path):
        return False
    with open(key_path, "rb") as f:
        pem = f.read()
    if b"ENCRYPTED" in pem:
        return False
    key = serialization.load_pem_private_key(pem, password=None)
    _write_key(key_path, key)
    return True


def _self_signed(path=None, cn="QuantiSheet User"):
    """Return (key_path, cert_path), creating them only if missing."""
    key_path = path or os.path.join(DEFAULT_DIR, "signing_key.pem")
    cert_path = key_path[:-4] + "_cert.pem" if key_path.endswith(".pem") \
        else key_path + "_cert.pem"
    if os.path.exists(key_path) and os.path.exists(cert_path):
        try:
            migrate_key(key_path)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "could not encrypt the signing key", exc_info=True)
        return key_path, cert_path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=True,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .sign(key, hashes.SHA256()))

    # private key readable only by this user, encrypted where DPAPI exists
    _write_key(key_path, key)
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


def _free_field_name(writer):
    try:
        from pyhanko.sign.fields import enumerate_sig_fields
        used = {name for name, _, _ in enumerate_sig_fields(writer)}
    except Exception:
        used = set()
    n = 1
    while f"Signature{n}" in used:
        n += 1
    return f"Signature{n}"


def sign_pdf(src, out, reason="Approved", location="",
             signer_name="QuantiSheet User", key_path=None, cert_path=None,
             key_passphrase=None, tsa_url=None):
    from pyhanko.sign import signers, timestamps
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    if not key_path or not cert_path:
        key_path, cert_path = _self_signed(cn=signer_name)
        if key_passphrase is None:
            key_passphrase = _own_passphrase(key_path)

    signer = signers.SimpleSigner.load(
        key_path, cert_path,
        key_passphrase=key_passphrase.encode() if isinstance(
            key_passphrase, str) else key_passphrase)
    if signer is None:
        raise ValueError("Could not load the signing key or certificate.")

    # write to a temp file first: signing a file onto itself would truncate
    # the source while it is still being read
    out_dir = os.path.dirname(os.path.abspath(out))
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=out_dir)
    try:
        with open(src, "rb") as f, os.fdopen(fd, "wb") as o:
            w = IncrementalPdfFileWriter(f)
            meta = signers.PdfSignatureMetadata(
                field_name=_free_field_name(w), reason=reason,
                location=location or None, name=signer_name)
            if tsa_url is None:     # Venice #3 / PR 14: the configured
                from . import timestamp     # server; off while it's empty
                tsa_url = timestamp.for_signing()
            ts = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
            signers.PdfSigner(meta, signer=signer, timestamper=ts).sign_pdf(
                w, output=o)
        os.replace(tmp, out)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return out
