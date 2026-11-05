"""Test runner helper for remote work sessions.

Watches the .run folder inside QuantiSheet for request files and runs them:
  tests            -> the test suite (same as run-tests.bat)
  tool NAME ARGS   -> python tools/NAME.py ARGS   (only scripts in tools/)
Each request <id>.req produces <id>.out (output) when finished.
Stops by itself after 10 hours, or when a file named STOP appears in .run.
"""
import os
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, ".run")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable


def handle(req):
    with open(req, encoding="utf-8") as f:
        line = f.read().strip()
    parts = shlex.split(line, posix=False) if line else []
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if parts[:1] == ["tests"]:
        cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + parts[1:]
    elif parts[:1] == ["tool"] and len(parts) >= 2 and \
            parts[1].replace("_", "").isalnum():
        script = os.path.join(ROOT, "tools", parts[1] + ".py")
        if not os.path.isfile(script):
            return f"no such tool: {parts[1]}\n"
        cmd = [PY, script] + parts[2:]
    else:
        return f"unknown request: {line!r}\n"
    t = time.time()
    # output goes to a file, not a pipe: a program the request starts
    # (ClaimIT, a browser) inherits a pipe and would keep the runner
    # waiting for it forever, timeout or not (Oct 21-22 overnight hang)
    import tempfile
    with tempfile.TemporaryFile(mode="w+b") as out:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=out,
                             stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL,
                             creationflags=getattr(
                                 subprocess, "CREATE_NO_WINDOW", 0))
        try:
            code = p.wait(timeout=900)
            note = ""
        except subprocess.TimeoutExpired:
            _kill_tree(p.pid)
            try:
                code = p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                code = None
            note = "\nrunner: timed out after 900 s; process tree killed\n"
        out.seek(0)
        text = out.read().decode("utf-8", errors="replace")
    return (text + note + f"\n[exit {code} in {time.time() - t:.1f}s]\n")


def _kill_tree(pid):
    """The request's process and everything it started."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           capture_output=True, timeout=30,
                           creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.kill(int(pid), 9)
    except (OSError, subprocess.SubprocessError):
        pass


def _cmdline(pid):
    """Command line of process `pid`, or "" if it isn't running (or can't
    be read)."""
    if sys.platform.startswith("win"):
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter "
                 f"'ProcessId={int(pid)}').CommandLine"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return (p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _is_runner(pid):
    """True only if `pid` is still this runner script. Windows reuses
    process ids, so a stale runner.alive can name an unrelated program."""
    cmd = _cmdline(pid).replace("\\", "/").lower()
    return "python" in cmd and "tools/runner.py" in cmd


def _stop_old():
    """Starting the runner again replaces an old one (and anything it was
    still running, such as a stuck test run). The id in runner.alive is
    checked first: if it now belongs to another program, it is left
    alone."""
    alive = os.path.join(RUN, "runner.alive")
    try:
        with open(alive) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    if not pid or pid == os.getpid():
        return
    if not _is_runner(pid):
        return
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))


def main():
    os.makedirs(RUN, exist_ok=True)
    _stop_old()
    stop = os.path.join(RUN, "STOP")
    if os.path.exists(stop):
        os.remove(stop)
    end = time.time() + 24 * 3600
    with open(os.path.join(RUN, "runner.alive"), "w") as f:
        f.write(str(os.getpid()))
    while time.time() < end and not os.path.exists(stop):
        for name in sorted(os.listdir(RUN)):
            if not name.endswith(".req"):
                continue
            req = os.path.join(RUN, name)
            out = req[:-4] + ".out"
            work = req[:-4] + ".work"
            try:
                os.replace(req, work)            # claim it
            except OSError:
                continue
            try:
                text = handle(work)
            except Exception as e:
                text = f"runner error: {e}\n"
            with open(out + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(out + ".tmp", out)
            os.remove(work)
        time.sleep(2)
    try:
        os.remove(os.path.join(RUN, "runner.alive"))
    except OSError:
        pass


if __name__ == "__main__":
    main()
