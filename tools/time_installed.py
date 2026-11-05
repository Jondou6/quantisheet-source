"""Time the installed QuantiSheet from launch until its main window is up
(works on any version: it watches for a new window, then closes it).

    python tools/time_installed.py [runs] [built]

"built" times the fresh build in %LOCALAPPDATA%\\QuantiSheetBuild instead,
and also prints that build's own step-by-step start-up times.
"""
import json
import tempfile
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _exe_of(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def windows():
    """[(hwnd, pid, exe, title)] of visible top-level windows."""
    out = []

    def cb(h, _l):
        if user32.IsWindowVisible(h):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            out.append((h, p.value, _exe_of(p.value), buf.value))
        return True
    user32.EnumWindows(PROC(cb), 0)
    return out


def _wide(h):
    """The main window: it has a title bar (the splash doesn't)."""
    style = user32.GetWindowLongW(h, -16)            # GWL_STYLE
    return (style & 0x00C00000) == 0x00C00000        # WS_CAPTION


def ours(ws):
    return [w for w in ws if w[2].lower().endswith("quantisheet.exe")]


def kill_all(extra=()):
    """End every QuantiSheet.exe that owns a
    window, plus `extra` pids."""
    pids = {w[1] for w in ours(windows())} | set(extra)
    for pid in pids:
        h = kernel32.OpenProcess(0x0001, False, pid)      # PROCESS_TERMINATE
        if h:
            kernel32.TerminateProcess(h, 1)
            kernel32.CloseHandle(h)


def main(argv):
    runs = int(argv[0]) if argv and argv[0].isdigit() else 3
    built = "built" in argv
    if built:
        exe = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                           "QuantiSheetBuild", "dist", "QuantiSheet",
                           "QuantiSheet.exe")
    else:
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        from app import branding
        exe = branding.installed_exe()
    print("exe:", exe, "exists" if os.path.exists(exe) else "MISSING",
          flush=True)
    already = ours(windows())
    if already:
        print("already open:", [w[3] for w in already], "- closing", flush=True)
        kill_all()
        time.sleep(3)
    print("desktop windows visible to me:", len(windows()), flush=True)
    for i in range(runs):
        t = time.perf_counter()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("QT_")}     # the runner sets offscreen
        marks = os.path.join(tempfile.gettempdir(), f"quantisheet-marks-{i}.json")
        if built:
            if os.path.exists(marks):
                os.remove(marks)
            env["QUANTISHEET_TIMING"] = marks         # it reports and quits
        p = subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=0x00000008)   # DETACHED_PROCESS
        first = main_up = None
        seen = []
        while time.perf_counter() - t < 90:
            now = time.perf_counter() - t
            mine = ours(windows())
            for w in mine:
                key = (w[0], _wide(w[0]))
                if key not in seen:
                    seen.append(key)
                    kind = "main" if key[1] else "splash/other"
                    print(f"  {now:5.1f}s {kind} window '{w[3]}'", flush=True)
            if mine and first is None:
                first = now
            if any("QuantiSheet" in w[3] and _wide(w[0]) for w in mine):
                main_up = now
                break
            time.sleep(0.05)
        print(f"launch {i + 1}: first window {first and round(first, 1)}s, "
              f"main window {main_up and round(main_up, 1)}s, "
              f"process {'running' if p.poll() is None else 'exited ' + str(p.returncode)}",
              flush=True)
        if built:
            t1 = time.time()
            while not os.path.exists(marks) and time.time() - t1 < 30:
                time.sleep(0.2)
            time.sleep(0.5)
            try:
                with open(marks, encoding="utf-8") as f:
                    print("   steps:", ", ".join(f"{n} {v}s"
                                                 for n, v in json.load(f)),
                          flush=True)
            except Exception as e:
                print("   steps: not written", e, flush=True)
        time.sleep(1.0)
        kill_all([p.pid])
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            print('  (process did not end)', flush=True)
        time.sleep(3.0)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
