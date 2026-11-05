"""The Microsoft Store copy's update reminder (Nov 2, Jon: "yes add store
route").

The Store copy (an MSIX package) is updated by the Microsoft Store, never
by QuantiSheet itself (Store rules for packaged apps). What it does:

- check(): asks the Store on this PC - Windows' own Store update service,
  StoreContext.GetAppAndOptionalStorePackageUpdatesAsync - whether an
  update for this app is waiting. Nothing is downloaded and nothing goes
  to us; the Store already knows what is installed. It runs in a hidden
  Windows PowerShell started from the packaged program, so it has the
  package's identity (no extra library ships for it).
- open_store(): opens the app's page in the Microsoft Store, where the
  person clicks Update (or Get updates). The Store downloads and
  installs it.
- The reminder itself (status bar, Start page) and What's New after an
  update are updatecheck_ui's, shared with the team copy.

Turned off like the team copy's check: Help > Check for Updates
Automatically, or IT's DisableUpdateCheck / OfflineMode. Any doubt or
error -> no reminder (never a wrong one).
"""
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger(__name__)

TIMEOUT = 60                       # seconds for the PowerShell check
STORE_FALLBACK = "ms-windows-store://downloadsandupdates"

# Windows PowerShell 5.1 (on every supported Windows) can call WinRT. The
# output is one line: "UPDATES <count> <version of the first one>".
PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Services.Store.StoreContext, Windows.Services.Store, ContentType=WindowsRuntime]
$ctx = [Windows.Services.Store.StoreContext]::GetDefault()
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$t = [System.Collections.Generic.IReadOnlyList[Windows.Services.Store.StorePackageUpdate]]
$op = $ctx.GetAppAndOptionalStorePackageUpdatesAsync()
$task = $asTask.MakeGenericMethod($t).Invoke($null, @($op))
$null = $task.Wait(50000)
$ups = $task.Result
$v = ''
if ($ups.Count -gt 0) {
  $p = $ups[0].Package.Id.Version
  $v = "$($p.Major).$($p.Minor).$($p.Build).$($p.Revision)"
}
"UPDATES $($ups.Count) $v"
"""

_OUT = re.compile(r"UPDATES\s+(\d+)\s*([\d.]*)")


def store_copy():
    """True for the Store (MSIX) copy."""
    try:
        from . import packaged
        return bool(packaged.is_packaged())
    except Exception:                                     # noqa: BLE001
        return False


def eligible(manual=False):
    """(ok, reason), as updatecheck.eligible for the team copy."""
    from . import updatecheck
    if not store_copy():
        return False, "not the Store copy"
    if not updatecheck.allowed_by_it():
        return False, "turned off by IT"
    if not manual and not updatecheck.enabled():
        return False, "turned off in settings"
    return True, ""


def parse(out):
    """(count, version or '') from the PowerShell output, or None."""
    m = _OUT.search(out or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2) or ""


def _run_ps(script, timeout=TIMEOUT):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    r = subprocess.run([exe, "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout,
                       creationflags=flags)
    return r.stdout


def check(manual=False, run=None, now=None):
    """Never raises. (status, info) like updatecheck.check:
        "ineligible" / "not_due" / "error" / "current" /
        "available" (info {"version": "1.0.3.0" or "", "notes": ""})."""
    import time
    from . import settings, updatecheck
    try:
        ok, why = eligible(manual)
        if not ok:
            return "ineligible", why
        now = time.time() if now is None else now
        if not manual and not updatecheck.due(now):
            return "not_due", None
        settings.set(updatecheck.S_LAST, now)
        if run is None and sys.platform != "win32":
            return "error", "not Windows"
        out = (run or _run_ps)(PS_SCRIPT)
        got = parse(out)
        if got is None:
            log.info("store update check: no answer (%r)", (out or "")[:200])
            return "error", "no answer from the Store"
        n, v = got
        if n <= 0:
            return "current", None
        if v and not updatecheck.is_newer(v, updatecheck.current_version()):
            return "current", None
        return "available", {"version": v, "notes": "", "store": True}
    except Exception as e:                                # noqa: BLE001
        log.debug("store update check failed", exc_info=True)
        return "error", str(e)


def family_name():
    """This package's family name (for the Store link), or ''."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        n = wintypes.UINT(0)
        k = ctypes.windll.kernel32
        k.GetCurrentPackageFamilyName(ctypes.byref(n), None)
        if not n.value:
            return ""
        buf = ctypes.create_unicode_buffer(n.value)
        if k.GetCurrentPackageFamilyName(ctypes.byref(n), buf) != 0:
            return ""
        return buf.value
    except (AttributeError, OSError):
        return ""


def store_link():
    fam = family_name()
    return f"ms-windows-store://pdp/?PFN={fam}" if fam else STORE_FALLBACK


def open_store(opener=None):
    """Open the app's Store page (the person clicks Update there)."""
    url = store_link()
    try:
        (opener or os.startfile)(url)            # noqa: S606
        return url
    except (AttributeError, OSError):
        try:
            (opener or os.startfile)(STORE_FALLBACK)   # noqa: S606
            return STORE_FALLBACK
        except (AttributeError, OSError):
            return None
