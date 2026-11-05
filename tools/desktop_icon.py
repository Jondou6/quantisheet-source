"""The Desktop "QuantiSheet" shortcut: show where it points, or point it
at the installed program again (after Defender removed and reinstalling
put back the program, Oct 20).

    python tools/desktop_icon.py show
    python tools/desktop_icon.py fix
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
from app import branding                             # noqa: E402

APP = branding.installed_exe()


def ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy",
                        "Bypass", "-Command", cmd], capture_output=True,
                       text=True, timeout=120)
    return (r.stdout + r.stderr).strip()


SHOW = ("$sh=New-Object -ComObject WScript.Shell;"
        "foreach($d in @([Environment]::GetFolderPath('Desktop'),"
        "[Environment]::GetFolderPath('CommonDesktopDirectory'))){"
        "Get-ChildItem -LiteralPath $d -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -like '*QuantiSheet*.lnk' } | ForEach-Object {"
        "$s=$sh.CreateShortcut($_.FullName);"
        "'{0}`n  target: {1} (exists: {2})`n  args: {3}`n  icon: {4}' -f "
        "$_.FullName,$s.TargetPath,(Test-Path -LiteralPath $s.TargetPath),"
        "$s.Arguments,$s.IconLocation}}")


def main(what):
    print("installed program:", APP, os.path.isfile(APP))
    if what == "fix":
        if not os.path.isfile(APP):
            print("not installed - nothing to point at")
            return 1
        print(ps("$d=[Environment]::GetFolderPath('Desktop');"
                 "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
                 "(Join-Path $d 'QuantiSheet.lnk'));"
                 f"$s.TargetPath='{APP}';$s.Arguments='';"
                 f"$s.WorkingDirectory='{os.path.dirname(APP)}';"
                 f"$s.IconLocation='{APP},0';"
                 "$s.Description='QuantiSheet';$s.Save();'saved'"))
        # ask Explorer to redraw icons (no settings changed)
        subprocess.run(["ie4uinit.exe", "-show"], capture_output=True)
    print(ps(SHOW) or "no QuantiSheet shortcut on the Desktop")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "show"))
