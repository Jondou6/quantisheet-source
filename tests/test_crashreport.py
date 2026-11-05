"""Crash reports kept on this PC (0.12.24)."""
import os
import sys
import zipfile


def _logs(tmp_path, monkeypatch):
    import app.main as main_mod
    d = tmp_path / "logs"
    d.mkdir()
    (d / "quantisheet.log").write_text("INFO start\nINFO user a.b@example.com "
                                     "opened a set\n", encoding="utf-8")
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(d))
    return d


def test_error_report_written_cleaned_and_pruned(tmp_path, monkeypatch):
    from app import crashreport
    d = _logs(tmp_path, monkeypatch)
    monkeypatch.setattr(crashreport, "_notify", lambda *a, **k: None)
    try:
        raise ValueError("bad page for x.y@example.com")
    except ValueError:
        path = crashreport.from_exception(*sys.exc_info())
    text = open(path, encoding="utf-8").read()
    assert "error: ValueError" in text and "Traceback" in text
    assert "Version:" in text and "last lines of the log" in text
    assert "@example.com" not in text and "[email removed]" in text
    assert os.path.dirname(path) == str(d / "crashes")
    for i in range(crashreport.KEEP + 5):
        crashreport.write("test", f"body {i}")
    assert len(crashreport.reports(100)) == crashreport.KEEP


def test_hard_crash_reported_once_at_next_start(tmp_path, monkeypatch):
    from app import crashreport
    d = _logs(tmp_path, monkeypatch)
    crash = d / "crash.log"
    crash.write_text("Windows fatal exception: old one\n", encoding="utf-8")
    # the first run only notes where crash.log ends - old crashes aren't
    # reported
    assert crashreport.check_previous_run(str(crash)) is None
    with open(crash, "a", encoding="utf-8") as f:
        f.write("Thread 0x1 (most recent call first):\n  frozen 12 s\n")
    assert crashreport.check_previous_run(str(crash)) is None   # a freeze
    with open(crash, "a", encoding="utf-8") as f:
        f.write("Windows fatal exception: access violation\n\n"
                "Current thread 0x2:\n  File app/render.py, line 9\n")
    p = crashreport.check_previous_run(str(crash))
    assert p and "hard crash in the previous session" in open(
        p, encoding="utf-8").read()
    assert crashreport.check_previous_run(str(crash)) is None   # once


def test_support_bundle_has_the_crash_reports(tmp_path, monkeypatch):
    from app import crashreport, diagnostics
    _logs(tmp_path, monkeypatch)
    crashreport.write("error: KeyError", "Traceback ... KeyError: 'w'")
    out = diagnostics.bundle(str(tmp_path / "b.zip"))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        crashes = [n for n in names if n.startswith("logs/crashes/crash-")]
        assert crashes
        assert "KeyError" in z.read(crashes[0]).decode()


def test_a_report_never_raises(tmp_path, monkeypatch):
    from app import crashreport
    monkeypatch.setattr(crashreport, "folder",
                        lambda: str(tmp_path / "nofile" / "x\0bad"))
    assert crashreport.write("x", "y") is None


def test_handled_windows_exceptions_are_not_crashes():
    """GUI user test r42 F10: 0x8001010D (UI Automation reading the
    splash) was logged at every start; it isn't a crash."""
    from app import crashreport as cr
    assert cr._fatal("Windows fatal exception: code 0x8001010d\n\n"
                     "Thread 0x01 (most recent call first):") is None
    assert cr._fatal("Windows fatal exception: code 0x406d1388\n") is None
    assert cr._fatal("Windows fatal exception: access violation\n")
    assert cr._fatal("Windows fatal exception: code 0xc0000409\n")
    assert cr._fatal("Fatal Python error: Aborted\n")


def test_same_crash_not_shown_again_when_seen_cant_be_saved(tmp_path,
                                                             monkeypatch):
    """Nov 3: where crashes\\seen.json couldn't be updated, an old crash
    was reported at every start. Each crash is reported once, whatever."""
    from app import crashreport, settings
    d = _logs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    crash = d / "crash.log"
    crash.write_text("--- start ---\n", encoding="utf-8")
    assert crashreport.check_previous_run(str(crash)) is None   # first run
    with open(crash, "a", encoding="utf-8") as f:
        f.write("Windows fatal exception: access violation\n")
    seen = os.path.join(crashreport.folder(), "seen.json")
    stale = open(seen, encoding="utf-8").read()
    real_open = open

    def no_write(path, mode="r", *a, **k):        # seen.json read only
        if str(path) == seen and "w" in mode:
            raise PermissionError(path)
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", no_write)
    assert crashreport.check_previous_run(str(crash))           # once
    assert open(seen, encoding="utf-8").read() == stale         # not saved
    assert crashreport.check_previous_run(str(crash)) is None   # not again
    assert crashreport.check_previous_run(str(crash)) is None


def test_crash_reports_can_be_left_out_of_the_report(tmp_path, monkeypatch):
    """Venice #8 (Nov 4): the Report an Issue checkbox."""
    from app import crashreport, diagnostics
    _logs(tmp_path, monkeypatch)
    crashreport.write("error: KeyError", "Traceback ... KeyError: 'w'")
    out = diagnostics.bundle(str(tmp_path / "b.zip"), crashes=False)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert not [n for n in names if "crashes/" in n]
    assert "install.txt" in names and "report.json" in names
