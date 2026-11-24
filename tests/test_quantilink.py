"""Send with QuantiLink (Jon, Nov 23): Project Center RFIs, submittals,
daily logs and meeting minutes sent to the office's QuantiLink server with
one shared key, share links handed back; the button is on the Home tab.
Tested against a fake QuantiLink server on this PC. Made-up project, key
and files only."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import policy, quantilink as ql  # noqa: E402
from app.pm.store import ProjectStore  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass

KEY = "qlt_madeUpTestKey123"


class Fake:
    """A pretend QuantiLink: records every request."""

    def __init__(self):
        self.calls = []
        self.files = {}
        self.fail = {}                 # path -> (status, error text)
        self.next_id = 1

    def handler(fake):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):          # noqa: N802
                u = urlsplit(self.path)
                q = parse_qs(u.query)
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                fake.calls.append({"path": u.path, "query": q,
                                   "auth": self.headers.get("Authorization"),
                                   "cookie": self.headers.get("Cookie"),
                                   "ctype": self.headers.get("Content-Type"),
                                   "body": body, "url": self.path})
                if self.headers.get("Authorization") != "Bearer " + KEY:
                    return self._send(401, {"error": "Bad key."})
                if u.path == "/api/upload":
                    p = q.get("path", [""])[0]
                    if p in fake.fail:
                        st, msg = fake.fail[p]
                        return self._send(st, {"error": msg})
                    fid = f"f{fake.next_id}"
                    fake.next_id += 1
                    fake.files[fid] = (q["space"][0], p, body)
                    return self._send(200, {"result": {
                        "id": fid, "name": p.rsplit("/", 1)[-1],
                        "versionCount": 1}})
                if u.path == "/api/rpc":
                    r = json.loads(body)
                    if r["method"] == "listSpaces":
                        return self._send(200, {"result": [
                            {"id": "s2", "name": "Estimating", "role":
                             "editor"},
                            {"id": "s1", "name": "Pat", "personal": True,
                             "role": "owner"},
                            {"id": "s3", "name": "Archive", "role":
                             "viewer"}]})
                    if r["method"] == "createShare":
                        fid, opts = r["args"]
                        return self._send(200, {"result": {
                            "token": f"tok{fid}x{opts['expiresDays']}"}})
                return self._send(404, {"error": "No such thing."})
        return H


@pytest.fixture
def server():
    fake = Fake()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    fake.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield fake
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def no_policy(monkeypatch):
    monkeypatch.setattr(policy, "_from_registry", lambda: {})
    monkeypatch.delenv("QUANTISHEET_POLICY_FILE", raising=False)
    policy.reload()
    yield
    policy.reload()


def _store(tmp_path, attach=None):
    s = ProjectStore(str(tmp_path / "Example Clinic"))
    rec = {"subject": "Roof drain location", "status": "Open",
           "question": "Confirm the roof drain at grid C-4."}
    if attach:
        rec["attachments"] = [s.attach(attach)]
    s.save_record("rfi", rec)
    s.save_record("rfi", {"subject": "Door swing at 104", "status": "Closed",
                          "question": "Which way does door 104 swing?"})
    return s


def test_server_address_rules():
    assert ql.check_url("files.example.com") == "https://files.example.com"
    assert ql.check_url("https://files.example.com/") == \
        "https://files.example.com"
    assert ql.check_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    for bad in ("http://files.example.com", "ftp://x.example.com",
                "https://user:pw@files.example.com",
                "https://files.example.com/?k=1", "not a url at all//"):
        with pytest.raises(ql.QuantiLinkError):
            ql.check_url(bad)


def test_folders_upload_and_share_link(server, no_policy):
    c = ql.Client(server.url, KEY)
    sp = c.spaces()
    assert [s["id"] for s in sp] == ["s1", "s3", "s2"]   # own files first
    got = c.upload("s2", "Example Clinic/RFIs/RFI 1.pdf", b"%PDF-1.4 x")
    link = c.share(got["id"], 7)
    assert link == f"{server.url}/s/tok{got['id']}x7"
    up = [x for x in server.calls if x["path"] == "/api/upload"][0]
    assert up["auth"] == "Bearer " + KEY and up["cookie"] is None
    assert KEY not in up["url"]                       # never in a URL
    assert up["query"]["space"] == ["s2"]
    assert up["query"]["path"] == ["Example Clinic/RFIs/RFI 1.pdf"]
    assert up["ctype"] == "application/pdf" and up["body"] == b"%PDF-1.4 x"


def test_errors_are_plain_messages(server, no_policy):
    with pytest.raises(ql.QuantiLinkError, match="Bad key"):
        ql.Client(server.url, "qlt_wrong").spaces()
    server.fail["P/RFIs/big.pdf"] = (507, "Storage is full (made-up).")
    with pytest.raises(ql.QuantiLinkError, match="Storage is full"):
        ql.Client(server.url, KEY).upload("s2", "P/RFIs/big.pdf", b"x")
    with pytest.raises(ql.QuantiLinkError, match="Couldn't reach"):
        ql.Client("http://127.0.0.1:9", KEY).spaces()
    with pytest.raises(ql.QuantiLinkError, match="no QuantiLink key"):
        ql.Client(server.url, "")


def test_send_records_and_attachments(server, no_policy, tmp_path):
    att = tmp_path / "photo of drain.jpg"
    att.write_bytes(b"\xff\xd8made-up-jpeg")
    s = _store(tmp_path, attach=str(att))
    recs = [r for r in s.list("rfi") if r["subject"].startswith("Roof")]
    items = ql.gather(s, "rfi", recs, attachments=True)
    assert len(items) == 2 and items[0][1].endswith(".pdf")
    assert "photo of drain.jpg" in items[1][1]
    server.fail[ql.remote_path(s.name, "rfi", items[1][1])] = (
        423, "That file is held (made-up).")
    seen = []
    res = ql.send(ql.Client(server.url, KEY), "s2", s.name, "rfi", items,
                  days=3, progress=lambda i, n, name: seen.append((i, n)))
    assert res[0]["link"].startswith(server.url + "/s/tok")
    assert res[0]["link"].endswith("x3")
    assert "held" in res[1]["error"]                  # the rest still went
    assert seen[0] == (0, 2) and seen[-1] == (2, 2)
    space, path, body = list(server.files.values())[0]
    assert space == "s2" and path.startswith("Example Clinic/RFIs/RFI ")
    assert body.startswith(b"%PDF")
    text = ql.links_text(res, 3)
    assert res[0]["link"] in text and "3 days" in text
    assert "held" not in text


def test_names_are_safe_folder_parts():
    assert ql.remote_path('Job: A/B "1"', "submittal", "a\\b?.pdf") == \
        "Job A B 1/Submittals/a b .pdf"
    assert ql.clean_part("...") == "item"


def test_connection_kept_and_key_encrypted(no_policy, tmp_path, monkeypatch):
    from app import secretstore, settings
    monkeypatch.setattr(secretstore, "protect",
                        lambda data, what="": b"ENC" + data[::-1])
    monkeypatch.setattr(secretstore, "unprotect",
                        lambda blob: blob[3:][::-1])
    ql.save_connection(url="files.example.com", key=KEY,
                       space={"id": "s2", "name": "Estimating"}, days=5)
    raw = settings.get(ql.S_KEY)
    assert KEY not in raw and raw.startswith("dpapi:")
    c = ql.connection()
    assert c == {"url": "https://files.example.com", "key": KEY,
                 "space": {"id": "s2", "name": "Estimating"}, "days": 5,
                 "it": False}


def test_it_policy_sets_server_and_key_or_turns_it_off(monkeypatch,
                                                       server):
    monkeypatch.setattr(policy, "_from_registry", lambda: {
        "QuantiLinkURL": server.url, "QuantiLinkKey": KEY})
    policy.reload()
    try:
        c = ql.connection()
        assert c["it"] and c["key"] == KEY and c["url"] == server.url
        assert policy.masked()["QuantiLinkKey"] == "(set)"
        from app import diagnostics
        assert KEY in diagnostics._secrets()
        assert ql.Client(c["url"], c["key"]).spaces()
        monkeypatch.setattr(policy, "_from_registry", lambda: {
            "DisableQuantiLink": 1})
        policy.reload()
        with pytest.raises(policy.Blocked):
            ql.Client(server.url, KEY)
        assert not policy.allowed("quantilink")
    finally:
        monkeypatch.setattr(policy, "_from_registry", lambda: {})
        policy.reload()


def test_home_tab_button_and_window(win, server, no_policy, tmp_path,
                                    monkeypatch):
    from app import quickaccess, quantilink_ui
    act = win.command("Send with QuantiLink")
    assert act is not None
    hit = quickaccess.where_is(win, act)
    assert hit and hit[1] == "Home"
    from app.ribbon import all_actions
    assert all(a is not act for _p, a in all_actions(win.menuBar()))
    monkeypatch.setattr(ql, "connection", lambda: {
        "url": server.url, "key": KEY, "space": {"id": "s2", "name":
                                                  "Estimating"},
        "days": 7, "it": False})
    monkeypatch.setattr(ql, "save_connection", lambda **kw: None)
    s = _store(tmp_path)
    d = win.send_quantilink(store=s, show=False)
    assert isinstance(d, quantilink_ui.SendDialog)
    assert d.list.count() == 2
    assert d.send(wait=True) is None                  # nothing ticked
    d.list.item(0).setCheckState(quantilink_ui.Qt.Checked)
    d.attach.setChecked(False)
    res = d.send(wait=True)
    assert len(res) == 1 and res[0]["link"].startswith(server.url + "/s/")
    assert res[0]["link"] in d.out.toPlainText()
    assert d.copy_btn.isEnabled()
    d.copy()
    from PySide6.QtGui import QGuiApplication
    assert res[0]["link"] in QGuiApplication.clipboard().text()
    d.close()


def test_connection_window_lists_folders_it_can_send_to(qapp, server,
                                                        no_policy,
                                                        monkeypatch):
    from app import quantilink_ui
    monkeypatch.setattr(ql, "connection", lambda: {
        "url": "", "key": "", "space": {}, "days": 7, "it": False})
    d = quantilink_ui.ConnectionDialog()
    d.url.setText(server.url)
    d.key.setText(KEY)
    d.load()
    names = [d.space.itemText(i) for i in range(d.space.count())]
    assert len(names) == 2 and not any("Archive" in n for n in names)
    saved = {}
    monkeypatch.setattr(ql, "save_connection",
                        lambda **kw: saved.update(kw))
    d.save()
    assert saved["key"] == KEY and saved["space"]["id"] in ("s1", "s2")
