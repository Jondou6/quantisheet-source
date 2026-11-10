"""One QuantiSheet per person (0.12.24): opening a PDF while QuantiSheet is
already running - double-click in Explorer, Open with, or the
"QuantiSheet" printer - opens it in the running window instead of a second
copy of the program.

Starting QuantiSheet with no file brings the running window forward too
(Nov 4, Jon: "sometimes when I click to open QuantiSheet it opens
twice"): the window takes about 4 s to appear, and a second click in that
time used to start a second copy. A start-up lock is taken first thing,
so a second start that comes while the first is still starting waits for
it and hands over. File > New Window (--new-window) still gives a second
window on purpose.
The channel is a local socket (a named pipe on Windows) named for this
user and Windows session, so people on a Remote Desktop server never reach
each other's QuantiSheet.
"""
import getpass
import json
import logging
import os

log = logging.getLogger("quantisheet")


def name():
    if os.environ.get("QUANTISHEET_PIPE"):            # tests: a pipe of its own
        return os.environ["QUANTISHEET_PIPE"]
    try:
        user = getpass.getuser()
    except Exception:                                     # noqa: BLE001
        user = os.environ.get("USERNAME", "user")
    session = os.environ.get("SESSIONNAME", "") or "0"
    try:
        import ctypes
        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),
                                                       ctypes.byref(sid)):
            session = str(sid.value)
    except Exception:                                     # noqa: BLE001
        pass
    safe = "".join(c for c in f"{user}-{session}" if c.isalnum() or c in "-_")
    return f"QuantiSheet-{safe}"


_lock = None                 # held for the life of the program
NEW_WINDOW = "--new-window"


def claim():
    """Take the start-up lock. True when no other QuantiSheet of this
    person is running or starting. The lock goes away with the program,
    crash included (Windows frees it)."""
    global _lock
    if os.name != "nt":
        return True
    try:
        import ctypes
        # Nov 5: GetLastError through ctypes.windll can read a value that
        # ctypes itself overwrote, so "already running" was missed and a
        # second QuantiSheet opened. use_last_error keeps the real one.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_wchar_p)
        ctypes.set_last_error(0)
        h = k32.CreateMutexW(None, False, "Local\\" + name() + "-start")
        already = ctypes.get_last_error() == 183     # ERROR_ALREADY_EXISTS
        if h:
            if _lock is None:
                _lock = h
            else:                   # a second claim in this same program
                k32.CloseHandle(ctypes.c_void_p(h))
        return not already
    except Exception:                                     # noqa: BLE001
        return True


def bring_forward(paths=(), wait_s=20.0, sleep=None, hand=None):
    """A second start: give the files (or none - just come forward) to the
    running QuantiSheet, waiting while it finishes starting. True when it
    took them; False when it never answered (start normally then)."""
    import time
    hand = hand or hand_over
    sleep = sleep or time.sleep
    end = time.monotonic() + wait_s
    while True:
        try:
            if hand(list(paths)):
                return True
        except Exception:                                 # noqa: BLE001
            pass
        if time.monotonic() >= end:
            return False
        sleep(0.25)


def hand_over(paths, timeout_ms=3000):
    """Give the files to a running QuantiSheet. True when one took them."""
    from PySide6.QtNetwork import QLocalSocket
    try:                     # let the running window come to the front
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    except Exception:                                     # noqa: BLE001
        pass
    s = QLocalSocket()
    s.connectToServer(name())
    if not s.waitForConnected(timeout_ms):
        return False
    s.write(json.dumps([os.path.abspath(p) for p in paths]).encode("utf-8")
            + b"\n")
    s.flush()
    ok = s.waitForBytesWritten(timeout_ms) or s.bytesToWrite() == 0
    reply = b""
    end = timeout_ms
    while ok and b"ok" not in reply and end > 0:   # "ok" back: it has them
        if not s.waitForReadyRead(100):
            if s.state() == QLocalSocket.UnconnectedState:
                break
        reply += bytes(s.readAll())
        end -= 100
    reply += bytes(s.readAll())
    s.disconnectFromServer()
    return bool(ok and b"ok" in reply)


def listen(open_paths):
    """In the running program: take files handed over. Returns the
    server (keep a reference) or None."""
    from PySide6.QtNetwork import QLocalServer
    srv = QLocalServer()
    srv.setSocketOptions(QLocalServer.UserAccessOption)
    if not srv.listen(name()):
        QLocalServer.removeServer(name())          # a stale one from a crash
        if not srv.listen(name()):
            log.info("single instance: can't listen (%s)", srv.errorString())
            return None

    def incoming():
        while srv.hasPendingConnections():
            c = srv.nextPendingConnection()

            def read(c=c):
                if not c.canReadLine():
                    return
                try:
                    paths = json.loads(bytes(c.readLine()).decode("utf-8"))
                    paths = [p for p in paths if isinstance(p, str) and
                             p.lower().endswith((".pdf", ".qstools")) and
                             os.path.isfile(p)]
                except (ValueError, UnicodeDecodeError):
                    paths = []
                c.write(b"ok\n")
                c.flush()
                c.waitForBytesWritten(500)     # the reply must get there
                c.disconnectFromServer()
                open_paths(paths)           # none: just come forward
            c.readyRead.connect(read)
            read()
    srv.newConnection.connect(incoming)
    return srv
