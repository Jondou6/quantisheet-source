"""Nov 6 security fixes (Chief's brief 4162NEA1).

1. qs-collab-ws-query-override: the field, sign and bid pages took any
   WebSocket address from the link's "ws" value, so a doctored link could
   send a login, a signature or a bid to someone else's server. The
   address now comes only from the page's own host.
2. qs-hub-att-key-in-query: the field page put the long-lived session key
   in attachment addresses (history, proxy logs, Referer). Attachments are
   fetched with an Authorization header now and shown from blob: URLs; the
   hub refuses a key in the address.

Made-up data only.
"""
import base64
import os
import re

import pytest

from app.collab import hub as hubmod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "app", "collab", "web")
PAGES = ("project.html", "sign.html", "bid.html")


def _page(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _ws_body(src):
    m = re.search(r"function wsUrl\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "wsUrl() not found"
    return m.group(1)


# ---- fix 1: the socket address -------------------------------------------

@pytest.mark.parametrize("name", PAGES)
def test_socket_address_ignores_the_link(name):
    """No value from the link (empty, malformed or a foreign wss://)
    can choose the socket: wsUrl() reads only the page's own location."""
    src = _page(name)
    body = _ws_body(src)
    assert "search" not in body and "URLSearchParams" not in body
    assert 'get("ws")' not in src and "get('ws')" not in src
    used = set(re.findall(r"location\.(\w+)", body))
    assert used <= {"port", "hostname", "host", "protocol"}, used
    # one socket, opened only from wsUrl()
    assert src.count("new WebSocket(") == 1
    assert "new WebSocket(wsUrl())" in src


def _ws_for(protocol, host, port):
    """What wsUrl() gives, worked out from its two rules (kept in step
    with the pages by the test below)."""
    if port == "8766":
        return f"ws://{host.split(':')[0]}:8765"
    return f"{'wss' if protocol == 'https:' else 'ws'}://{host}/"


@pytest.mark.parametrize("name", PAGES)
def test_socket_rules_https_and_local_pairing(name):
    body = _ws_body(_page(name))
    assert 'location.port === "8766"' in body
    assert "ws://${location.hostname}:8765" in body
    assert '"https:" ? "wss" : "ws"' in body
    assert "://${location.host}/" in body
    assert _ws_for("https:", "hub.example.test", "") == \
        "wss://hub.example.test/"
    assert _ws_for("http:", "192.168.1.20:8766", "8766") == \
        "ws://192.168.1.20:8765"
    assert _ws_for("http:", "localhost:8000", "8000") == \
        "ws://localhost:8000/"


# ---- fix 2: the key stays out of addresses -------------------------------

def test_field_page_never_puts_the_key_in_an_address():
    src = _page("project.html")
    assert "?k=" not in src and "&k=" not in src
    for m in re.finditer(r"`[^`]*\$\{[^}]*S\.key[^}]*\}[^`]*`", src):
        assert "/hub/" not in m.group(0), m.group(0)
    assert "photoUrl" not in src
    assert '"Authorization": "Bearer " + S.key' in src
    assert "URL.createObjectURL" in src and "URL.revokeObjectURL" in src
    assert 'referrerPolicy: "no-referrer"' in src
    # images and the open-full-size links both go through the fetch path
    assert src.count("photoAttr(") >= 4 and "fillAtt(" in src
    assert re.search(r"<a \$\{photoAttr\(p\)\}", src)
    assert "function logout(){ dropAtt();" in src


def test_service_worker_is_bumped_and_never_caches_hub_data():
    with open(os.path.join(WEB, "sw.js"), encoding="utf-8") as fh:
        sw = fh.read()
    assert "quantisheet-v5" in sw and "quantisheet-v4" not in sw
    assert "indexOf('/hub/')" in sw


def _hub(tmp_path):
    H = hubmod.Hub(str(tmp_path / "hub"))
    key = H.call("proj.open", {"project": "Job", "password": "pw123456",
                               "user": "Tester"}, {"ip": "10.0.0.5"},
                 True)["key"]
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 20
    att = H.call("att.put", {"project": "Job", "key": key, "name": "a.png",
                             "data": base64.b64encode(png).decode()}, {},
                 True)
    return H, key, png, f"/hub/att/Job/{att['sha256']}"


def test_hub_serves_an_attachment_only_with_the_header(tmp_path):
    H, key, png, url = _hub(tmp_path)
    assert H.get(url, {"Authorization": f"Bearer {key}"}) == (
        200, "image/png", png)
    assert H.get(url, {"authorization": f"bearer {key}"})[0] == 200
    assert H.get(url)[0] == 401                          # no header
    assert H.get(url, {})[0] == 401
    assert H.get(url, {"Authorization": f"Basic {key}"})[0] == 401
    assert H.get(url, {"Authorization": "Bearer "})[0] == 401
    assert H.get(url, {"Authorization": "Bearer wrong"})[0] == 403


def test_a_key_in_the_address_is_refused_even_when_right(tmp_path):
    H, key, png, url = _hub(tmp_path)
    st, _ct, body = H.get(f"{url}?k={key}")
    assert st == 401 and b"no longer accepted" in body
    # the header still wins when an old link also carries k
    assert H.get(f"{url}?k=junk", {"Authorization": f"Bearer {key}"})[0] \
        == 200


def test_another_projects_key_cant_read_it(tmp_path):
    H, key, png, url = _hub(tmp_path)
    other = H.call("proj.open", {"project": "Other", "password":
                                 "pw654321", "user": "Tester"},
                   {"ip": "10.0.0.6"}, True)["key"]
    assert H.get(url, {"Authorization": f"Bearer {other}"})[0] == 403
    assert H.get("/hub/att/Other/" + url.rsplit("/", 1)[1],
                 {"Authorization": f"Bearer {other}"})[0] == 404


def test_bearer_parsing():
    assert hubmod.bearer({"Authorization": "Bearer abc"}) == "abc"
    assert hubmod.bearer({"authorization": "  bearer  abc "}) == "abc"
    assert hubmod.bearer({"Authorization": "Token abc"}) == ""
    assert hubmod.bearer(None) == "" and hubmod.bearer({}) == ""
    assert hubmod.bearer("not headers") == ""


def test_server_copy_matches_and_passes_headers():
    with open(os.path.join(ROOT, "server", "hub.py"), "rb") as a, \
            open(os.path.join(ROOT, "app", "collab", "hub.py"), "rb") as b:
        assert a.read() == b.read()
    with open(os.path.join(ROOT, "server", "relay_server.py"),
              encoding="utf-8") as fh:
        rs = fh.read()
    assert "HUB.get(path, headers)" in rs
    assert "_http(request.path, request.headers)" in rs
    assert "_http(path, request_headers)" in rs
    with open(os.path.join(ROOT, "app", "collab", "relay.py"),
              encoding="utf-8") as fh:
        assert "self.hub.get(self.path, self.headers)" in fh.read()


def test_existing_sessions_keep_working(tmp_path):
    """A phone signed in before the change keeps its key in local storage;
    the new page sends that same key in the header."""
    H, key, png, url = _hub(tmp_path)
    src = _page("project.html")
    assert 'localStorage.setItem("quantisheet.field"' in src
    assert H.get(url, {"Authorization": f"Bearer {key}"})[0] == 200
