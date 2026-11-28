"""tools/r2_release.py: S3 signature v4 (checked against AWS's published
example), installer before version.json, and the key never in a request
URL or an error. Made-up keys and a fake bucket on localhost."""
import datetime
import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import r2_release as r2                                     # noqa: E402

KEY_ID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_signature_matches_the_aws_example():
    # AWS S3 docs, "Example: GET Object" (header-based auth, sigv4)
    empty = hashlib.sha256(b"").hexdigest()
    auth = r2.sign("GET", "examplebucket.s3.amazonaws.com", "/test.txt",
                   {"Range": "bytes=0-9"}, empty, KEY_ID, SECRET,
                   "20130524T000000Z", region="us-east-1")
    assert auth.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0"
                         "170aba48dd91039c6036bdb41")
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in auth


@pytest.fixture
def bucket():
    got = []

    class H(BaseHTTPRequestHandler):
        def do_PUT(self):
            n = int(self.headers["Content-Length"])
            body = self.rfile.read(n)
            got.append({"path": self.path, "auth":
                        self.headers["Authorization"],
                        "sha": self.headers["x-amz-content-sha256"],
                        "body": body})
            code = 403 if b"deny" in body else 200
            self.send_response(code)
            out = b"<Error><Code>AccessDenied</Code></Error>" \
                if code == 403 else b""
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.got = got
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


def test_put_signs_the_file_it_sends(bucket, tmp_path):
    p = tmp_path / "QuantiSheet-Beta-Setup-9.9.9.exe"
    p.write_bytes(b"made-up installer" * 100)
    cred = {"account": "made-up", "key_id": KEY_ID, "secret": SECRET}
    now = datetime.datetime(2026, 11, 25, 12, 0, tzinfo=datetime.timezone.utc)
    assert r2.put(cred, "f0/team/" + p.name, str(p), "application/x",
                  bucket.url, now) == 200
    g = bucket.got[0]
    assert g["path"] == "/quantisheet-updates/f0/team/" + p.name
    assert g["sha"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert g["auth"].startswith(f"AWS4-HMAC-SHA256 Credential={KEY_ID}/"
                                "20261125/auto/s3/aws4_request")
    assert SECRET not in g["auth"] and SECRET not in g["path"]
    bad = tmp_path / "deny.bin"
    bad.write_bytes(b"deny")
    with pytest.raises(SystemExit) as e:
        r2.put(cred, "f0/team/deny.bin", str(bad), "application/x",
               bucket.url, now)
    assert "AccessDenied" in str(e.value) and SECRET not in str(e.value)


def test_installer_goes_before_version_json(bucket, tmp_path, monkeypatch):
    from app import updatecheck
    folder = "madeupfolder"
    monkeypatch.setattr(updatecheck, "UPDATE_BASE",
                        f"https://updates.example.com/{folder}")
    monkeypatch.setattr(r2, "ROOT", str(tmp_path))
    team = tmp_path / "release" / "r2_upload" / folder / "team"
    team.mkdir(parents=True)
    (team / "QuantiSheet-Beta-Setup-9.9.9.exe").write_bytes(b"x" * 10)
    (team / "version.json").write_text(json.dumps(
        {"manifest": {"version": "9.9.8"}, "sig": "s"}))
    with pytest.raises(SystemExit, match="another version"):
        r2.files("9.9.9")
    (team / "version.json").write_text(json.dumps(
        {"manifest": {"version": "9.9.9"}, "sig": "s"}))
    monkeypatch.setattr(r2, "load_cred", lambda: {
        "account": "a", "key_id": KEY_ID, "secret": SECRET})
    r2.upload(bucket.url, "9.9.9")
    assert [g["path"].rsplit("/", 1)[1] for g in bucket.got] == [
        "QuantiSheet-Beta-Setup-9.9.9.exe", "version.json"]


def test_key_is_kept_encrypted(tmp_path, monkeypatch):
    from app import secretstore
    monkeypatch.setattr(secretstore, "protect",
                        lambda data, what="": b"ENC" + data[::-1])
    monkeypatch.setattr(secretstore, "unprotect", lambda b: b[3:][::-1])
    path = str(tmp_path / "keys" / "r2_upload.dat")
    cred = {"account": "a", "key_id": KEY_ID, "secret": SECRET}
    r2.save_cred(cred, path)
    raw = open(path, "rb").read()
    assert SECRET.encode() not in raw
    assert r2.load_cred(path) == cred


def test_setup_from_a_file_encrypts_and_removes_it(tmp_path, monkeypatch,
                                                   capsys):
    from app import secretstore
    monkeypatch.setattr(secretstore, "protect",
                        lambda data, what="": b"ENC" + data[::-1])
    monkeypatch.setattr(secretstore, "unprotect", lambda b: b[3:][::-1])
    plain = tmp_path / "r2_upload.json"
    plain.write_text(json.dumps({"account": "acct", "key_id": KEY_ID,
                                 "secret": SECRET}))
    dat = str(tmp_path / "r2_upload.dat")
    r2.setup_from_file(str(plain), dat)
    assert not plain.exists()
    assert r2.load_cred(dat)["secret"] == SECRET
    r2.check(dat)
    out = capsys.readouterr().out
    assert SECRET not in out and KEY_ID not in out
    plain.write_text(json.dumps({"account": "a", "key_id": ""}))
    with pytest.raises(SystemExit):
        r2.setup_from_file(str(plain), dat)
    assert plain.exists()                 # nothing removed on a bad file
