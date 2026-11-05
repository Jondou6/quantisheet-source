"""Dropbox open / save (app/dropbox_sync.py, app/dropbox_ui.py), with an
in-memory fake Dropbox in place of the HTTP layer: no network."""
import ast
import hashlib
import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

import pytest

from app import dropbox_sync as dbx
from app import policy, settings

KEY = "abc123def456ghi"
REFRESH = "RT-very-secret-refresh-0001"
CODE = "AUTH-CODE-secret-777"


# ---- the fake Dropbox -------------------------------------------------------------
def _hash(data):
    h = dbx.ContentHasher()
    h.update(data)
    return h.hexdigest()


class FakeDropbox:
    """Just enough of the Dropbox API v2, in memory."""

    def __init__(self):
        self.files = {}               # lower path -> {"name","path","data","rev"}
        self.folders = {""}
        self.calls = []
        self.n = 0
        self.valid = set()
        self.expired = set()
        self.refresh_tokens = {REFRESH}
        self.sessions = {}
        self.page = 2
        self.revoked = False
        self.challenge = None

    # helpers
    def put(self, path, data):
        path = dbx.normalize(path)
        self.n += 1
        rev = f"{self.n:09x}"
        self.files[path.lower()] = {"path": path, "data": data, "rev": rev}
        p = dbx.parent(path)
        while p:
            self.folders.add(p.lower())
            p = dbx.parent(p)
        return self.meta(path)

    def meta(self, path):
        f = self.files[dbx.normalize(path).lower()]
        return {".tag": "file", "name": dbx.basename(f["path"]),
                "path_display": f["path"], "path_lower": f["path"].lower(),
                "id": "id:" + hashlib.md5(f["path"].lower().encode())
                .hexdigest()[:8], "rev": f["rev"], "size": len(f["data"]),
                "content_hash": _hash(f["data"]),
                "server_modified": "2026-10-23T10:00:00Z"}

    def new_token(self):
        self.n += 1
        t = f"AT-secret-{self.n}"
        self.valid.add(t)
        return t

    @staticmethod
    def _resp(status, obj=None, headers=None, body=None):
        if body is None:
            body = json.dumps(obj).encode() if obj is not None else b""
        return dbx.Response(status, headers or {}, body=body)

    def _err(self, summary, status=409):
        return self._resp(status, {"error_summary": summary + "/..",
                                   "error": {".tag": summary.split("/")[0]}})

    # the transport
    def __call__(self, method, url, headers, data, timeout):
        assert method == "POST"
        assert url.startswith("https://")
        body = data.read() if hasattr(data, "read") else (data or b"")
        u = urllib.parse.urlsplit(url)
        assert not u.query, "nothing in the URL"
        name = u.path.split("/2/", 1)[-1] if "/2/" in u.path else u.path
        self.calls.append(name)
        if url == dbx.TOKEN_URL:
            return self._token(urllib.parse.parse_qs(body.decode()))
        auth = headers.get("Authorization", "")
        tok = auth[len("Bearer "):]
        if tok in self.expired:
            return self._resp(401, {"error_summary": "expired_access_token/",
                                    "error": {".tag":
                                              "expired_access_token"}})
        if tok not in self.valid:
            return self._resp(401, {"error_summary": "invalid_access_token/",
                                    "error": {".tag":
                                              "invalid_access_token"}})
        if u.netloc == "content.dropboxapi.com":
            arg = json.loads(headers["Dropbox-API-Arg"])
            return self._content(name, arg, body, headers)
        assert headers.get("Content-Type") == "application/json"
        return self._rpc(name, json.loads(body.decode() or "null"))

    def _token(self, q):
        q = {k: v[0] for k, v in q.items()}
        if q["grant_type"] == "authorization_code":
            if q.get("code") != CODE:
                return self._resp(400, {"error": "invalid_grant"})
            if self.challenge and dbx.pkce_challenge(q["code_verifier"]) \
                    != self.challenge:
                return self._resp(400, {"error": "invalid_grant"})
            return self._resp(200, {"access_token": self.new_token(),
                                    "expires_in": 14400,
                                    "refresh_token": REFRESH,
                                    "account_id": "dbid:1"})
        if q["grant_type"] == "refresh_token":
            if q.get("refresh_token") not in self.refresh_tokens:
                return self._resp(400, {"error": "invalid_grant"})
            return self._resp(200, {"access_token": self.new_token(),
                                    "expires_in": 14400})
        return self._resp(400, {"error": "unsupported_grant_type"})

    def _rpc(self, name, a):
        if name == "files/list_folder":
            path = a["path"].lower()
            if path not in self.folders:
                return self._err("path/not_found")
            items = []
            for f in sorted(self.folders):
                if f and dbx.parent(f) == path:
                    items.append({".tag": "folder", "name": dbx.basename(f),
                                  "path_display": f, "path_lower": f})
            for k in sorted(self.files):
                if dbx.parent(k) == path:
                    items.append(self.meta(k))
            return self._page(items, 0)
        if name == "files/list_folder/continue":
            items, start = json.loads(a["cursor"])
            return self._page(items, start)
        if name == "files/get_metadata":
            if a["path"].lower() in self.files:
                return self._resp(200, self.meta(a["path"]))
            if a["path"].lower() in self.folders:
                return self._resp(200, {".tag": "folder",
                                        "path_display": a["path"]})
            return self._err("path/not_found")
        if name == "files/create_folder_v2":
            self.folders.add(a["path"].lower())
            return self._resp(200, {"metadata": {"path_display": a["path"]}})
        if name == "users/get_current_account":
            return self._resp(200, {"account_id": "dbid:1",
                                    "name": {"display_name": "Sam Builder"},
                                    "email": "sam@example.com"})
        if name == "auth/token/revoke":
            self.revoked = True
            self.refresh_tokens.clear()
            self.valid.clear()
            return self._resp(200, None)
        return self._resp(400, body=b"unknown endpoint")

    def _page(self, items, start):
        chunk = items[start:start + self.page]
        more = start + self.page < len(items)
        return self._resp(200, {"entries": chunk, "has_more": more,
                                "cursor": json.dumps([items,
                                                      start + self.page])})

    def _commit(self, c, data):
        path = c["path"]
        cur = self.files.get(path.lower())
        mode = c["mode"]
        assert c["autorename"] is False
        if mode == "add" and cur:
            return self._err("path/conflict/file")
        if isinstance(mode, dict) and mode[".tag"] == "update":
            if not cur or cur["rev"] != mode["update"]:
                return self._err("path/conflict/file")
        return self._resp(200, self.put(path, data))

    def _content(self, name, arg, body, headers):
        if name == "files/download":
            if arg["path"].lower() not in self.files:
                return self._err("path/not_found")
            m = self.meta(arg["path"])
            return self._resp(200, headers={"Dropbox-API-Result":
                                            json.dumps(m)},
                              body=self.files[arg["path"].lower()]["data"])
        assert headers["Content-Type"] == "application/octet-stream"
        if name == "files/upload":
            assert len(body) < dbx.SINGLE_UPLOAD_MAX
            return self._commit(arg, body)
        if name == "files/upload_session/start":
            sid = f"s{len(self.sessions)}"
            self.sessions[sid] = [body]
            return self._resp(200, {"session_id": sid})
        if name == "files/upload_session/append_v2":
            c = arg["cursor"]
            got = sum(len(b) for b in self.sessions[c["session_id"]])
            if c["offset"] != got:
                return self._err("incorrect_offset")
            self.sessions[c["session_id"]].append(body)
            return self._resp(200, None)
        if name == "files/upload_session/finish":
            c = arg["cursor"]
            parts = self.sessions.pop(c["session_id"]) + [body]
            data = b"".join(parts)
            assert len(data) == c["offset"]
            return self._commit(arg["commit"], data)
        return self._resp(400, body=b"unknown endpoint")


@pytest.fixture
def home(tmp_path, monkeypatch):
    d = tmp_path / "home"
    d.mkdir()
    monkeypatch.setattr(settings, "DIR", str(d))
    monkeypatch.setattr(settings, "PATH", str(d / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})
    from app import secretstore
    monkeypatch.setattr(secretstore, "_backend", lambda: None)  # file 0600
    return d


@pytest.fixture
def fake(monkeypatch, home):
    f = FakeDropbox()
    monkeypatch.setattr(dbx, "transport", f)

    def no_net(*a, **k):
        raise AssertionError("real network used")
    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    settings.set("dropbox_app_key", KEY)
    return f


@pytest.fixture
def client(fake):
    c = dbx.Client(KEY, tokens={})
    c.exchange_code(CODE, "v" * 50)
    return c


# ---- PKCE, content hash --------------------------------------------------------------
def test_pkce_rfc7636_example():
    # RFC 7636 appendix B
    assert dbx.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") \
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    v, c = dbx.pkce_pair()
    assert 43 <= len(v) <= 128 and set(v) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert c == dbx.pkce_challenge(v) and "=" not in c
    assert dbx.pkce_pair()[0] != v


def test_authorize_url_has_pkce_offline_scopes_and_no_secret():
    url = dbx.authorize_url(KEY, "CH", "ST", "http://127.0.0.1:53917/")
    u = urllib.parse.urlsplit(url)
    assert url.startswith(dbx.AUTHORIZE_URL + "?")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    assert q["client_id"] == KEY and q["code_challenge"] == "CH"
    assert q["code_challenge_method"] == "S256"
    assert q["token_access_type"] == "offline"
    assert q["response_type"] == "code" and q["state"] == "ST"
    assert q["redirect_uri"] == "http://127.0.0.1:53917/"
    for s in ("files.metadata.read", "files.content.read",
              "files.content.write"):
        assert s in q["scope"].split()
    assert "secret" not in url.lower()
    # the code flow: no redirect
    assert "redirect_uri" not in dbx.authorize_url(KEY, "CH")


def test_content_hash_matches_dropbox_algorithm(tmp_path):
    # an empty file: SHA-256 of no block hashes (Dropbox gives e3b0...)
    assert _hash(b"") == hashlib.sha256(b"").hexdigest()
    data = os.urandom(dbx.BLOCK * 2 + 12345)
    want = hashlib.sha256(b"".join(
        hashlib.sha256(data[i:i + dbx.BLOCK]).digest()
        for i in range(0, len(data), dbx.BLOCK))).hexdigest()
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    assert dbx.content_hash(str(p)) == want
    # fed in odd-sized pieces, same answer
    h = dbx.ContentHasher()
    for i in range(0, len(data), 999_983):
        h.update(data[i:i + 999_983])
    assert h.hexdigest() == want
    # exactly one block: one block hash, not two
    one = b"x" * dbx.BLOCK
    assert _hash(one) == hashlib.sha256(
        hashlib.sha256(one).digest()).hexdigest()
    assert _hash(data) != hashlib.sha256(data).hexdigest()


# ---- paths -------------------------------------------------------------------------------
def test_paths_and_working_copy_location(home):
    assert dbx.normalize("") == "" and dbx.normalize("/") == ""
    assert dbx.normalize("a//b/") == "/a/b"
    assert dbx.parent("/a/b.pdf") == "/a" and dbx.parent("/b.pdf") == ""
    p = dbx.local_path_for("/Jobs/Smith Residence/A-101.pdf")
    assert p == os.path.join(str(home), "Dropbox", "Jobs",
                             "Smith Residence", "A-101.pdf")
    # never outside the Dropbox folder, and Windows-safe names
    bad = dbx.local_path_for("/../x/CON/a:b?.pdf")
    assert bad.startswith(os.path.join(str(home), "Dropbox") + os.sep)
    assert ".." not in bad.split(os.sep) and ":" not in os.path.basename(bad)
    assert dbx.is_working_copy(p)


# ---- listing, download, sidecar ------------------------------------------------------------
def test_list_folder_follows_every_page(fake, client):
    for i in range(7):
        fake.put(f"/Jobs/sheet{i}.pdf", b"%PDF-1.7 " + bytes([i]))
    fake.folders.add("/jobs/sub")
    names = sorted(e["name"] for e in client.list_folder("/Jobs"))
    assert names == sorted([f"sheet{i}.pdf" for i in range(7)] + ["sub"])
    assert fake.calls.count("files/list_folder") == 1
    assert fake.calls.count("files/list_folder/continue") == 3   # 8 / 2 - 1


def test_download_makes_working_copy_and_sidecar(fake, client, home):
    data = os.urandom(dbx.READ * 3 + 7)
    m = fake.put("/Jobs/Plan Set.pdf", data)
    seen = []
    local = dbx.fetch(client, "/Jobs/Plan Set.pdf",
                      progress=lambda d, t: seen.append((d, t)))
    assert local == dbx.local_path_for("/Jobs/Plan Set.pdf")
    assert open(local, "rb").read() == data
    assert not os.path.exists(local + ".part")
    assert seen[-1] == (len(data), len(data))
    link = dbx.read_link(local)
    assert link["path"] == "/Jobs/Plan Set.pdf"
    assert link["rev"] == m["rev"] and link["content_hash"] == m[
        "content_hash"]
    assert dbx.local_state(local) == "clean"
    # edited here: a second download asks first
    with open(local, "ab") as f:
        f.write(b"more")
    assert dbx.local_state(local) == "changed"
    with pytest.raises(dbx.LocalChanges):
        dbx.fetch(client, "/Jobs/Plan Set.pdf")
    dbx.fetch(client, "/Jobs/Plan Set.pdf", replace_local=True)
    assert open(local, "rb").read() == data


def test_damaged_download_is_not_kept(fake, client, monkeypatch):
    fake.put("/a.pdf", b"good data")
    real = fake.meta

    def lying(path):
        m = real(path)
        m["content_hash"] = "0" * 64
        return m
    monkeypatch.setattr(fake, "meta", lying)
    with pytest.raises(dbx.DropboxError, match="damaged"):
        dbx.fetch(client, "/a.pdf")
    assert not os.path.exists(dbx.local_path_for("/a.pdf"))


# ---- re-save: update vs conflict -------------------------------------------------------------
def test_resave_unchanged_rev_updates(fake, client):
    fake.put("/Jobs/A.pdf", b"v1")
    local = dbx.fetch(client, "/Jobs/A.pdf")
    # nothing changed: nothing is sent
    meta, sent = dbx.resave(client, local)
    assert not sent and "files/upload" not in fake.calls
    with open(local, "wb") as f:
        f.write(b"v2 from QuantiSheet")
    meta, sent = dbx.resave(client, local)
    assert sent and fake.files["/jobs/a.pdf"]["data"] == b"v2 from QuantiSheet"
    assert dbx.read_link(local)["rev"] == meta["rev"]
    # and again (the remembered rev moved on with the save)
    with open(local, "wb") as f:
        f.write(b"v3")
    assert dbx.resave(client, local)[1]


def test_resave_changed_rev_raises_conflict_and_overwrites_on_request(
        fake, client):
    fake.put("/Jobs/A.pdf", b"v1")
    local = dbx.fetch(client, "/Jobs/A.pdf")
    fake.put("/Jobs/A.pdf", b"someone else's v2")
    with open(local, "wb") as f:
        f.write(b"my v2")
    with pytest.raises(dbx.Conflict) as e:
        dbx.resave(client, local)
    assert e.value.remote["rev"] == fake.files["/jobs/a.pdf"]["rev"]
    assert fake.files["/jobs/a.pdf"]["data"] == b"someone else's v2"
    assert "files/upload" not in fake.calls          # nothing was sent
    # the user chose Overwrite
    dbx.resave(client, local, overwrite_rev=e.value.remote["rev"])
    assert fake.files["/jobs/a.pdf"]["data"] == b"my v2"


def test_conflict_between_check_and_upload_is_caught(fake, client,
                                                     monkeypatch):
    fake.put("/A.pdf", b"v1")
    local = dbx.fetch(client, "/A.pdf")
    with open(local, "wb") as f:
        f.write(b"mine")
    real = client.get_metadata
    state = {"n": 0}

    def racing(path):
        m = real(path)
        if state["n"] == 0:
            fake.put("/A.pdf", b"theirs, just now")
        state["n"] += 1
        return m
    monkeypatch.setattr(client, "get_metadata", racing)
    with pytest.raises(dbx.Conflict) as e:
        dbx.resave(client, local)
    assert e.value.remote["rev"] == fake.files["/a.pdf"]["rev"]
    assert fake.files["/a.pdf"]["data"] == b"theirs, just now"


def test_resave_of_a_deleted_file_and_plan(fake, client):
    fake.put("/A.pdf", b"v1")
    local = dbx.fetch(client, "/A.pdf")
    del fake.files["/a.pdf"]
    with pytest.raises(dbx.NotFound):
        dbx.resave(client, local)
    link = {"rev": "1", "content_hash": "h1"}
    assert dbx.resave_plan(link, None, "x") == ("missing", None)
    assert dbx.resave_plan(link, {"rev": "1", "content_hash": "h1"},
                           "h1") == ("up_to_date", "1")
    assert dbx.resave_plan(link, {"rev": "1", "content_hash": "h1"},
                           "h2") == ("update", "1")
    assert dbx.resave_plan(link, {"rev": "2", "content_hash": "h9"},
                           "h2") == ("changed", "2")
    # a new rev with the very same content isn't a change
    assert dbx.resave_plan(link, {"rev": "2", "content_hash": "h1"},
                           "h2") == ("update", "2")


def test_new_file_never_overwrites_silently(fake, client, tmp_path):
    p = tmp_path / "Takeoff Report.xlsx"
    p.write_bytes(b"PK excel")
    fake.put("/Reports/Takeoff Report.xlsx", b"older report")
    with pytest.raises(dbx.Conflict):
        dbx.save_new(client, str(p), "/Reports/Takeoff Report.xlsx")
    assert fake.files["/reports/takeoff report.xlsx"]["data"] == \
        b"older report"
    m = dbx.save_new(client, str(p), "/Reports/Takeoff Report 2.xlsx")
    assert m["path_display"] == "/Reports/Takeoff Report 2.xlsx"
    assert dbx.read_link(str(p))["path"] == "/Reports/Takeoff Report 2.xlsx"
    # Replace (the user said so): update with the rev that is there
    rev = fake.files["/reports/takeoff report.xlsx"]["rev"]
    dbx.save_new(client, str(p), "/Reports/Takeoff Report.xlsx",
                 replace_rev=rev)
    assert fake.files["/reports/takeoff report.xlsx"]["data"] == b"PK excel"


def test_encrypted_pdf_uploads_byte_for_byte(fake, client, tmp_path):
    raw = b"%PDF-1.7\n1 0 obj<</Filter/Standard/V 5/R 6>>endobj\n" + \
        os.urandom(5000)
    p = tmp_path / "locked.pdf"
    p.write_bytes(raw)
    dbx.save_new(client, str(p), "/locked.pdf")
    assert fake.files["/locked.pdf"]["data"] == raw


def test_copy_name():
    assert dbx.copy_name("A-101.pdf", "Sam", "2026-10-23") == \
        "A-101 (copy by Sam 2026-10-23).pdf"


# ---- big files: upload sessions -------------------------------------------------------------
def test_big_file_goes_up_in_session_chunks(fake, client, tmp_path,
                                            monkeypatch):
    monkeypatch.setattr(dbx, "SINGLE_UPLOAD_MAX", 1000)
    monkeypatch.setattr(dbx, "CHUNK", 300)
    data = os.urandom(1000 + 250)                 # 300 x 4 + 50
    p = tmp_path / "big.pdf"
    p.write_bytes(data)
    seen = []
    m = dbx.save_new(client, str(p), "/Big/big.pdf",
                     progress=lambda d, t: seen.append((d, t)))
    assert fake.files["/big/big.pdf"]["data"] == data
    assert m["content_hash"] == dbx.content_hash(str(p))
    assert fake.calls.count("files/upload_session/start") == 1
    assert fake.calls.count("files/upload_session/append_v2") == 4
    assert fake.calls.count("files/upload_session/finish") == 1
    assert "files/upload" not in fake.calls
    assert seen[-1] == (len(data), len(data))
    assert all(a <= b for (a, _), (b, _) in zip(seen, seen[1:]))


def test_upload_can_be_cancelled(fake, client, tmp_path, monkeypatch):
    monkeypatch.setattr(dbx, "SINGLE_UPLOAD_MAX", 10)
    monkeypatch.setattr(dbx, "CHUNK", 10)
    p = tmp_path / "x.pdf"
    p.write_bytes(b"y" * 100)
    with pytest.raises(dbx.Cancelled):
        dbx.save_new(client, str(p), "/x.pdf", cancel=lambda: True)
    assert "/x.pdf" not in fake.files


# ---- tokens ---------------------------------------------------------------------------------
def test_expired_access_token_is_refreshed_once(fake, client):
    fake.put("/a.pdf", b"x")
    old = client._access
    fake.valid.discard(old)
    fake.expired.add(old)
    assert client.get_metadata("/a.pdf")["rev"]
    assert client._access != old
    assert fake.calls.count("/oauth2/token") == 2      # sign-in + refresh
    # the stored refresh token keeps working for a new Client
    c2 = dbx.Client(KEY)
    assert c2.tokens["refresh_token"] == REFRESH and c2._access is None
    assert c2.get_metadata("/a.pdf")


def test_revoked_refresh_token_signs_out(fake, client):
    fake.refresh_tokens.clear()
    fake.valid.clear()
    with pytest.raises(dbx.NotSignedIn):
        client.list_folder("")
    assert not dbx.signed_in() and dbx.load_tokens() == {}


def test_sign_out_revokes_and_deletes(fake, client, home):
    client.current_account()
    t = dbx.load_tokens()
    assert t["name"] == "Sam Builder" and t["email"] == "sam@example.com"
    assert dbx.signed_in()
    dbx.Client(KEY).revoke()
    assert fake.revoked and "auth/token/revoke" in fake.calls
    assert not dbx.signed_in()
    assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))


@pytest.mark.skipif(os.name == "nt", reason="file mode bits")
def test_token_file_is_user_only_off_windows(fake, client, home):
    st = os.stat(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))
    assert st.st_mode & 0o077 == 0


def test_tokens_use_dpapi_when_available(home, monkeypatch):
    from app import secretstore

    class Fake:
        @staticmethod
        def protect(b):
            return b"ENC" + bytes(x ^ 0x5A for x in b)

        @staticmethod
        def unprotect(b):
            return bytes(x ^ 0x5A for x in b[3:])
    monkeypatch.setattr(secretstore, "_backend", lambda: Fake)
    dbx.save_tokens({"refresh_token": REFRESH, "app_key": KEY})
    p = os.path.join(str(home), dbx.TOKEN_FILE_DPAPI)
    assert REFRESH.encode() not in open(p, "rb").read()
    assert dbx.load_tokens()["refresh_token"] == REFRESH
    assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))
    dbx.clear_tokens()
    assert not os.path.exists(p)


def test_a_different_app_key_is_not_signed_in(fake, client):
    assert dbx.signed_in()
    settings.set("dropbox_app_key", "zzzzzzzzzzzzzzz")
    assert not dbx.signed_in()


def test_no_token_or_code_in_logs(fake, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    c = dbx.Client(KEY, tokens={})
    c.exchange_code(CODE, "v" * 50)
    fake.put("/a.pdf", b"SECRET-FILE-CONTENTS")
    local = dbx.fetch(c, "/a.pdf")
    fake.expired.add(c._access)
    fake.valid.discard(c._access)
    with open(local, "wb") as f:
        f.write(b"SECRET-FILE-CONTENTS-2")
    dbx.resave(c, local)
    c.current_account()
    with pytest.raises(dbx.DropboxError):
        dbx.Client(KEY, tokens={}).exchange_code("wrong-code", "v" * 50)
    c.revoke()
    text = caplog.text + " ".join(str(r.args) for r in caplog.records)
    assert "files/download" in text                 # it did log
    for secret in [REFRESH, CODE, "AT-secret", "SECRET-FILE-CONTENTS",
                   "wrong-code"]:
        assert secret not in text, secret


# ---- policy -----------------------------------------------------------------------------
def _it(tmp_path, monkeypatch, **kw):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(kw))
    monkeypatch.setenv("QUANTISHEET_POLICY_FILE", str(p))
    policy.reload()


def test_policy_turns_dropbox_off(fake, client, tmp_path, monkeypatch):
    assert dbx.allowed()
    _it(tmp_path, monkeypatch, DisableDropbox=True)
    assert not dbx.allowed()
    with pytest.raises(policy.Blocked, match="DisableDropbox"):
        client.list_folder("")
    n = len(fake.calls)
    _it(tmp_path, monkeypatch, OfflineMode=True)
    assert not dbx.allowed()
    with pytest.raises(policy.Blocked):
        client.get_metadata("/x")
    assert len(fake.calls) == n                      # nothing was sent


def test_policy_app_key_wins(home, tmp_path, monkeypatch):
    settings.set("dropbox_app_key", "userkey1234567")
    assert dbx.app_key() == "userkey1234567" and not dbx.app_key_from_policy()
    _it(tmp_path, monkeypatch, DropboxAppKey="itkey12345678ab")
    assert dbx.app_key() == "itkey12345678ab" and dbx.app_key_from_policy()
    assert "dropbox" in policy.NETWORK
    assert "DisableDropbox" in policy.SETTINGS
    assert "DropboxAppKey" in policy.SETTINGS


# ---- the loopback sign-in server -------------------------------------------------------------
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _get(port, query):
    url = f"http://127.0.0.1:{port}/?" + urllib.parse.urlencode(query)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_loopback_binds_127_only_and_checks_state(caplog):
    caplog.set_level(logging.DEBUG)
    port = _free_port()
    rec = dbx.LoopbackReceiver("good-state", port).start()
    try:
        assert rec.server.server_address[0] == "127.0.0.1"
        assert rec.redirect == f"http://127.0.0.1:{port}/"
        st, body = _get(port, {"code": "STOLEN", "state": "bad"})
        assert st == 400 and rec.code is None and rec.rejected == 1
        st, _ = _get(port, {"code": "STOLEN"})             # no state
        assert st == 400 and rec.code is None
        assert not rec.done.is_set()
        st, body = _get(port, {"code": CODE, "state": "good-state"})
        assert st == 200 and CODE not in body
        assert rec.wait(5) == CODE
    finally:
        rec.close()
    assert CODE not in caplog.text and "STOLEN" not in caplog.text
    assert rec.server is None                     # one-shot: closed


def test_loopback_reports_user_cancel():
    port = _free_port()
    rec = dbx.LoopbackReceiver("s1", port).start()
    try:
        _get(port, {"error": "access_denied", "state": "s1"})
        assert rec.wait(5) is None and rec.error == "access_denied"
    finally:
        rec.close()


def test_loopback_port_in_use_raises_oserror():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        with pytest.raises(OSError):
            dbx.LoopbackReceiver("s", s.getsockname()[1]).start()
    finally:
        s.close()


def test_redirect_uri_is_fixed_and_documented(home):
    assert dbx.redirect_uri() == "http://127.0.0.1:53917/"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),
               encoding="utf-8").read()
    assert dbx.redirect_uri() in doc


# ---- the Qt side ----------------------------------------------------------------------------
def test_dropbox_buttons_connect_through_a_lambda():
    """Every clicked/triggered connect in dropbox_ui is lambda _c=False:"""
    src = open(os.path.join(os.path.dirname(dbx.__file__), "dropbox_ui.py"),
               encoding="utf-8").read()
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and \
                isinstance(node.func, ast.Attribute) and \
                node.func.attr == "connect" and \
                isinstance(node.func.value, ast.Attribute) and \
                node.func.value.attr in ("clicked", "triggered"):
            n += 1
            lam = node.args[0]
            assert isinstance(lam, ast.Lambda), node.lineno
            a = lam.args
            assert a.args and a.args[0].arg == "_c", node.lineno
            assert isinstance(a.defaults[0], ast.Constant) and \
                a.defaults[0].value is False, node.lineno
    assert n >= 8


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fake_win():
    from PySide6.QtWidgets import QMainWindow
    w = QMainWindow()
    w._doc_actions = []
    w._view = None
    w._path = None
    return w


def test_menu_entries_hidden_when_policy_off(qt, home, tmp_path,
                                              monkeypatch):
    from PySide6.QtWidgets import QMenu
    from app import dropbox_ui
    w = _fake_win()
    m = QMenu()
    acts = dropbox_ui.add_actions(w, m)
    assert list(acts) == ["Open from Dropbox…", "Save to Dropbox",
                          "Save to Dropbox As…", "Dropbox Settings…"]
    assert all(a.isVisible() for a in acts.values())
    assert acts["Save to Dropbox"] in w._doc_actions
    _it(tmp_path, monkeypatch, DisableDropbox=True)
    m2 = QMenu()
    acts = dropbox_ui.add_actions(_fake_win(), m2)
    assert not any(a.isVisible() or a.isEnabled() for a in acts.values())
    # reached another way: a message, no network, no setup screen
    seen = []
    monkeypatch.setattr(dropbox_ui, "_say",
                        lambda parent, text, icon=None: seen.append(text))
    monkeypatch.setattr(dropbox_ui, "setup_screen",
                        lambda p: pytest.fail("setup shown"))
    assert dropbox_ui.ensure_client(w) is None
    assert dropbox_ui.save_to_dropbox(w) is False
    assert seen and "IT department" in seen[0]


def test_no_app_key_shows_the_setup_screen(qt, home, monkeypatch):
    from app import dropbox_ui
    monkeypatch.setattr(dbx, "transport",
                        lambda *a: pytest.fail("network used"))
    shown = []

    def fake_exec(self):
        shown.append(self)
        text = self.steps.text()
        assert "dropbox.com/developers/apps" in text
        assert "Scoped access" in text and "Full Dropbox" in text
        for s in ("files.metadata.read", "files.content.read",
                  "files.content.write"):
            assert s in text
        assert dbx.redirect_uri() in text
        labels = " ".join(w.text() for w in self.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
        assert "App secret" in labels and "not" in labels
        return 0
    monkeypatch.setattr(dropbox_ui.SetupDialog, "exec", fake_exec)
    # the company's own build ships its key; this test is the no-key case
    monkeypatch.setattr(dbx, "company_app_key", lambda: "")
    assert dbx.app_key() == ""
    assert dropbox_ui.ensure_client(_fake_win()) is None
    assert len(shown) == 1
    # pasting a key saves it
    d = dropbox_ui.SetupDialog()
    d.key.setText("not a key!")
    d._save()
    assert dbx.app_key() == "" and not d.error.isHidden()
    d.key.setText(KEY)
    d._save()
    assert dbx.app_key() == KEY


def test_settings_dialog_shows_the_account(qt, fake, client):
    from app import dropbox_ui
    client.current_account()
    d = dropbox_ui.SettingsDialog(_fake_win())
    assert "Sam Builder" in d.account.text()
    assert "sam@example.com" in d.account.text()
    assert d.sign.text() == "Sign Out"
    d.folder.setText("Jobs/2026")
    d.done(0)
    assert settings.get("dropbox_default_folder") == "/Jobs/2026"


try:                                   # the real window, where it can run
    from test_gui import qapp, win  # noqa: F401,E402
    HAVE_GUI = True
except Exception:                                         # noqa: BLE001
    HAVE_GUI = False


@pytest.mark.skipif(not HAVE_GUI, reason="needs PySide6 and PyMuPDF")
def test_main_window_has_the_dropbox_commands(win):  # noqa: F811
    texts = [a.text() for a in win._file_menu.actions()]
    for t in ("Open from Dropbox…", "Save to Dropbox",
              "Save to Dropbox As…", "Dropbox Settings…"):
        assert t in texts, t
    assert texts.index("Save to Dropbox") > texts.index("Save As…")
    acts = win._dropbox_actions
    assert all(a.isVisible() for a in acts.values())
    assert acts["Save to Dropbox"] in win._doc_actions
