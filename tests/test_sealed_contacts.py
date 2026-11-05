"""The tester build's contact list is sealed with a password."""
import os

import pytest

from app import sealed_contacts as sc, settings, subdir


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    os.makedirs(settings.DIR, exist_ok=True)


def test_seal_unseal_and_import(tmp_path):
    people = [{"company": "Dig Co", "email": "a@dig.example"},
              {"company": "Pipe Pros", "email": "b@pipe.example"}]
    blob = sc.seal(people, "correct horse")
    assert b"Dig Co" not in blob and b"dig.example" not in blob
    assert sc.unseal(blob, "correct horse") == people
    with pytest.raises(sc.WrongPassword):
        sc.unseal(blob, "wrong")
    with pytest.raises(sc.WrongPassword):
        sc.unseal(blob, "")
    p = tmp_path / "c.sealed"
    p.write_bytes(blob)
    assert sc.import_into_directory("correct horse", str(p))[0] == 2
    assert {c["company"] for c in subdir.load()} == {"Dig Co", "Pipe Pros"}
    assert sc.import_into_directory("correct horse", str(p))[0] == 0
