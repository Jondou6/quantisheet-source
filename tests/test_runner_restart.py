"""The PC test runner keeps itself going: every HOURS (or when .run/RESTART
appears) it starts a fresh copy and exits, and only .run/STOP stops it
(Nov 25 optimization list: it used to stop after 24 hours)."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runner(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qs_runner", os.path.join(ROOT, "tools", "runner.py"))
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    monkeypatch.setattr(r, "RUN", str(tmp_path))
    started = []
    monkeypatch.setattr(r, "_restart", lambda: started.append(1))
    monkeypatch.setattr(r.time, "sleep", lambda s: None)
    return r, started


def test_restarts_when_its_time_is_up(tmp_path, monkeypatch):
    r, started = _runner(tmp_path, monkeypatch)
    monkeypatch.setattr(r, "HOURS", 0)
    r.main()
    assert started == [1]


def test_restart_file_restarts_at_once(tmp_path, monkeypatch):
    r, started = _runner(tmp_path, monkeypatch)
    (tmp_path / "RESTART").write_text("")
    r.main()
    assert started == [1] and not (tmp_path / "RESTART").exists()


def test_stop_file_stops_without_a_restart(tmp_path, monkeypatch):
    r, started = _runner(tmp_path, monkeypatch)
    calls = {"n": 0}
    real = os.path.exists

    def exists(p):                      # STOP appears after the first pass
        if p.endswith("STOP"):
            calls["n"] += 1
            return calls["n"] > 2
        return real(p)
    monkeypatch.setattr(r.os.path, "exists", exists)
    r.main()
    assert started == [] and not (tmp_path / "runner.alive").exists()


def test_restart_clears_runner_alive_first(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "qs_runner2", os.path.join(ROOT, "tools", "runner.py"))
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    monkeypatch.setattr(r, "RUN", str(tmp_path))
    (tmp_path / "runner.alive").write_text("123")
    seen = {}

    def popen(cmd, **kw):
        seen["alive"] = (tmp_path / "runner.alive").exists()
        seen["cmd"] = cmd
    monkeypatch.setattr(r.subprocess, "Popen", popen)
    r._restart()
    assert seen["alive"] is False
    assert seen["cmd"][-1].replace("\\", "/").endswith("tools/runner.py")
