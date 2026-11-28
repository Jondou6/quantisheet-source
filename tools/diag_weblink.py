"""Is the quantisheet:// link type registered on this PC, to which
program, and does Windows itself open it?

    python tools/diag_weblink.py           what is registered (read-only)
    python tools/diag_weblink.py launch    ask Windows to open a made-up
                                           PDF through the link (this is
                                           what a browser does)
"""
import ctypes
import os
import sys
import tempfile
import time
import winreg
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def registered():
    for root, name in ((winreg.HKEY_CURRENT_USER, "this user"),
                       (winreg.HKEY_LOCAL_MACHINE, "all users")):
        try:
            with winreg.OpenKey(root, r"Software\Classes\quantisheet") as k:
                proto = winreg.QueryValueEx(k, "URL Protocol")[0]
            with winreg.OpenKey(root, r"Software\Classes\quantisheet\shell"
                                r"\open\command") as k:
                cmd = winreg.QueryValue(k, None)
            print(f"{name}: registered (URL Protocol={proto!r}) -> {cmd}")
        except OSError:
            print(f"{name}: not registered")


def assoc(what, flags=0x1000):          # ASSOCF_IS_PROTOCOL
    """What Windows tells a browser about the link type."""
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.c_ulong(1024)
    hr = ctypes.windll.shlwapi.AssocQueryStringW(
        flags, what, "quantisheet", None, buf, ctypes.byref(n))
    return buf.value if hr == 0 else f"(none, error {hr & 0xffffffff:#x})"


def launch():
    sys.path.insert(0, ROOT)
    import fitz
    d = tempfile.mkdtemp(prefix="qs-weblink-")
    pdf = os.path.join(d, "Made-up link test.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Made-up PDF: the quantisheet:// "
                               "link opened this.")
    doc.save(pdf)
    doc.close()
    link = "quantisheet://open?path=" + quote(pdf, safe="")
    from app import weblink
    print("the program reads the link back as:", weblink.path_from(link))
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", link, None, None,
                                             1)
    print("Windows ShellExecute returned", rc, "(over 32 = started)")
    time.sleep(8)
    log = os.path.join(os.path.expanduser("~"), ".quantisheet")
    for base, _d, files in os.walk(log):
        for f in files:
            if f.endswith(".log"):
                p = os.path.join(base, f)
                if time.time() - os.path.getmtime(p) < 60:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        tail = fh.read()[-1500:]
                    print("--- end of", f, "---")
                    print(tail.encode("ascii", "replace").decode())


def windows():
    """Titles of the visible windows that mention QuantiSheet or the
    made-up test file, and how many QuantiSheet.exe are running."""
    import subprocess
    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    u.IsWindowVisible.argtypes = (ctypes.c_void_p,)
    u.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    seen = []
    r0 = subprocess.run(["tasklist", "/fi", "imagename eq QuantiSheet.exe",
                         "/fo", "csv", "/nh"], capture_output=True, text=True)
    mine = {int(ln.split('","')[1]) for ln in r0.stdout.splitlines()
            if ln.count('","') >= 2 and ln.split('","')[1].isdigit()}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(h, _l):
        pid0 = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid0))
        if pid0.value in mine and not u.IsWindowVisible(h):
            b0 = ctypes.create_unicode_buffer(300)
            u.GetWindowTextW(h, b0, 300)
            if b0.value and "QuantiSheet" in b0.value or ".pdf" in b0.value:
                seen.append("(hidden) " + b0.value)
        if u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(300)
            u.GetWindowTextW(h, b, 300)
            t = b.value
            pid = ctypes.c_ulong(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if "QuantiSheet" in t or "Made-up" in t or pid.value in mine:
                seen.append(t or "(no title)")
        return True
    u.EnumWindows(each, 0)
    for t in seen:
        print("window:", t.encode("ascii", "replace").decode())
    r = subprocess.run(["tasklist", "/fi", "imagename eq QuantiSheet.exe",
                        "/fo", "csv", "/nh"], capture_output=True, text=True)
    print("its process ids:", len(mine))
    print("QuantiSheet.exe running:",
          r.stdout.count("QuantiSheet.exe"))


def log_tail(n=25):
    sys.path.insert(0, ROOT)
    from app import settings
    from app.main import log_folder
    for d in dict.fromkeys((log_folder(), settings.DIR)):
        p = os.path.join(d, settings.LOG_NAME)
        if os.path.isfile(p):
            age = time.time() - os.path.getmtime(p)
            print(f"--- log, last written {age:.0f} s ago ---")
            with open(p, encoding="utf-8", errors="replace") as f:
                for ln in f.read().splitlines()[-n:]:
                    print(ln.encode("ascii", "replace").decode()[:1500])


def exe(with_link):
    """Start the installed program directly (with a made-up link or with
    nothing) and say whether it stays up, and its exit code if not."""
    import subprocess
    sys.path.insert(0, ROOT)
    path = assoc(2)
    args = [path]
    if with_link:
        import fitz
        d = tempfile.mkdtemp(prefix="qs-weblink-")
        pdf = os.path.join(d, "Made-up link test.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Made-up PDF")
        doc.save(pdf)
        doc.close()
        args.append("quantisheet://open?path=" + quote(pdf, safe=""))
    p = subprocess.Popen(args, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(timeout=25)
        print("it stopped by itself, exit code", p.returncode)
        print(out.decode("utf-8", "replace")[-1500:]
              .encode("ascii", "replace").decode())
    except subprocess.TimeoutExpired:
        print("still running after 25 s (left open)")
    windows()
    log_tail(8)


def held():
    """Is the newest made-up test PDF open in a program? (Windows won't
    let an open drawing be renamed.)"""
    import glob
    found = sorted(glob.glob(os.path.join(tempfile.gettempdir(),
                                          "qs-weblink-*", "*.pdf")),
                   key=os.path.getmtime)
    if not found:
        print("no made-up test PDF")
        return
    pdf = found[-1]
    try:
        os.rename(pdf, pdf + ".x")
        os.rename(pdf + ".x", pdf)
        print("the made-up PDF is NOT open in any program")
    except OSError as e:
        print("the made-up PDF is open in a program:", type(e).__name__)


if __name__ == "__main__":
    if sys.argv[1:2] == ["held"]:
        held()
        sys.exit(0)
    if sys.argv[1:2] == ["exe"]:
        exe(sys.argv[2:3] == ["link"])
        sys.exit(0)
    if sys.argv[1:2] == ["windows"]:
        windows()
        log_tail()
        sys.exit(0)
    registered()
    for label, what in (("command", 1), ("program", 2),
                        ("friendly name", 4)):
        print(f"Windows says {label}:", assoc(what))
    if sys.argv[1:2] == ["launch"]:
        launch()
