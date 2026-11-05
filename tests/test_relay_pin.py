"""PR 16 wired (Nov 4): a pinned relay certificate is checked on every
wss:// connection; the wrong certificate is refused before anything is
sent."""
import importlib.util
import os
import socket
import ssl
import threading

import pytest

from app import settings
from app.collab import pin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _relay_cert():
    spec = importlib.util.spec_from_file_location(
        "relay_cert", os.path.join(ROOT, "tools", "relay_cert.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return tmp_path


def test_no_pin_no_change(cfg):
    assert pin.pinned() == ""
    assert pin.context("wss://relay.example.test/") is None
    assert pin.check_der(b"anything") is True


def test_bad_pin_text_is_ignored(cfg):
    settings.set("relay_cert_sha256", "not-a-fingerprint")
    assert pin.pinned() == ""


def _serve(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        try:
            with ctx.wrap_socket(conn, server_side=True) as s:
                s.recv(1)
        except (OSError, ssl.SSLError):
            pass
    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


def test_pinned_certificate_accepted_other_refused(cfg):
    rc = _relay_cert()
    cert, key = str(cfg / "r.crt"), str(cfg / "r.key")
    rc.generate(cert, key, cn="relay.example.test", sans=("127.0.0.1",),
                bits=2048)
    fp = rc.fingerprint_sha256(cert)
    for want, ok in ((fp, True), ("AA" * 32, False)):
        settings.set("relay_cert_sha256", want)
        ctx = pin.context("wss://127.0.0.1/")
        assert ctx is not None
        port = _serve(cert, key)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname="127.0.0.1") as s:
                if ok:
                    assert pin.check_socket(s) is True
                else:
                    with pytest.raises(pin.PinMismatch):
                        pin.check_socket(s)
                s.send(b"x")


def test_clients_use_the_pin(cfg):
    from app.collab import client, hubclient
    settings.set("relay_cert_sha256", "AB" * 32)
    c = client.CollabClient("wss://relay.example.test/")
    assert isinstance(c._connect_kwargs().get("ssl"), ssl.SSLContext)
    src = open(hubclient.__file__, encoding="utf-8").read()
    assert "pin.check_socket(ws.socket)" in src
