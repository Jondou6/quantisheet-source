"""v33: relay token in an Authorization header + TLS / LAN opt-in (H2),
DPAPI-protected secrets and signing key (H3), one source for the server
copies and the BLS tool (H4)."""
import asyncio
import datetime
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
websockets = pytest.importorskip("websockets")

from app import settings                                       # noqa: E402
from app.collab import relaycore as rc                         # noqa: E402
from app.collab import hub as hubmod                           # noqa: E402
from test_gui import ANSWERS, win, qapp                        # noqa: E402,F401


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _load_server():
    spec = importlib.util.spec_from_file_location(
        "relay_server", os.path.join(ROOT, "server", "relay_server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tool(name):
    spec = importlib.util.spec_from_file_location(
        f"_tool_{name}", os.path.join(ROOT, "tools", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _cert(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return str(c), str(k)


# ---- H2: transport rules -----------------------------------------------------

def test_plain_ws_refused_off_loopback_unless_opted_in():
    with pytest.raises(SystemExit) as e:
        rc.check_transport("0.0.0.0", tls=False, allow_plain=False)
    assert "unencrypted" in str(e.value).lower()
    assert rc.check_transport("127.0.0.1", tls=False, allow_plain=False) \
        is None
    assert rc.check_transport("0.0.0.0", tls=True, allow_plain=False) is None
    warn = rc.check_transport("0.0.0.0", tls=False, allow_plain=True)
    assert warn and "unencrypted" in warn.lower()


def test_bearer_header_preferred_over_hello_token():
    h = {"Authorization": "Bearer abc"}
    assert rc.given_token({"token": "zzz"}, h) == "abc"
    assert rc.given_token({"token": "zzz"}, {}) == "zzz"
    assert rc.given_token({}, None) == ""
    assert rc.auth_headers("abc") == [("Authorization", "Bearer abc")]
    assert rc.auth_headers("") == []


def test_client_url_check():
    from app.collab import client
    client.check_url("ws://127.0.0.1:8765")
    client.check_url("ws://localhost:8765")
    client.check_url("wss://relay.example.com/")
    with pytest.raises(client.InsecureRelay) as e:
        client.check_url("ws://192.168.1.20:8765")
    assert "in-house" in str(e.value).lower()
    settings.set("collab_allow_plain_lan", True)
    client.check_url("ws://192.168.1.20:8765")


def test_hubclient_refuses_plain_lan_without_opt_in():
    from app.collab import hubclient
    c = hubclient.HubClient("ws://10.1.2.3:8765", token="t")
    with pytest.raises(hubclient.HubClientError) as e:
        c._connect()
    assert "in-house" in str(e.value).lower()


def test_hosted_relay_accepts_bearer_header_and_rejects_bad_one(tmp_path):
    rs = _load_server()
    port = _port()
    relay = rs.Relay(token="t0k", data_dir=str(tmp_path / "d"))

    async def run():
        async with rs.serve(relay.handler, "127.0.0.1", port,
                            process_request=rs.process_request):
            url = f"ws://127.0.0.1:{port}/"
            # token only in the header; hello carries none
            async with websockets.connect(
                    url, additional_headers=rc.auth_headers("t0k")) as a:
                await a.send(json.dumps({"type": "hello", "room": "j",
                                         "password": "p"}))
                m = json.loads(await asyncio.wait_for(a.recv(), 5))
                assert m["type"] == "peer_join"
            # a wrong header is turned away before the upgrade
            with pytest.raises(Exception) as e:
                async with websockets.connect(
                        url, additional_headers=rc.auth_headers("nope")):
                    pass
            assert "401" in str(e.value)
            # old clients: token in the hello still works
            async with websockets.connect(url) as b:
                await b.send(json.dumps({"type": "hello", "room": "k",
                                         "password": "p", "token": "t0k"}))
                m = json.loads(await asyncio.wait_for(b.recv(), 5))
                assert m["type"] == "peer_join"
            # hub api with the header is authed
            async with websockets.connect(
                    url, additional_headers=rc.auth_headers("t0k")) as c:
                await c.send(json.dumps({"type": "api"}))
                m = json.loads(await asyncio.wait_for(c.recv(), 5))
                assert m == {"type": "api_ready", "authed": True}
    asyncio.run(run())


def test_hosted_relay_serves_wss_with_cert(tmp_path, monkeypatch):
    rs = _load_server()
    c, k = _cert(tmp_path)
    monkeypatch.setenv("TLS_CERT", c)
    monkeypatch.setenv("TLS_KEY", k)
    ctx = rs.tls_context()
    assert isinstance(ctx, ssl.SSLContext)
    monkeypatch.delenv("TLS_CERT")
    assert rs.tls_context() is None
    port = _port()
    relay = rs.Relay(token="t0k", data_dir=str(tmp_path / "d"))
    cli = ssl.create_default_context()
    cli.check_hostname = False
    cli.verify_mode = ssl.CERT_NONE

    async def run():
        async with rs.serve(relay.handler, "127.0.0.1", port, ssl=ctx,
                            process_request=rs.process_request):
            async with websockets.connect(
                    f"wss://127.0.0.1:{port}/", ssl=cli,
                    additional_headers=rc.auth_headers("t0k")) as a:
                await a.send(json.dumps({"type": "hello", "room": "j",
                                         "password": "p"}))
                m = json.loads(await asyncio.wait_for(a.recv(), 5))
                assert m["type"] == "peer_join"
    asyncio.run(run())


def test_server_main_refuses_plain_public_bind(monkeypatch):
    rs = _load_server()
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("RELAY_TOKEN", "t")
    for k in ("TLS_CERT", "TLS_KEY", "TLS_PROXY", "ALLOW_PLAIN_WS"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        asyncio.run(asyncio.wait_for(rs.main(), 5))


def test_deploy_configs_declare_tls_proxy():
    for name in ("fly.toml", "render.yaml"):
        text = open(os.path.join(ROOT, "server", name)).read()
        assert "TLS_PROXY" in text, name


def test_desktop_relay_phone_link_keeps_token_out_of_query():
    from app.collab import relay
    h = relay.RelayHandle("0.0.0.0", 8765, 8766, token="abc123")
    ws_url, web = h.urls()
    assert "?t=" not in web and "#t=abc123" in web
    assert "abc123" not in ws_url


def test_web_client_reads_hash_token_and_hides_it():
    html = open(os.path.join(ROOT, "app", "collab", "web", "index.html"),
                encoding="utf-8").read()
    assert "location.hash" in html and "replaceState" in html
    assert 'get("t")' in html               # old ?t= links still work


def test_collab_client_sends_bearer_header(monkeypatch):
    from app.collab import client
    seen = {}

    class Boom(Exception):
        pass

    def fake_connect(url, **kw):
        seen.update(kw)
        raise Boom()
    monkeypatch.setattr(client, "ws_connect", fake_connect)
    c = client.CollabClient("ws://127.0.0.1:1", room="r", token="t0k")
    assert c._connect_kwargs()["additional_headers"] == \
        [("Authorization", "Bearer t0k")]


def test_start_relay_asks_before_plain_lan(qapp, win, monkeypatch):
    from app.collab import relay
    from PySide6.QtWidgets import QMessageBox
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    started = []
    monkeypatch.setattr(relay, "start_background",
                        lambda **k: started.append(k))
    win.start_relay()
    assert asked and "unencrypted" in asked[0].lower()
    assert started == [] and not settings.get("collab_allow_plain_lan")


# ---- H3: DPAPI secrets ------------------------------------------------------

class _FakeDPAPI:
    """Reversible stand-in for CryptProtectData on non-Windows boxes."""
    @staticmethod
    def protect(b):
        return b"FAKE" + bytes(x ^ 0x5A for x in b)

    @staticmethod
    def unprotect(b):
        assert b.startswith(b"FAKE")
        return bytes(x ^ 0x5A for x in b[4:])


@pytest.fixture
def dpapi(monkeypatch):
    from app import secretstore
    monkeypatch.setattr(secretstore, "_backend", lambda: _FakeDPAPI)
    return secretstore


def test_secret_roundtrip_is_not_plain(dpapi):
    dpapi.set_secret("docusign_token", "tok-123")
    raw = settings.get("docusign_token")
    assert raw.startswith("dpapi:") and "tok-123" not in raw
    assert dpapi.get_secret("docusign_token") == "tok-123"


def test_plain_secret_migrates_on_first_read(dpapi):
    settings.set("docusign_token", "legacy")
    assert dpapi.get_secret("docusign_token") == "legacy"
    assert settings.get("docusign_token").startswith("dpapi:")


def test_without_dpapi_falls_back_to_plain_with_warning(monkeypatch, caplog):
    from app import secretstore
    monkeypatch.setattr(secretstore, "_backend", lambda: None)
    secretstore._warned.clear()
    with caplog.at_level("WARNING"):
        secretstore.set_secret("docusign_token", "plain")
    assert settings.get("docusign_token") == "plain"
    assert secretstore.get_secret("docusign_token") == "plain"
    assert "not encrypted" in caplog.text


def test_docusign_uses_protected_token(dpapi):
    from app import esign_docusign
    settings.set("docusign_base", "https://demo.docusign.net/restapi")
    settings.set("docusign_account", "a")
    settings.set("docusign_token", "legacy-tok")
    assert esign_docusign.configured()
    assert esign_docusign._token() == "legacy-tok"
    assert settings.get("docusign_token").startswith("dpapi:")


def test_signing_key_encrypted_and_legacy_key_migrated(dpapi, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.sign import signer
    kp, cp = signer._self_signed(str(tmp_path / "signing_key.pem"))
    pem = open(kp, "rb").read()
    assert b"ENCRYPTED PRIVATE KEY" in pem
    pw = signer.key_passphrase(kp)
    assert pw and serialization.load_pem_private_key(pem, password=pw)
    # a plain key from an older version is re-encrypted, same key
    old = tmp_path / "old" / "signing_key.pem"
    old.parent.mkdir()
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    old.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    (old.parent / "signing_key_cert.pem").write_bytes(b"cert")
    assert signer.migrate_key(str(old)) is True
    new = old.read_bytes()
    assert b"ENCRYPTED PRIVATE KEY" in new
    k2 = serialization.load_pem_private_key(
        new, password=signer.key_passphrase(str(old)))
    assert k2.public_key().public_numbers() == k.public_key().public_numbers()
    assert signer.migrate_key(str(old)) is False          # already done


def test_signing_key_stays_plain_without_dpapi(monkeypatch, tmp_path):
    from app import secretstore
    from app.sign import signer
    monkeypatch.setattr(secretstore, "_backend", lambda: None)
    kp, _ = signer._self_signed(str(tmp_path / "signing_key.pem"))
    assert b"BEGIN PRIVATE KEY" in open(kp, "rb").read()
    assert signer.key_passphrase(kp) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_real_dpapi_roundtrip():
    from app import secretstore
    b = secretstore._backend()
    assert b is not None
    blob = b.protect(b"hello")
    assert blob != b"hello" and b.unprotect(blob) == b"hello"


def test_sign_message_explains_self_signed_identity():
    src = open(os.path.join(ROOT, "app", "main_window.py"),
               encoding="utf-8").read()
    assert "proves this QuantiSheet install signed it" in src


# ---- H4: one source ---------------------------------------------------------

def test_bls_tool_is_a_shim_over_app_copy():
    from app import bls_core
    tool = _tool("bls")
    assert tool.escalation is bls_core.escalation
    assert os.path.getsize(os.path.join(ROOT, "tools", "bls.py")) < 2000


def test_server_copies_generated_and_in_sync():
    sync = _tool("sync_server")
    assert sync.main(["--check"]) == 0
    assert set(sync.FILES) >= {"hub.py", "relaycore.py"}


def test_sync_server_rewrites_a_drifted_copy(tmp_path, monkeypatch):
    sync = _tool("sync_server")
    (tmp_path / "app" / "collab").mkdir(parents=True)
    (tmp_path / "server").mkdir()
    for n in sync.FILES:
        (tmp_path / "app" / "collab" / n).write_text("v2\n")
        (tmp_path / "server" / n).write_text("v1\n")
    monkeypatch.setattr(sync, "ROOT", str(tmp_path))
    assert sync.main(["--check"]) == 1
    assert sync.main([]) == 0
    assert sync.main(["--check"]) == 0
    assert (tmp_path / "server" / "hub.py").read_text() == "v2\n"


def test_collab_client_stops_on_refused_token(tmp_path):
    import threading
    import time
    from app.collab.client import CollabClient
    rs = _load_server()
    port = _port()
    relay = rs.Relay(token="t0k", data_dir=str(tmp_path / "d"))
    ready, stop = threading.Event(), {}

    def serve():
        async def main():
            async with rs.serve(relay.handler, "127.0.0.1", port,
                                process_request=rs.process_request):
                stop["loop"] = asyncio.get_running_loop()
                stop["fut"] = stop["loop"].create_future()
                ready.set()
                await stop["fut"]
        asyncio.run(main())
    threading.Thread(target=serve, daemon=True).start()
    assert ready.wait(10)
    try:
        c = CollabClient(f"ws://127.0.0.1:{port}/", room="r", token="bad")
        c.start()
        for _ in range(100):
            if c.error:
                break
            time.sleep(0.05)
        assert c.error == "Bad relay token."
        c.stop()
    finally:
        stop["loop"].call_soon_threadsafe(stop["fut"].set_result, None)
