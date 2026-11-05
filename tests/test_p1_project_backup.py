"""P1 'backup/restore of a project folder with integrity check': a zip
with a SHA-256 manifest; restore checks every file first and changes
nothing when one fails (made-up job)."""
import json
import os
import zipfile

import pytest

from app.pm import project_backup as pb


def _job(tmp_path):
    j = tmp_path / "Example Job"
    (j / "files").mkdir(parents=True)
    (j / "project.json").write_text(json.dumps({"records": {"rfi": {}}}))
    (j / "files" / "photo.jpg").write_bytes(b"\xff\xd8 example")
    return j


def test_backup_and_restore_round_trip(tmp_path):
    j = _job(tmp_path)
    z = tmp_path / "b.qsjob.zip"
    man = pb.backup(str(j), str(z))
    assert set(man["files"]) == {"project.json", "files/photo.jpg"}
    assert pb.verify(str(z))[1] == []
    out = tmp_path / "restored"
    assert pb.restore(str(z), str(out)) == 2
    assert (out / "files" / "photo.jpg").read_bytes() == b"\xff\xd8 example"


def test_a_changed_file_is_refused_and_nothing_changes(tmp_path):
    j = _job(tmp_path)
    z = tmp_path / "b.qsjob.zip"
    pb.backup(str(j), str(z))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:
        for i in src.infolist():
            data = src.read(i.filename)
            if i.filename == "project.json":
                data = data.replace(b"rfi", b"xyz")
            dst.writestr(i, data)
    target = tmp_path / "live"
    target.mkdir()
    (target / "project.json").write_text("live")
    with pytest.raises(pb.BackupError, match="changed"):
        pb.restore(str(bad), str(target), overwrite=True)
    assert (target / "project.json").read_text() == "live"
    assert not [d for d in os.listdir(tmp_path) if d.startswith(".qs-")]


def test_unsafe_paths_and_extra_files_are_refused(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("../outside.txt", b"x")
        w.writestr(pb.MANIFEST, json.dumps({"files": {
            "../outside.txt": {"sha256": "0" * 64, "size": 1}}}))
    with pytest.raises(pb.BackupError):
        pb.restore(str(z), str(tmp_path / "t"))
    assert not (tmp_path / "outside.txt").exists()


def test_replacing_a_job_keeps_the_old_one(tmp_path):
    j = _job(tmp_path)
    z = tmp_path / "b.zip"
    pb.backup(str(j), str(z))
    (j / "project.json").write_text("changed since")
    pb.restore(str(z), str(j), overwrite=True)
    kept = [d for d in os.listdir(tmp_path) if ".before-restore-" in d]
    assert kept and (tmp_path / kept[0] / "project.json").read_text() == \
        "changed since"
    with pytest.raises(pb.BackupError, match="already holds"):
        pb.restore(str(z), str(j))
