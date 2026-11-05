"""QuantiSheet's own folders, registry key and printer names only (Jon,
Oct 30: nothing on any PC uses the earlier name's folders any more, so
nothing looks for them): the printed-PDFs and local folders, IT policy,
the printer and its helper, ClaimIT's folders."""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import policy, settings
    home = tmp_path / "home"
    folders = {"home": home,
               "docs": home / "Documents",
               "appdata": home / "AppData" / "Roaming",
               "local": home / "AppData" / "Local",
               "programdata": tmp_path / "ProgramData"}
    for p in folders.values():
        p.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(folders["appdata"]))
    monkeypatch.setenv("LOCALAPPDATA", str(folders["local"]))
    monkeypatch.delenv("QUANTISHEET_CLAIMS_HOME", raising=False)
    monkeypatch.delenv("QUANTISHEET_POLICY_FILE", raising=False)
    monkeypatch.setattr(settings, "DIR", str(home / ".quantisheet"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(policy, "_program_data",
                        lambda: str(folders["programdata"]))
    monkeypatch.setattr(policy, "_from_registry", lambda: {})
    policy.reload()
    yield folders
    policy.reload()


def test_quantisheet_folders(env):
    from app import brand_paths, codelib, printhelper
    assert brand_paths.local_dir() == str(env["local"] / "QuantiSheet")
    assert brand_paths.printed_folder(str(env["docs"])) == \
        str(env["docs"] / "QuantiSheet" / "Printed")
    assert codelib.folder() == str(env["local"] / "QuantiSheet" /
                                   "Code Library")
    assert printhelper.log_path() == str(env["local"] / "QuantiSheet" /
                                         "print-helper.log")


def test_printer_names(env):
    from app import printer_setup, printhelper
    assert printhelper.PRINTER == "QuantiSheet"
    assert printhelper.RUN_NAME == "QuantiSheet Printer"
    assert printhelper.ports() == (printhelper.PORT,)
    assert "QuantiSheet" in printhelper.PORT
    assert printhelper.active_printer() == "QuantiSheet"
    assert not hasattr(printer_setup, "migrate")
    assert printhelper.MUTEX.endswith("QuantiSheetPrintHelper")


def test_policy_from_the_quantisheet_folder_only(env, monkeypatch):
    from app import policy
    assert policy.data_dir() == str(env["programdata"] / "QuantiSheet")
    d = env["programdata"] / "QuantiSheet"
    d.mkdir()
    (d / "policy.json").write_text('{"OfflineMode": true}')
    monkeypatch.setattr(policy, "_admin_made", lambda p: True)
    policy.reload()
    assert policy.get("OfflineMode") is True
    monkeypatch.setattr(policy, "_admin_made", lambda p: False)
    policy.reload()
    assert policy.get("OfflineMode") in (None, False)       # not trusted


def test_claimit_folders(env, monkeypatch):
    from quantisheet_claims import settings as cs
    cs.reload()
    monkeypatch.setattr(os, "name", "nt")
    assert cs.home() == str(env["appdata"] / "ClaimIT")
    assert os.path.isdir(cs.home())
    assert cs.claims_folder() == str(env["docs"] / "ClaimIT")
    assert cs.quantisheet_dirs() == (os.path.realpath(
        str(env["home"] / ".quantisheet")),)
    with pytest.raises(cs.UnsafePathError):
        cs.check_safe(str(env["home"] / ".quantisheet" / "x"))
    cs.reload()


def test_claimit_launcher_only_claimit_exe(tmp_path, monkeypatch):
    from app import claims_hook, settings
    exe = tmp_path / "ClaimIT.exe"
    exe.write_bytes(b"")
    other = tmp_path / "Other.exe"
    other.write_bytes(b"")
    monkeypatch.setattr(settings, "get", lambda k, d=None:
                        str(exe) if k == "claims_exe" else d)
    assert claims_hook.launcher() == [str(exe)]
    monkeypatch.setattr(settings, "get", lambda k, d=None:
                        str(other) if k == "claims_exe" else d)
    assert claims_hook.launcher() != [str(other)]


def test_no_migration_left_in_settings():
    from app import settings
    for gone in ("migrate_data_dir", "OLD_DIR", "OLD_LOG_NAME",
                 "SAFE_MODE", "MIGRATION"):
        assert not hasattr(settings, gone), gone
