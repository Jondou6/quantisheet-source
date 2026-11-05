"""The "QuantiSheet" printer's helper (0.12.26 - runs as you).

Print from any program to the printer named "QuantiSheet" and the pages
open in QuantiSheet as a new PDF - like "Adobe PDF" or "Microsoft Print to
PDF", without a Save dialog.

How it works (no driver of our own):
  * The printer uses Windows' own "Microsoft Print To PDF" driver, so the
    print job comes out as a finished PDF.
  * Its port is a file, C:\\ProgramData\\QuantiSheet\\print\\spool\\job.pdf
    Windows writes each job there as the person printing, so the file's
    owner says whose it is. People may only create that file - they can't
    read or change anyone else's.
  * This helper - `QuantiSheet.exe print-helper` - runs as the signed-in
    person, started when they sign in (the "QuantiSheet Printer" entry under
    Windows' Run key) and by QuantiSheet itself. It watches the queue for
    that person's own jobs, moves each finished file into their
    Documents\\QuantiSheet\\Printed and opens it in QuantiSheet. It never
    touches anyone else's job or file.

0.12.24-0.12.25 ran the helper as SYSTEM from a start-up task and opened
the file in the user's session from there. Windows Defender's automatic
rules took that for malware (Trojan:Win32/Bearfoos.A!ml, Oct 20) - so
nothing here runs with more rights than the person printing.

Set up by `QuantiSheet.exe printer --install` (admin: the printer and port)
and `printer --user-on` (the person: the sign-in entry). See
app/printer_setup.py.
"""
import ctypes
import datetime
import logging
import os
import re
import subprocess
import sys
import time as time_mod

PRINTER = "QuantiSheet"
# the spool folder (the printer's file port)
_PROGRAM_DATA = os.environ.get("ProgramData", r"C:\ProgramData")
SPOOL_DIR = os.path.join(_PROGRAM_DATA, "QuantiSheet", "print", "spool")
PORT = os.path.join(SPOOL_DIR, "job.pdf")
POLL = 0.5                           # seconds between looks at the queue
DRIVER = "Microsoft Print To PDF"
# in the person's Documents
SUBFOLDER = os.path.join("QuantiSheet", "Printed")
MAX_JOB = 2 * 1024 ** 3                 # 2 GB: a job bigger than that is cut
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "QuantiSheet Printer"

log = logging.getLogger("quantisheet.print")


# ---- pure parts (tested everywhere) ---------------------------------------
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_APP_SUFFIX = re.compile(r"\s+-\s+(Notepad|Word|Excel|Paint|WordPad|"
                         r"Microsoft Edge|Google Chrome|Outlook)\s*$", re.I)


def file_name(document, when=None):
    """'Report.docx - Word' -> 'Report 2026-10-20 081530.pdf'."""
    when = when or datetime.datetime.now()
    d = _APP_SUFFIX.sub("", (document or "").strip())
    d = os.path.splitext(d)[0] if re.search(r"\.\w{2,4}$", d) else d
    d = _BAD.sub("_", d).strip(" .") or "Printed"
    return f"{d[:80].rstrip(' .')} {when:%Y-%m-%d %H%M%S}.pdf"


def unique(folder, name):
    base, ext = os.path.splitext(name)
    p, k = os.path.join(folder, name), 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{base} ({k}){ext}")
        k += 1
    return p


def pick_job(jobs):
    """The job being written to the port now: [(id, user, document,
    status, position)] -> (user, document) or (None, None)."""
    printing = [j for j in jobs if j[3] & 0x10]           # JOB_STATUS_PRINTING
    pool = printing or sorted(jobs, key=lambda j: j[4])
    return (pool[0][1], pool[0][2]) if pool else (None, None)


def looks_like_pdf(data):
    return data[:1024].lstrip().startswith(b"%PDF")


def me():
    """This person's account name, lower-case, no domain."""
    return (os.environ.get("USERNAME") or "").split("\\")[-1].lower()


def _bare(user):
    return (user or "").split("\\")[-1].lower()


def _windowless(exe):
    """pythonw.exe beside python.exe (a source run): no CMD window."""
    d, b = os.path.split(exe)
    w = os.path.join(d, "pythonw.exe")
    return w if b.lower() == "python.exe" and os.path.isfile(w) else exe


def helper_command(exe=None):
    """What the sign-in entry runs."""
    exe = exe or sys.executable
    if getattr(sys, "frozen", False) or exe != sys.executable:
        return f'"{exe}" print-helper'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f'"{_windowless(exe)}" "{os.path.join(root, "quantisheet.py")}" ' \
        'print-helper'


def app_command(path):
    """How to open a printed file in QuantiSheet (a running QuantiSheet takes
    it over - app/singleinstance.py)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, path]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [_windowless(sys.executable), os.path.join(root, "quantisheet.py"),
            path]


# ---- Windows ----------------------------------------------------------------
if sys.platform.startswith("win"):
    from ctypes import wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [(n, wt.WORD) for n in ("y", "mo", "dow", "d", "h", "mi",
                                           "s", "ms")]

    class JOB_INFO_1(ctypes.Structure):
        _fields_ = [("JobId", wt.DWORD), ("pPrinterName", wt.LPWSTR),
                    ("pMachineName", wt.LPWSTR), ("pUserName", wt.LPWSTR),
                    ("pDocument", wt.LPWSTR), ("pDatatype", wt.LPWSTR),
                    ("pStatus", wt.LPWSTR), ("Status", wt.DWORD),
                    ("Priority", wt.DWORD), ("Position", wt.DWORD),
                    ("TotalPages", wt.DWORD), ("PagesPrinted", wt.DWORD),
                    ("Submitted", SYSTEMTIME)]

    class PRINTER_DEFAULTS(ctypes.Structure):
        _fields_ = [("pDatatype", wt.LPWSTR), ("pDevMode", ctypes.c_void_p),
                    ("DesiredAccess", wt.DWORD)]

    class GUID(ctypes.Structure):
        _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD),
                    ("d", ctypes.c_ubyte * 8)]
    # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    DOCUMENTS = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                     (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03,
                                          0x69, 0xC7))
    spool.OpenPrinterW.argtypes = [wt.LPWSTR, ctypes.POINTER(wt.HANDLE),
                                   ctypes.c_void_p]
    spool.EnumJobsW.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD),
                                ctypes.POINTER(wt.DWORD)]
    spool.SetJobW.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                              wt.DWORD]
    spool.ClosePrinter.argtypes = [wt.HANDLE]
    adv.GetNamedSecurityInfoW.argtypes = [
        wt.LPCWSTR, ctypes.c_int, wt.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    adv.LookupAccountSidW.argtypes = [
        wt.LPCWSTR, ctypes.c_void_p, wt.LPWSTR, ctypes.POINTER(wt.DWORD),
        wt.LPWSTR, ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD)]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.CreateMutexW.restype = wt.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    k32.OpenMutexW.restype = wt.HANDLE
    k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wt.DWORD,
                                             wt.HANDLE,
                                             ctypes.POINTER(ctypes.c_wchar_p)]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

MUTEX = "Local\\QuantiSheetPrintHelper"      # Local: one per signed-in session


def _exists(name):
    h = wt.HANDLE()
    if not spool.OpenPrinterW(name, ctypes.byref(h), None):
        return False
    spool.ClosePrinter(h)
    return True


def active_printer(refresh=False):
    """The printer this helper serves."""
    return PRINTER


def jobs(printer=None):
    """[(id, user, document, status, position)] in the printer's queue."""
    printer = printer or active_printer()
    h = wt.HANDLE()
    if not spool.OpenPrinterW(printer, ctypes.byref(h), None):
        return []
    try:
        need, n = wt.DWORD(), wt.DWORD()
        spool.EnumJobsW(h, 0, 64, 1, None, 0, ctypes.byref(need),
                        ctypes.byref(n))
        if not need.value:
            return []
        buf = ctypes.create_string_buffer(need.value)
        if not spool.EnumJobsW(h, 0, 64, 1, buf, need, ctypes.byref(need),
                               ctypes.byref(n)):
            return []
        arr = ctypes.cast(buf, ctypes.POINTER(JOB_INFO_1))
        return [(arr[i].JobId, arr[i].pUserName or "", arr[i].pDocument or "",
                 arr[i].Status, arr[i].Position) for i in range(n.value)]
    finally:
        spool.ClosePrinter(h)


def documents():
    """This person's Documents folder (redirected ones too)."""
    path = ctypes.c_wchar_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(DOCUMENTS), 0, None,
                                    ctypes.byref(path)) != 0:
        return os.path.join(os.path.expanduser("~"), "Documents")
    try:
        return path.value
    finally:
        ole32.CoTaskMemFree(path)


def file_owner(path):
    """The account name (no domain) that owns `path`, lower-case."""
    sd = ctypes.c_void_p()
    owner = ctypes.c_void_p()
    if adv.GetNamedSecurityInfoW(path, 1, 1, ctypes.byref(owner), None,
                                 None, None, ctypes.byref(sd)) != 0:
        return ""
    try:
        name = ctypes.create_unicode_buffer(256)
        dom = ctypes.create_unicode_buffer(256)
        n, d, use = wt.DWORD(256), wt.DWORD(256), wt.DWORD()
        if not adv.LookupAccountSidW(None, owner, name, ctypes.byref(n), dom,
                                     ctypes.byref(d), ctypes.byref(use)):
            return ""
        return name.value.lower()
    finally:
        k32.LocalFree(sd)


def set_job(job_id, control, printer=None):
    """Pause (1) or resume (2) one of this person's own jobs - Windows lets
    everyone manage their own documents."""
    printer = printer or active_printer()
    h = wt.HANDLE()
    defaults = PRINTER_DEFAULTS(None, None, 0x00000008)   # PRINTER_ACCESS_USE
    if not spool.OpenPrinterW(printer, ctypes.byref(h),
                              ctypes.byref(defaults)):
        return False
    try:
        return bool(spool.SetJobW(h, job_id, 0, None, control))
    finally:
        spool.ClosePrinter(h)


def running():
    """Is a helper already running in this session?"""
    h = k32.OpenMutexW(0x00100000, False, MUTEX)           # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
        return True
    return False


def _hold_mutex():
    h = k32.CreateMutexW(None, False, MUTEX)
    if not h or ctypes.get_last_error() == 183:            # ALREADY_EXISTS
        return None
    return h


# ---- the work (Windows calls are module functions, so tests swap them) ----
def _stable(path, wait=0.6):
    """The file has stopped growing and can be opened (the spooler has let
    go of it)."""
    try:
        a = os.path.getsize(path)
        time_mod.sleep(wait)
        b = os.path.getsize(path)
        with open(path, "rb"):
            pass
        return a == b and b > 0
    except OSError:
        return False


def ports():
    """The spool files a job can arrive in."""
    return (PORT,)


def _waiting_port():
    """The port when it has a job file in it now."""
    return PORT if os.path.exists(PORT) else None


def printed_folder():
    """This person's Documents\\QuantiSheet\\Printed."""
    from . import brand_paths
    return brand_paths.printed_folder(documents())


def deliver(data, document, folder=None):
    """A finished job -> Documents\\QuantiSheet\\Printed\\<name>.pdf."""
    folder = folder or printed_folder()
    os.makedirs(folder, exist_ok=True)
    path = unique(folder, file_name(document))
    with open(path, "wb") as f:
        f.write(data)
    return path


def open_in_app(path):
    try:
        subprocess.Popen(app_command(path), close_fds=True)
        return True
    except OSError:
        log.warning("print: couldn't start QuantiSheet for %s", path,
                    exc_info=True)
        return False


def collect(document, user=None, port=None):
    """The job file (`port`, default PORT), if it's this person's: read,
    removed from the spool, saved and opened. Someone else's file is left
    alone (their own helper collects it). Returns the delivered path or
    None."""
    user = user or me()
    port = port or PORT
    owner = file_owner(port)
    if not user or owner != user:
        log.info("print: job file belongs to %r - left for them", owner)
        return None
    try:
        with open(port, "rb") as f:
            data = f.read(MAX_JOB)
    except OSError as e:
        log.warning("print: couldn't read the job file: %s", e)
        return None
    finally:
        try:
            os.remove(port)
        except OSError:
            pass
    if not looks_like_pdf(data):
        log.warning("print: the job isn't a PDF (%d bytes) - is the "
                    "printer's driver %s?", len(data), DRIVER)
        return None
    path = deliver(data, document)
    log.info("print: %r -> %s", document, path)
    open_in_app(path)
    return path


def step(state, user=None):
    """One look at the queue (state: {"current": (id, doc) | None,
    "paused": set()}). Only this person's jobs are looked at. Returns a
    delivered path or None."""
    user = user or me()
    q = [j for j in jobs() if _bare(j[1]) == user]
    ids = {j[0] for j in q}
    printing = [j for j in q if j[3] & 0x10]
    cur = state.get("current")
    if printing and cur is None:
        state["current"] = cur = (printing[0][0], printing[0][2])
    # my later jobs wait until the current one's file is collected
    for j in q:
        if cur and j[0] != cur[0] and not (j[3] & (0x1 | 0x10)) \
                and j[0] not in state["paused"]:
            if set_job(j[0], 1):
                state["paused"].add(j[0])
    out = None
    port = _waiting_port()
    if cur is not None and cur[0] not in ids:          # the job has finished
        if port and _stable(port):
            out = collect(cur[1], user, port)
        state["current"] = None
        waiting = sorted((j for j in q if j[0] in state["paused"]),
                         key=lambda j: j[4])
        if waiting:
            set_job(waiting[0][0], 2)
            state["paused"].discard(waiting[0][0])
    elif cur is None and port and _stable(port, 2.0):
        # a file left from before the helper started: mine only
        out = collect("Printed", user, port)
    state["paused"] &= ids
    return out


def serve(once=False):
    state = {"current": None, "paused": set()}
    checked = time_mod.monotonic()
    while True:
        if not once and time_mod.monotonic() - checked > 60:
            checked = time_mod.monotonic()
            if not user_enabled():           # turned off or removed: stop
                log.info("print helper: turned off - stopping")
                return None
            try:                             # renamed since? (an upgrade)
                active_printer(refresh=True)
            except Exception:                             # noqa: BLE001
                log.debug("printer lookup failed", exc_info=True)
        try:
            got = step(state)
        except Exception:                                 # noqa: BLE001
            log.exception("print: step failed")
            got = None
        if once and got:
            return got
        time_mod.sleep(POLL)


def log_path():
    """%LOCALAPPDATA%\\QuantiSheet\\print-helper.log."""
    from . import brand_paths
    return os.path.join(brand_paths.local_dir(), "print-helper.log")


def run_helper():
    """`QuantiSheet.exe print-helper`: one per session, logs to the person's
    LocalAppData, serves until they sign out."""
    if not sys.platform.startswith("win"):
        return 1
    held = _hold_mutex()
    if held is None:
        return 0                                  # already running
    path = log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logging.basicConfig(filename=path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log.info("print helper starting for %s (ports %s)", me(),
             ", ".join(ports()))
    serve()
    return 0


def ensure_running():
    """Start the helper if this person has the printer turned on and none
    is running (called when QuantiSheet starts). Never raises."""
    try:
        if not sys.platform.startswith("win") or not user_enabled() or \
                running():
            return False
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = app_command("")[:-1] + ["print-helper"]
        subprocess.Popen(cmd, close_fds=True, creationflags=flags)
        return True
    except Exception:                                     # noqa: BLE001
        log.warning("print helper not started", exc_info=True)
        return False


def user_enabled():
    """Does this person (or every user, set by IT) have the sign-in entry?"""
    try:
        import winreg
    except ImportError:
        return False
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, RUN_KEY) as k:
                winreg.QueryValueEx(k, RUN_NAME)
                return True
        except OSError:
            continue
    return False
