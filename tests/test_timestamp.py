"""RFC 3161 client against a fake timestamp server on 127.0.0.1.

No test contacts a host other than loopback. The suggested public URL is
not requested.
"""
import datetime
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from asn1crypto import tsp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper

from app.sign import timestamp


FIXED = datetime.datetime(2026, 11, 4, 15, 0, tzinfo=datetime.timezone.utc)


def _material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake TSA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage(
            [ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
        .sign(key, hashes.SHA256()))
    from asn1crypto import keys, x509 as ax509
    tsa_cert = ax509.Certificate.load(
        cert.public_bytes(serialization.Encoding.DER))
    tsa_key = keys.PrivateKeyInfo.load(key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    return tsa_cert, tsa_key, pem


class _Server(ThreadingHTTPServer):
    def __init__(self, stamper):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.stamper = stamper
        self.hits = 0
        self.mode = "ok"
        self.last_content_type = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        self.send_error(405)

    def do_POST(self):
        srv = self.server
        srv.hits += 1
        srv.last_content_type = self.headers.get("Content-Type", "")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if srv.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://timestamp.example.test/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if srv.mode == "html":
            payload = b"<html>no</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        req = tsp.TimeStampReq.load(body)
        resp = srv.stamper.request_tsa_response(req)
        if srv.mode == "reject":
            # asn1crypto's TimeStampResp requires the token field, so the
            # refusal keeps a token and the client must still honour the
            # status (RFC 3161: a rejected response is not a stamp).
            resp["status"] = tsp.PKIStatusInfo({
                "status": tsp.PKIStatus("rejection"),
                "status_string": ["made-up refusal"],
            })
        payload = resp.dump()
        self.send_response(200)
        self.send_header("Content-Type", "application/timestamp-reply")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def tsa():
    cert, key, pem = _material()
    srv = _Server(DummyTimeStamper(cert, key, fixed_dt=FIXED))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.pem = pem
    yield srv
    srv.shutdown()


def _off(monkeypatch):
    monkeypatch.setattr(timestamp.settings, "get",
                        lambda key, default=None: "")


def test_setting_off_does_not_use_the_suggestion_or_the_network(
        monkeypatch, tsa):
    _off(monkeypatch)
    assert timestamp.timestamp_url() == ""
    assert timestamp.enabled() is False
    assert timestamp.for_signing() is None
    assert timestamp.SUGGESTED_TIMESTAMP_URL.startswith("http://")
    assert timestamp.timestamp_url() != timestamp.SUGGESTED_TIMESTAMP_URL
    with pytest.raises(timestamp.TimestampDisabled):
        timestamp.request_timestamp(b"drawing bytes")
    assert tsa.hits == 0


def test_request_and_verify_against_the_local_server(monkeypatch, tsa):
    _off(monkeypatch)
    stamped = timestamp.request_timestamp(b"made-up drawing", url=tsa.url)
    assert tsa.hits == 1
    assert tsa.last_content_type == "application/timestamp-query"
    assert stamped.gen_time == FIXED
    assert stamped.hash_algorithm == "sha256"
    assert stamped.signer
    again = timestamp.verify_timestamp(stamped.token, b"made-up drawing")
    assert again.fingerprint == stamped.fingerprint
    assert timestamp.verify_timestamp(stamped, b"made-up drawing").serial == \
        stamped.serial
    # the setting turns the same server on, with no url argument
    monkeypatch.setattr(
        timestamp.settings, "get",
        lambda key, default=None: tsa.url if key == timestamp.SETTING else default)
    assert timestamp.enabled()
    assert timestamp.for_signing() == tsa.url
    via_setting = timestamp.request_timestamp(b"second")
    assert via_setting.token
    assert tsa.hits == 2


def test_pin_and_rejections(tsa):
    data = b"page 4"
    stamped = timestamp.request_timestamp(
        data, url=tsa.url, certs=[tsa.pem])
    assert timestamp.verify_timestamp(
        stamped.token, data, certs=[stamped.fingerprint.lower()]).fingerprint
    with pytest.raises(timestamp.TimestampError):
        timestamp.verify_timestamp(stamped.token, data, certs=["ab" * 32])
    with pytest.raises(timestamp.TimestampError):
        timestamp.verify_timestamp(stamped.token, b"different bytes")
    tampered = bytearray(stamped.token)
    tampered[-2] ^= 0xFF
    with pytest.raises(timestamp.TimestampError):
        timestamp.verify_timestamp(bytes(tampered), data)
    tsa.mode = "reject"
    with pytest.raises(timestamp.TimestampRejected):
        timestamp.request_timestamp(data, url=tsa.url)
    tsa.mode = "redirect"
    with pytest.raises(timestamp.TimestampRejected):
        timestamp.request_timestamp(data, url=tsa.url)
    tsa.mode = "html"
    with pytest.raises(timestamp.TimestampError):
        timestamp.request_timestamp(data, url=tsa.url)


def test_bad_url_and_bad_input_do_not_need_a_server():
    with pytest.raises(timestamp.TimestampError):
        timestamp.request_timestamp(b"x", url="not a url")
    with pytest.raises(timestamp.TimestampError):
        timestamp.request_timestamp("a string, not bytes", url="http://127.0.0.1:9/")
    with pytest.raises(timestamp.TimestampError):
        timestamp.verify_timestamp(b"", b"x")
    with pytest.raises(timestamp.TimestampError):
        timestamp.request_timestamp(b"x", url="http://127.0.0.1:9/",
                                    hash_algo="md5")
