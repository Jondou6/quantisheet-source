"""Support zip kept on this computer (app/support_bundle.py).

Made-up names and example.com addresses only. Nothing is uploaded.
"""
import json
import os
import socket
import zipfile

from app import __version__


def _isolate(tmp_path, monkeypatch):
    import app.main as main_mod
    from app import settings
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(logs))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH",
                        str(tmp_path / "cfg" / "settings.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("USERNAME", "ExampleUser")
    monkeypatch.setenv("USER", "ExampleUser")
    import getpass
    monkeypatch.setattr(getpass, "getuser", lambda: "ExampleUser")
    return logs


def _sample_settings():
    from app import settings
    settings.set("author", "Example User")
    settings.set("recent", [r"C:\Users\ExampleUser\Documents\ExampleJob.pdf"])
    settings.set("note", "wrote to person@example.com about Example User")
    settings.set("beta_key", "example-secret-value")
    settings.set("share", r"\\fileserver\example")


def test_scrub_rewrites_profile_paths_and_drops_email():
    from app.support_bundle import scrub
    text = scrub(r"see C:\Users\ExampleUser\Desktop and "
                 r"C:/Users/OtherExample/Jobs and "
                 "person@example.com")
    assert r"C:\Users" not in text
    assert "C:/Users" not in text
    assert "%USERPROFILE%\\Desktop" in text
    assert "%USERPROFILE%/Jobs" in text
    assert "person@example.com" not in text
    assert "[email removed]" in text


def test_scrub_rewrites_a_json_escaped_windows_path():
    from app.support_bundle import scrub
    raw = json.dumps({"recent": [r"C:\Users\ExampleUser\Documents\a.pdf"]})
    text = scrub(raw)
    assert "ExampleUser" not in text
    assert "%USERPROFILE%" in text
    assert "a.pdf" in text


def test_make_bundle_collects_version_install_settings_log_and_newest_crash(
        tmp_path, monkeypatch):
    from app import crashreport, support_bundle
    logs = _isolate(tmp_path, monkeypatch)
    _sample_settings()
    (logs / "quantisheet.log").write_text(
        "INFO open C:\\Users\\ExampleUser\\Documents\\ExampleJob.pdf "
        "person@example.com\n", encoding="utf-8")
    (logs / "quantisheet.log.old").write_text("INFO older log\n",
                                              encoding="utf-8")
    (logs / "crash.log").write_text("INFO crash log\n", encoding="utf-8")
    monkeypatch.setattr(crashreport, "_notify", lambda *a, **k: None)
    crashreport.write("error: older", "OLDER-MARKER person@example.com")
    newest = crashreport.write(
        "error: newer",
        r"NEWER-MARKER C:\Users\ExampleUser\AppData\crash.txt")
    assert support_bundle.crash_path() == newest

    install = tmp_path / "install"
    install.mkdir()
    exe = install / "QuantiSheet.exe"
    exe.write_bytes(b"example")
    from app import branding
    monkeypatch.setattr(branding, "installed_exe", lambda base=None: str(exe))
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setenv("TEMP", str(temp))
    (temp / "Setup Log example.txt").write_text(
        "example setup line\n", encoding="utf-8")
    from app import updatecheck
    downloads = tmp_path / "updates"
    downloads.mkdir()
    (downloads / "example-setup.bin").write_bytes(b"abc")
    monkeypatch.setattr(updatecheck, "download_dir", lambda: str(downloads))

    out = support_bundle.make_bundle(str(tmp_path / "out" / "bundle.zip"))
    assert out.endswith("bundle.zip")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        whole = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
        version = z.read("version.txt").decode()
        install_txt = z.read("install.txt").decode()
        notice = z.read("NOTICE.txt").decode()
        settings = json.loads(z.read("settings.json"))
        crashes = [n for n in names if n.startswith("crashes/")]
        crash_text = z.read(crashes[0]).decode() if crashes else ""
    assert "does not upload" in notice
    assert "QuantiSheet" in version and __version__ in version
    assert "install folder:" in install_txt
    assert "QuantiSheet.exe" in install_txt
    assert "TEMP:" in install_txt
    assert "Setup Log example.txt" in install_txt
    assert "update downloads:" in install_txt
    assert "example-setup.bin" in install_txt
    assert settings["beta_key"] == "[withheld]"
    assert settings["author"] == "%USERNAME%"
    assert settings["recent"][0].startswith("%USERPROFILE%")
    assert settings["recent"][0].endswith("ExampleJob.pdf")
    assert "logs/quantisheet.log" in names
    assert "logs/quantisheet.log.old" in names
    assert "logs/crash.log" in names
    assert len(crashes) == 1
    assert os.path.basename(newest) in crashes[0]
    assert "NEWER-MARKER" in crash_text
    assert "OLDER-MARKER" not in whole
    assert "person@example.com" not in whole
    assert "[email removed]" in whole
    assert "ExampleUser" not in whole
    assert "Example User" not in whole
    assert "example-secret-value" not in whole
    assert r"C:\Users" not in whole
    assert "fileserver" not in whole
    home = os.path.expanduser("~")
    assert home not in whole


def test_crash_path_is_none_without_a_crash(tmp_path, monkeypatch):
    from app import support_bundle
    _isolate(tmp_path, monkeypatch)
    assert support_bundle.crash_path() is None
    out = support_bundle.make_bundle(str(tmp_path / "empty.zip"))
    with zipfile.ZipFile(out) as z:
        assert not any(n.startswith("crashes/") for n in z.namelist())
        assert "version.txt" in z.namelist()
        assert "install.txt" in z.namelist()


def test_make_bundle_does_not_open_a_network_connection(tmp_path, monkeypatch):
    from app import support_bundle
    _isolate(tmp_path, monkeypatch)

    def refuse(*_a, **_k):
        raise AssertionError("support bundle tried to use the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    support_bundle.make_bundle(str(tmp_path / "local.zip"))
