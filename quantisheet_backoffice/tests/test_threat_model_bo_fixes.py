"""Threat model T-012 / T-013 / T-015 (0.13.14), made-up data."""
import pytest

from quantisheet_backoffice import backup, remote, security


@pytest.mark.parametrize("url", ["http://localhost.example.invalid",
                                 "http://127.0.0.1.example.invalid:80",
                                 "ftp://example.invalid", "http://example.invalid"])
def test_server_address_must_be_https_or_this_pc(url):
    with pytest.raises(remote.RemoteError):
        remote.HttpTransport(url, "t")


@pytest.mark.parametrize("url", ["https://example.invalid",
                                 "http://localhost:8080", "http://127.0.0.1"])
def test_good_server_addresses(url):
    t = remote.HttpTransport(url + "/", "tok")
    assert t.url == url                      # trailing slash dropped
    assert t.token == "tok" and t.timeout == 30


def test_restore_needs_permission(office, tmp_path):
    office.act_as("viewer@bo.test")
    with pytest.raises(Exception):
        backup.restore(office.folder, str(tmp_path / "x.qsbk"),
                       office=office)


def test_restore_refuses_absurd_key_rounds(office, tmp_path, monkeypatch):
    p = tmp_path / "x.qsbk"
    import json
    p.write_bytes(backup.MAGIC + json.dumps({"password": {
        "salt": "00" * 16, "rounds": 10**12, "dbkey": "x",
        "datakey": "x"}}).encode() + b"\n" + b"body")
    with pytest.raises(backup.BackupError):
        backup.restore(office.folder, str(p), password="example pw")


def test_wrong_passwords_lock_the_address_not_the_worker(tmp_path):
    """T-013: 5 wrong passwords from one address lock that address; the
    worker can still sign in from their own phone."""
    from datetime import datetime, timezone
    from cryptography.fernet import Fernet
    from quantisheet_backoffice.server.app import ServerApp, _Err
    t = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
    app = ServerApp(str(tmp_path / "srv"), key=Fernet.generate_key(),
                    office_token="office-token-0123456789abcdef",
                    now=lambda: t)
    app.db.execute("INSERT INTO accounts (employee_no, data, pw_hash, "
                   "must_change, photo_consent, active) VALUES "
                   "(?,?,?,?,?,?)", ("E900", app.enc({}),
                                     security.hash_password("right pass 9"),
                                     0, 0, 1))
    for _ in range(5):
        with pytest.raises(_Err):
            app.login({"employee_no": "E900", "password": "nope"},
                      "203.0.113.9")
    with pytest.raises(_Err, match="locked"):
        app.login({"employee_no": "E900", "password": "right pass 9"},
                  "203.0.113.9")
    assert app.login({"employee_no": "E900", "password": "right pass 9"},
                     "198.51.100.4")["token"]
