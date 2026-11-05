"""Threat model lower items (0.13.14): T-005 Ghostscript in safe mode,
T-010 exe overrides, T-011 old job snapshots, T-014 weather key, T-017
helpers by trusted path (made-up data only)."""
import os
import time

from app import backoffice_hook, claims_hook, pdfa, preflight, settings


def test_ghostscript_runs_in_safe_mode():
    for mod in (pdfa, preflight):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "-dNOSAFER" not in src and "-dSAFER" in src


def test_ghostscript_and_tesseract_never_from_the_current_folder(
        tmp_path, monkeypatch):
    from app import ocr
    fake = tmp_path / ("gswin64c.exe" if os.name == "nt" else "gs")
    fake.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pdfa.shutil, "which", lambda n: str(tmp_path / n))
    monkeypatch.setattr(pdfa.glob, "glob", lambda p: [])
    assert pdfa.ghostscript() is None
    monkeypatch.setattr(ocr.shutil, "which", lambda n: str(tmp_path / n))
    monkeypatch.setattr(ocr.os.path, "exists", lambda p: False)
    assert ocr.find_tesseract() is None


def test_exe_overrides_only_point_at_the_real_programs(tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    evil = tmp_path / "calc.exe"
    evil.write_bytes(b"")
    settings.set("backoffice_exe", str(evil))
    settings.set("claims_exe", str(evil))
    assert backoffice_hook.launcher() != [str(evil)]
    assert claims_hook.launcher() != [str(evil)]
    ok = tmp_path / backoffice_hook.EXE_NAME
    ok.write_bytes(b"")
    settings.set("backoffice_exe", str(ok))
    assert backoffice_hook.launcher() == [str(ok)]


def test_old_job_snapshots_are_cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(backoffice_hook.tempfile, "gettempdir",
                        lambda: str(tmp_path))
    old = tmp_path / "quantisheet-backoffice-old"
    new = tmp_path / "quantisheet-backoffice-new"
    other = tmp_path / "something-else"
    for d in (old, new, other):
        d.mkdir()
        (d / "snapshot.json").write_text("{}")
    past = time.time() - 3 * 24 * 3600
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert backoffice_hook.cleanup_snapshots() == 1
    assert not old.exists() and new.exists() and other.exists()


def test_weather_key_kept_protected(tmp_path, monkeypatch):
    from app import secretstore
    from app.pm import weather
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    secretstore.set_secret("weather_api_key", "EXAMPLE-KEY-123")
    assert weather._api_key() == "EXAMPLE-KEY-123"
    if secretstore.available():
        assert "EXAMPLE-KEY-123" not in open(settings.PATH,
                                             encoding="utf-8").read()
