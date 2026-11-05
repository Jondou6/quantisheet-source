"""Install or remove the "QuantiSheet" printer (0.12.26).

    QuantiSheet.exe printer --install [--all-users]   printer and port (admin)
    QuantiSheet.exe printer --remove                  printer, port and the
                                                      sign-in entries (admin)
    QuantiSheet.exe printer --user-on / --user-off    this person's helper
    QuantiSheet.exe printer --status                  what is there

The printer itself needs an administrator (Windows asks). The helper that
opens printed pages runs as each person - started at sign-in by an entry
under HKCU\\...\\Run (--user-on), or for every user under HKLM\\...\\Run
(--install --all-users, which the server setup and the MSI use when IT
turns the printer on). Nothing runs as SYSTEM (app/printhelper.py says
why). Each step is skipped when already done, so running twice is safe.
"""
import os
import subprocess
import sys

from . import printhelper as ph

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)



def _ps_exe():
    """Windows PowerShell by full path (threat model T-017)."""
    from .syspaths import powershell
    return powershell()

def _q(s):
    """A PowerShell single-quoted string."""
    return "'" + str(s).replace("'", "''") + "'"


def _ps(cmd, check=False):
    p = subprocess.run([_ps_exe(), "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, text=True, timeout=300,
                       creationflags=NOWIN)
    out = (p.stdout + p.stderr).strip()
    if check and p.returncode != 0:
        raise RuntimeError(out[-800:] or f"PowerShell exit {p.returncode}")
    return p.returncode, out


def _run(args, check=False):
    p = subprocess.run(args, capture_output=True, text=True, timeout=120,
                       creationflags=NOWIN)
    out = (p.stdout + p.stderr).strip()
    if check and p.returncode != 0:
        raise RuntimeError(out[-800:] or f"{args[0]} exit {p.returncode}")
    return p.returncode, out


def _delete_run(winreg, hive, name):
    try:
        with winreg.OpenKey(hive, ph.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _set_run(hive_name, command):
    """The sign-in entry, in HKCU or HKLM (None removes it)."""
    import winreg
    hive = getattr(winreg, hive_name)
    if command is None:
        _delete_run(winreg, hive, ph.RUN_NAME)
        return
    with winreg.CreateKeyEx(hive, ph.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, ph.RUN_NAME, 0, winreg.REG_SZ, command)


def _get_run(hive_name):
    """The sign-in entry's command, or None."""
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, hive_name), ph.RUN_KEY) as k:
            return winreg.QueryValueEx(k, ph.RUN_NAME)[0]
    except (OSError, ImportError):
        pass
    return None


def status():
    rows = {}
    _c, out = _ps("$p = Get-Printer -Name " + _q(ph.PRINTER) +
                  " -ErrorAction SilentlyContinue; if ($p) { $p.DriverName "
                  "+ ' | ' + $p.PortName } else { 'missing' }")
    rows["printer"] = out
    _c, out = _ps("if (Get-PrinterDriver -Name " + _q(ph.DRIVER) +
                  " -ErrorAction SilentlyContinue) {'installed'} "
                  "else {'missing'}")
    rows["driver"] = out
    rows["helper (you)"] = _get_run("HKEY_CURRENT_USER") or "off"
    rows["helper (all users)"] = _get_run("HKEY_LOCAL_MACHINE") or "off"
    rows["helper running"] = "yes" if (sys.platform.startswith("win") and
                                       ph.running()) else "no"
    try:
        with open(ph.log_path(), encoding="utf-8", errors="replace") as f:
            rows["helper log"] = "".join(f.readlines()[-5:]).strip()
    except OSError:
        rows["helper log"] = "(none yet)"
    return rows


def install(all_users=False, exe=None, log=print):
    """Driver check, spool folder, port and printer (admin). With
    all_users, every person gets the sign-in entry (HKLM). Raises
    RuntimeError with what went wrong (e.g. not run as administrator)."""
    code, out = _ps("Get-PrinterDriver -Name " + _q(ph.DRIVER) +
                    " -ErrorAction SilentlyContinue | Out-Null; "
                    "if ($?) {'ok'}")
    if "ok" not in out:
        log("adding the Microsoft Print To PDF driver...")
        c, o = _ps("Add-PrinterDriver -Name " + _q(ph.DRIVER))
        if c:
            raise RuntimeError(
                "Windows' Microsoft Print To PDF driver isn't installed. Turn "
                "on the Windows feature 'Microsoft Print to PDF' "
                "(Printing-PrintToPDFServices-Features), then run this "
                "again.\n" + o[-400:])
    # the spool folder: SYSTEM and admins full; signed-in users may only
    # create a file there (as the spooler does, acting as them), and own
    # what they create - nobody reads anyone else's print job
    os.makedirs(ph.SPOOL_DIR, exist_ok=True)
    _run(["icacls", ph.SPOOL_DIR, "/inheritance:r", "/grant:r",
          "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F",
          "*S-1-5-11:(WD,AD,S,RA)", "*S-1-3-0:(OI)(CI)(IO)F"], check=True)
    _ps("if (-not (Get-PrinterPort -Name " + _q(ph.PORT) +
        " -ErrorAction SilentlyContinue)) { Add-PrinterPort -Name " +
        _q(ph.PORT) + " }", check=True)
    log("port ready: " + ph.PORT)
    _ps("if (Get-Printer -Name " + _q(ph.PRINTER) + " -ErrorAction "
        "SilentlyContinue) { Set-Printer -Name " + _q(ph.PRINTER) +
        " -DriverName " + _q(ph.DRIVER) + " -PortName " + _q(ph.PORT) +
        " } else { Add-Printer -Name " + _q(ph.PRINTER) + " -DriverName " +
        _q(ph.DRIVER) + " -PortName " + _q(ph.PORT) + " }", check=True)
    log("printer ready: " + ph.PRINTER)
    if all_users:
        _set_run("HKEY_LOCAL_MACHINE", ph.helper_command(exe))
        log("every user's print helper starts when they sign in")
    return status()


def user_on(exe=None, log=print):
    """This person's sign-in entry, and the helper started now (run as the
    person, not elevated)."""
    from . import packaged
    if packaged.is_packaged():
        # the Store version: a Run-key entry would be virtualized and never
        # run at sign-in - its startup task is switched on in Settings
        ph.ensure_running()
        packaged.open_startup_settings()
        log("your print helper is running; to start it at sign-in, switch "
            "on 'QuantiSheet Printer' in Settings > Apps > Startup")
        return status()
    _set_run("HKEY_CURRENT_USER", ph.helper_command(exe))
    ph.ensure_running()
    log("your print helper is on")
    return status()


def user_off(log=print):
    from . import packaged
    if packaged.is_packaged():
        packaged.open_startup_settings()
        log("switch off 'QuantiSheet Printer' in Settings > Apps > Startup")
        return status()
    _set_run("HKEY_CURRENT_USER", None)
    log("your print helper is off (it stops when you sign out)")
    return status()


def remove(log=print):
    _set_run("HKEY_LOCAL_MACHINE", None)
    _set_run("HKEY_CURRENT_USER", None)
    _ps("Remove-Printer -Name " + _q(ph.PRINTER) +
        " -ErrorAction SilentlyContinue")
    _ps("Remove-PrinterPort -Name " + _q(ph.PORT) +
        " -ErrorAction SilentlyContinue")
    if os.path.isdir(ph.SPOOL_DIR):                  # unread jobs go too
        _run(["cmd", "/c", "rmdir", "/s", "/q", ph.SPOOL_DIR])
    log("printer, port, spool folder and sign-in entries removed")
    return status()
