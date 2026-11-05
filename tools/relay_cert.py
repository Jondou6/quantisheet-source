"""Make a self-signed TLS certificate for the QuantiSheet collaboration relay.

    python tools/relay_cert.py C:\\ProgramData\\QuantiSheet
    python tools/relay_cert.py --cert C:\\path\\relay.crt --key C:\\path\\relay.key

Writes a certificate and an unencrypted private key to the path you choose,
and prints the certificate's SHA-256 fingerprint. That fingerprint is what
to pin. Nothing is written unless you pass a path. The key is not printed.

The desktop client does not read this fingerprint yet. See docs/RELAY_TLS.md.
"""
import argparse
import datetime
import hashlib
import hmac
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Same lifetime the app uses for its own self-signed signing certificate
# (app/sign/signer.py). A public CA would use a shorter one; this is private.
DEFAULT_DAYS = 825
DEFAULT_CN = "quantisheet-relay"
DEFAULT_BITS = 2048
CERT_EXTS = (".crt", ".cer", ".pem")


class Issued:
    """What generate() wrote."""

    def __init__(self, cert_path, key_path, fingerprint):
        self.cert_path = cert_path
        self.key_path = key_path
        # Uppercase hex pairs, colon-separated. SHA-256 of the DER
        # certificate (not of the PEM file bytes).
        self.fingerprint = fingerprint

    def __str__(self):
        return self.fingerprint


def destinations(path):
    """(cert_path, key_path) for a folder or a certificate file path."""
    path = os.path.abspath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    if os.path.isdir(path) or (not os.path.exists(path) and ext not in CERT_EXTS):
        return (os.path.join(path, "relay.crt"),
                os.path.join(path, "relay.key"))
    if ext in CERT_EXTS and not os.path.isdir(path):
        return path, os.path.splitext(path)[0] + ".key"
    raise ValueError(f"{path} is a file, not a folder or a certificate path.")


def _san_name(text):
    try:
        return x509.IPAddress(ipaddress.ip_address(text))
    except ValueError:
        return x509.DNSName(text)


def fingerprint_sha256(cert):
    """SHA-256 of the certificate's DER form, ``AA:BB:...``.

    `cert` may be PEM text, PEM or DER bytes, or a filesystem path.
    """
    if isinstance(cert, str):
        if "BEGIN CERTIFICATE" in cert:
            data = cert.encode("ascii", "replace")
        elif os.path.isfile(cert):
            with open(cert, "rb") as f:
                data = f.read()
        else:
            data = cert.encode("ascii", "replace")
    else:
        data = bytes(cert)
    if b"BEGIN CERTIFICATE" in data:
        loaded = x509.load_pem_x509_certificate(data)
        der = loaded.public_bytes(serialization.Encoding.DER)
    else:
        loaded = x509.load_der_x509_certificate(data)
        der = loaded.public_bytes(serialization.Encoding.DER)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def fingerprint_matches(cert, expected):
    """True when `expected` is the SHA-256 fingerprint of `cert`.

    Colons, spaces and case are ignored. A wrong length is a mismatch,
    not an error. Comparison is constant-time for two 64-hex strings.
    """
    try:
        got = fingerprint_sha256(cert).replace(":", "")
    except Exception:
        return False
    want = "".join(str(expected or "").split()).replace(":", "").upper()
    if len(got) != 64 or len(want) != 64:
        return False
    if any(c not in "0123456789ABCDEF" for c in want):
        return False
    return hmac.compare_digest(got, want)


def generate(cert_path, key_path, *, cn=DEFAULT_CN, sans=(), days=DEFAULT_DAYS,
             bits=DEFAULT_BITS, force=False):
    """Write a new self-signed server certificate and its key.

    Raises FileExistsError if either file exists and force is false.
    The key is unencrypted PEM, mode 0o600. The certificate is PEM.
    """
    if not cn or any(c in cn for c in "\r\n\x00"):
        raise ValueError("The certificate name is empty or has a newline.")
    if days < 1 or days > 8250:
        raise ValueError("days must be from 1 to 8250.")
    if bits not in (2048, 3072, 4096):
        raise ValueError("bits must be 2048, 3072 or 4096.")
    cert_path = os.path.abspath(cert_path)
    key_path = os.path.abspath(key_path)
    if cert_path == key_path:
        raise ValueError("The certificate and the key must be different files.")
    for path in (cert_path, key_path):
        if os.path.exists(path) and not force:
            raise FileExistsError(path)
    names = []
    seen = set()
    for item in (cn, *tuple(sans or ())):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        names.append(_san_name(text))
    if not names:
        raise ValueError("Need a host name or an address for the certificate.")

    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "QuantiSheet"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=True, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage(
            [ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    _write(key_path, key_pem, 0o600, force)
    try:
        _write(cert_path, cert_pem, 0o644, force)
    except Exception:
        if os.path.exists(key_path):
            os.remove(key_path)
        raise
    return Issued(cert_path, key_path, fingerprint_sha256(cert_pem))


def _write(path, data, mode, force):
    if force and os.path.exists(path):
        os.remove(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
    except Exception:
        os.close(fd)
        if os.path.exists(path):
            os.remove(path)
        raise
    else:
        os.close(fd)


def _print_issued(issued):
    print(f"Wrote {issued.cert_path}")
    print(f"Wrote {issued.key_path}")
    print(f"SHA-256 fingerprint: {issued.fingerprint}")
    # The app does not read this setting yet. docs/RELAY_TLS.md says so.
    print(f"relay_cert_sha256={issued.fingerprint}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Make a self-signed certificate for the collaboration "
                    "relay and print its SHA-256 fingerprint.")
    parser.add_argument(
        "path", nargs="?",
        help="folder to write relay.crt and relay.key into, or a "
             ".crt/.cer/.pem path (the key is written beside it as .key)")
    parser.add_argument("--cert", help="certificate file to write")
    parser.add_argument("--key", help="private key file to write")
    parser.add_argument("--cn", default=DEFAULT_CN,
                        help=f"common name (default {DEFAULT_CN}). "
                             "Use the host name people will type.")
    parser.add_argument("--san", action="append", default=[],
                        help="extra DNS name or IP address. Repeat for each. "
                             "The common name is always included.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"lifetime in days (default {DEFAULT_DAYS})")
    parser.add_argument("--bits", type=int, default=DEFAULT_BITS,
                        help=f"RSA key size (default {DEFAULT_BITS})")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing certificate and key")
    args = parser.parse_args(argv)
    try:
        if args.cert or args.key:
            if not (args.cert and args.key):
                raise ValueError("Pass both --cert and --key.")
            cert_path, key_path = args.cert, args.key
        elif args.path:
            cert_path, key_path = destinations(args.path)
        else:
            raise ValueError("Choose a folder, or pass --cert and --key.")
        issued = generate(cert_path, key_path, cn=args.cn, sans=args.san,
                          days=args.days, bits=args.bits, force=args.force)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    _print_issued(issued)
    return 0


if __name__ == "__main__":
    sys.exit(main())
