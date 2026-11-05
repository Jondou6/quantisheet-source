"""Why does the QuantiSheet icon show the UAC shield? Read-only unless
'fix-shortcut' is given (clears only the 'Run as administrator' flag on
QuantiSheet's own Desktop / Start-menu shortcuts).

    python tools/uac_check.py [fix-shortcut]
"""
import os
import re
import struct
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
from app import branding                             # noqa: E402

LOCAL = os.environ.get("LOCALAPPDATA", "")
EXE = branding.installed_exe()
LINKS = [p for name in ("QuantiSheet.lnk",) for p in (
    os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", name),
    os.path.join(os.path.expanduser("~"), "Desktop", name),
    os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                 "Start Menu", "Programs", name))]
# The public Desktop (Windows sets PUBLIC). No profile path is written here.
_public = os.environ.get("PUBLIC")
if _public:
    LINKS.append(os.path.join(_public, "Desktop", "QuantiSheet.lnk"))
RUNAS = 0x2000          # SLDF_RUNAS_USER in the .lnk LinkFlags


def manifest_level(path):
    with open(path, "rb") as f:
        b = f.read()
    m = re.search(rb'requestedExecutionLevel\s+level="([^"]+)"', b)
    return m.group(1).decode() if m else "(no manifest level found)"


def layers():
    out = []
    for hive, name in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                       (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            k = winreg.OpenKey(hive, r"Software\Microsoft\Windows NT"
                               r"\CurrentVersion\AppCompatFlags\Layers")
        except OSError:
            continue
        i = 0
        while True:
            try:
                n, v, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            flat = n.lower().replace(" ", "")
            if "quantisheet" in flat:
                out.append(f"{name}: {n} = {v}")
            i += 1
    return out


def main(fix):
    print("exe:", EXE, os.path.isfile(EXE))
    if os.path.isfile(EXE):
        print("manifest level:", manifest_level(EXE))
    print("compat layers:", layers() or "none")
    for p in LINKS:
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            b = bytearray(f.read())
        flags = struct.unpack_from("<I", b, 0x14)[0]
        runas = bool(flags & RUNAS)
        print(f"shortcut {p}: run as administrator = {runas}")
        if fix and runas:
            struct.pack_into("<I", b, 0x14, flags & ~RUNAS)
            with open(p, "wb") as f:
                f.write(b)
            print("   cleared")


if __name__ == "__main__":
    main(len(sys.argv) > 1 and sys.argv[1] == "fix-shortcut")
