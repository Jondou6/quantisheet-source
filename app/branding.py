"""The program's name and program file, in one place."""
import os
import sys

NAME = "QuantiSheet"
EXE = "QuantiSheet.exe"
# the standalone setup's Inno Setup AppId
STANDALONE_UNINSTALL = (r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Uninstall\{375F90B3-3B41-4FE9-B790-B29C6D30C75E}"
                        r"_is1")


def _registered_dir():
    """Where the standalone setup says it installed the program, or None."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, STANDALONE_UNINSTALL) as k:
                d = winreg.QueryValueEx(k, "InstallLocation")[0]
            if d and os.path.isfile(os.path.join(d, EXE)):
                return d
        except OSError:
            continue
    return None


def installed_exe(base=None):
    """The installed program (standalone setup): the folder the setup
    registered, else <base>\\QuantiSheet\\QuantiSheet.exe. `base` is the
    folder that holds the install folder (default %LOCALAPPDATA%\\Programs).
    Returns that path even when nothing is installed there."""
    if base is None:
        reg = _registered_dir()
        if reg:
            return os.path.join(reg, EXE)
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")
    return os.path.join(base, NAME, EXE)


def is_program(path):
    """Does `path` (a file path or process name) name the program?
    Case-insensitive, as Windows is."""
    base = os.path.basename(str(path or "").replace("\\", "/")).lower()
    return base == EXE.lower()
