"""Back up and restore QuantiSheet's data (review QS-006). Made-up data."""
import os
import sqlite3
import zipfile

from app import databackup, settings


def _setup(tmp_path, monkeypatch):
    data = tmp_path / "qs"
    bo = tmp_path / "bo"
    monkeypatch.setattr(settings, "DIR", str(data))
    monkeypatch.setattr(settings, "PATH", str(data / "settings.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QS_BACKOFFICE_HOME", str(bo))
    (data / "autosave").mkdir(parents=True)
    (data / "autosave" / "big.pdf").write_bytes(b"x" * 1000)
    (data / "toolchest.json").write_text('{"Mine": []}')
    (data / "logs").mkdir()
    (data / "logs" / "a.log").write_text("log")
    bo.mkdir()
    db = sqlite3.connect(str(bo / "backoffice.db"))
    db.execute("pragma journal_mode=wal")
    db.execute("create table t (v text)")
    db.execute("insert into t values ('made up vendor')")
    db.commit()                      # left open: a database in use
    return data, bo, db


def test_backup_has_data_and_skips_caches(tmp_path, monkeypatch):
    data, bo, db = _setup(tmp_path, monkeypatch)
    out = str(tmp_path / "b.qsbackup")
    r = databackup.make(out, password="example pass 1")
    assert r["encrypted"] and databackup.is_encrypted(out)
    assert r["files"] == 2 and r["verified"]["databases_checked"] == 1
    plain = str(tmp_path / "plain.zip")
    databackup._decrypt_file(out, plain, "example pass 1")
    names = zipfile.ZipFile(plain).namelist()
    assert "quantisheet/toolchest.json" in names
    assert "backoffice/backoffice.db" in names
    assert not any("autosave" in n or n.endswith(".log") for n in names)
    # the database copy is whole even though it's open in WAL mode
    z = zipfile.ZipFile(plain)
    p = tmp_path / "check.db"
    p.write_bytes(z.read("backoffice/backoffice.db"))
    assert sqlite3.connect(str(p)).execute(
        "select v from t").fetchone()[0] == "made up vendor"
    db.close()


def test_without_a_password_keys_and_back_office_stay_out(tmp_path,
                                                          monkeypatch):
    """Reviews 1 + 2 (Nov 4): a plain zip never holds keys or payroll."""
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    (data / "signing_key.pem").write_text("-----BEGIN PRIVATE KEY-----x")
    (data / "carrier_keys.json").write_text("{}")
    out = str(tmp_path / "b.zip")
    r = databackup.make(out)
    names = zipfile.ZipFile(out).namelist()
    assert not r["encrypted"]
    assert "quantisheet/toolchest.json" in names
    assert not any(n.startswith("backoffice/") for n in names)
    assert "quantisheet/signing_key.pem" not in names
    assert "quantisheet/carrier_keys.json" not in names
    assert "LEFT OUT.txt" in names
    assert any("signing_key.pem" in x for x in r["left_out"])
    import pytest
    with pytest.raises(databackup.BackupError):
        databackup.make(out, include_keys=True)          # needs a password
    with pytest.raises(databackup.BackupError):
        databackup.make(out, password="short")


def test_wrong_password_and_damage_are_loud(tmp_path, monkeypatch):
    import pytest
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    out = str(tmp_path / "b.qsbackup")
    databackup.make(out, password="example pass 1")
    with pytest.raises(databackup.BackupError, match="password"):
        databackup.contents(out, password="not the password")
    raw = bytearray(open(out, "rb").read())
    raw[-20] ^= 0xFF
    bad = tmp_path / "bad.qsbackup"
    bad.write_bytes(bytes(raw))
    with pytest.raises(databackup.BackupError):
        databackup.verify(str(bad), "example pass 1")
    assert databackup.contents(out, "example pass 1")["count"] == 2


def test_encrypted_restore_round_trip(tmp_path, monkeypatch):
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    out = str(tmp_path / "b.qsbackup")
    databackup.make(out, password="example pass 1")
    (data / "toolchest.json").write_text('{"Changed": []}')
    safety = databackup.restore(out, safety_dir=str(tmp_path),
                                password="example pass 1")
    assert safety.endswith(".qsbackup") and databackup.is_encrypted(safety)
    assert (data / "toolchest.json").read_text() == '{"Mine": []}'


def test_restore_puts_it_back_and_keeps_a_safety_copy(tmp_path,
                                                      monkeypatch):
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    out = str(tmp_path / "b.zip")
    databackup.make(out)
    (data / "toolchest.json").write_text('{"Changed": []}')
    safety = databackup.restore(out, safety_dir=str(tmp_path))
    assert os.path.isfile(safety)
    assert (data / "toolchest.json").read_text() == '{"Mine": []}'
    assert databackup.contents(out)["count"] == 1   # Back Office left out


def test_restore_never_writes_outside_the_folder(tmp_path, monkeypatch):
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    evil = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("quantisheet_backup.json", '{"app": "x"}')
        z.writestr("quantisheet/../../outside.txt", "no")
    databackup.restore(evil, safety_dir=str(tmp_path))
    assert not (tmp_path.parent / "outside.txt").exists()
    assert not (tmp_path / "outside.txt").exists()


def test_weekly_copy_keeps_four(tmp_path, monkeypatch):
    data, bo, db = _setup(tmp_path, monkeypatch)
    db.close()
    folder = str(tmp_path / "backups")
    day = 24 * 3600
    t0 = 1_800_000_000
    made = []
    for k in range(6):
        made.append(databackup.weekly(now=t0 + k * 8 * day, folder=folder))
    assert all(made)
    assert databackup.weekly(now=t0 + 5 * 8 * day + day, folder=folder) \
        is None                                   # not a week yet
    assert len([f for f in os.listdir(folder) if f.endswith(".zip")]) == 4


def test_synced_data_folder_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(databackup, "sources", lambda: [
        ("quantisheet", r"D:\OneDrive\.quantisheet")])
    assert "synced folder" in databackup.data_location_warning()
    monkeypatch.setattr(databackup, "sources", lambda: [
        ("quantisheet", r"D:\LocalData\.quantisheet")])
    assert databackup.data_location_warning() == ""
