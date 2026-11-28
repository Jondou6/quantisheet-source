"""The browser add-on's direct line to QuantiSheet (Nov 26).

Jon, Brave: every download the add-on started brought up the browser's
Save As window, and the PDF never reached QuantiSheet. So the add-on no
longer goes through the browser's downloads. The browser starts this
program as a "native messaging host" (the same way other PDF programs'
add-ons work): it runs

    QuantiSheet.exe chrome-extension://<the add-on's id>/

with a pipe, the add-on sends the PDF it has down the pipe in pieces, and
this writes it to Downloads\\QuantiSheet and opens it in QuantiSheet.

What it will and won't do:
  * the browser only lets the add-ons named in browser-host.json connect;
  * it writes one kind of file, a PDF (it must start with %PDF), with a
    cleaned-up name, into one folder; nothing is run, nothing is fetched
    from the internet by this side, nothing is sent back but "ok" and the
    saved file's path;
  * a file larger than MAX_BYTES is refused.

Messages (JSON, each with the browser's 4-byte length in front):
    {"type": "hello"}                  -> {"ok": true, "version": "..."}
    {"type": "begin", "name": "..."}   -> {"ok": true}
    {"type": "data", "b64": "..."}     -> {"ok": true, "got": <bytes>}
    {"type": "end"}                    -> {"ok": true, "path": "..."}
        ("end" may carry "marks": takeoff clicked out in the add-on's
        viewer, kept beside the PDF for app/webmarks.py)
    {"type": "abort"}                  -> {"ok": true}
"""
import base64
import json
import os
import re
import struct
import subprocess
import sys

NAME = "com.quantisheet.open"
FOLDER = "QuantiSheet"
MAX_BYTES = 2 * 1024 ** 3
MAX_MESSAGE = 64 * 1024 * 1024
ORIGIN = "chrome-extension://"


def is_host_call(args):
    """Did a browser start us as its native messaging host?"""
    return any(isinstance(a, str) and a.lower().startswith(ORIGIN)
               for a in args)


def folder():
    """Downloads\\QuantiSheet for this user (made when needed)."""
    base = None
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                    r"\User Shell Folders") as k:
                base = os.path.expandvars(winreg.QueryValueEx(
                    k, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
        except OSError:
            base = None
    if not base or not os.path.isdir(base):
        base = os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(base, FOLDER)


_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)$", re.I)


def safe_name(name):
    """A plain file name ending in .pdf, whatever the add-on sent."""
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    stem = stem.strip(" .")[:120] or "document"
    if _RESERVED.match(stem):
        stem = "_" + stem
    return stem + ".pdf"


def free_path(folder_, name):
    """folder\\name, or name (2), name (3)... when it is taken."""
    stem = name[:-4]
    path = os.path.join(folder_, name)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder_, f"{stem} ({n}).pdf")
        n += 1
    return path


class Receiver:
    """One PDF arriving in pieces."""

    def __init__(self, where=None, opener=None):
        self.where = where
        self.opener = opener or open_in_app
        self.part = None
        self.file = None
        self.name = None
        self.got = 0

    def _drop(self):
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
        if self.part and os.path.exists(self.part):
            try:
                os.remove(self.part)
            except OSError:
                pass
        self.file = self.part = self.name = None
        self.got = 0

    def handle(self, msg):
        kind = msg.get("type") if isinstance(msg, dict) else None
        if kind == "hello":
            from . import __version__
            return {"ok": True, "version": __version__}
        if kind == "begin":
            self._drop()
            where = self.where or folder()
            os.makedirs(where, exist_ok=True)
            self.name = safe_name(msg.get("name"))
            self.part = os.path.join(
                where, f".{os.getpid()}-{self.name}.part")
            self.file = open(self.part, "wb")
            return {"ok": True}
        if kind == "data":
            if self.file is None:
                return {"ok": False, "error": "no file started"}
            try:
                piece = base64.b64decode(msg.get("b64") or "", validate=True)
            except (ValueError, TypeError):
                self._drop()
                return {"ok": False, "error": "bad data"}
            if self.got == 0 and b"%PDF-" not in piece[:1024]:
                self._drop()
                return {"ok": False, "error": "not a PDF"}
            self.got += len(piece)
            if self.got > MAX_BYTES:
                self._drop()
                return {"ok": False, "error": "too large"}
            self.file.write(piece)
            return {"ok": True, "got": self.got}
        if kind == "end":
            if self.file is None or self.got == 0:
                self._drop()
                return {"ok": False, "error": "nothing received"}
            self.file.close()
            self.file = None
            final = free_path(os.path.dirname(self.part), self.name)
            os.replace(self.part, final)
            self.part = None
            self.got = 0
            marks = msg.get("marks")
            if isinstance(marks, dict):
                # takeoff clicked out in the add-on's viewer: kept beside
                # the PDF; QuantiSheet works the quantities out on opening
                try:
                    from . import webmarks
                    webmarks.write(final, marks)
                except Exception:                         # noqa: BLE001
                    pass                # the PDF still opens
            try:
                self.opener(final)
            except Exception as e:                        # noqa: BLE001
                return {"ok": False, "path": final,
                        "error": f"saved, but QuantiSheet didn't start: {e}"}
            return {"ok": True, "path": final}
        if kind == "abort":
            self._drop()
            return {"ok": True}
        return {"ok": False, "error": "unknown message"}


def open_in_app(path):
    """Start QuantiSheet with the file (a running QuantiSheet takes it)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, path]
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, os.path.join(root, "quantisheet.py"), path]
    flags = 0
    for f in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP",
              "CREATE_BREAKAWAY_FROM_JOB"):
        flags |= getattr(subprocess, f, 0)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    try:
        subprocess.Popen(cmd, creationflags=flags, **kw)
    except OSError:
        # the browser's job doesn't allow breaking away: start it inside
        flags &= ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        subprocess.Popen(cmd, creationflags=flags, **kw)


# ---- the pipe
def _std_streams():
    """Binary stdin and stdout. The Windows build has no console, so
    Python's own sys.stdin may be missing: use the handles themselves."""
    if sys.platform.startswith("win"):
        import msvcrt
        import ctypes
        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = ctypes.c_void_p
        out = []
        for which, mode in ((-10, "rb"), (-11, "wb")):
            h = k.GetStdHandle(which)
            if not h or h == ctypes.c_void_p(-1).value:
                raise OSError("no pipe from the browser")
            fd = msvcrt.open_osfhandle(h, os.O_BINARY)
            out.append(os.fdopen(fd, mode, buffering=0))
        return out
    return sys.stdin.buffer, sys.stdout.buffer


def _read_exact(stream, n):
    data = b""
    while len(data) < n:
        got = stream.read(n - len(data))
        if not got:
            return None
        data += got
    return data


def read_message(stream):
    head = _read_exact(stream, 4)
    if head is None:
        return None
    (n,) = struct.unpack("<I", head)
    if n > MAX_MESSAGE:
        raise ValueError("message too large")
    body = _read_exact(stream, n)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(stream, obj):
    body = json.dumps(obj).encode("utf-8")
    stream.write(struct.pack("<I", len(body)) + body)
    try:
        stream.flush()
    except (OSError, ValueError):
        pass


def serve(stdin, stdout, receiver=None):
    """Answer the add-on until the browser closes the pipe."""
    rx = receiver or Receiver()
    try:
        while True:
            try:
                msg = read_message(stdin)
            except ValueError:
                write_message(stdout, {"ok": False, "error": "bad message"})
                break
            if msg is None:
                break
            try:
                reply = rx.handle(msg)
            except OSError as e:
                rx._drop()
                reply = {"ok": False,
                         "error": f"couldn't save the file: {e.strerror}"}
            write_message(stdout, reply)
    finally:
        rx._drop()                     # a half-sent file is not kept
    return 0


def main():
    stdin, stdout = _std_streams()
    return serve(stdin, stdout)
