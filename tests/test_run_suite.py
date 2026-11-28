"""tools/run_suite.py status (Nov 27): when the run's own summary never
arrives, status still says what each pytest process finished with."""
import importlib.util
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool():
    spec = importlib.util.spec_from_file_location(
        "qs_run_suite", os.path.join(ROOT, "tools", "run_suite.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _worker(tmp_path, name, text, age=0):
    d = tmp_path / name
    d.mkdir()
    (d / "out.txt").write_text(text, encoding="utf-8")
    return d


def test_status_reads_the_workers_when_no_summary_came(tmp_path,
                                                       monkeypatch, capsys):
    m = _tool()
    since = time.time()
    _worker(tmp_path, "qs_suite0_aaaa",
            "....\n===== 40 passed, 2 skipped in 12.50s =====\n")
    _worker(tmp_path, "qs_suite1_bbbb",
            "..F\nFAILED tests/test_made_up.py::test_x - AssertionError\n"
            "1 failed, 9 passed in 3.10s\n")
    _worker(tmp_path, "qs_suite2_cccc", "......")           # not done yet
    rows = m.workers_now(since, str(tmp_path))
    assert [r[0] for r in rows] == ["qs_suite0_aaaa", "qs_suite1_bbbb",
                                    "qs_suite2_cccc"]
    assert rows[0][1] and rows[2][1] is None
    assert rows[1][2] == [
        "FAILED tests/test_made_up.py::test_x - AssertionError"]
    monkeypatch.setattr(m, "OUT", str(tmp_path / "run_suite.out"))
    monkeypatch.setattr(m, "STARTED", str(tmp_path / "run_suite.started"))
    monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "run_suite.out").write_text("running since 10:00:00\n")
    (tmp_path / "run_suite.started").write_text(str(since))
    assert m.status() == 0
    out = capsys.readouterr().out
    assert "qs_suite2_cccc: still running" in out
    assert "1 failed, 49 passed, 2 skipped" in out
    assert "1 of 3 processes still running" in out
    assert "FAILED tests/test_made_up.py::test_x" in out


def test_status_leaves_a_finished_run_alone(tmp_path, monkeypatch, capsys):
    m = _tool()
    monkeypatch.setattr(m, "OUT", str(tmp_path / "run_suite.out"))
    monkeypatch.setattr(m, "STARTED", str(tmp_path / "missing"))
    (tmp_path / "run_suite.out").write_text(
        "5 test files in 2 processes: 50 passed in 1.0 min\n"
        "[done, exit 0]\n")
    assert m.status() == 0
    out = capsys.readouterr().out
    assert "[done, exit 0]" in out and "so far" not in out


def test_older_runs_folders_are_not_counted(tmp_path):
    m = _tool()
    _worker(tmp_path, "qs_suite0_old", "9 passed in 1.00s\n")
    assert m.workers_now(time.time() + 60, str(tmp_path)) == []
