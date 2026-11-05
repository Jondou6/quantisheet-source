"""Try the "QuantiSheet" printer on this PC from the source folder.

    python tools/printer_trial.py install   (asks Windows for admin: UAC)
    python tools/printer_trial.py print     print a test page to it
    python tools/printer_trial.py status
    python tools/printer_trial.py remove    (UAC)

install/remove run `quantisheet.py printer ...` elevated; the helper task
runs this folder's Python as SYSTEM and opens printed files with the
installed QuantiSheet. Output of the elevated part: .run\\printer_admin.out
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
OUT = os.path.join(ROOT, ".run", "printer_admin.out")
from app import branding                             # noqa: E402
from app.printhelper import PRINTER                  # noqa: E402
# the installed program
APP = branding.installed_exe()


def elevated(args, env_cmd=None):
    """Run `python quantisheet.py ARGS` as administrator, wait, show output.
    env_cmd goes in QUANTISHEET_PRINT_HELPER_CMD (Windows PowerShell drops
    double quotes inside native-program arguments)."""
    if os.path.exists(OUT):
        os.remove(OUT)
    script = os.path.join(ROOT, ".run", "printer_admin.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        if env_cmd:
            f.write("$env:QUANTISHEET_PRINT_HELPER_CMD = '"
                    + env_cmd.replace("'", "''") + "'\n")
        f.write(f"& '{PY}' '{os.path.join(ROOT, 'quantisheet.py')}' "
                + " ".join("'" + a.replace("'", "''") + "'" for a in args)
                + f" *> '{OUT}'\n")
    cmd = ("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
           "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"
           f"'\"{script}\"'")
    p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=900)
    print("elevation:", p.returncode, (p.stdout + p.stderr).strip()[-500:])
    try:
        with open(OUT, encoding="utf-16", errors="replace") as f:
            text = f.read()
        if "\x00" in text or not text.strip():
            raise UnicodeError
    except (OSError, UnicodeError):
        try:
            with open(OUT, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            text = "(no output - was the Windows prompt declined?)"
    print(text)


def raw_ps(lines):
    """Run PowerShell lines as administrator (UAC), output into OUT."""
    if os.path.exists(OUT):
        os.remove(OUT)
    script = os.path.join(ROOT, ".run", "printer_admin.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write("& {\n" + "\n".join(lines) + f"\n}} *> '{OUT}'\n")
    cmd = ("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
           "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"
           f"'\"{script}\"'")
    p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=900)
    print("elevation:", p.returncode, (p.stdout + p.stderr).strip()[-300:])
    for enc in ("utf-16", "utf-8"):
        try:
            with open(OUT, encoding=enc) as f:
                text = f.read()
            if "\x00" not in text:
                print(text)
                return
        except (OSError, UnicodeError):
            continue
    print("(no admin output)")


def printed_folder():
    from app import printhelper
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    try:
        import ctypes
        from ctypes import wintypes as wt
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(printhelper.DOCUMENTS), 0, None,
                ctypes.byref(p)) == 0:
            docs = p.value
    except Exception:                                     # noqa: BLE001
        pass
    return os.path.join(docs, printhelper.SUBFOLDER)


def test_print():
    folder = printed_folder()
    before = set(glob.glob(os.path.join(folder, "*.pdf")))
    t = time.time()
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"'{PRINTER} printer test page' , (Get-Date) | "
                        f"Out-Printer -Name '{PRINTER}'"],
                       capture_output=True, text=True, timeout=120)
    print("sent:", p.returncode, (p.stdout + p.stderr).strip()[-400:])
    while time.time() - t < 90:
        new = set(glob.glob(os.path.join(folder, "*.pdf"))) - before
        if new:
            f = sorted(new)[0]
            time.sleep(1)
            with open(f, "rb") as fh:
                head = fh.read(8)
            print(f"arrived in {time.time() - t:.1f}s: {f} "
                  f"({os.path.getsize(f)} bytes, starts {head!r})")
            return 0
        time.sleep(0.5)
    print("nothing arrived in", folder)
    return 1


def main(argv):
    what = argv[0] if argv else "status"
    if what == "install":
        # the printer (admin), then this person's helper (as you)
        elevated(["printer", "--install"])
        p = subprocess.run([PY, os.path.join(ROOT, "quantisheet.py"),
                            "printer", "--user-on"], capture_output=True,
                           text=True, timeout=120)
        print("user-on:", p.returncode, (p.stdout + p.stderr)[-600:])
    elif what == "remove":
        elevated(["printer", "--remove"])
    elif what == "installed":
        # the installed program: printer as admin, helper as you
        raw_ps([f"Start-Process -Wait -FilePath '{APP}' -ArgumentList "
                "'printer','--install'"])
        p = subprocess.run([APP, "printer", "--user-on"],
                           capture_output=True, text=True, timeout=120)
        print("user-on:", p.returncode, (p.stdout + p.stderr)[-600:])
    elif what == "useron":
        # point the sign-in helper at the installed program (as you):
        # stop the source-folder helper first (it's yours, no admin)
        k = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process | Where-Object "
                            "{ $_.CommandLine -like '*quantisheet.py*print-"
                            "helper*' } | ForEach-Object { Stop-Process -Id "
                            "$_.ProcessId -Force; 'stopped ' + "
                            "$_.ProcessId }"],
                           capture_output=True, text=True, timeout=120)
        print(k.stdout.strip())
        time.sleep(1)
        p = subprocess.run([APP, "printer", "--user-on"],
                           capture_output=True, text=True, timeout=120)
        print("user-on:", p.returncode, (p.stdout + p.stderr)[-600:])
        time.sleep(3)
    elif what == "defender":
        # read-only: Defender's last detections
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-MpThreatDetection | Sort-Object "
                            "InitialDetectionTime | Select-Object -Last 5 "
                            "InitialDetectionTime,ThreatID,Resources,"
                            "ActionSuccess | Format-List; "
                            "Get-MpThreat | Select-Object -Last 3 "
                            "ThreatName,ThreatID | Format-List"],
                           capture_output=True, text=True, timeout=120)
        print(p.stdout[-3000:], p.stderr[-500:])
        return 0
    elif what == "fileport":
        # try a file port instead of the pipe: who writes the file?
        spool = r"C:\ProgramData\QuantiSheet\print\spool"
        port = spool + r"\job.pdf"
        raw_ps([f"New-Item -ItemType Directory -Force '{spool}' | Out-Null",
                f"icacls '{spool}' /grant '*S-1-5-32-545:(OI)(CI)M' | Out-Null",
                f"if (-not (Get-PrinterPort -Name '{port}' -ErrorAction "
                f"SilentlyContinue)) {{ Add-PrinterPort -Name '{port}' }}",
                f"Get-PrintJob -PrinterName '{PRINTER}' | Remove-PrintJob",
                f"Set-Printer -Name '{PRINTER}' -PortName '{port}'",
                f"Get-Printer -Name '{PRINTER}' | Format-List Name,PortName,"
                "PrinterStatus"])
        before = os.path.getmtime(port) if os.path.exists(port) else 0
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "'file port test', (Get-Date) | Out-Printer "
                            f"-Name '{PRINTER}'"], capture_output=True,
                           text=True, timeout=120)
        t = time.time()
        while time.time() - t < 60:
            if os.path.exists(port) and os.path.getmtime(port) > before:
                time.sleep(2)
                break
            time.sleep(0.5)
        if os.path.exists(port):
            with open(port, "rb") as f:
                head = f.read(8)
            own = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"(Get-Acl '{port}').Owner"],
                                 capture_output=True, text=True).stdout
            print(f"file port wrote {os.path.getsize(port)} bytes, starts "
                  f"{head!r}, owner {own.strip()}")
        else:
            print("file port: nothing written")
        what = "diag"
    elif what == "print":
        return test_print()
    elif what == "pipetest":
        try:
            with open(r"\\.\pipe\QuantiSheetPrint", "wb") as f:
                f.write(b"not a print job")
            print("pipe: opened and written (the helper should refuse it)")
        except OSError as e:
            print("pipe: can't open -", e)
        time.sleep(2)
        what = "diag"
    if what in ("diag",) or what == "fileport_done":
        for c in (f"Get-PrintJob -PrinterName '{PRINTER}' | Format-List "
                  "Id,DocumentName,UserName,JobStatus,Size,PagesPrinted",
                  f"Get-Printer -Name '{PRINTER}' | Format-List Name,"
                  "PrinterStatus,JobCount,PortName,DriverName",
                  "Get-WinEvent -LogName 'Microsoft-Windows-PrintService/Admin'"
                  " -MaxEvents 8 -ErrorAction SilentlyContinue | Format-List "
                  "TimeCreated,Id,Message"):
            p = subprocess.run(["powershell", "-NoProfile", "-Command", c],
                               capture_output=True, text=True, timeout=120)
            print("###", c[:40], "\n", (p.stdout + p.stderr).strip()[-3000:])
        log = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                           "QuantiSheet", "print", "print-helper.log")
        try:
            print("### helper log\n", open(log, encoding="utf-8",
                                            errors="replace").read()[-3000:])
        except OSError as e:
            print("### helper log unreadable:", e)
    from app import printer_setup
    for k, v in printer_setup.status().items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
